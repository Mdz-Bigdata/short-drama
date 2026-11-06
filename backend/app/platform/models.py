from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PlatformUser(Base):
    __tablename__ = "platform_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(24), default="user", index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    # Loaded with the user: every request needs them, and a detached user cannot load them later.
    role_grants: Mapped[list["UserRole"]] = relationship(lazy="selectin", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def roles(self) -> list[str]:
        return sorted(grant.role for grant in self.role_grants)


class UserRole(Base):
    """An operator role someone holds. Customers have none."""

    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(24), primary_key=True)
    granted_by: Mapped[str | None] = mapped_column(String(36))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CapabilitySetting(Base):
    __tablename__ = "capability_settings"
    __table_args__ = (
        UniqueConstraint("command", name="uq_capability_command"),
        Index("ix_capability_source_enabled", "source_id", "enabled"),
    )

    source_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    source_url: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(240))
    command: Mapped[str] = mapped_column(String(220))
    entrypoint: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ProjectSkill(Base):
    __tablename__ = "project_skills"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_project_skill_slug"),
        UniqueConstraint("command", name="uq_project_skill_command"),
        Index("ix_project_skill_enabled", "enabled", "slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    markdown_content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(32), default="created")
    command: Mapped[str] = mapped_column(String(96))
    content_sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), index=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ModelProviderConfiguration(Base):
    __tablename__ = "model_provider_configurations"
    __table_args__ = (
        UniqueConstraint("category", "provider", name="uq_model_configuration_category_provider"),
        Index("ix_model_configuration_category_enabled", "category", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(24), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    base_url: Mapped[str] = mapped_column(Text)
    api_key_ciphertext: Mapped[str] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    models: Mapped[list["ConfiguredModel"]] = relationship(
        back_populates="configuration",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ConfiguredModel.display_name",
    )


class ConfiguredModel(Base):
    __tablename__ = "configured_models"
    __table_args__ = (
        UniqueConstraint(
            "configuration_id", "model_id", "subcategory",
            name="uq_configured_model_identity",
        ),
        Index("ix_configured_model_enabled", "configuration_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    configuration_id: Mapped[str] = mapped_column(
        ForeignKey("model_provider_configurations.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(24), index=True)
    subcategory: Mapped[str] = mapped_column(String(24), default="")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    configuration: Mapped[ModelProviderConfiguration] = relationship(back_populates="models")


class ElementAsset(Base):
    __tablename__ = "element_assets"
    __table_args__ = (Index("ix_element_owner_kind", "owner_id", "kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    files: Mapped[list["ElementFile"]] = relationship(
        back_populates="element", cascade="all, delete-orphan", lazy="selectin",
        order_by="ElementFile.position",
    )


class ElementFile(Base):
    __tablename__ = "element_files"
    __table_args__ = (UniqueConstraint("element_id", "slot", name="uq_element_file_slot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    element_id: Mapped[str] = mapped_column(ForeignKey("element_assets.id", ondelete="CASCADE"), index=True)
    slot: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    element: Mapped[ElementAsset] = relationship(back_populates="files")


class ElementFolder(Base):
    """A folder someone made in their element library; elements outside any folder are simply unfiled."""

    __tablename__ = "element_folders"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_element_folder_owner_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    cover_element_id: Mapped[str | None] = mapped_column(ForeignKey("element_assets.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ElementFolderMember(Base):
    """Which folder an element sits in. A table of its own: ``create_all`` cannot add a column to a live database."""

    __tablename__ = "element_folder_members"

    element_id: Mapped[str] = mapped_column(ForeignKey("element_assets.id", ondelete="CASCADE"), primary_key=True)
    folder_id: Mapped[str] = mapped_column(ForeignKey("element_folders.id", ondelete="CASCADE"), index=True)


class DirectorDeskPose(Base):
    """A pose someone saved on the 3D director desk; it follows the person, not the project."""

    __tablename__ = "director_desk_poses"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_director_desk_pose_owner_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    pose_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class RegenerationRequest(Base):
    __tablename__ = "element_regeneration_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    element_id: Mapped[str] = mapped_column(ForeignKey("element_assets.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="CASCADE"))
    prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="queued")
    paid_submission_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MembershipPlan(Base):
    __tablename__ = "membership_plans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(12), default="CNY")
    points: Mapped[int] = mapped_column(Integer, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserMembership(Base):
    __tablename__ = "user_memberships"

    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("membership_plans.id"))
    status: Mapped[str] = mapped_column(String(24), default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_order_user_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # 财务记录比账号活得久：有订单、账本或会员记录的用户不能被物理删除。
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("membership_plans.id"))
    provider: Mapped[str] = mapped_column(String(24), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    provider_event_id: Mapped[str | None] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentAttempt(Base):
    """One QR code at one channel. An order can have several, because people change their mind about how to pay."""

    __tablename__ = "payment_attempts"
    __table_args__ = (UniqueConstraint("provider", "channel_trade_no", name="uq_attempt_channel_trade"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(ForeignKey("payment_orders.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    merchant_id: Mapped[str] = mapped_column(String(120))
    out_trade_no: Mapped[str] = mapped_column(String(32), unique=True)
    channel_trade_no: Mapped[str | None] = mapped_column(String(64))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    qr_code: Mapped[str | None] = mapped_column(Text)
    settled_by: Mapped[str | None] = mapped_column(String(24))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_queried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PaymentRefund(Base):
    """Money going back: a second payment on an order already paid, which goes by itself, or one two people agreed.

    Status: requested, then rejected or pending; pending goes to the channel, then processing, then succeeded or failed.
    """

    __tablename__ = "payment_refunds"
    __table_args__ = (CheckConstraint("requested_by <> approved_by", name="ck_refund_two_people"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(ForeignKey("payment_orders.id"), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("payment_attempts.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    out_trade_no: Mapped[str] = mapped_column(String(32))
    # Sent again unchanged after a timeout: the channel refunds one number once.
    out_refund_no: Mapped[str] = mapped_column(String(64), unique=True)
    channel_refund_no: Mapped[str | None] = mapped_column(String(64))
    refund_minor: Mapped[int] = mapped_column(Integer)
    total_minor: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    detail: Mapped[str] = mapped_column(String(200), default="")
    #: Set aside when asked for, so they cannot be spent while the decision is pending; taken back if the money goes.
    points_clawback: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    lot_id: Mapped[str | None] = mapped_column(String(36))
    note: Mapped[str] = mapped_column(String(500), default="")
    suggested_minor: Mapped[int | None] = mapped_column(Integer)
    requested_by: Mapped[str | None] = mapped_column(String(36))
    approved_by: Mapped[str | None] = mapped_column(String(36))
    rejected_by: Mapped[str | None] = mapped_column(String(36))
    decision_note: Mapped[str] = mapped_column(String(500), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerEntry(Base):
    __tablename__ = "billing_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("payment_orders.id"), index=True)
    asset: Mapped[str] = mapped_column(String(24), default="points")
    direction: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(12), default="PTS")
    category: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PointRate(Base):
    """What a model costs in points. Only ever added to: a new price is a new row, so old charges stay explainable."""

    __tablename__ = "point_rates"
    __table_args__ = (Index("ix_point_rate_model", "model", "effective_from"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    model: Mapped[str] = mapped_column(String(160))
    # Empty applies to every resolution.
    resolution: Mapped[str] = mapped_column(String(24), default="")
    kind: Mapped[str] = mapped_column(String(32))
    input: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    cached_input: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    output: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UsageCharge(Base):
    """What one provider call comes to in points. A record only, until balances are charged."""

    __tablename__ = "usage_charges"
    __table_args__ = (Index("ix_usage_charge_user_time", "user_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    usage_id: Mapped[str] = mapped_column(String(36), unique=True)
    # No foreign key: a call happened whether or not the account it was for still resolves.
    user_id: Mapped[str | None] = mapped_column(String(36))
    task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    operator_id: Mapped[str | None] = mapped_column(String(36))
    billing_mode: Mapped[str] = mapped_column(String(24), index=True)
    media_type: Mapped[str] = mapped_column(String(12))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(160), index=True)
    purpose: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(12))
    units: Mapped[dict] = mapped_column(JSON, default=dict)
    points: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    rate_id: Mapped[str | None] = mapped_column(String(36))
    rate_missing: Mapped[bool] = mapped_column(Boolean, default=False)
    reference_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    reference_currency: Mapped[str | None] = mapped_column(String(12))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MembershipTerm(Base):
    """One paid period, with a copy of what the plan included at the time."""

    __tablename__ = "membership_terms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("payment_orders.id"), unique=True)
    plan_id: Mapped[str] = mapped_column(String(40))
    entitlements: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PointLot(Base):
    """Points from one source, spent earliest-expiring first. Knowing what each point cost ties points back to money."""

    __tablename__ = "point_lots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("payment_orders.id"), unique=True)
    granted: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    remaining: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    #: The part of ``remaining`` waiting on a refund decision, which nothing may spend.
    frozen: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    unit_value_minor: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PointBalance(Base):
    """What can be spent now and what is held for calls under way. Can be worked out again from lots and holds."""

    __tablename__ = "point_balances"

    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), primary_key=True)
    available: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    held: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    frozen: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)


class UserNotification(Base):
    """Something a customer should hear about. What it says is decided when shown, in their language, from ``kind`` and ``data``."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification_once"),
        Index("ix_notification_user_time", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(120))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WalletAdjustment(Base):
    """Points added or taken by hand. One person asks and another agrees; nothing moves until then."""

    __tablename__ = "wallet_adjustments"
    __table_args__ = (CheckConstraint("requested_by <> approved_by", name="ck_adjustment_two_people"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), index=True)
    points: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), default="requested", index=True)
    requested_by: Mapped[str] = mapped_column(String(36))
    approved_by: Mapped[str | None] = mapped_column(String(36))
    rejected_by: Mapped[str | None] = mapped_column(String(36))
    decision_note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChannelBill(Base):
    """One day's statement from a channel, as it was received."""

    __tablename__ = "channel_bills"
    __table_args__ = (UniqueConstraint("provider", "bill_date", name="uq_channel_bill_day"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(24))
    bill_date: Mapped[date] = mapped_column(Date, index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    paid_minor: Mapped[int] = mapped_column(BigInteger)
    refunded_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChannelBillRow(Base):
    __tablename__ = "channel_bill_rows"
    __table_args__ = (Index("ix_bill_row_trade", "provider", "out_trade_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bill_id: Mapped[str] = mapped_column(ForeignKey("channel_bills.id"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(12))
    out_trade_no: Mapped[str] = mapped_column(String(64))
    channel_trade_no: Mapped[str] = mapped_column(String(64), default="")
    out_refund_no: Mapped[str] = mapped_column(String(64), default="")
    amount_minor: Mapped[int] = mapped_column(BigInteger)


class ReconRun(Base):
    __tablename__ = "recon_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    #: "hourly:2026-11-05T10", "daily:2026-11-05" or "manual:<id>". Unique, so several workers run each period once.
    period: Mapped[str] = mapped_column(String(80), unique=True)
    rules: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="running")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReconItem(Base):
    """One difference, followed from when it was found until it is explained. Fixes are new records, never edits."""

    __tablename__ = "recon_items"
    __table_args__ = (Index("ix_recon_item_open", "status", "severity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fingerprint: Mapped[str] = mapped_column(String(200), index=True)
    rule: Mapped[str] = mapped_column(String(8), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(12))
    order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    reference: Mapped[str] = mapped_column(String(160), default="")
    expected: Mapped[str] = mapped_column(String(200), default="")
    actual: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    first_run_id: Mapped[str] = mapped_column(String(36))
    last_run_id: Mapped[str] = mapped_column(String(36))
    resolved_by: Mapped[str | None] = mapped_column(String(36))
    resolution: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PointHold(Base):
    __tablename__ = "point_holds"
    __table_args__ = (Index("ix_point_hold_status_expiry", "status", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(160), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    captured: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    usage_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(24))
    event_id: Mapped[str] = mapped_column(String(160))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str | None] = mapped_column(String(36))
    result: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ModelConfigurationCredential(Base):
    """One more key for a provider configuration; calls rotate across the enabled ones of their bucket."""

    __tablename__ = "model_configuration_credentials"
    __table_args__ = (Index("ix_model_credential_configuration", "configuration_id", "enabled"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    configuration_id: Mapped[str] = mapped_column(
        ForeignKey("model_provider_configurations.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(80), default="")
    api_key_ciphertext: Mapped[str] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(16))
    # Job-type buckets this key may serve (text / image / video / audio); empty means any.
    buckets: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlatformSetting(Base):
    """A named global setting (text tiers, declarative video endpoints …) as one JSON value."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class McpToken(Base):
    """A bearer token an external agent uses to reach this user's projects over MCP; only its hash is kept."""

    __tablename__ = "mcp_tokens"
    __table_args__ = (Index("ix_mcp_token_user", "user_id", "revoked"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    token_hint: Mapped[str] = mapped_column(String(8), default="")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "platform_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(160))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
