"""initial schema: events (plate event schema 2.0), users, audit_log

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("camera_id", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_uri", sa.String(512), nullable=False, server_default=""),
        sa.Column("source_file", sa.String(256)),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("track_id", sa.Integer),
        sa.Column("model_version", sa.String(8), nullable=False),
        sa.Column("model_sha256", sa.String(64), nullable=False),
        sa.Column("engine_sha256", sa.String(64)),
        sa.Column("precision", sa.String(8), nullable=False),
        sa.Column("batch_profile", sa.JSON, nullable=False),
        sa.Column("plate_type", sa.String(16), nullable=False),
        sa.Column("plate_string_fa", sa.String(64), nullable=False, server_default=""),
        sa.Column("plate_string_latin", sa.String(96), nullable=False, server_default=""),
        sa.Column("plate_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("zone", sa.String(16)),
        sa.Column("expiry", sa.String(8)),
        sa.Column("markers", sa.JSON, nullable=False),
        sa.Column("characters", sa.JSON, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("is_valid", sa.Boolean),
        sa.Column("invalid_reason", sa.String(200)),
        sa.Column("frames_voted", sa.Integer, nullable=False),
        sa.Column("plate_bbox", sa.JSON, nullable=False),
        sa.Column("frame_size", sa.JSON, nullable=False),
        sa.Column("crop_path", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for col in ("camera_id", "ts", "model_version", "plate_type", "plate_key", "zone", "is_valid"):
        op.create_index(f"ix_events_{col}", "events", [col])
    op.create_index("ix_events_camera_ts", "events", ["camera_id", "ts"])
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("target", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])


def downgrade():
    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("events")
