"""Refunds become a two-person decision, and points waiting on one are set aside.

Revision ID: 0004_refund_approvals
Revises: 0003_user_roles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0004_refund_approvals"
down_revision = "0003_user_roles"
branch_labels = None
depends_on = None

_ADDED = {
    "point_lots": [("frozen", lambda: sa.Numeric(18, 4), "0")],
    "point_balances": [("frozen", lambda: sa.Numeric(18, 4), "0")],
    "payment_refunds": [
        ("points_clawback", lambda: sa.Numeric(18, 4), "0"),
        ("lot_id", lambda: sa.String(36), None),
        ("note", lambda: sa.String(500), "''"),
        ("suggested_minor", lambda: sa.Integer(), None),
        ("requested_by", lambda: sa.String(36), None),
        ("approved_by", lambda: sa.String(36), None),
        ("rejected_by", lambda: sa.String(36), None),
        ("decision_note", lambda: sa.String(500), "''"),
        ("decided_at", lambda: sa.DateTime(timezone=True), None),
    ],
}
_TWO_PEOPLE = "ck_refund_two_people"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table, columns in _ADDED.items():
        present = {column["name"] for column in inspector.get_columns(table)}
        for name, kind, default in columns:
            if name not in present:
                op.add_column(table, sa.Column(name, kind(), server_default=sa.text(default) if default else None))
    # The rule holds in the code on every database. SQLite cannot add a constraint to a table that already exists.
    if bind.dialect.name == "postgresql":
        names = {item["name"] for item in inspector.get_check_constraints("payment_refunds")}
        if _TWO_PEOPLE not in names:
            op.create_check_constraint(_TWO_PEOPLE, "payment_refunds", "requested_by <> approved_by")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(_TWO_PEOPLE, "payment_refunds", type_="check")
    for table, columns in _ADDED.items():
        for name, _kind, _default in columns:
            op.drop_column(table, name)
