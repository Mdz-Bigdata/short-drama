"""Financial records outlive the account: deleting a user no longer deletes their orders, ledger or membership.

Revision ID: 0002_keep_financial_records
Revises: 0001_baseline
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0002_keep_financial_records"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_TABLES = ("payment_orders", "billing_ledger", "user_memberships")
# SQLite foreign keys have no names to drop by; this names them for the rebuild.
_NAMES = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _set_on_delete(action: str) -> None:
    inspector = inspect(op.get_bind())
    for table in _TABLES:
        current = next(
            key for key in inspector.get_foreign_keys(table)
            if key["referred_table"] == "platform_users" and key["constrained_columns"] == ["user_id"]
        )
        if (current["options"].get("ondelete") or "").upper() == action:
            continue
        name = current["name"] or f"fk_{table}_user_id_platform_users"
        with op.batch_alter_table(table, naming_convention=_NAMES) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.create_foreign_key(name, "platform_users", ["user_id"], ["id"], ondelete=action)


def upgrade() -> None:
    _set_on_delete("RESTRICT")


def downgrade() -> None:
    _set_on_delete("CASCADE")
