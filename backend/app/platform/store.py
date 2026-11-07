from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import delete, event, exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app import settings
from app.core.element_scope import element_in_task, link_task, unlink_task
from app.core.capability_manifest import capability_command_catalog
from app.platform.entitlements import current_term, entitlements_from, plan_entitlements
from app.platform.payments.base import ChannelTrade, new_merchant_no
from app.platform.migrate import upgrade_platform_schema
from app.platform.permissions import (
    RECON_READ,
    REFUND_APPROVE,
    ROLE_PERMISSIONS,
    SUPER_ADMIN,
    WALLET_ADJUST_APPROVE,
    has_permission,
    legacy_role,
)
from app.platform.models import (
    MembershipTerm,
    PointBalance,
    PointHold,
    PointLot,
    PointRate,
    ReconItem,
    UsageCharge,
    UserNotification,
    UserRole,
    WalletAdjustment,
    AuditEvent,
    CapabilitySetting,
    ConfiguredModel,
    DirectorDeskPose,
    ElementAsset,
    ElementFile,
    ElementFolder,
    ElementFolderMember,
    LedgerEntry,
    MembershipPlan,
    ModelProviderConfiguration,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    PaymentWebhookEvent,
    PlatformUser,
    ProjectSkill,
    RegenerationRequest,
    UserMembership,
    ModelConfigurationCredential,
    PlatformSetting,
    McpToken,
)
from app.repository.user_repo import hash_password, verify_password
from app.core.look_board import LOOK_VIEW_SLOTS
from app.schema.production import IDENTITY_VIEW_ORDER, LEGACY_IDENTITY_VIEW_ORDER


# 数字演员的图片槽位 = 设定集的五个身份锚点。
ACTOR_VIEW_SLOTS = IDENTITY_VIEW_ORDER
# 旧五视图角度：存量演员就存在这些槽位里，上传/删除/就绪判定都必须继续认。
LEGACY_ACTOR_VIEW_SLOTS = LEGACY_IDENTITY_VIEW_ORDER
# element_file.position 的排序表：以旧五视图的转面顺序打底，新增的两张头部挂在后面。
# 这样两代资产各自读起来都对——旧演员仍是 0°→45°→90°→135°→180°，
# 新演员按位置升序就是 front/profile/back/face_front/face_three_quarter。
ACTOR_VIEW_SLOT_ORDER = LEGACY_ACTOR_VIEW_SLOTS + tuple(
    slot for slot in ACTOR_VIEW_SLOTS if slot not in LEGACY_ACTOR_VIEW_SLOTS
)


# 表演妆造的定妆图整板(front)切出来的七张(见 core/look_board)：只给人看，排在身份视图后面，分镜仍取整板。
ACTOR_FILE_SLOT_ORDER = ACTOR_VIEW_SLOT_ORDER + LOOK_VIEW_SLOTS


def _wants_identity_views(element: "ElementAsset") -> bool:
    """数字演员要齐五个身份视图才算就绪；角色穿戏服的定妆图是一张展示板，有图就算。"""
    variant = (element.metadata_json or {}).get("variant")
    return element.kind == "actor" and not (isinstance(variant, dict) and variant.get("source") == "costume")


def actor_views_complete(slots: set[str]) -> bool:
    """任意一代的整套身份视图齐了，演员就算 ready。"""
    return set(ACTOR_VIEW_SLOTS) <= slots or set(LEGACY_ACTOR_VIEW_SLOTS) <= slots
ELEMENT_KINDS = {"actor", "prop", "scene", "costume", "effect", "product", "extra", "vehicle", "stunt", "set_dressing", "makeup"}
logger = logging.getLogger("app.platform.store")

ACCOUNT_DELETED = "deleted"
REFUND_ON_REQUEST = "requested"
REFUND_OPEN = ("requested", "pending", "processing")
#: An order that was paid, whatever has happened to it since.
PAID_ORDER_STATES = ("paid", "partially_refunded", "refunded")
_ADJUSTED_POINTS_LAST = timedelta(days=365)
REMINDER_EARLIEST = timedelta(days=7)
_ALERTS_SHOWN_FOR = timedelta(days=7)
PAYMENT_ALERTS = (
    "payment.mismatch", "payment.unknown_trade", "payment.late", "payment.duplicate", "payment.refund_failed", "payment.refunded_elsewhere",
)

PAYMENT_PROVIDERS = {"sandbox", "wechat", "alipay"}


class PaymentInFlight(ValueError):
    """Another request for this order is talking to the channel right now."""


def _aware_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)  # SQLite hands back naive datetimes


def money_audit(session, actor: Mapping, action: str, resource_type: str, resource_id: str, **details) -> None:
    """A person moving money. The roles they held go in the record, so it can be checked later that they were allowed."""
    session.add(AuditEvent(
        actor_id=actor["user_id"], action=action, resource_type=resource_type, resource_id=resource_id,
        details={"actor_roles": list(actor.get("roles") or ()), **details},
    ))


def _notify(session, user_id: str, kind: str, dedupe_key: str, **data) -> None:
    session.add(UserNotification(user_id=user_id, kind=kind, dedupe_key=dedupe_key[:120], data=data))


def _payment_event(session, action: str, refund: PaymentRefund) -> None:
    session.add(AuditEvent(
        actor_id=None, action=action, resource_type="payment_refund", resource_id=refund.id,
        details={"order_id": refund.order_id, "refund_minor": refund.refund_minor, "points": str(refund.points_clawback)},
    ))


def _payment_alert(session, action: str, order: PaymentOrder | None, **details) -> None:
    """Something about real money that a person should look at. Goes to the audit trail, in the caller's transaction, and the log."""
    logger.error("支付告警 %s: 订单 %s %s", action, order.id if order else "-", details)
    session.add(AuditEvent(
        actor_id=None, action=action, resource_type="payment_order", resource_id=order.id if order else "",
        details={key: str(value) for key, value in details.items()},
    ))


def _enforce_sqlite_foreign_keys(connection, _record) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
PROJECT_SKILL_SOURCE_TYPES = {"created", "markdown_upload", "skill_package"}
MAX_PROJECT_SKILL_BYTES = 128 * 1024
MAX_ENABLED_SKILLS = 12
MAX_ENABLED_SKILL_BYTES = 96 * 1024
MAX_DESK_POSES_PER_OWNER = 200
MAX_DESK_POSE_NAME = 40
MAX_ELEMENT_FOLDERS_PER_OWNER = 200
MAX_ELEMENT_FOLDER_NAME = 80
ELEMENT_FOLDER_UNFILED = "unfiled"


MAX_ELEMENT_ASSETS_PER_OWNER = settings.env_int(
    "ELEMENT_ASSET_COUNT_QUOTA", 1_000, minimum=10, maximum=100_000
)
MAX_ELEMENT_STORAGE_BYTES = settings.env_int(
    "ELEMENT_STORAGE_QUOTA_BYTES", 5 * 1024**3, minimum=50 * 1024**2, maximum=1024**5
)
MAX_GLOBAL_ELEMENT_STORAGE_BYTES = settings.env_int(
    "ELEMENT_GLOBAL_STORAGE_QUOTA_BYTES", 20 * 1024**3, minimum=1024**3, maximum=1024**5
)


@dataclass(frozen=True)
class ResolvedCommand:
    source_id: str
    capability_id: str
    label: str
    command: str
    entrypoint: str
    payload: str


@dataclass(frozen=True)
class WalletSnapshot:
    points: Decimal
    money: dict[str, Decimal]
    entries: Sequence[LedgerEntry]


@dataclass(frozen=True)
class StoredElementFileResult:
    element: ElementAsset
    replaced_storage_path: str | None


@dataclass(frozen=True)
class DeletedElementFileRecord:
    id: str
    element_id: str
    slot: str
    storage_path: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class DeletedElementFileResult:
    element: ElementAsset
    deleted_file: DeletedElementFileRecord


@dataclass(frozen=True)
class DeletedElementResult:
    element_id: str
    deleted_files: tuple[DeletedElementFileRecord, ...]


DeletionStorageHook = Callable[
    [tuple[DeletedElementFileRecord, ...]],
    Awaitable[dict[str, object] | None],
]


class StorageMutationCommittedWithError(BaseException):
    """Carries a committed result through context-exit/cancellation failures."""

    def __init__(
        self,
        result: StoredElementFileResult | DeletedElementFileResult | DeletedElementResult,
        original_error: BaseException,
    ):
        super().__init__("storage mutation committed before a later error")
        self.result = result
        self.original_error = original_error


def _deleted_element_file_record(item: ElementFile) -> DeletedElementFileRecord:
    return DeletedElementFileRecord(
        id=item.id,
        element_id=item.element_id,
        slot=item.slot,
        storage_path=item.storage_path,
        mime_type=item.mime_type,
        size_bytes=item.size_bytes,
    )


async def _commit_deletion_with_cancellation_boundary(session) -> bool:
    """Commit exactly once and report cancellation only after its outcome is known.

    Shielding avoids the unsafe state where the filesystem has already been
    quarantined but request cancellation leaves the database commit outcome
    ambiguous. Repeated cancellation requests are deferred until the commit
    task has either succeeded or failed.
    """

    commit_task = asyncio.create_task(session.commit())
    cancellation_requested = False
    while not commit_task.done():
        try:
            await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            cancellation_requested = True
            if commit_task.done():
                break
            continue
    commit_task.result()
    return cancellation_requested


