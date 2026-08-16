from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.core.capability_manifest import capability_command_catalog
from app.platform.models import (
    AuditEvent,
    Base,
    CapabilitySetting,
    ConfiguredModel,
    ElementAsset,
    ElementFile,
    LedgerEntry,
    MembershipPlan,
    ModelProviderConfiguration,
    PaymentOrder,
    PaymentWebhookEvent,
    PlatformUser,
    ProjectSkill,
    RegenerationRequest,
    UserMembership,
)
from app.repository.user_repo import hash_password, verify_password


ACTOR_VIEW_SLOTS = (
    "front",
    "front_three_quarter",
    "profile",
    "rear_three_quarter",
    "back",
)
ELEMENT_KINDS = {"actor", "prop", "scene", "effect"}
PAYMENT_PROVIDERS = {"sandbox", "wechat", "alipay"}
PROJECT_SKILL_SOURCE_TYPES = {"created", "markdown_upload", "skill_package"}
MAX_PROJECT_SKILL_BYTES = 128 * 1024
MAX_ENABLED_SKILLS = 12
MAX_ENABLED_SKILL_BYTES = 96 * 1024


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


class PlatformStore:
    def __init__(self, database_url: str, *, echo: bool = False):
        if not database_url.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError("DATABASE_URL 必须使用 postgresql+asyncpg 或 sqlite+aiosqlite")
        self.engine: AsyncEngine = create_async_engine(database_url, echo=echo, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def create_user(
        self,
        *,
        email: str | None,
        phone: str | None,
        password: str,
        username: str | None = None,
        role: str = "user",
        must_change_password: bool = False,
        _minimum_password_length: int = 10,
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
            )
            session.add(user)
            await session.commit()
            return user, True

    async def bootstrap_admin(
        self, password: str, *, login: str = "admin@short-drama"
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
            _minimum_password_length=8,
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
        if len(new_password) < 10:
            raise ValueError("新密码至少需要 10 位")
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

    async def admin_update_user(self, actor_id: str, user_id: str, *, role: str | None, status: str | None) -> PlatformUser:
        if role is not None and role not in {"admin", "editor", "user"}:
            raise ValueError("无效角色")
        if status is not None and status not in {"active", "suspended"}:
            raise ValueError("无效状态")
        async with self.sessions() as session:
            user = await session.get(PlatformUser, user_id)
            if not user:
                raise ValueError("用户不存在")
            removes_admin = user.role == "admin" and (role not in {None, "admin"} or status == "suspended")
            if removes_admin:
                active_admins = int(await session.scalar(select(func.count()).select_from(PlatformUser).where(
                    PlatformUser.role == "admin", PlatformUser.status == "active"
                )) or 0)
                if active_admins <= 1:
                    raise ValueError("不能停用或降级最后一个有效管理员")
            previous = {"role": user.role, "status": user.status}
            if role is not None:
                user.role = role
            if status is not None:
                user.status = status
            session.add(AuditEvent(
                actor_id=actor_id,
                action="user.admin_update",
                resource_type="user",
                resource_id=user.id,
                details={"previous": previous, "new": {"role": user.role, "status": user.status}},
            ))
            await session.commit()
            return user

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
            raise ValueError("元素类型必须是 actor、prop、scene 或 effect")
        if not name.strip():
            raise ValueError("元素名称不能为空")
        async with self.sessions() as session:
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

    async def list_elements(
        self, owner_id: str, kind: str, page: int, page_size: int
    ) -> tuple[list[ElementAsset], int]:
        if kind not in ELEMENT_KINDS:
            raise ValueError("无效元素类型")
        where = (ElementAsset.owner_id == owner_id, ElementAsset.kind == kind)
        async with self.sessions() as session:
            total = int(await session.scalar(select(func.count()).select_from(ElementAsset).where(*where)) or 0)
            items = list((await session.scalars(
                select(ElementAsset).options(selectinload(ElementAsset.files)).where(*where)
                .order_by(ElementAsset.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )).all())
            return items, total

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
    ) -> ElementAsset:
        async with self.sessions() as session:
            element = await session.scalar(
                select(ElementAsset).options(selectinload(ElementAsset.files)).where(ElementAsset.id == element_id)
            )
            if not element or element.owner_id != owner_id:
                raise ValueError("元素不存在")
            if element.kind == "actor":
                if slot not in ACTOR_VIEW_SLOTS:
                    raise ValueError("演员图片必须使用规定的五视图槽位")
                position = ACTOR_VIEW_SLOTS.index(slot)
            else:
                if not re.fullmatch(r"[a-z0-9_-]{1,64}", slot):
                    raise ValueError("文件槽位无效")
                position = len(element.files)
            existing = next((item for item in element.files if item.slot == slot), None)
            if existing:
                existing.storage_path = storage_path
                existing.mime_type = mime_type
                existing.size_bytes = size_bytes
                existing.sha256 = sha256
                existing.position = position
            else:
                session.add(ElementFile(
                    element_id=element.id,
                    slot=slot,
                    position=position,
                    storage_path=storage_path,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    sha256=sha256,
                ))
            element.version += 1
            slots = {item.slot for item in element.files}
            slots.add(slot)
            element.status = "ready" if (
                element.kind != "actor" or slots == set(ACTOR_VIEW_SLOTS)
            ) else "draft"
            await session.commit()
            loaded = await self._loaded_element(session, element.id)
            assert loaded is not None
            return loaded

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

    async def list_plans(self) -> list[MembershipPlan]:
        async with self.sessions() as session:
            return list((await session.scalars(
                select(MembershipPlan).where(MembershipPlan.active.is_(True)).order_by(MembershipPlan.price)
            )).all())

    async def create_order(
        self, *, user_id: str, plan_id: str, provider: str, idempotency_key: str
    ) -> PaymentOrder:
        if provider not in PAYMENT_PROVIDERS:
            raise ValueError("不支持的支付渠道")
        if provider != "sandbox":
            raise ValueError("真实支付渠道尚未配置商户证书")
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
                user_id=user_id, plan_id=plan.id, provider=provider,
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
            plan = await session.get(MembershipPlan, membership.plan_id)
            return (membership, plan) if plan else None

    async def confirm_paid_order(self, order_id: str, provider_event_id: str) -> PaymentOrder:
        async with self.sessions() as session:
            order = await session.get(PaymentOrder, order_id)
            if not order:
                raise ValueError("订单不存在")
            if order.status == "paid":
                if order.provider_event_id != provider_event_id:
                    raise ValueError("订单已由其他支付事件完成")
                return order
            if order.status != "pending":
                raise ValueError("订单状态不允许支付")
            plan = await session.get(MembershipPlan, order.plan_id)
            if not plan:
                raise ValueError("会员计划不存在")
            now = datetime.now(timezone.utc)
            order.status = "paid"
            order.provider_event_id = provider_event_id
            order.paid_at = now
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
            membership = await session.get(UserMembership, order.user_id)
            expires = now + timedelta(days=plan.duration_days)
            if membership:
                membership.plan_id = plan.id
                membership.status = "active"
                membership.started_at = now
                membership.expires_at = expires
            else:
                session.add(UserMembership(
                    user_id=order.user_id, plan_id=plan.id, status="active",
                    started_at=now, expires_at=expires,
                ))
            await session.commit()
            return order

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

    async def record_webhook_event(
        self, provider: str, event_id: str, payload_sha256: str, order_id: str, result: str
    ) -> bool:
        async with self.sessions() as session:
            existing = await session.scalar(select(PaymentWebhookEvent).where(
                PaymentWebhookEvent.provider == provider, PaymentWebhookEvent.event_id == event_id
            ))
            if existing:
                return False
            session.add(PaymentWebhookEvent(
                provider=provider,
                event_id=event_id,
                payload_sha256=payload_sha256,
                order_id=order_id,
                result=result,
            ))
            await session.commit()
            return True

    async def process_webhook_payment(
        self,
        *,
        provider: str,
        event_id: str,
        order_id: str,
        amount: Decimal,
        currency: str,
        payload_sha256: str,
    ) -> tuple[PaymentOrder, bool]:
        """Verify immutable order facts and apply webhook, ledger, and membership atomically."""
        async with self.sessions() as session:
            async with session.begin():
                duplicate = await session.scalar(select(PaymentWebhookEvent).where(
                    PaymentWebhookEvent.provider == provider,
                    PaymentWebhookEvent.event_id == event_id,
                ))
                if duplicate:
                    order = await session.get(PaymentOrder, duplicate.order_id)
                    if not order:
                        raise ValueError("重复回调关联的订单不存在")
                    return order, False
                order = await session.get(PaymentOrder, order_id, with_for_update=True)
                if not order:
                    raise ValueError("订单不存在")
                if order.provider != provider:
                    raise ValueError("支付渠道与订单不匹配")
                if order.amount != amount or order.currency != currency:
                    raise ValueError("支付金额或币种与订单不匹配")
                if order.status == "paid":
                    if order.provider_event_id != event_id:
                        raise ValueError("订单已由其他支付事件完成")
                elif order.status == "pending":
                    plan = await session.get(MembershipPlan, order.plan_id)
                    if not plan:
                        raise ValueError("会员计划不存在")
                    now = datetime.now(timezone.utc)
                    order.status = "paid"
                    order.provider_event_id = event_id
                    order.paid_at = now
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
                    membership = await session.get(UserMembership, order.user_id)
                    expires = now + timedelta(days=plan.duration_days)
                    if membership:
                        membership.plan_id = plan.id
                        membership.status = "active"
                        membership.started_at = now
                        membership.expires_at = expires
                    else:
                        session.add(UserMembership(
                            user_id=order.user_id, plan_id=plan.id, status="active",
                            started_at=now, expires_at=expires,
                        ))
                else:
                    raise ValueError("订单状态不允许支付")
                session.add(PaymentWebhookEvent(
                    provider=provider,
                    event_id=event_id,
                    payload_sha256=payload_sha256,
                    order_id=order.id,
                    result="paid",
                ))
            return order, True
