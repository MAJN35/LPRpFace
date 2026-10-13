"""force a password change: users.must_change_password; set for the existing default admin

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()))
    users = sa.table("users", sa.column("username", sa.String), sa.column("must_change_password", sa.Boolean))
    op.execute(users.update().where(users.c.username == os.environ.get("ADMIN_USERNAME", "admin"))
               .values(must_change_password=True))


def downgrade():
    op.drop_column("users", "must_change_password")