class PlatformStore:
    def __init__(self, database_url: str, *, echo: bool = False):
        if not database_url.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError("DATABASE_URL 必须使用 postgresql+asyncpg 或 sqlite+aiosqlite")
        self.engine: AsyncEngine = create_async_engine(database_url, echo=echo, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        if self.engine.dialect.name == "sqlite":
            # SQLite leaves foreign keys off unless asked; local development should fail the way PostgreSQL does.
            event.listen(self.engine.sync_engine, "connect", _enforce_sqlite_foreign_keys)

    async def create_schema(self) -> None:
        sqlite = self.engine.dialect.name == "sqlite"
        async with self.engine.connect() as connection:
            if sqlite:
                # Rebuilding a table on SQLite drops the old one, which would fire its foreign keys.
                await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                await connection.commit()
            async with connection.begin():
                if not sqlite:
                    # Workers starting together take turns.
                    await connection.execute(
                        text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 6_002_829_067_579_314_754},
                    )
                await connection.run_sync(upgrade_platform_schema)
            if sqlite:
                await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                await connection.commit()

    async def close(self) -> None:
        await self.engine.dispose()

    async def _lock_element_storage_budget(self, session) -> None:
        if self.engine.dialect.name == "postgresql":
            # Serializes the global quota calculation across every account and
            # process without introducing a migration-only sentinel row.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": 6_002_829_067_579_314_753},
            )
        else:
            # SQLite is a local-development boundary. This remains a no-op lock
            # there, while SQLite itself serializes the eventual write commit.
            await session.scalar(
                select(PlatformUser.id).order_by(PlatformUser.id).limit(1).with_for_update()
            )

    async def create_user(
        self,
        *,
        email: str | None,
        phone: str | None,
        password: str,
        username: str | None = None,
        role: str = "user",
        must_change_password: bool = False,
        _minimum_password_length: int = settings.PASSWORD_MIN_LENGTH,
    ) -> tuple[PlatformUser, bool]:
        clean_email = email.strip().lower() if email else None
        clean_phone = phone.strip() if phone else None
        if not clean_email and not clean_phone:
            raise ValueError("邮箱和手机号至少填写一项")
        if len(password) < _minimum_password_length:
            raise ValueError(f"密码至少需要 {_minimum_password_length} 位")
        async with self.sessions() as session:
            clauses = []
            if clean_email:
                clauses.append(PlatformUser.email == clean_email)
            if clean_phone:
                clauses.append(PlatformUser.phone == clean_phone)
            for clause in clauses:
                existing = await session.scalar(select(PlatformUser).where(clause))
                if existing:
                    return existing, False
            base_name = username or (clean_email.split("@", 1)[0] if clean_email else f"user-{clean_phone[-4:]}")
            clean_name = re.sub(r"[^a-zA-Z0-9_-]", "-", base_name).strip("-")[:60] or "user"
            candidate = clean_name
            if await session.scalar(select(PlatformUser.id).where(PlatformUser.username == candidate)):
                candidate = f"{clean_name}-{secrets.token_hex(3)}"
            user = PlatformUser(
                username=candidate,
                email=clean_email,
                phone=clean_phone,
                password_hash=hash_password(password),
                role=role,
                status="active",
                must_change_password=must_change_password,
                role_grants=[UserRole(role=SUPER_ADMIN)] if role == "admin" else [],
            )
            session.add(user)
            await session.commit()
            return user, True

    async def bootstrap_admin(
        self, password: str, *, login: str
    ) -> tuple[PlatformUser, bool]:
        clean_login = login.strip().lower()
        if "@" not in clean_login or len(clean_login) > 320:
            raise ValueError("默认管理员登录名必须为有效邮箱格式")
        async with self.sessions() as session:
            existing = await session.scalar(
                select(PlatformUser).where(PlatformUser.email == clean_login)
            )
            if existing:
                return existing, False
        return await self.create_user(
            email=clean_login,
            phone=None,
            password=password,
            username="admin",
            role="admin",
            must_change_password=True,
            _minimum_password_length=settings.BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH,
        )

    async def verify_login(self, login_id: str, password: str) -> PlatformUser | None:
        clean = login_id.strip().lower()
        async with self.sessions() as session:
            user = await session.scalar(
                select(PlatformUser).where(
                    (PlatformUser.email == clean)
                    | (PlatformUser.phone == login_id.strip())
                    | (PlatformUser.username == login_id.strip())
                )
            )
            if not user or user.status != "active" or not verify_password(password, user.password_hash):
                return None
            return user

    async def get_user(self, user_id: str) -> PlatformUser | None:
        async with self.sessions() as session:
            return await session.get(PlatformUser, user_id)

    async def get_user_by_login(self, login_id: str) -> PlatformUser | None:
        clean = login_id.strip().lower()
        async with self.sessions() as session:
            return await session.scalar(
                select(PlatformUser).where(
                    (PlatformUser.email == clean)
                    | (PlatformUser.phone == login_id.strip())
                    | (PlatformUser.username == login_id.strip())
                )
            )

    async def update_profile(
        self, user_id: str, *, display_name: str | None = None, phone: str | None = None
    ) -> PlatformUser:
        async with self.sessions() as session:
            user = await session.get(PlatformUser, user_id)
            if not user:
                raise ValueError("用户不存在")
            if display_name is not None:
                user.display_name = display_name.strip()[:120] or None
            if phone is not None:
                clean_phone = phone.strip() or None
                if clean_phone:
                    duplicate = await session.scalar(
                        select(PlatformUser.id).where(
                            PlatformUser.phone == clean_phone, PlatformUser.id != user_id
                        )
                    )
                    if duplicate:
                        raise ValueError("手机号已被使用")
                user.phone = clean_phone
            await session.commit()
            return user

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> PlatformUser:
        if len(new_password) < settings.PASSWORD_MIN_LENGTH:
            raise ValueError(f"新密码至少需要 {settings.PASSWORD_MIN_LENGTH} 位")
        async with self.sessions() as session:
            user = await session.get(PlatformUser, user_id)
            if not user or not verify_password(current_password, user.password_hash):
                raise ValueError("当前密码错误")
            user.password_hash = hash_password(new_password)
            user.must_change_password = False
            await session.commit()
            return user

    async def list_users(self, page: int, page_size: int) -> tuple[list[PlatformUser], int]:
        offset = (page - 1) * page_size
        async with self.sessions() as session:
            total = int(await session.scalar(select(func.count()).select_from(PlatformUser)) or 0)
            users = list((await session.scalars(
                select(PlatformUser).order_by(PlatformUser.created_at.desc()).offset(offset).limit(page_size)
            )).all())
            return users, total

    async def _assert_keeps_a_super_admin(self, session, user: PlatformUser) -> None:
        others = int(await session.scalar(
            select(func.count()).select_from(UserRole).join(PlatformUser, PlatformUser.id == UserRole.user_id).where(
                UserRole.role == SUPER_ADMIN, PlatformUser.status == "active", PlatformUser.id != user.id,
            )
        ) or 0)
        if not others:
            raise ValueError("不能停用或降级最后一个有效超级管理员")

    async def _close_account_money(self, session, user_id: str) -> dict:
        """Unpaid orders close, points held for calls go back, and tokens stop. Refunds carry on: that money is owed regardless."""
        closed = await session.execute(
            update(PaymentOrder).where(PaymentOrder.user_id == user_id, PaymentOrder.status == "pending").values(status="closed")
        )
        holds = (await session.scalars(select(PointHold).where(PointHold.user_id == user_id, PointHold.status == "active"))).all()
        released = 0
        balance = await session.get(PointBalance, user_id, with_for_update=True) if holds else None
        for hold in holds:
            # A call under way that reports back later is treated like one whose hold went stale: a fresh debit.
            moved = await session.execute(
                update(PointHold).where(PointHold.id == hold.id, PointHold.status == "active").values(status="released")
            )
            if moved.rowcount == 1 and balance:
                balance.available += hold.amount
                balance.held -= hold.amount
                released += 1
        revoked = await session.execute(
            update(McpToken).where(McpToken.user_id == user_id, McpToken.revoked.is_(False)).values(revoked=True)
        )
        return {"orders_closed": closed.rowcount, "holds_released": released, "tokens_revoked": revoked.rowcount}

    async def set_user_status(self, actor_id: str, user_id: str, status: str) -> PlatformUser:
        if status not in {"active", "suspended"}:
            raise ValueError("无效状态")
        async with self.sessions() as session:
            user = await session.get(PlatformUser, user_id)
            if not user:
                raise ValueError("用户不存在")
            if user.status == ACCOUNT_DELETED:
                raise ValueError("账号已删除，不能再启用")
            if status == "suspended" and SUPER_ADMIN in user.roles and user.status == "active":
                await self._assert_keeps_a_super_admin(session, user)
            previous = user.status
            user.status = status
            effects = await self._close_account_money(session, user.id) if status == "suspended" and previous != "suspended" else {}
            session.add(AuditEvent(
                actor_id=actor_id, action="user.status_change", resource_type="user", resource_id=user.id,
                details={"previous": previous, "new": status, **effects},
            ))
            await session.commit()
            return user

    async def delete_account(self, *, actor_id: str, user_id: str) -> PlatformUser:
        """Removes who they were and keeps what happened: orders, ledger and audit stay, tied to an id nobody can log in with."""
        if actor_id == user_id:
            raise ValueError("不能删除自己的账号")
        async with self.sessions() as session:
            user = await session.get(PlatformUser, user_id, with_for_update=True)
            if not user:
                raise LookupError("用户不存在")
            if user.status == ACCOUNT_DELETED:
                raise ValueError("账号已删除")
            if SUPER_ADMIN in user.roles and user.status == "active":
                await self._assert_keeps_a_super_admin(session, user)
            effects = await self._close_account_money(session, user.id)
            removed_roles = user.roles
            user.role_grants = []
            user.role, user.status, user.must_change_password = "user", ACCOUNT_DELETED, False
            user.username, user.email, user.phone, user.display_name = f"deleted-{user.id}"[:80], None, None, None
            user.password_hash = hash_password(secrets.token_urlsafe(32))
            await session.execute(delete(UserNotification).where(UserNotification.user_id == user.id))
            session.add(AuditEvent(
                actor_id=actor_id, action="user.delete", resource_type="user", resource_id=user.id,
                details={"roles_removed": removed_roles, **effects},
            ))
            await session.commit()
            return user

    async def open_attempts_of_user(self, user_id: str) -> list[PaymentAttempt]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(PaymentAttempt).where(PaymentAttempt.user_id == user_id, PaymentAttempt.status == "pending")
            )).all())

    async def set_user_roles(self, actor_id: str, user_id: str, roles: Sequence[str]) -> PlatformUser:
        wanted = set(roles)
        if wanted - set(ROLE_PERMISSIONS):
            raise ValueError("无效角色")
        async with self.sessions() as session:
            user = await session.get(PlatformUser, user_id, with_for_update=True)
            if not user:
                raise ValueError("用户不存在")
            previous = set(user.roles)
            if SUPER_ADMIN in previous and SUPER_ADMIN not in wanted and user.status == "active":
                await self._assert_keeps_a_super_admin(session, user)
            user.role_grants = [
                *(grant for grant in user.role_grants if grant.role in wanted),
                *(UserRole(role=role, granted_by=actor_id) for role in sorted(wanted - previous)),
            ]
            user.role = legacy_role(wanted)
            session.add(AuditEvent(
                actor_id=actor_id, action="user.roles_change", resource_type="user", resource_id=user.id,
                details={"previous": sorted(previous), "new": sorted(wanted)},
            ))
            await session.commit()
            return user

    async def record_audit(
        self, *, actor_id: str | None, action: str, resource_type: str, resource_id: str, details: dict | None = None,
    ) -> None:
        async with self.sessions() as session:
            session.add(AuditEvent(
                actor_id=actor_id, action=action, resource_type=resource_type, resource_id=resource_id,
                details=details or {},
            ))
            await session.commit()

    async def list_audit_events(self, page: int, page_size: int) -> tuple[list[AuditEvent], int]:
        async with self.sessions() as session:
            total = int(await session.scalar(select(func.count()).select_from(AuditEvent)) or 0)
            events = list((await session.scalars(
                select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )).all())
            return events, total

    async def seed_capabilities(self) -> None:
        catalog = capability_command_catalog()
        async with self.sessions() as session:
            for item in catalog:
                persisted = {
                    key: item[key]
                    for key in (
                        "source_id", "capability_id", "source_url", "label", "command", "entrypoint"
                    )
                }
                setting = await session.get(CapabilitySetting, (item["source_id"], item["capability_id"]))
                if setting:
                    setting.source_url = persisted["source_url"]
                    setting.label = persisted["label"]
                    setting.command = persisted["command"]
                    setting.entrypoint = persisted["entrypoint"]
                else:
                    session.add(CapabilitySetting(**persisted, enabled=True))
            await session.commit()

    async def list_capabilities(self) -> list[CapabilitySetting]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(CapabilitySetting).order_by(CapabilitySetting.source_id, CapabilitySetting.label)
            )).all())

    async def set_capability_enabled(
        self,
        source_id: str,
        capability_id: str,
        enabled: bool,
        *,
        actor_id: str | None,
    ) -> CapabilitySetting:
        async with self.sessions() as session:
            setting = await session.get(CapabilitySetting, (source_id, capability_id))
            if not setting:
                raise ValueError("能力不存在")
            previous = setting.enabled
            setting.enabled = enabled
            setting.updated_by = actor_id
            session.add(AuditEvent(
                actor_id=actor_id,
                action="capability.toggle",
                resource_type="capability",
                resource_id=f"{source_id}:{capability_id}",
                details={"previous": previous, "enabled": enabled, "command": setting.command},
            ))
            await session.commit()
            return setting

    async def resolve_command(self, text: str) -> ResolvedCommand:
        command_text = (text or "").strip()
        command, _, payload = command_text.partition(" ")
        if not re.fullmatch(r"/[a-z0-9][a-z0-9._-]{1,219}", command):
            raise ValueError("命令格式无效")
        async with self.sessions() as session:
            setting = await session.scalar(select(CapabilitySetting).where(CapabilitySetting.command == command))
            if setting:
                if not setting.enabled:
                    raise ValueError("该能力尚未启用")
                return ResolvedCommand(
                    source_id=setting.source_id,
                    capability_id=setting.capability_id,
                    label=setting.label,
                    command=setting.command,
                    entrypoint=setting.entrypoint,
                    payload=payload.strip(),
                )
            skill = await session.scalar(select(ProjectSkill).where(ProjectSkill.command == command))
            if not skill:
                raise ValueError("命令不存在")
            if not skill.enabled:
                raise ValueError("该 Skill 尚未启用")
            return ResolvedCommand(
                source_id="project-skills",
                capability_id=skill.slug,
                label=skill.name,
                command=skill.command,
                entrypoint="project-skill-runtime",
                payload=payload.strip(),
            )

    @staticmethod
    def _validate_project_skill(
        *, name: str, slug: str, markdown_content: str, source_type: str
    ) -> tuple[str, str, str]:
        clean_name = name.strip()
        clean_slug = slug.strip().lower()
        content = markdown_content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not clean_name or len(clean_name) > 160:
            raise ValueError("Skill 名称必须为 1-160 个字符")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,78}[a-z0-9]", clean_slug):
            raise ValueError("命令标识仅允许 3-80 位小写字母、数字和中横线")
        if source_type not in PROJECT_SKILL_SOURCE_TYPES:
            raise ValueError("Skill 来源类型无效")
        encoded = content.encode("utf-8")
        if not encoded or len(encoded) > MAX_PROJECT_SKILL_BYTES or "\x00" in content:
            raise ValueError("Markdown 内容必须为 1 字节至 128 KiB 的 UTF-8 文本")
        return clean_name, clean_slug, content

    async def _check_project_skill_enable_budget(
        self, session, *, added_content: str = "", excluding_id: str | None = None
    ) -> None:
        query = select(ProjectSkill).where(ProjectSkill.enabled.is_(True))
        if excluding_id:
            query = query.where(ProjectSkill.id != excluding_id)
        active = list((await session.scalars(query)).all())
        count = len(active) + (1 if added_content else 0)
        total = sum(len(item.markdown_content.encode("utf-8")) for item in active)
        total += len(added_content.encode("utf-8"))
        if count > MAX_ENABLED_SKILLS or total > MAX_ENABLED_SKILL_BYTES:
            raise ValueError("启用的项目 Skill 超过 12 个或 96 KiB 运行时上限")

    async def list_project_skills(self, *, enabled_only: bool = False) -> list[ProjectSkill]:
        async with self.sessions() as session:
            query = select(ProjectSkill)
            if enabled_only:
                query = query.where(ProjectSkill.enabled.is_(True))
            return list((await session.scalars(query.order_by(ProjectSkill.name, ProjectSkill.slug))).all())

    async def create_project_skill(
        self,
        *,
        name: str,
        slug: str,
        description: str,
        markdown_content: str,
        source_type: str,
        enabled: bool,
        actor_id: str,
    ) -> ProjectSkill:
        clean_name, clean_slug, content = self._validate_project_skill(
            name=name, slug=slug, markdown_content=markdown_content, source_type=source_type
        )
        if len(description) > 4000:
            raise ValueError("Skill 描述不能超过 4000 个字符")
        async with self.sessions() as session:
            if await session.scalar(select(ProjectSkill.id).where(ProjectSkill.slug == clean_slug)):
                raise ValueError("命令标识已存在")
            if enabled:
                await self._check_project_skill_enable_budget(session, added_content=content)
            item = ProjectSkill(
                name=clean_name,
                slug=clean_slug,
                description=description.strip(),
                markdown_content=content,
                source_type=source_type,
                command=f"/skill.{clean_slug}",
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                enabled=enabled,
                created_by=actor_id,
                updated_by=actor_id,
            )
            session.add(item)
            await session.flush()
            session.add(AuditEvent(
                actor_id=actor_id,
                action="project_skill.create",
                resource_type="project_skill",
                resource_id=item.id,
                details={"slug": clean_slug, "source_type": source_type, "enabled": enabled,
                         "version": 1, "content_sha256": item.content_sha256},
            ))
            await session.commit()
            return item

    async def update_project_skill(
        self,
        skill_id: str,
        *,
        name: str | None,
        description: str | None,
        markdown_content: str | None,
        actor_id: str,
    ) -> ProjectSkill:
        async with self.sessions() as session:
            item = await session.get(ProjectSkill, skill_id)
            if not item:
                raise ValueError("Skill 不存在")
            next_name = item.name if name is None else name
            next_description = item.description if description is None else description
            next_content = item.markdown_content if markdown_content is None else markdown_content
            clean_name, _, content = self._validate_project_skill(
                name=next_name, slug=item.slug, markdown_content=next_content,
                source_type=item.source_type,
            )
            if len(next_description) > 4000:
                raise ValueError("Skill 描述不能超过 4000 个字符")
            if item.enabled:
                await self._check_project_skill_enable_budget(
                    session, added_content=content, excluding_id=item.id
                )
            previous_digest = item.content_sha256
            item.name = clean_name
            item.description = next_description.strip()
            item.markdown_content = content
            item.content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            item.version += 1
            item.updated_by = actor_id
            session.add(AuditEvent(
                actor_id=actor_id,
                action="project_skill.update",
                resource_type="project_skill",
                resource_id=item.id,
                details={"slug": item.slug, "version": item.version,
                         "previous_sha256": previous_digest, "content_sha256": item.content_sha256},
            ))
            await session.commit()
            return item

    async def set_project_skill_enabled(
        self, skill_id: str, enabled: bool, *, actor_id: str
    ) -> ProjectSkill:
        async with self.sessions() as session:
            item = await session.get(ProjectSkill, skill_id)
            if not item:
                raise ValueError("Skill 不存在")
            if enabled and not item.enabled:
                await self._check_project_skill_enable_budget(
                    session, added_content=item.markdown_content, excluding_id=item.id
                )
            previous = item.enabled
            item.enabled = enabled
            item.updated_by = actor_id
            session.add(AuditEvent(
                actor_id=actor_id,
                action="project_skill.toggle",
                resource_type="project_skill",
                resource_id=item.id,
                details={"slug": item.slug, "previous": previous, "enabled": enabled,
                         "version": item.version, "content_sha256": item.content_sha256},
            ))
            await session.commit()
            return item

    async def list_model_configurations(self) -> list[ModelProviderConfiguration]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(ModelProviderConfiguration)
                .options(selectinload(ModelProviderConfiguration.models))
                .order_by(ModelProviderConfiguration.category, ModelProviderConfiguration.provider)
            )).all())

    async def get_model_configuration(
        self, configuration_id: str
    ) -> ModelProviderConfiguration | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(ModelProviderConfiguration)
                .options(selectinload(ModelProviderConfiguration.models))
                .where(ModelProviderConfiguration.id == configuration_id)
            )

    async def find_model_configuration(
        self, category: str, provider: str
    ) -> ModelProviderConfiguration | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(ModelProviderConfiguration)
                .options(selectinload(ModelProviderConfiguration.models))
                .where(
                    ModelProviderConfiguration.category == category,
                    ModelProviderConfiguration.provider == provider,
                )
            )

    async def save_model_configuration(
        self,
        *,
        actor_id: str,
        category: str,
        provider: str,
        base_url: str,
        api_key_ciphertext: str,
        api_key_hint: str,
        models: list[dict],
    ) -> ModelProviderConfiguration:
        if not models:
            raise ValueError("至少选择一个模型")
        async with self.sessions() as session:
            configuration = await session.scalar(
                select(ModelProviderConfiguration)
                .options(selectinload(ModelProviderConfiguration.models))
                .where(
                    ModelProviderConfiguration.category == category,
                    ModelProviderConfiguration.provider == provider,
                )
            )
            if configuration is None:
                configuration = ModelProviderConfiguration(
                    category=category,
                    provider=provider,
                    base_url=base_url,
                    api_key_ciphertext=api_key_ciphertext,
                    api_key_hint=api_key_hint,
                    enabled=True,
                    updated_by=actor_id,
                    models=[],
                )
                session.add(configuration)
                await session.flush()
            else:
                configuration.base_url = base_url
                configuration.api_key_ciphertext = api_key_ciphertext
                configuration.api_key_hint = api_key_hint
                configuration.updated_by = actor_id

            existing = {
                (item.model_id, item.subcategory): item for item in configuration.models
            }
            for discovered in models:
                subcategory = discovered.get("subcategory") or ""
                key = (discovered["model_id"], subcategory)
                entry = existing.get(key)
                if entry is None:
                    entry = ConfiguredModel(
                        configuration_id=configuration.id,
                        model_id=discovered["model_id"],
                        display_name=discovered["display_name"],
                        description=discovered.get("description", ""),
                        category=category,
                        subcategory=subcategory,
                        capabilities=list(discovered.get("capabilities") or []),
                        enabled=True,
                    )
                    session.add(entry)
                else:
                    entry.display_name = discovered["display_name"]
                    entry.description = discovered.get("description", "")
                    entry.capabilities = list(discovered.get("capabilities") or [])

            session.add(AuditEvent(
                actor_id=actor_id,
                action="model_configuration.save",
                resource_type="model_configuration",
                resource_id=configuration.id,
                details={
                    "category": category,
                    "provider": provider,
                    "base_url": base_url,
                    "selected_model_ids": [item["model_id"] for item in models],
                },
            ))
            await session.commit()
            loaded = await session.scalar(
                select(ModelProviderConfiguration)
                .options(selectinload(ModelProviderConfiguration.models))
                .where(ModelProviderConfiguration.id == configuration.id)
                .execution_options(populate_existing=True)
            )
            assert loaded is not None
            return loaded

    # ------------------------------------------------------------ extra credentials

    async def list_model_credentials(self, configuration_id: str | None = None) -> list[ModelConfigurationCredential]:
        async with self.sessions() as session:
            query = select(ModelConfigurationCredential).order_by(ModelConfigurationCredential.created_at)
            if configuration_id:
                query = query.where(ModelConfigurationCredential.configuration_id == configuration_id)
            return list((await session.scalars(query)).all())

    async def add_model_credential(
        self, configuration_id: str, *, actor_id: str, label: str, api_key_ciphertext: str, api_key_hint: str, buckets: list[str],
    ) -> ModelConfigurationCredential:
        async with self.sessions() as session:
            configuration = await session.get(ModelProviderConfiguration, configuration_id)
            if not configuration:
                raise ValueError("模型配置不存在")
            credential = ModelConfigurationCredential(
                configuration_id=configuration_id, label=label[:80], api_key_ciphertext=api_key_ciphertext,
                api_key_hint=api_key_hint, buckets=list(buckets), enabled=True, created_by=actor_id,
            )
            session.add(credential)
            session.add(AuditEvent(
                actor_id=actor_id, action="model_credential.add", resource_type="model_configuration",
                resource_id=configuration_id, details={"label": label[:80], "buckets": list(buckets)},
            ))
            await session.commit()
            await session.refresh(credential)
            return credential

    async def update_model_credential(
        self, configuration_id: str, credential_id: str, *, actor_id: str, enabled: bool | None = None, buckets: list[str] | None = None,
    ) -> ModelConfigurationCredential:
        async with self.sessions() as session:
            credential = await session.get(ModelConfigurationCredential, credential_id)
            if not credential or credential.configuration_id != configuration_id:
                raise ValueError("凭据不存在")
            if enabled is not None:
                credential.enabled = enabled
            if buckets is not None:
                credential.buckets = list(buckets)
            session.add(AuditEvent(
                actor_id=actor_id, action="model_credential.update", resource_type="model_configuration",
                resource_id=configuration_id, details={"credential_id": credential_id, "enabled": enabled, "buckets": buckets},
            ))
            await session.commit()
            await session.refresh(credential)
            return credential

    async def delete_model_credential(self, configuration_id: str, credential_id: str, *, actor_id: str) -> dict:
        async with self.sessions() as session:
            credential = await session.get(ModelConfigurationCredential, credential_id)
            if not credential or credential.configuration_id != configuration_id:
                raise ValueError("凭据不存在")
            await session.delete(credential)
            session.add(AuditEvent(
                actor_id=actor_id, action="model_credential.delete", resource_type="model_configuration",
                resource_id=configuration_id, details={"credential_id": credential_id},
            ))
            await session.commit()
            return {"credential_id": credential_id, "deleted": True}

    # ------------------------------------------------------------ MCP tokens

    async def create_mcp_token(self, user_id: str, *, label: str) -> tuple[McpToken, str]:
        """Issue a token; the clear text is returned once and never stored."""
        clear = "mcp_" + secrets.token_urlsafe(32)
        digest = hashlib.sha256(clear.encode("utf-8")).hexdigest()
        async with self.sessions() as session:
            token = McpToken(user_id=user_id, label=label[:80], token_digest=digest, token_hint=clear[-4:])
            session.add(token)
            await session.flush()  # the audit row names the token's id
            session.add(AuditEvent(actor_id=user_id, action="mcp_token.create", resource_type="mcp_token", resource_id=token.id, details={"label": label[:80]}))
            await session.commit()
            await session.refresh(token)
            return token, clear

    async def list_mcp_tokens(self, user_id: str) -> list[McpToken]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(McpToken).where(McpToken.user_id == user_id, McpToken.revoked.is_(False)).order_by(McpToken.created_at)
            )).all())

    async def revoke_mcp_token(self, user_id: str, token_id: str) -> bool:
        async with self.sessions() as session:
            token = await session.get(McpToken, token_id)
            if not token or token.user_id != user_id or token.revoked:
                return False
            token.revoked = True
            session.add(AuditEvent(actor_id=user_id, action="mcp_token.revoke", resource_type="mcp_token", resource_id=token_id, details={}))
            await session.commit()
            return True

    async def verify_mcp_token(self, clear: str) -> PlatformUser | None:
        """The active user a token belongs to, or None; a used token's last_used_at moves."""
        if not clear.startswith("mcp_") or len(clear) > 128:
            return None
        digest = hashlib.sha256(clear.encode("utf-8")).hexdigest()
        async with self.sessions() as session:
            token = await session.scalar(select(McpToken).where(McpToken.token_digest == digest))
            if not token or token.revoked or not hmac.compare_digest(token.token_digest, digest):
                return None
            user = await session.get(PlatformUser, token.user_id)
            if not user or user.status != "active":
                return None
            token.last_used_at = datetime.now(timezone.utc)
            await session.commit()
            return user

    # ------------------------------------------------------------ global settings

    async def get_setting(self, key: str) -> dict:
        async with self.sessions() as session:
            row = await session.get(PlatformSetting, key)
            return dict(row.value or {}) if row else {}

    async def put_setting(self, key: str, value: dict, *, actor_id: str) -> dict:
        async with self.sessions() as session:
            row = await session.get(PlatformSetting, key)
            if row is None:
                row = PlatformSetting(key=key, value=dict(value), updated_by=actor_id)
                session.add(row)
            else:
                row.value = dict(value)
                row.updated_by = actor_id
            session.add(AuditEvent(
                actor_id=actor_id, action="platform_setting.put", resource_type="platform_setting", resource_id=key,
                details={"keys": sorted(str(k) for k in value)},
            ))
            await session.commit()
            return dict(value)

    async def put_settings(self, values: dict[str, dict], *, actor_id: str) -> dict[str, dict]:
        """Write several global settings in one transaction: all of them land, or none."""
        async with self.sessions() as session:
            for key, value in values.items():
                row = await session.get(PlatformSetting, key)
                if row is None:
                    session.add(PlatformSetting(key=key, value=dict(value), updated_by=actor_id))
                else:
                    row.value = dict(value)
                    row.updated_by = actor_id
                session.add(AuditEvent(
                    actor_id=actor_id, action="platform_setting.put", resource_type="platform_setting", resource_id=key,
                    details={"keys": sorted(str(k) for k in value), "batch": sorted(values)},
                ))
            await session.commit()
            return {key: dict(value) for key, value in values.items()}

    async def set_model_configuration_enabled(
        self, configuration_id: str, enabled: bool, *, actor_id: str
    ) -> ModelProviderConfiguration:
        async with self.sessions() as session:
            configuration = await session.get(ModelProviderConfiguration, configuration_id)
            if not configuration:
                raise ValueError("模型配置不存在")
            previous = configuration.enabled
            configuration.enabled = enabled
            configuration.updated_by = actor_id
            session.add(AuditEvent(
                actor_id=actor_id,
                action="model_configuration.toggle",
                resource_type="model_configuration",
                resource_id=configuration.id,
                details={"previous": previous, "enabled": enabled},
            ))
            await session.commit()
            loaded = await session.scalar(
                select(ModelProviderConfiguration)
                .options(selectinload(ModelProviderConfiguration.models))
                .where(ModelProviderConfiguration.id == configuration.id)
                .execution_options(populate_existing=True)
            )
            assert loaded is not None
            return loaded

    async def set_configured_model_enabled(
        self, configuration_id: str, entry_id: str, enabled: bool, *, actor_id: str
    ) -> ConfiguredModel:
        async with self.sessions() as session:
            entry = await session.get(ConfiguredModel, entry_id)
            if not entry or entry.configuration_id != configuration_id:
                raise ValueError("模型不存在")
            configuration = await session.get(ModelProviderConfiguration, configuration_id)
            if not configuration:
                raise ValueError("模型配置不存在")
            previous = entry.enabled
            entry.enabled = enabled
            session.add(AuditEvent(
                actor_id=actor_id,
                action="configured_model.toggle",
                resource_type="configured_model",
                resource_id=entry.id,
                details={
                    "previous": previous,
                    "enabled": enabled,
                    "model_id": entry.model_id,
                    "category": entry.category,
                },
            ))
            await session.commit()
            return entry

    async def delete_configured_model(
        self, configuration_id: str, entry_id: str, *, actor_id: str
    ) -> dict:
        """Delete one saved model and remove the credential container when it becomes empty."""
        async with self.sessions() as session:
            configuration = await session.scalar(
                select(ModelProviderConfiguration)
                .options(selectinload(ModelProviderConfiguration.models))
                .where(ModelProviderConfiguration.id == configuration_id)
            )
            if not configuration:
                raise ValueError("模型配置不存在")
            entry = next((item for item in configuration.models if item.id == entry_id), None)
            if entry is None:
                raise ValueError("模型不存在")

            result = {
                "entry_id": entry.id,
                "model_id": entry.model_id,
                "category": entry.category,
                "was_enabled": bool(configuration.enabled and entry.enabled),
                "configuration_deleted": len(configuration.models) == 1,
            }
            session.add(AuditEvent(
                actor_id=actor_id,
                action="configured_model.delete",
                resource_type="configured_model",
                resource_id=entry.id,
                details={
                    "configuration_id": configuration.id,
                    "model_id": entry.model_id,
                    "category": entry.category,
                    "configuration_deleted": result["configuration_deleted"],
                },
            ))
            if result["configuration_deleted"]:
                await session.delete(configuration)
            else:
                await session.delete(entry)
                configuration.updated_by = actor_id
            await session.commit()
            return result

    async def create_element(
        self, *, owner_id: str, kind: str, name: str, description: str = "", metadata: dict | None = None
    ) -> ElementAsset:
        if kind not in ELEMENT_KINDS:
            raise ValueError("元素类型必须是 actor、prop、scene、costume 或 effect")
        if not name.strip():
            raise ValueError("元素名称不能为空")
        async with self.sessions() as session:
            locked_owner = await session.scalar(
                select(PlatformUser.id).where(PlatformUser.id == owner_id).with_for_update()
            )
            if not locked_owner:
                raise ValueError("用户不存在")
            existing_count = int(await session.scalar(
                select(func.count()).select_from(ElementAsset).where(ElementAsset.owner_id == owner_id)
            ) or 0)
            if existing_count >= MAX_ELEMENT_ASSETS_PER_OWNER:
                raise ValueError(f"元素数量已达到 {MAX_ELEMENT_ASSETS_PER_OWNER} 项配额")
            element = ElementAsset(
                owner_id=owner_id,
                kind=kind,
                name=name.strip()[:160],
                description=description.strip(),
                metadata_json=metadata or {},
            )
            session.add(element)
            await session.commit()
            return element

    async def _loaded_element(self, session, element_id: str) -> ElementAsset | None:
        return await session.scalar(
            select(ElementAsset).options(selectinload(ElementAsset.files))
            .where(ElementAsset.id == element_id)
            .execution_options(populate_existing=True)
        )

    async def get_element(self, element_id: str, owner_id: str) -> ElementAsset | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(ElementAsset).options(selectinload(ElementAsset.files)).where(
                    ElementAsset.id == element_id, ElementAsset.owner_id == owner_id
                )
            )

    async def list_all_elements(self, owner_id: str, kind: str) -> list[ElementAsset]:
        """Every element of one kind the owner holds, newest first; bounded by the owner quota."""
        if kind not in ELEMENT_KINDS:
            raise ValueError("无效元素类型")
        async with self.sessions() as session:
            return list((await session.scalars(
                select(ElementAsset).options(selectinload(ElementAsset.files))
                .where(ElementAsset.owner_id == owner_id, ElementAsset.kind == kind)
                .order_by(ElementAsset.updated_at.desc())
            )).all())

    async def list_elements(
        self, owner_id: str, kind: str, page: int, page_size: int, task_id: str | None = None, folder: str | None = None,
    ) -> tuple[list[ElementAsset], int]:
        """``folder`` narrows to one folder's elements, or to the unfiled ones with ``ELEMENT_FOLDER_UNFILED``."""
        if kind not in ELEMENT_KINDS:
            raise ValueError("无效元素类型")
        if task_id:
            # Project scope lives in JSON metadata; filtering in Python keeps SQLite
            # and PostgreSQL identical, and the per-owner quota bounds the scan.
            scoped = [
                item for item in await self.list_all_elements(owner_id, kind)
                if element_in_task(item.metadata_json, task_id)
            ]
            if folder:
                placed = await self.element_folder_ids(owner_id, [item.id for item in scoped])
                scoped = [
                    item for item in scoped
                    if (item.id not in placed if folder == ELEMENT_FOLDER_UNFILED else placed.get(item.id) == folder)
                ]
            start = (page - 1) * page_size
            return scoped[start:start + page_size], len(scoped)
        where = [ElementAsset.owner_id == owner_id, ElementAsset.kind == kind]
        if folder == ELEMENT_FOLDER_UNFILED:
            where.append(ElementAsset.id.not_in(select(ElementFolderMember.element_id)))
        elif folder:
            where.append(ElementAsset.id.in_(select(ElementFolderMember.element_id).where(ElementFolderMember.folder_id == folder)))
        async with self.sessions() as session:
            total = int(await session.scalar(select(func.count()).select_from(ElementAsset).where(*where)) or 0)
            items = list((await session.scalars(
                select(ElementAsset).options(selectinload(ElementAsset.files)).where(*where)
                .order_by(ElementAsset.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )).all())
            return items, total

    async def merge_element_metadata(self, element_id: str, owner_id: str, patch: dict) -> ElementAsset:
        """Shallow-merge metadata; the model3d record is owned by the model upload path."""
        async with self.sessions() as session:
            element = await session.get(ElementAsset, element_id)
            if not element or element.owner_id != owner_id:
                raise ValueError("元素不存在")
            metadata = dict(element.metadata_json or {})
            metadata.update({key: value for key, value in patch.items() if key != "model3d"})
            element.metadata_json = metadata
            await session.commit()
            loaded = await self._loaded_element(session, element.id)
            assert loaded is not None
            return loaded

    async def link_element_to_task(self, element_id: str, owner_id: str, task_id: str) -> ElementAsset:
        """Make an existing library asset visible to another project without copying it."""
        async with self.sessions() as session:
            element = await session.get(ElementAsset, element_id)
            if not element or element.owner_id != owner_id:
                raise ValueError("元素不存在")
            element.metadata_json = link_task(element.metadata_json, task_id)
            await session.commit()
            loaded = await self._loaded_element(session, element.id)
            assert loaded is not None
            return loaded

    async def unlink_element_from_task(self, element_id: str, owner_id: str, task_id: str) -> ElementAsset:
        """Take a shared library asset out of one project; the other projects keep it."""
        async with self.sessions() as session:
            element = await session.get(ElementAsset, element_id)
            if not element or element.owner_id != owner_id:
                raise ValueError("元素不存在")
            element.metadata_json = unlink_task(element.metadata_json, task_id)
            await session.commit()
            loaded = await self._loaded_element(session, element.id)
            assert loaded is not None
            return loaded

    async def update_element(self, element_id: str, owner_id: str, *, name: str | None, description: str | None) -> ElementAsset:
        async with self.sessions() as session:
            element = await session.get(ElementAsset, element_id)
            if not element or element.owner_id != owner_id:
                raise ValueError("元素不存在")
            if name is not None:
                if not name.strip():
                    raise ValueError("元素名称不能为空")
                element.name = name.strip()[:160]
            if description is not None:
                element.description = description.strip()
            element.version += 1
            await session.commit()
            loaded = await self._loaded_element(session, element.id)
            assert loaded is not None
            return loaded

    async def set_element_variant(self, element_id: str, owner_id: str, variant: dict | None) -> ElementAsset:
        """Set or clear an actor element's derived-look facts; nothing else on its metadata moves."""
        async with self.sessions() as session:
            element = await session.get(ElementAsset, element_id)
            if not element or element.owner_id != owner_id:
                raise ValueError("元素不存在")
            if element.kind != "actor":
                raise ValueError("只有数字演员可以设为衍生形象")
            metadata = dict(element.metadata_json or {})
            if variant is None:
                metadata.pop("variant", None)
            else:
                metadata["variant"] = dict(variant)
            element.metadata_json = metadata
            element.version += 1
            await session.commit()
            loaded = await self._loaded_element(session, element.id)
            assert loaded is not None
            return loaded

    async def set_prop_length(self, element_id: str, owner_id: str, length_cm: float | None) -> ElementAsset:
        """Set or clear a prop's stated longest side; nothing else on its metadata moves."""
        async with self.sessions() as session:
            element = await session.get(ElementAsset, element_id)
            if not element or element.owner_id != owner_id:
                raise ValueError("元素不存在")
            if element.kind != "prop":
                raise ValueError("只有拍摄道具可以设置尺寸")
            metadata = dict(element.metadata_json or {})
            if length_cm is None:
                metadata.pop("prop_length_cm", None)
            else:
                metadata["prop_length_cm"] = float(length_cm)
            element.metadata_json = metadata
            element.version += 1
            await session.commit()
            loaded = await self._loaded_element(session, element.id)
            assert loaded is not None
            return loaded

    async def add_element_file(
        self,
        *,
        element_id: str,
        owner_id: str,
        slot: str,
        storage_path: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        model_metadata: dict | None = None,
        before_commit: DeletionStorageHook | None = None,
    ) -> StoredElementFileResult:
        result: StoredElementFileResult | None = None
        cancellation_requested = False
        try:
            async with self.sessions() as session:
                await self._lock_element_storage_budget(session)
                locked_owner = await session.scalar(
                    select(PlatformUser.id).where(PlatformUser.id == owner_id).with_for_update()
                )
                if not locked_owner:
                    raise ValueError("用户不存在")
                element = await session.scalar(
                    select(ElementAsset).options(selectinload(ElementAsset.files))
                    .where(ElementAsset.id == element_id)
                    .with_for_update()
                )
                if not element or element.owner_id != owner_id:
                    raise ValueError("元素不存在")
                is_3d_model = mime_type == "model/gltf-binary"
                if is_3d_model and (element.kind not in {"prop", "scene"} or slot != "model_glb"):
                    raise ValueError("3D 模型只允许绑定到场景或道具的 model_glb 槽位")
                if slot == "model_glb" and not is_3d_model:
                    raise ValueError("model_glb 槽位只接受 GLB 3D 模型")
                if element.kind == "actor":
                    look_view = slot in LOOK_VIEW_SLOTS and not _wants_identity_views(element)
                    if slot not in ACTOR_VIEW_SLOT_ORDER and not look_view:
                        raise ValueError("演员图片必须使用规定的身份视图槽位")
                    position = ACTOR_FILE_SLOT_ORDER.index(slot)
                else:
                    if not re.fullmatch(r"[a-z0-9_-]{1,64}", slot):
                        raise ValueError("文件槽位无效")
                    position = len(element.files)
                existing = next((item for item in element.files if item.slot == slot), None)
                owner_usage = int(await session.scalar(
                    select(func.coalesce(func.sum(ElementFile.size_bytes), 0))
                    .select_from(ElementFile)
                    .join(ElementAsset, ElementFile.element_id == ElementAsset.id)
                    .where(ElementAsset.owner_id == owner_id)
                ) or 0)
                projected_usage = owner_usage - (existing.size_bytes if existing else 0) + size_bytes
                if size_bytes < 0 or projected_usage > MAX_ELEMENT_STORAGE_BYTES:
                    raise ValueError("元素资产存储空间已达到账号配额")
                global_usage = int(await session.scalar(
                    select(func.coalesce(func.sum(ElementFile.size_bytes), 0)).select_from(ElementFile)
                ) or 0)
                projected_global_usage = global_usage - (existing.size_bytes if existing else 0) + size_bytes
                if projected_global_usage > MAX_GLOBAL_ELEMENT_STORAGE_BYTES:
                    raise ValueError("元素资产已达到服务全局存储配额")
                replaced_storage_path = existing.storage_path if existing else None
                replaced_file = _deleted_element_file_record(existing) if existing else None
                if existing:
                    existing.storage_path = storage_path
                    existing.mime_type = mime_type
                    existing.size_bytes = size_bytes
                    existing.sha256 = sha256
                    existing.position = position
                else:
                    element.files.append(ElementFile(
                        element_id=element.id,
                        slot=slot,
                        position=position,
                        storage_path=storage_path,
                        mime_type=mime_type,
                        size_bytes=size_bytes,
                        sha256=sha256,
                    ))
                element.version += 1
                if is_3d_model and model_metadata is not None:
                    element.metadata_json = {**(element.metadata_json or {}), "model3d": model_metadata}
                slots = {item.slot for item in element.files}
                slots.add(slot)
                element.status = "ready" if (
                    not _wants_identity_views(element) or actor_views_complete(slots)
                ) else "draft"
                storage_cleanup = (
                    await before_commit((replaced_file,))
                    if before_commit is not None and replaced_file is not None
                    else None
                )
                audit_details: dict[str, object] = {
                    "slot": slot,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "replaced": existing is not None,
                }
                if storage_cleanup:
                    audit_details["storage_cleanup"] = storage_cleanup
                session.add(AuditEvent(
                    actor_id=owner_id,
                    action="element.file.upload",
                    resource_type="element",
                    resource_id=element.id,
                    details=audit_details,
                ))
                cancellation_requested = await _commit_deletion_with_cancellation_boundary(session)
                result = StoredElementFileResult(
                    element=element,
                    replaced_storage_path=replaced_storage_path,
                )
        except BaseException as exc:
            if result is not None:
                raise StorageMutationCommittedWithError(result, exc) from exc
            raise
        assert result is not None
        if cancellation_requested:
            raise StorageMutationCommittedWithError(result, asyncio.CancelledError())
        return result

    async def delete_element_file(
        self,
        element_id: str,
        file_id: str,
        owner_id: str,
        *,
        before_commit: DeletionStorageHook | None = None,
    ) -> DeletedElementFileResult:
        result: DeletedElementFileResult | None = None
        cancellation_requested = False
        try:
            async with self.sessions() as session:
                element = await session.scalar(
                    select(ElementAsset)
                    .options(selectinload(ElementAsset.files))
                    .where(
                        ElementAsset.id == element_id,
                        ElementAsset.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                if not element:
                    raise ValueError("元素不存在")
                target = next((item for item in element.files if item.id == file_id), None)
                if target is None:
                    raise ValueError("元素文件不存在")

                deleted_file = _deleted_element_file_record(target)
                element.files.remove(target)
                if element.kind == "actor":
                    for item in element.files:
                        item.position = ACTOR_FILE_SLOT_ORDER.index(item.slot)
                else:
                    for position, item in enumerate(element.files):
                        item.position = position
                if target.slot == "model_glb":
                    metadata = dict(element.metadata_json or {})
                    metadata.pop("model3d", None)
                    element.metadata_json = metadata
                slots = {item.slot for item in element.files}
                if _wants_identity_views(element):
                    element.status = "ready" if actor_views_complete(slots) else "draft"
                else:
                    element.status = "ready" if element.files else "draft"
                element.version += 1
                storage_cleanup = (
                    await before_commit((deleted_file,))
                    if before_commit is not None
                    else None
                )
                audit_details: dict[str, object] = {
                    "file_id": target.id,
                    "slot": target.slot,
                    "mime_type": target.mime_type,
                    "size_bytes": target.size_bytes,
                }
                if storage_cleanup:
                    audit_details["storage_cleanup"] = storage_cleanup
                session.add(AuditEvent(
                    actor_id=owner_id,
                    action="element.file.delete",
                    resource_type="element",
                    resource_id=element.id,
                    details=audit_details,
                ))
                cancellation_requested = await _commit_deletion_with_cancellation_boundary(session)
                result = DeletedElementFileResult(element=element, deleted_file=deleted_file)
        except BaseException as exc:
            if result is not None:
                raise StorageMutationCommittedWithError(result, exc) from exc
            raise
        assert result is not None
        if cancellation_requested:
            raise StorageMutationCommittedWithError(result, asyncio.CancelledError())
        return result

    async def delete_element(
        self,
        element_id: str,
        owner_id: str,
        *,
        before_commit: DeletionStorageHook | None = None,
    ) -> DeletedElementResult:
        result: DeletedElementResult | None = None
        cancellation_requested = False
        try:
            async with self.sessions() as session:
                element = await session.scalar(
                    select(ElementAsset)
                    .options(selectinload(ElementAsset.files))
                    .where(
                        ElementAsset.id == element_id,
                        ElementAsset.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                if not element:
                    raise ValueError("元素不存在")

                deleted_files = tuple(_deleted_element_file_record(item) for item in element.files)
                await session.execute(
                    delete(RegenerationRequest).where(RegenerationRequest.element_id == element.id)
                )
                await session.delete(element)
                storage_cleanup = (
                    await before_commit(deleted_files)
                    if before_commit is not None
                    else None
                )
                audit_details: dict[str, object] = {
                    "kind": element.kind,
                    "name": element.name,
                    "file_count": len(deleted_files),
                    "size_bytes": sum(item.size_bytes for item in deleted_files),
                }
                if storage_cleanup:
                    audit_details["storage_cleanup"] = storage_cleanup
                session.add(AuditEvent(
                    actor_id=owner_id,
                    action="element.delete",
                    resource_type="element",
                    resource_id=element.id,
                    details=audit_details,
                ))
                cancellation_requested = await _commit_deletion_with_cancellation_boundary(session)
                result = DeletedElementResult(element_id=element_id, deleted_files=deleted_files)
        except BaseException as exc:
            if result is not None:
                raise StorageMutationCommittedWithError(result, exc) from exc
            raise
        assert result is not None
        if cancellation_requested:
            raise StorageMutationCommittedWithError(result, asyncio.CancelledError())
        return result

    async def element_folder_ids(self, owner_id: str, element_ids: list[str]) -> dict[str, str]:
        """``{element_id: folder_id}`` for those of ``element_ids`` that sit in a folder."""
        if not element_ids:
            return {}
        async with self.sessions() as session:
            rows = await session.execute(
                select(ElementFolderMember.element_id, ElementFolderMember.folder_id)
                .join(ElementFolder, ElementFolder.id == ElementFolderMember.folder_id)
                .where(ElementFolder.owner_id == owner_id, ElementFolderMember.element_id.in_(element_ids))
            )
            return {element_id: folder_id for element_id, folder_id in rows.all()}

    async def list_element_folders(self, owner_id: str, kind: str | None = None) -> dict:
        """The owner's folders with counts, joined on live elements so a deleted one is never counted."""
        if kind is not None and kind not in ELEMENT_KINDS:
            raise ValueError("无效元素类型")
        scope = [ElementAsset.owner_id == owner_id, *([ElementAsset.kind == kind] if kind else [])]
        async with self.sessions() as session:
            folders = list((await session.scalars(
                select(ElementFolder).where(ElementFolder.owner_id == owner_id).order_by(ElementFolder.created_at, ElementFolder.id)
            )).all())
            counted = dict((await session.execute(
                select(ElementFolderMember.folder_id, func.count())
                .join(ElementAsset, ElementAsset.id == ElementFolderMember.element_id)
                .where(*scope).group_by(ElementFolderMember.folder_id)
            )).all())
            total = int(await session.scalar(select(func.count()).select_from(ElementAsset).where(*scope)) or 0)
            covers = {
                item.id: item for item in (await session.scalars(
                    select(ElementAsset).options(selectinload(ElementAsset.files))
                    .where(ElementAsset.owner_id == owner_id, ElementAsset.id.in_([f.cover_element_id for f in folders if f.cover_element_id]))
                )).all()
            }
        filed = sum(counted.get(folder.id, 0) for folder in folders)
        return {
            "folders": [
                {"folder": folder, "count": int(counted.get(folder.id, 0)), "cover": covers.get(folder.cover_element_id or "")}
                for folder in folders
            ],
            "total": total,
            "unfiled": max(total - filed, 0),
        }

    async def _owned_element_ids(self, session, owner_id: str, element_ids: list[str]) -> set[str]:
        return set((await session.scalars(
            select(ElementAsset.id).where(ElementAsset.owner_id == owner_id, ElementAsset.id.in_(element_ids))
        )).all())

    @staticmethod
    def _element_folder_name(name: str) -> str:
        label = name.strip()
        if not label:
            raise ValueError("文件夹需要一个名称")
        if len(label) > MAX_ELEMENT_FOLDER_NAME:
            raise ValueError(f"文件夹名称最长 {MAX_ELEMENT_FOLDER_NAME} 个字符")
        return label

    async def _assert_folder_name_free(self, session, owner_id: str, label: str, *, ignoring: str = "") -> None:
        clash = await session.scalar(
            select(ElementFolder.id).where(ElementFolder.owner_id == owner_id, ElementFolder.name == label, ElementFolder.id != ignoring)
        )
        if clash:
            raise ValueError(f"已经有叫「{label}」的文件夹")

    async def create_element_folder(self, owner_id: str, name: str, cover_element_id: str | None = None) -> ElementFolder:
        label = self._element_folder_name(name)
        async with self.sessions() as session:
            # The owner row serializes the count-then-insert of two creates racing for the last slot.
            if not await session.scalar(select(PlatformUser.id).where(PlatformUser.id == owner_id).with_for_update()):
                raise ValueError("用户不存在")
            await self._assert_folder_name_free(session, owner_id, label)
            count = int(await session.scalar(
                select(func.count()).select_from(ElementFolder).where(ElementFolder.owner_id == owner_id)
            ) or 0)
            if count >= MAX_ELEMENT_FOLDERS_PER_OWNER:
                raise ValueError(f"最多 {MAX_ELEMENT_FOLDERS_PER_OWNER} 个文件夹，请先删除不用的")
            if cover_element_id and not await self._owned_element_ids(session, owner_id, [cover_element_id]):
                raise ValueError("封面元素不存在")
            folder = ElementFolder(owner_id=owner_id, name=label, cover_element_id=cover_element_id or None)
            session.add(folder)
            await session.commit()
            return folder

    async def update_element_folder(self, owner_id: str, folder_id: str, *, name: str | None = None, cover_element_id: str | None = "") -> ElementFolder | None:
        """``cover_element_id``: leave out (``""``) to keep the cover, ``None`` to clear it."""
        async with self.sessions() as session:
            folder = await session.get(ElementFolder, folder_id)
            if folder is None or folder.owner_id != owner_id:
                return None
            if name is not None:
                label = self._element_folder_name(name)
                await self._assert_folder_name_free(session, owner_id, label, ignoring=folder_id)
                folder.name = label
            if cover_element_id != "":
                if cover_element_id and not await self._owned_element_ids(session, owner_id, [cover_element_id]):
                    raise ValueError("封面元素不存在")
                folder.cover_element_id = cover_element_id
            await session.commit()
            return folder

    async def delete_element_folder(self, owner_id: str, folder_id: str) -> bool:
        """Remove the folder; its elements stay in the library, unfiled."""
        async with self.sessions() as session:
            folder = await session.get(ElementFolder, folder_id)
            if folder is None or folder.owner_id != owner_id:
                return False
            # Explicit rather than ON DELETE CASCADE: SQLite runs here without foreign-key enforcement.
            await session.execute(delete(ElementFolderMember).where(ElementFolderMember.folder_id == folder_id))
            await session.delete(folder)
            await session.commit()
            return True

    async def move_elements_to_folder(self, owner_id: str, element_ids: list[str], folder_id: str | None) -> int:
        """File the elements in a folder, or take them out with ``None``; refuses all of them if any is not the owner's."""
        wanted = list(dict.fromkeys(element_ids))
        async with self.sessions() as session:
            if await self._owned_element_ids(session, owner_id, wanted) != set(wanted):
                raise LookupError("元素不存在")
            if folder_id is not None:
                folder = await session.get(ElementFolder, folder_id)
                if folder is None or folder.owner_id != owner_id:
                    raise LookupError("文件夹不存在")
            await session.execute(delete(ElementFolderMember).where(ElementFolderMember.element_id.in_(wanted)))
            if folder_id is not None:
                session.add_all(ElementFolderMember(element_id=element_id, folder_id=folder_id) for element_id in wanted)
            await session.commit()
            return len(wanted)

    async def list_desk_poses(self, owner_id: str) -> list[DirectorDeskPose]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(DirectorDeskPose).where(DirectorDeskPose.owner_id == owner_id)
                .order_by(DirectorDeskPose.created_at, DirectorDeskPose.id)
            )).all())

    async def save_desk_pose(self, owner_id: str, name: str, pose: dict) -> DirectorDeskPose:
        """Save under a name; the same name again replaces that pose (names are unique per owner)."""
        label = name.strip()
        if not label:
            raise ValueError("姿势需要一个名称")
        if len(label) > MAX_DESK_POSE_NAME:
            raise ValueError(f"姿势名称最长 {MAX_DESK_POSE_NAME} 个字符")
        async with self.sessions() as session:
            # The owner row serializes the count-then-insert of two saves racing for the last slot.
            locked_owner = await session.scalar(
                select(PlatformUser.id).where(PlatformUser.id == owner_id).with_for_update()
            )
            if not locked_owner:
                raise ValueError("用户不存在")
            record = await session.scalar(
                select(DirectorDeskPose).where(DirectorDeskPose.owner_id == owner_id, DirectorDeskPose.name == label)
            )
            if record is None:
                count = int(await session.scalar(
                    select(func.count()).select_from(DirectorDeskPose).where(DirectorDeskPose.owner_id == owner_id)
                ) or 0)
                if count >= MAX_DESK_POSES_PER_OWNER:
                    raise ValueError(f"最多保存 {MAX_DESK_POSES_PER_OWNER} 个姿势，请先删除不用的")
                record = DirectorDeskPose(owner_id=owner_id, name=label, pose_json=pose)
                session.add(record)
            else:
                record.pose_json = pose
            await session.commit()
            return record

    async def delete_desk_pose(self, owner_id: str, pose_id: str) -> bool:
        async with self.sessions() as session:
            record = await session.get(DirectorDeskPose, pose_id)
            if record is None or record.owner_id != owner_id:
                return False
            await session.delete(record)
            await session.commit()
            return True

    async def request_regeneration(self, element_id: str, owner_id: str, prompt: str) -> RegenerationRequest:
        async with self.sessions() as session:
            element = await session.get(ElementAsset, element_id)
            if not element or element.owner_id != owner_id:
                raise ValueError("元素不存在")
            request = RegenerationRequest(
                element_id=element_id,
                requested_by=owner_id,
                prompt=prompt.strip()[:4000],
                status="queued",
                paid_submission_approved=False,
            )
            session.add(request)
            await session.commit()
            return request

    async def seed_billing_plans(self) -> None:
        plans = (
            ("starter", "创作入门", "每月 500 创作积分", Decimal("29.00"), 500, 30),
            ("studio", "工作室", "每月 3000 创作积分", Decimal("129.00"), 3000, 30),
            ("pro", "专业制作", "每月 10000 创作积分", Decimal("399.00"), 10000, 30),
        )
        async with self.sessions() as session:
            for plan_id, name, description, price, points, days in plans:
                if not await session.get(MembershipPlan, plan_id):
                    session.add(MembershipPlan(
                        id=plan_id, name=name, description=description, price=price,
                        currency="CNY", points=points, duration_days=days, active=True,
                    ))
            await session.commit()

    async def get_plan(self, plan_id: str) -> MembershipPlan | None:
        async with self.sessions() as session:
            return await session.get(MembershipPlan, plan_id)

    async def list_plans(self) -> list[MembershipPlan]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(MembershipPlan).where(MembershipPlan.active.is_(True)).order_by(MembershipPlan.price)
            )).all())

    async def create_order(
        self, *, user_id: str, plan_id: str, provider: str | None, idempotency_key: str
    ) -> PaymentOrder:
        if provider and provider not in PAYMENT_PROVIDERS:
            raise ValueError("不支持的支付渠道")
        if provider == "sandbox" and not settings.payment_sandbox_enabled():
            raise ValueError("沙箱支付未开启")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,120}", idempotency_key):
            raise ValueError("幂等键格式无效")
        async with self.sessions() as session:
            existing = await session.scalar(select(PaymentOrder).where(
                PaymentOrder.user_id == user_id, PaymentOrder.idempotency_key == idempotency_key
            ))
            if existing:
                return existing
            plan = await session.get(MembershipPlan, plan_id)
            if not plan or not plan.active:
                raise ValueError("会员计划不存在")
            order = PaymentOrder(
                user_id=user_id, plan_id=plan.id, provider=provider or "",  # the channel is chosen when paying
                amount=plan.price, currency=plan.currency, status="pending",
                idempotency_key=idempotency_key,
            )
            session.add(order)
            await session.commit()
            return order

    async def list_orders(self, user_id: str, page: int, page_size: int) -> tuple[list[PaymentOrder], int]:
        async with self.sessions() as session:
            total = int(await session.scalar(select(func.count()).select_from(PaymentOrder).where(
                PaymentOrder.user_id == user_id
            )) or 0)
            orders = list((await session.scalars(
                select(PaymentOrder).where(PaymentOrder.user_id == user_id)
                .order_by(PaymentOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )).all())
            return orders, total

    async def get_order(self, order_id: str) -> PaymentOrder | None:
        async with self.sessions() as session:
            return await session.get(PaymentOrder, order_id)

    async def get_membership(self, user_id: str) -> tuple[UserMembership, MembershipPlan] | None:
        async with self.sessions() as session:
            membership = await session.get(UserMembership, user_id)
            if not membership:
                return None
            term = current_term(
                (await session.scalars(select(MembershipTerm).where(MembershipTerm.user_id == user_id))).all(),
                datetime.now(timezone.utc),
            )
            if term and term.plan_id != membership.plan_id:  # a downgrade whose time has come
                membership.plan_id, membership.started_at, membership.expires_at = term.plan_id, term.starts_at, term.expires_at
                await session.commit()
            plan = await session.get(MembershipPlan, membership.plan_id)
            return (membership, plan) if plan else None

    async def effective_entitlements(self, user_id: str) -> dict:
        async with self.sessions() as session:
            terms = (await session.scalars(select(MembershipTerm).where(MembershipTerm.user_id == user_id))).all()
            return entitlements_from(terms, datetime.now(timezone.utc))

    async def frozen_points(self, user_id: str) -> Decimal:
        async with self.sessions() as session:
            balance = await session.get(PointBalance, user_id)
            return balance.frozen if balance else Decimal(0)

    async def point_balance(self, user_id: str) -> tuple[Decimal, Decimal]:
        async with self.sessions() as session:
            balance = await session.get(PointBalance, user_id)
            return (balance.available, balance.held) if balance else (Decimal(0), Decimal(0))

    async def void_sandbox_points(self) -> int:
        """Points from sandbox orders had no money behind them. Charging starts without them; the ledger keeps the trail."""
        voided = 0
        async with self.sessions() as session:
            async with session.begin():
                orders = (await session.scalars(
                    select(PaymentOrder).where(PaymentOrder.provider == "sandbox", PaymentOrder.status == "paid")
                )).all()
                for order in orders:
                    key = f"void:order:{order.id}"
                    if await session.scalar(select(LedgerEntry.id).where(LedgerEntry.idempotency_key == key)):
                        continue
                    credit = await session.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == f"order:{order.id}:points"))
                    if not credit:
                        continue
                    lot = await session.scalar(select(PointLot).where(PointLot.order_id == order.id).with_for_update())
                    unspent = lot.remaining if lot else credit.amount
                    if lot:
                        balance = await session.get(PointBalance, order.user_id, with_for_update=True)
                        if balance:
                            balance.available -= lot.remaining
                        lot.remaining = Decimal(0)
                    session.add(LedgerEntry(
                        user_id=order.user_id, order_id=order.id, asset="points", direction="debit", amount=unspent,
                        currency="PTS", category="reversal", idempotency_key=key,
                        metadata_json={"reason": "sandbox_points_voided", "lot_id": lot.id if lot else None},
                    ))
                    voided += 1
                if voided:
                    session.add(AuditEvent(
                        actor_id=None, action="billing.sandbox_points_voided", resource_type="ledger", resource_id="sandbox",
                        details={"orders": voided},
                    ))
        return voided

    async def expire_points(self) -> int:
        """Lots past their date go to zero, with a ledger line. Someone with a call under way waits for the next pass."""
        now, expired = datetime.now(timezone.utc), 0
        async with self.sessions() as session:
            async with session.begin():
                lots = (await session.scalars(
                    select(PointLot).where(PointLot.expires_at <= now, PointLot.remaining > PointLot.frozen).with_for_update()
                )).all()
                for lot in lots:
                    balance = await session.get(PointBalance, lot.user_id, with_for_update=True)
                    if balance and balance.held > 0:
                        continue
                    # What a refund has set aside stays. If the refund fails it comes back, and goes at a later pass.
                    amount = lot.remaining - lot.frozen
                    key = f"expire:{lot.id}:{lot.remaining}"
                    lot.remaining = lot.frozen
                    if balance:
                        balance.available -= amount
                    session.add(LedgerEntry(
                        user_id=lot.user_id, order_id=lot.order_id, asset="points", direction="debit", amount=amount,
                        currency="PTS", category="points_expired", idempotency_key=key,
                        metadata_json={"lot_id": lot.id},
                    ))
                    expired += 1
        return expired

    async def billing_differences(self, *, settled_before: datetime, sample: int = 20) -> dict:
        """R3 and R5, and that what calls came to was what was taken. Worked out when asked for."""
        async with self.sessions() as session:
            orders = (await session.scalars(select(PaymentOrder).where(PaymentOrder.status.in_(PAID_ORDER_STATES)))).all()
            lots = (await session.scalars(select(PointLot))).all()
            terms = (await session.scalars(select(MembershipTerm))).all()
            entries = (await session.scalars(select(LedgerEntry).where(LedgerEntry.asset == "points"))).all()
            balances = (await session.scalars(select(PointBalance))).all()
            charged = (await session.scalars(select(UsageCharge).where(UsageCharge.billing_mode == "charged"))).all()
            plans = {plan.id: plan for plan in (await session.scalars(select(MembershipPlan))).all()}
        lot_by_order = {lot.order_id: lot for lot in lots if lot.order_id}
        term_orders = {term.order_id for term in terms}
        by_key = {entry.idempotency_key: entry for entry in entries}

        r3, legacy = [], {}
        for order in orders:
            credit = by_key.get(f"order:{order.id}:points")
            lot = lot_by_order.get(order.id)
            if order.provider == "sandbox" and not lot:
                # From before lots existed. Until voided they sit outside the balance.
                voided = by_key.get(f"void:order:{order.id}")
                if credit and not voided:
                    legacy[order.user_id] = legacy.get(order.user_id, Decimal(0)) + credit.amount
                continue
            plan = plans.get(order.plan_id)
            problems = [
                name for name, bad in (
                    ("no_ledger_credit", not credit), ("no_lot", not lot), ("no_term", order.id not in term_orders),
                    ("wrong_amount", bool(plan and credit and credit.amount != Decimal(plan.points))),
                    ("lot_does_not_match", bool(plan and lot and lot.granted != Decimal(plan.points))),
                ) if bad
            ]
            if problems:
                r3.append({"order_id": order.id, "problems": problems})

        users = {entry.user_id for entry in entries} | {lot.user_id for lot in lots} | {balance.user_id for balance in balances}
        balance_of = {balance.user_id: balance for balance in balances}
        r5 = []
        for user_id in users:
            ledger = sum(
                (entry.amount if entry.direction == "credit" else -entry.amount) for entry in entries if entry.user_id == user_id
            ) - legacy.get(user_id, Decimal(0))
            in_lots = sum((lot.remaining for lot in lots if lot.user_id == user_id), Decimal(0))
            balance = balance_of.get(user_id)
            on_balance = (balance.available + balance.held + balance.frozen) if balance else Decimal(0)
            if ledger != in_lots or in_lots != on_balance or (balance and balance.available < 0):
                r5.append({"user_id": user_id, "ledger": str(ledger), "lots": str(in_lots), "balance": str(on_balance)})

        usage = []
        for charge in charged:
            occurred = charge.occurred_at if charge.occurred_at.tzinfo else charge.occurred_at.replace(tzinfo=timezone.utc)
            if charge.status != "success" or charge.points <= 0 or occurred > settled_before:
                continue
            debit = by_key.get(f"usage:{charge.usage_id}")
            taken = debit.amount + Decimal(str((debit.metadata_json or {}).get("shortfall") or 0)) if debit else None
            if taken != Decimal(str(charge.points)):
                usage.append({"usage_id": charge.usage_id, "expected": str(charge.points), "taken": str(taken)})
        return {
            "r3": {"orders": len(orders), "differences": len(r3), "samples": r3[:sample]},
            "r5": {"users": len(users), "differences": len(r5), "samples": r5[:sample]},
            "usage_vs_ledger": {"checked": len(charged), "differences": len(usage), "samples": usage[:sample]},
            "sandbox_points_not_voided": {user_id: str(amount) for user_id, amount in legacy.items()},
        }

    async def _apply_paid_order(self, session, order: PaymentOrder, event_id: str, *, late_is_paid: bool = False) -> None:
        """The one place an order becomes paid: order, points and membership move together in the caller's transaction.

        Every payment source ends here. Only the update that moves the order out of pending grants anything, so a
        replay or two sources arriving together grant once. ``late_is_paid`` is for money a channel says arrived after
        the order was closed: it was still received, so what it bought is still owed.
        """
        if order.status == "paid":
            if order.provider_event_id != event_id:
                raise ValueError("订单已由其他支付事件完成")
            return
        open_states = ("pending", "closed") if late_is_paid else ("pending",)
        if order.status not in open_states:
            raise ValueError("订单状态不允许支付")
        plan = await session.get(MembershipPlan, order.plan_id)
        if not plan:
            raise ValueError("会员计划不存在")
        now = datetime.now(timezone.utc)
        moved = await session.execute(
            update(PaymentOrder)
            .where(PaymentOrder.id == order.id, PaymentOrder.status.in_(open_states))
            .values(status="paid", provider_event_id=event_id, paid_at=now)
        )
        await session.refresh(order)
        if moved.rowcount != 1:
            if order.provider_event_id != event_id:
                raise ValueError("订单已由其他支付事件完成")
            return
        session.add(LedgerEntry(
            user_id=order.user_id,
            order_id=order.id,
            asset="points",
            direction="credit",
            amount=Decimal(plan.points),
            currency="PTS",
            category="membership_purchase",
            idempotency_key=f"order:{order.id}:points",
            metadata_json={"plan_id": plan.id},
        ))
        membership = await session.get(UserMembership, order.user_id, with_for_update=True)
        period = timedelta(days=plan.duration_days)
        starts_at = now
        if membership:
            current_end = membership.expires_at
            if current_end.tzinfo is None:  # SQLite hands back naive datetimes
                current_end = current_end.replace(tzinfo=timezone.utc)
            current_plan = await session.get(MembershipPlan, membership.plan_id)
            if membership.status == "active" and current_end > now:
                if membership.plan_id == plan.id:
                    # 提前续费不吃亏：新周期接在旧周期后面。
                    starts_at = current_end
                    membership.expires_at = current_end + period
                elif current_plan and plan.price < current_plan.price:
                    # 降级不打断已付的周期：等当前周期结束再生效。
                    starts_at = current_end
                else:
                    membership.plan_id, membership.started_at, membership.expires_at = plan.id, now, now + period
            else:
                membership.plan_id, membership.status = plan.id, "active"
                membership.started_at, membership.expires_at = now, now + period
        else:
            session.add(UserMembership(
                user_id=order.user_id, plan_id=plan.id, status="active", started_at=now, expires_at=now + period,
            ))
        expires_at = starts_at + period
        session.add(MembershipTerm(
            user_id=order.user_id, order_id=order.id, plan_id=plan.id, entitlements=plan_entitlements(plan.id),
            starts_at=starts_at, expires_at=expires_at,
        ))
        session.add(PointLot(
            user_id=order.user_id, order_id=order.id, granted=Decimal(plan.points), remaining=Decimal(plan.points),
            unit_value_minor=(order.amount * 100 / plan.points) if plan.points else Decimal(0), expires_at=expires_at,
        ))
        balance = await session.get(PointBalance, order.user_id, with_for_update=True)
        if balance:
            balance.available += Decimal(plan.points)
        else:
            session.add(PointBalance(user_id=order.user_id, available=Decimal(plan.points), held=Decimal(0)))
        _notify(session, order.user_id, "order_paid", f"order_paid:{order.id}", order_id=order.id, plan_name=plan.name, points=plan.points)

    async def confirm_paid_order(self, order_id: str, provider_event_id: str) -> PaymentOrder:
        async with self.sessions() as session:
            async with session.begin():
                order = await session.get(PaymentOrder, order_id, with_for_update=True)
                if not order:
                    raise ValueError("订单不存在")
                if order.provider == "sandbox" and not settings.payment_sandbox_enabled():
                    raise ValueError("沙箱支付未开启")
                await self._apply_paid_order(session, order, provider_event_id)
            return order

    async def list_point_rates(self) -> list[PointRate]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(PointRate).order_by(PointRate.model, PointRate.effective_from.desc())
            )).all())

    async def add_point_rate(self, *, actor_id: str, **fields) -> PointRate:
        """A new price from now or later. The past is not rewritten: charges are explained by the rate of their time."""
        async with self.sessions() as session:
            rate = PointRate(created_by=actor_id, **fields)
            session.add(rate)
            await session.flush()
            session.add(AuditEvent(
                actor_id=actor_id, action="pricing.rate_add", resource_type="point_rate", resource_id=rate.id,
                details={key: str(value) for key, value in fields.items()},
            ))
            await session.commit()
            return rate

    async def save_usage_charges(self, rows: Sequence[dict]) -> int:
        """Adds the rows not already kept and says how many that was; loading the same file twice adds nothing."""
        saved = 0
        async with self.sessions() as session:
            known = set((await session.scalars(
                select(UsageCharge.usage_id).where(UsageCharge.usage_id.in_([row["usage_id"] for row in rows]))
            )).all())
        for row in rows:
            if row["usage_id"] in known:
                continue
            known.add(row["usage_id"])
            async with self.sessions() as session:
                session.add(UsageCharge(**row))
                try:
                    await session.commit()
                    saved += 1
                except IntegrityError:  # another process loaded it first
                    await session.rollback()
        return saved

    async def list_usage_charges(self, *, since: datetime | None = None) -> list[UsageCharge]:
        async with self.sessions() as session:
            query = select(UsageCharge).order_by(UsageCharge.occurred_at)
            if since is not None:
                query = query.where(UsageCharge.occurred_at >= since)
            return list((await session.scalars(query)).all())

    async def wallet(self, user_id: str) -> WalletSnapshot:
        async with self.sessions() as session:
            entries = list((await session.scalars(
                select(LedgerEntry).where(LedgerEntry.user_id == user_id).order_by(LedgerEntry.created_at.desc())
            )).all())
            points = sum(
                (entry.amount if entry.direction == "credit" else -entry.amount)
                for entry in entries if entry.asset == "points"
            )
            money: dict[str, Decimal] = {}
            for entry in entries:
                if entry.asset == "money":
                    money.setdefault(entry.currency, Decimal("0"))
                    money[entry.currency] += entry.amount if entry.direction == "credit" else -entry.amount
            return WalletSnapshot(points=Decimal(points), money=money, entries=entries)

    async def open_payment_attempt(
        self, *, order_id: str, user_id: str, provider: str, merchant_id: str, now: datetime, lifetime: timedelta,
        keep_if_left: timedelta, in_flight_for: timedelta,
    ) -> tuple[PaymentAttempt, bool, list[PaymentAttempt]]:
        """The attempt to show for this order, whether it is new, and the other open ones to close at their channels.

        It is saved before the channel hears of it, so a notification can never arrive for a trade unknown here.
        """
        async with self.sessions() as session:
            async with session.begin():
                # A write first, so two requests take turns on any database. SQLite has no row locks to rely on.
                await session.execute(update(PaymentOrder).where(PaymentOrder.id == order_id).values(provider=provider))
                order = await session.get(PaymentOrder, order_id, with_for_update=True)
                if not order or order.user_id != user_id:
                    raise LookupError("订单不存在")
                if order.status != "pending":
                    raise ValueError("订单状态不允许支付")
                if order.currency != "CNY" or order.amount <= 0:
                    raise ValueError("该订单不能在线支付")
                attempts = (await session.scalars(select(PaymentAttempt).where(
                    PaymentAttempt.order_id == order.id, PaymentAttempt.status == "pending",
                ))).all()
                others = []
                for attempt in attempts:
                    if attempt.provider != provider:
                        others.append(attempt)
                    elif attempt.qr_code and _aware_utc(attempt.expires_at) > now + keep_if_left:
                        return attempt, False, [item for item in attempts if item.id != attempt.id]
                    elif not attempt.qr_code and _aware_utc(attempt.created_at) > now - in_flight_for:
                        raise PaymentInFlight("正在生成付款码，请稍候")
                    else:
                        others.append(attempt)
                attempt = PaymentAttempt(
                    order_id=order.id, user_id=order.user_id, provider=provider, merchant_id=merchant_id,
                    out_trade_no=new_merchant_no("P"), amount_minor=int(order.amount * 100), currency=order.currency,
                    expires_at=now + lifetime,
                )
                session.add(attempt)
            return attempt, True, others

    async def set_attempt_qr(self, attempt_id: str, qr_code: str) -> bool:
        async with self.sessions() as session:
            moved = await session.execute(
                update(PaymentAttempt)
                .where(PaymentAttempt.id == attempt_id, PaymentAttempt.status == "pending")
                .values(qr_code=qr_code)
            )
            await session.commit()
            return moved.rowcount == 1

    async def end_attempt(self, attempt_id: str, status: str) -> bool:
        """Closed or failed, from pending only: a payment that got there first stays."""
        async with self.sessions() as session:
            moved = await session.execute(
                update(PaymentAttempt)
                .where(PaymentAttempt.id == attempt_id, PaymentAttempt.status == "pending")
                .values(status=status, qr_code=None)
            )
            await session.commit()
            return moved.rowcount == 1

    async def open_attempts(self, order_id: str) -> list[PaymentAttempt]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(PaymentAttempt)
                .where(PaymentAttempt.order_id == order_id, PaymentAttempt.status == "pending")
                .order_by(PaymentAttempt.created_at.desc())
            )).all())

    async def claim_attempt_query(self, attempt_id: str, now: datetime, every: timedelta) -> bool:
        """Whether it is this caller's turn to ask the channel. Any number of tabs and workers ask once between them."""
        async with self.sessions() as session:
            moved = await session.execute(
                update(PaymentAttempt)
                .where(
                    PaymentAttempt.id == attempt_id,
                    PaymentAttempt.status.in_(("pending", "closed")),
                    or_(PaymentAttempt.last_queried_at.is_(None), PaymentAttempt.last_queried_at <= now - every),
                )
                .values(last_queried_at=now)
            )
            await session.commit()
            return moved.rowcount == 1

    async def attempts_due(self, *, now: datetime, settled_after: timedelta, every: timedelta, limit: int) -> list[PaymentAttempt]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(PaymentAttempt)
                .where(
                    PaymentAttempt.status == "pending",
                    PaymentAttempt.created_at <= now - settled_after,
                    or_(PaymentAttempt.last_queried_at.is_(None), PaymentAttempt.last_queried_at <= now - every),
                )
                .order_by(PaymentAttempt.created_at).limit(limit)
            )).all())

    async def closed_attempts_still_payable(
        self, *, providers: Sequence[str], now: datetime, code_lifetime: timedelta, every: timedelta, limit: int,
    ) -> list[PaymentAttempt]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(PaymentAttempt)
                .where(
                    PaymentAttempt.status == "closed",
                    PaymentAttempt.provider.in_(providers),
                    PaymentAttempt.created_at >= now - code_lifetime,
                    or_(PaymentAttempt.last_queried_at.is_(None), PaymentAttempt.last_queried_at <= now - every),
                )
                .order_by(PaymentAttempt.created_at).limit(limit)
            )).all())

    async def apply_channel_payment(
        self, *, provider: str, trade: ChannelTrade, source: str, event_id: str = "", payload_sha256: str = "",
    ) -> str:
        """What a channel reports as paid, from a notification or a query, in any order and any number of times.

        One transaction, so credit and record cannot part. What it did comes back as a word; ``unknown`` and ``mismatch``
        grant nothing and are not errors, because the channel's retries could not change them.
        """
        async with self.sessions() as session:
            async with session.begin():
                order_id = await session.scalar(select(PaymentAttempt.order_id).where(
                    PaymentAttempt.provider == provider, PaymentAttempt.out_trade_no == trade.out_trade_no,
                ))
                if not order_id:
                    _payment_alert(session, "payment.unknown_trade", None, provider=provider, out_trade_no=trade.out_trade_no, source=source)
                    return "unknown"
                # Order first, then attempt, everywhere: two paths taking them the other way round would deadlock.
                order = await session.get(PaymentOrder, order_id, with_for_update=True)
                attempt = await session.scalar(select(PaymentAttempt).where(
                    PaymentAttempt.provider == provider, PaymentAttempt.out_trade_no == trade.out_trade_no,
                ).with_for_update())
                outcome = await self._settle_attempt(session, order, attempt, trade, source)
                if event_id and not await session.scalar(select(PaymentWebhookEvent.id).where(
                    PaymentWebhookEvent.provider == provider, PaymentWebhookEvent.event_id == event_id,
                )):
                    session.add(PaymentWebhookEvent(
                        provider=provider, event_id=event_id, payload_sha256=payload_sha256, order_id=order.id, result=outcome,
                    ))
                return outcome

    async def _settle_attempt(self, session, order: PaymentOrder, attempt: PaymentAttempt, trade: ChannelTrade, source: str) -> str:
        wrong = [name for name, bad in (
            ("merchant", trade.merchant_id != attempt.merchant_id),
            ("amount", trade.amount_minor != attempt.amount_minor),
            ("currency", trade.currency != attempt.currency),
            ("channel_trade_no", not trade.channel_trade_no),
            ("other_trade", attempt.status == "paid" and trade.channel_trade_no != attempt.channel_trade_no),
        ) if bad]
        if wrong:
            _payment_alert(
                session, "payment.mismatch", order, attempt_id=attempt.id, wrong=wrong, source=source,
                reported_amount=trade.amount_minor, expected_amount=attempt.amount_minor,
            )
            await session.execute(
                update(PaymentAttempt).where(PaymentAttempt.id == attempt.id, PaymentAttempt.status == "pending").values(status="mismatch")
            )
            return "mismatch"
        was_closed = attempt.status != "pending"
        now = datetime.now(timezone.utc)
        moved = await session.execute(
            update(PaymentAttempt)
            .where(PaymentAttempt.id == attempt.id, PaymentAttempt.status != "paid")
            .values(
                status="paid", channel_trade_no=trade.channel_trade_no, settled_by=source, qr_code=None,
                # Channels report China time. In UTC it means the same on a database that drops the offset.
                paid_at=(trade.paid_at or now).astimezone(timezone.utc),
            )
        )
        if moved.rowcount != 1:
            return "replayed"
        if order.status not in ("pending", "closed"):
            # The first payment bought this. The second is someone's money with nothing behind it, so it goes back.
            session.add(PaymentRefund(
                order_id=order.id, attempt_id=attempt.id, user_id=order.user_id, provider=attempt.provider,
                out_trade_no=attempt.out_trade_no, out_refund_no=new_merchant_no("R"), refund_minor=attempt.amount_minor,
                total_minor=attempt.amount_minor, reason="duplicate_payment",
            ))
            _payment_alert(session, "payment.duplicate", order, attempt_id=attempt.id, source=source)
            return "duplicate"
        was_closed = was_closed or order.status == "closed"
        await self._apply_paid_order(session, order, f"{attempt.provider}:{trade.channel_trade_no}", late_is_paid=True)
        order.provider = attempt.provider
        if was_closed:
            _payment_alert(session, "payment.late", order, attempt_id=attempt.id, source=source)
            return "late"
        return "applied"

    async def note_refunded_elsewhere(self, attempt: PaymentAttempt) -> None:
        """Paid and refunded at the channel with nothing noticed here. Nothing was granted and nothing is owed; someone should know."""
        async with self.sessions() as session:
            order = await session.get(PaymentOrder, attempt.order_id)
            _payment_alert(session, "payment.refunded_elsewhere", order, attempt_id=attempt.id)
            await session.commit()

    async def close_order(self, order_id: str) -> bool:
        async with self.sessions() as session:
            moved = await session.execute(
                update(PaymentOrder).where(PaymentOrder.id == order_id, PaymentOrder.status == "pending").values(status="closed")
            )
            await session.commit()
            return moved.rowcount == 1

    async def close_abandoned_orders(self, *, created_before: datetime) -> int:
        """Unpaid for long enough that the price it locked may no longer be right. Sandbox orders are left alone."""
        async with self.sessions() as session:
            moved = await session.execute(
                update(PaymentOrder)
                .where(
                    PaymentOrder.status == "pending", PaymentOrder.provider != "sandbox", PaymentOrder.created_at <= created_before,
                    ~exists().where(PaymentAttempt.order_id == PaymentOrder.id, PaymentAttempt.status == "pending"),
                )
                .values(status="closed")
            )
            await session.commit()
            return moved.rowcount

    async def _lock_order(self, session, order_id: str) -> PaymentOrder | None:
        """A write first, so two requests take turns on any database. SQLite has no row locks to rely on."""
        await session.execute(update(PaymentOrder).where(PaymentOrder.id == order_id).values(status=PaymentOrder.status))
        return await session.get(PaymentOrder, order_id, with_for_update=True)

    async def _refund_position(self, session, order: PaymentOrder, *, lock_points: bool = False) -> dict:
        """What can still be given back on this order, and what stands in the way.

        ``lock_points`` is for a caller about to change them: spending goes on at the same moment, without the order.
        Balance before lots, the order charging takes them in.
        """
        attempt = next((
            item for item in (await session.scalars(select(PaymentAttempt).where(
                PaymentAttempt.order_id == order.id, PaymentAttempt.status == "paid", PaymentAttempt.provider == order.provider,
            ))).all()
            if f"{item.provider}:{item.channel_trade_no}" == order.provider_event_id
        ), None)
        refunds = (await session.scalars(select(PaymentRefund).where(
            PaymentRefund.order_id == order.id, PaymentRefund.reason == REFUND_ON_REQUEST,
        ))).all()
        balance = await session.get(PointBalance, order.user_id, with_for_update=lock_points or None, populate_existing=lock_points)
        lots = select(PointLot).where(PointLot.order_id == order.id)
        lot = await session.scalar(lots.with_for_update().execution_options(populate_existing=True) if lock_points else lots)
        refunded = sum(item.refund_minor for item in refunds if item.status == "succeeded")
        flagged = await session.scalar(select(func.count()).select_from(ReconItem).where(
            ReconItem.order_id == order.id, ReconItem.status == "open", ReconItem.severity == "critical",
        ))
        spendable = min(lot.remaining - lot.frozen, balance.available) if lot and balance else Decimal(0)
        paid = attempt.amount_minor if attempt else 0
        points = max(spendable, Decimal(0))
        return {
            "attempt": attempt, "lot": lot, "balance": balance, "refundable_minor": paid - refunded, "refunded_minor": refunded,
            "paid_minor": paid, "granted": lot.granted if lot else Decimal(0), "remaining": lot.remaining if lot else Decimal(0),
            "freezable": points, "suggested_points": points,
            "suggested_minor": min(int(paid * points // lot.granted), paid - refunded) if lot and lot.granted else 0,
            "open_refund": any(item.status in REFUND_OPEN for item in refunds), "flagged": bool(flagged),
        }

    @staticmethod
    def _refund_blocker(order: PaymentOrder, position: dict) -> str | None:
        if order.status not in ("paid", "partially_refunded"):
            return "订单状态不允许退款"
        if not position["attempt"]:
            return "这笔订单没有真实的渠道收款，不能退款"
        if position["open_refund"]:
            return "这笔订单已有退款在处理中"
        if position["flagged"]:
            return "这笔订单有未处理的严重对账差异，处理后才能退款"
        if position["refundable_minor"] <= 0:
            return "这笔订单已全部退款"
        return None

    async def refund_quote(self, order_id: str) -> dict:
        async with self.sessions() as session:
            order = await session.get(PaymentOrder, order_id)
            if not order:
                raise LookupError("订单不存在")
            position = await self._refund_position(session, order)
            return {
                **{key: position[key] for key in (
                    "paid_minor", "refunded_minor", "refundable_minor", "granted", "remaining", "freezable",
                    "suggested_points", "suggested_minor",
                )},
                "blocked": self._refund_blocker(order, position),
            }

    async def request_refund(
        self, *, order_id: str, actor: Mapping, note: str, points: Decimal | None = None, amount_minor: int | None = None,
    ) -> PaymentRefund:
        """Sets the unused points aside at once, so they cannot be spent while someone else decides."""
        async with self.sessions() as session:
            async with session.begin():
                order = await self._lock_order(session, order_id)
                if not order:
                    raise LookupError("订单不存在")
                position = await self._refund_position(session, order, lock_points=True)
                blocked = self._refund_blocker(order, position)
                if blocked:
                    raise ValueError(blocked)
                lot, balance, attempt = position["lot"], position["balance"], position["attempt"]
                clawback = position["freezable"] if points is None else points
                if clawback < 0 or clawback > position["freezable"]:
                    raise ValueError(f"最多可回收 {position['freezable']} 积分")
                suggested = min(
                    int(position["paid_minor"] * clawback // lot.granted) if lot and lot.granted else 0, position["refundable_minor"],
                )
                amount = suggested if amount_minor is None else amount_minor
                if amount <= 0 or amount > position["refundable_minor"]:
                    raise ValueError("退款金额必须大于 0，且不超过可退金额")
                if lot and clawback > 0:
                    lot.frozen += clawback
                    balance.available -= clawback
                    balance.frozen += clawback
                refund = PaymentRefund(
                    order_id=order.id, attempt_id=attempt.id, user_id=order.user_id, provider=attempt.provider,
                    out_trade_no=attempt.out_trade_no, out_refund_no=new_merchant_no("R"), refund_minor=amount,
                    total_minor=attempt.amount_minor, reason=REFUND_ON_REQUEST, status="requested", note=note[:500],
                    points_clawback=clawback, lot_id=lot.id if lot else None, suggested_minor=suggested,
                    requested_by=actor["user_id"],
                )
                session.add(refund)
                await session.flush()
                money_audit(
                    session, actor, "refund.request", "payment_refund", refund.id, order_id=order.id, amount_minor=amount,
                    suggested_minor=suggested, points=str(clawback), note=note[:200],
                )
            return refund

    async def _locked_refund(self, session, refund_id: str) -> tuple[PaymentRefund, PaymentOrder]:
        order_id = await session.scalar(select(PaymentRefund.order_id).where(PaymentRefund.id == refund_id))
        if not order_id:
            raise LookupError("退款单不存在")
        order = await self._lock_order(session, order_id)
        refund = await session.get(PaymentRefund, refund_id, with_for_update=True, populate_existing=True)
        return refund, order

    async def approve_refund(self, *, refund_id: str, actor: Mapping, amount_minor: int | None = None, note: str = "") -> PaymentRefund:
        async with self.sessions() as session:
            async with session.begin():
                refund, order = await self._locked_refund(session, refund_id)
                if refund.status != "requested":
                    raise ValueError("退款单已处理")
                if refund.requested_by == actor["user_id"]:
                    # No exception for super admins: two people is the whole point.
                    raise PermissionError("发起人不能批准自己发起的退款")
                position = await self._refund_position(session, order)
                if position["flagged"]:
                    raise ValueError("这笔订单有未处理的严重对账差异，处理后才能退款")
                amount = refund.refund_minor if amount_minor is None else amount_minor
                if amount <= 0 or amount > position["refundable_minor"]:
                    raise ValueError("退款金额必须大于 0，且不超过可退金额")
                money_audit(
                    session, actor, "refund.approve", "payment_refund", refund.id, order_id=order.id, amount_minor=amount,
                    requested_minor=refund.refund_minor, amount_changed=amount != refund.refund_minor, note=note[:200],
                )
                refund.refund_minor, refund.status, refund.approved_by = amount, "pending", actor["user_id"]
                refund.decision_note, refund.decided_at = note[:500], datetime.now(timezone.utc)
            return refund

    async def reject_refund(self, *, refund_id: str, actor: Mapping, note: str) -> PaymentRefund:
        async with self.sessions() as session:
            async with session.begin():
                refund, order = await self._locked_refund(session, refund_id)
                if refund.status != "requested":
                    raise ValueError("退款单已处理")
                await self._unfreeze(session, refund, order)
                refund.status, refund.rejected_by = "rejected", actor["user_id"]
                refund.decision_note, refund.decided_at = note[:500], datetime.now(timezone.utc)
                money_audit(session, actor, "refund.reject", "payment_refund", refund.id, order_id=order.id, note=note[:200])
            return refund

    async def _unfreeze(self, session, refund: PaymentRefund, order: PaymentOrder) -> None:
        if refund.points_clawback <= 0 or not refund.lot_id:
            return
        balance = await session.get(PointBalance, order.user_id, with_for_update=True, populate_existing=True)
        lot = await session.get(PointLot, refund.lot_id, with_for_update=True, populate_existing=True)
        lot.frozen -= refund.points_clawback
        balance.frozen -= refund.points_clawback
        balance.available += refund.points_clawback

    async def _finish_requested_refund(self, session, refund: PaymentRefund, order: PaymentOrder) -> None:
        """The money has gone back: take the points set aside, and end the membership if all of it went."""
        if refund.points_clawback > 0 and refund.lot_id:
            balance = await session.get(PointBalance, order.user_id, with_for_update=True, populate_existing=True)
            lot = await session.get(PointLot, refund.lot_id, with_for_update=True, populate_existing=True)
            lot.frozen -= refund.points_clawback
            lot.remaining -= refund.points_clawback
            balance.frozen -= refund.points_clawback
            session.add(LedgerEntry(
                user_id=order.user_id, order_id=order.id, asset="points", direction="debit", amount=refund.points_clawback,
                currency="PTS", category="refund_clawback", idempotency_key=f"refund:{refund.id}:clawback",
                metadata_json={"lot_id": refund.lot_id, "refund_id": refund.id, "refund_minor": refund.refund_minor},
            ))
        done = await session.scalar(select(func.coalesce(func.sum(PaymentRefund.refund_minor), 0)).where(
            PaymentRefund.order_id == order.id, PaymentRefund.reason == REFUND_ON_REQUEST, PaymentRefund.status == "succeeded",
        ))
        if int(done) < refund.total_minor:
            order.status = "partially_refunded"
            return
        order.status = "refunded"
        term = await session.scalar(select(MembershipTerm).where(MembershipTerm.order_id == order.id).with_for_update())
        if not term:
            return
        term.status = "refunded"
        now = datetime.now(timezone.utc)
        membership = await session.get(UserMembership, order.user_id, with_for_update=True)
        if membership and membership.plan_id == term.plan_id:
            terms = (await session.scalars(select(MembershipTerm).where(
                MembershipTerm.user_id == order.user_id, MembershipTerm.id != term.id,
            ))).all()
            following = current_term(terms, now)
            if following:
                membership.plan_id, membership.started_at, membership.expires_at = following.plan_id, following.starts_at, following.expires_at
            else:
                membership.status, membership.expires_at = "refunded", now

    async def list_notifications(self, user_id: str, *, limit: int = 30) -> tuple[list[UserNotification], int]:
        async with self.sessions() as session:
            unread = int(await session.scalar(select(func.count()).select_from(UserNotification).where(
                UserNotification.user_id == user_id, UserNotification.read_at.is_(None),
            )) or 0)
            items = (await session.scalars(
                select(UserNotification).where(UserNotification.user_id == user_id)
                .order_by(UserNotification.created_at.desc()).limit(limit)
            )).all()
            return list(items), unread

    async def mark_notifications_read(self, user_id: str, notification_id: str | None = None) -> int:
        """All of theirs, or one of theirs: someone else's id simply matches nothing."""
        conditions = [UserNotification.user_id == user_id, UserNotification.read_at.is_(None)]
        if notification_id:
            conditions.append(UserNotification.id == notification_id)
        async with self.sessions() as session:
            moved = await session.execute(update(UserNotification).where(*conditions).values(read_at=datetime.now(timezone.utc)))
            await session.commit()
            return moved.rowcount

    async def staff_to_do(self, actor: Mapping, *, now: datetime | None = None) -> dict:
        """Counted when asked, so it is always right and nobody has to be told twice. Only what this person could act on."""
        moment = now or datetime.now(timezone.utc)
        user_id = actor["user_id"]
        found: dict[str, int] = {}
        async with self.sessions() as session:
            async def count(model, *conditions) -> int:
                return int(await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)

            if has_permission(actor, REFUND_APPROVE):
                found["refunds_to_decide"] = await count(PaymentRefund, PaymentRefund.status == "requested", PaymentRefund.requested_by != user_id)
            if has_permission(actor, WALLET_ADJUST_APPROVE):
                found["adjustments_to_decide"] = await count(WalletAdjustment, WalletAdjustment.status == "requested", WalletAdjustment.requested_by != user_id)
            if has_permission(actor, RECON_READ):
                found["critical_differences"] = await count(ReconItem, ReconItem.status == "open", ReconItem.severity == "critical")
                found["payment_alerts"] = await count(
                    AuditEvent, AuditEvent.action.in_(PAYMENT_ALERTS), AuditEvent.created_at >= moment - _ALERTS_SHOWN_FOR,
                )
        return found

    async def send_membership_reminders(self, *, now: datetime | None = None) -> int:
        """Once per term per threshold. Someone already renewed hears nothing: the reminder is about losing access."""
        moment = now or datetime.now(timezone.utc)
        sent = 0
        async with self.sessions() as session:
            rows = (await session.execute(
                select(MembershipTerm, PlatformUser.status, MembershipPlan.name)
                .join(PlatformUser, PlatformUser.id == MembershipTerm.user_id)
                .join(MembershipPlan, MembershipPlan.id == MembershipTerm.plan_id, isouter=True)
                .where(MembershipTerm.status == "active", MembershipTerm.expires_at > moment - REMINDER_EARLIEST)
            )).all()
            last_end: dict[str, datetime] = {}
            for term, _status, _name in rows:
                end = _aware_utc(term.expires_at)
                last_end[term.user_id] = max(last_end.get(term.user_id, end), end)
            wanted = []
            for term, status, name in rows:
                end = _aware_utc(term.expires_at)
                if status != "active" or last_end[term.user_id] > end:
                    continue
                left = end - moment
                if left <= timedelta(0):
                    wanted.append((term, "membership_expired", f"expired:{term.id}", name, 0))
                elif left <= timedelta(days=1):
                    wanted.append((term, "membership_expiring", f"expiring:{term.id}:1", name, 1))
                elif left <= REMINDER_EARLIEST:
                    wanted.append((term, "membership_expiring", f"expiring:{term.id}:7", name, 7))
            for term, kind, key, name, days in wanted:
                exists_already = await session.scalar(select(UserNotification.id).where(
                    UserNotification.user_id == term.user_id, UserNotification.dedupe_key == key,
                ))
                if not exists_already:
                    _notify(session, term.user_id, kind, key, plan_name=name or term.plan_id, days=days, expires_at=_aware_utc(term.expires_at).isoformat())
                    sent += 1
            try:
                await session.commit()
            except IntegrityError:
                # Another worker sent them. The next pass finds nothing left to do.
                await session.rollback()
                return 0
        return sent

    async def get_refund(self, refund_id: str) -> PaymentRefund | None:
        async with self.sessions() as session:
            return await session.get(PaymentRefund, refund_id)

    async def list_refunds(self, *, status: str | None, page: int, page_size: int) -> tuple[list[tuple[PaymentRefund, str]], int]:
        async with self.sessions() as session:
            conditions = [PaymentRefund.status == status] if status else []
            total = int(await session.scalar(select(func.count()).select_from(PaymentRefund).where(*conditions)) or 0)
            rows = (await session.execute(
                select(PaymentRefund, PlatformUser.email)
                .join(PlatformUser, PlatformUser.id == PaymentRefund.user_id).where(*conditions)
                .order_by(PaymentRefund.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )).all()
            return [(row[0], row[1] or "") for row in rows], total

    async def list_all_orders(self, *, status: str | None, query: str, page: int, page_size: int) -> tuple[list[tuple[PaymentOrder, str]], int]:
        conditions = [PaymentOrder.status == status] if status else []
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(or_(
                PaymentOrder.id == query, PlatformUser.id == query, PlatformUser.email.ilike(f"%{escaped}%", escape="\\"),
                PaymentOrder.id.in_(select(PaymentAttempt.order_id).where(or_(
                    PaymentAttempt.out_trade_no == query, PaymentAttempt.channel_trade_no == query,
                ))),
            ))
        async with self.sessions() as session:
            joined = select(PaymentOrder, PlatformUser.email).join(PlatformUser, PlatformUser.id == PaymentOrder.user_id).where(*conditions)
            total = int(await session.scalar(select(func.count()).select_from(joined.subquery())) or 0)
            rows = (await session.execute(
                joined.order_by(PaymentOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )).all()
            return [(row[0], row[1] or "") for row in rows], total

    async def order_details(self, order_id: str) -> dict:
        async with self.sessions() as session:
            order = await session.get(PaymentOrder, order_id)
            if not order:
                raise LookupError("订单不存在")
            return {
                "order": order,
                "user": await session.get(PlatformUser, order.user_id),
                "attempts": list((await session.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == order_id).order_by(PaymentAttempt.created_at))).all()),
                "refunds": list((await session.scalars(select(PaymentRefund).where(PaymentRefund.order_id == order_id).order_by(PaymentRefund.created_at))).all()),
                "lot": await session.scalar(select(PointLot).where(PointLot.order_id == order_id)),
                "term": await session.scalar(select(MembershipTerm).where(MembershipTerm.order_id == order_id)),
                "recon_items": list((await session.scalars(select(ReconItem).where(ReconItem.order_id == order_id, ReconItem.status == "open"))).all()),
            }

    async def request_wallet_adjustment(self, *, user_id: str, points: Decimal, reason: str, actor: Mapping) -> WalletAdjustment:
        if points == 0:
            raise ValueError("调整积分不能为 0")
        async with self.sessions() as session:
            if not await session.get(PlatformUser, user_id):
                raise LookupError("用户不存在")
            adjustment = WalletAdjustment(user_id=user_id, points=points, reason=reason[:500], requested_by=actor["user_id"])
            session.add(adjustment)
            await session.flush()
            money_audit(session, actor, "wallet.adjust_request", "wallet_adjustment", adjustment.id, user_id=user_id, points=str(points), reason=reason[:200])
            await session.commit()
            return adjustment

    async def approve_wallet_adjustment(self, *, adjustment_id: str, actor: Mapping, note: str = "") -> WalletAdjustment:
        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            async with session.begin():
                await session.execute(update(WalletAdjustment).where(WalletAdjustment.id == adjustment_id).values(status=WalletAdjustment.status))
                adjustment = await session.get(WalletAdjustment, adjustment_id, with_for_update=True)
                if not adjustment:
                    raise LookupError("调整单不存在")
                if adjustment.status != "requested":
                    raise ValueError("调整单已处理")
                if adjustment.requested_by == actor["user_id"]:
                    raise PermissionError("发起人不能批准自己发起的调整")
                balance = await session.get(PointBalance, adjustment.user_id, with_for_update=True)
                metadata = {"adjustment_id": adjustment.id}
                if adjustment.points > 0:
                    lot = PointLot(
                        user_id=adjustment.user_id, granted=adjustment.points, remaining=adjustment.points,
                        unit_value_minor=Decimal(0), expires_at=now + _ADJUSTED_POINTS_LAST,
                    )
                    session.add(lot)
                    await session.flush()
                    metadata["lot_id"] = lot.id
                    if balance:
                        balance.available += adjustment.points
                    else:
                        session.add(PointBalance(user_id=adjustment.user_id, available=adjustment.points, held=Decimal(0), frozen=Decimal(0)))
                else:
                    needed = -adjustment.points
                    if not balance or balance.available < needed:
                        raise ValueError(f"用户可用积分不足，最多可扣 {balance.available if balance else 0}")
                    balance.available -= needed
                    lots = (await session.scalars(
                        select(PointLot).where(PointLot.user_id == adjustment.user_id, PointLot.remaining > PointLot.frozen)
                        .order_by(PointLot.expires_at, PointLot.created_at).with_for_update()
                    )).all()
                    drawn, left = {}, needed
                    for lot in lots:
                        if left <= 0:
                            break
                        part = min(left, lot.remaining - lot.frozen)
                        lot.remaining -= part
                        left -= part
                        drawn[lot.id] = str(part)
                    metadata["lots"] = drawn
                session.add(LedgerEntry(
                    user_id=adjustment.user_id, asset="points", direction="credit" if adjustment.points > 0 else "debit",
                    amount=abs(adjustment.points), currency="PTS", category="manual_adjust",
                    idempotency_key=f"adjust:{adjustment.id}", metadata_json=metadata,
                ))
                adjustment.status, adjustment.approved_by, adjustment.decision_note, adjustment.decided_at = "approved", actor["user_id"], note[:500], now
                money_audit(session, actor, "wallet.adjust_approve", "wallet_adjustment", adjustment.id, user_id=adjustment.user_id, points=str(adjustment.points), note=note[:200])
            return adjustment

    async def reject_wallet_adjustment(self, *, adjustment_id: str, actor: Mapping, note: str) -> WalletAdjustment:
        async with self.sessions() as session:
            adjustment = await session.get(WalletAdjustment, adjustment_id)
            if not adjustment:
                raise LookupError("调整单不存在")
            moved = await session.execute(
                update(WalletAdjustment).where(WalletAdjustment.id == adjustment_id, WalletAdjustment.status == "requested")
                .values(status="rejected", rejected_by=actor["user_id"], decision_note=note[:500], decided_at=datetime.now(timezone.utc))
            )
            if moved.rowcount != 1:
                raise ValueError("调整单已处理")
            money_audit(session, actor, "wallet.adjust_reject", "wallet_adjustment", adjustment_id, note=note[:200])
            await session.commit()
            await session.refresh(adjustment)
            return adjustment

    async def list_wallet_adjustments(self, *, status: str | None, page: int, page_size: int) -> tuple[list[tuple[WalletAdjustment, str]], int]:
        conditions = [WalletAdjustment.status == status] if status else []
        async with self.sessions() as session:
            total = int(await session.scalar(select(func.count()).select_from(WalletAdjustment).where(*conditions)) or 0)
            rows = (await session.execute(
                select(WalletAdjustment, PlatformUser.email).join(PlatformUser, PlatformUser.id == WalletAdjustment.user_id)
                .where(*conditions).order_by(WalletAdjustment.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )).all()
            return [(row[0], row[1] or "") for row in rows], total

    async def refunds_due(self, *, now: datetime, every: timedelta, limit: int) -> list[PaymentRefund]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(PaymentRefund)
                .where(
                    PaymentRefund.status.in_(("pending", "processing")),
                    or_(PaymentRefund.last_tried_at.is_(None), PaymentRefund.last_tried_at <= now - every),
                )
                .order_by(PaymentRefund.created_at).limit(limit)
            )).all())

    async def claim_refund(self, refund_id: str, now: datetime, every: timedelta) -> bool:
        async with self.sessions() as session:
            moved = await session.execute(
                update(PaymentRefund)
                .where(
                    PaymentRefund.id == refund_id,
                    or_(PaymentRefund.last_tried_at.is_(None), PaymentRefund.last_tried_at <= now - every),
                )
                .values(last_tried_at=now)
            )
            await session.commit()
            return moved.rowcount == 1

    async def record_refund(self, refund_id: str, *, status: str, channel_refund_no: str | None = None, detail: str = "") -> None:
        """Only a final answer ends a refund, and a failed one needs a person: the money has not gone back."""
        async with self.sessions() as session:
            async with session.begin():
                refund, order = await self._locked_refund(session, refund_id)
                if refund.status in ("succeeded", "failed", "rejected"):
                    return
                refund.status, refund.detail = status, detail[:200]
                refund.channel_refund_no = channel_refund_no or refund.channel_refund_no
                if status in ("succeeded", "failed"):
                    refund.finished_at = datetime.now(timezone.utc)
                if refund.reason == REFUND_ON_REQUEST and status == "succeeded":
                    await self._finish_requested_refund(session, refund, order)
                    _payment_event(session, "refund.succeeded", refund)
                if status == "succeeded":
                    _notify(
                        session, refund.user_id, "duplicate_refunded" if refund.reason != REFUND_ON_REQUEST else "refund_succeeded",
                        f"refund:{refund.id}", order_id=refund.order_id, amount_minor=refund.refund_minor, points=str(refund.points_clawback),
                    )
                if status == "failed":
                    if refund.reason == REFUND_ON_REQUEST:
                        await self._unfreeze(session, refund, order)
                    _payment_alert(session, "payment.refund_failed", order, refund_id=refund.id, detail=detail[:200])
