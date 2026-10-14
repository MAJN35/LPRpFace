"""face_events.yaw: head turn of the face (landmark ratio), used to keep turned faces from starting new persons

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("face_events", sa.Column("yaw", sa.Float))


def downgrade():
    op.drop_column("face_events", "yaw")
