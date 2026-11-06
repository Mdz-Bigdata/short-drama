"""Roles move to their own table: today's admins become super admins, and ``editor``, which granted nothing, goes.

Revision ID: 0003_user_roles
Revises: 0002_keep_financial_records
"""

from __future__ import annotations

from alembic import op

revision = "0003_user_roles"
down_revision = "0002_keep_financial_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``create_all`` has already made user_roles by the time this runs.
    op.execute("""
        INSERT INTO user_roles (user_id, role, granted_at)
        SELECT id, 'super_admin', CURRENT_TIMESTAMP FROM platform_users
        WHERE role = 'admin' AND id NOT IN (SELECT user_id FROM user_roles WHERE role = 'super_admin')
    """)
    op.execute("UPDATE platform_users SET role = 'user' WHERE role = 'editor'")


def downgrade() -> None:
    op.execute("DELETE FROM user_roles")
