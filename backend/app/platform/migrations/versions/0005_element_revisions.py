"""Element library assets keep their earlier versions, so a change can be rolled back.

Revision ID: 0005_element_revisions
Revises: 0004_refund_approvals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0005_element_revisions"
down_revision = "0004_refund_approvals"
branch_labels = None
depends_on = None

_TABLE = "element_revisions"


def upgrade() -> None:
    # ``create_all`` normally makes the table before this runs; this covers a database brought up by migrations alone.
    if _TABLE in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("element_id", sa.String(36), sa.ForeignKey("element_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("files_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("element_id", "revision", name="uq_element_revision_number"),
    )
    op.create_index("ix_element_revisions_element_id", _TABLE, ["element_id"])
    op.create_index("ix_element_revisions_owner_id", _TABLE, ["owner_id"])


def downgrade() -> None:
    op.drop_table(_TABLE)
