"""face recognition: face_events (snapshot, ArcFace embedding, matched person); persons.auto_named

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("persons", sa.Column("auto_named", sa.Boolean, nullable=False, server_default=sa.false()))
    op.create_table(
        "face_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("camera_id", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_file", sa.String(256)),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("track_id", sa.Integer),
        sa.Column("face_bbox", sa.JSON, nullable=False),
        sa.Column("frame_size", sa.JSON, nullable=False),
        sa.Column("det_score", sa.Float, nullable=False),
        sa.Column("frames_seen", sa.Integer, nullable=False, server_default="1"),
        sa.Column("snapshot_path", sa.String(256)),
        sa.Column("embed_model", sa.String(32), nullable=False, server_default=""),
        sa.Column("embedding", sa.LargeBinary),
        sa.Column("embed_det_score", sa.Float),
        sa.Column("sharpness", sa.Float),
        sa.Column("anchor", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("person_id", sa.Integer, sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("similarity", sa.Float),
        sa.Column("match", sa.String(16), nullable=False, server_default="none"),
        sa.Column("list_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_face_events_camera_id", "face_events", ["camera_id"])
    op.create_index("ix_face_events_ts", "face_events", ["ts"])
    op.create_index("ix_face_events_person_id", "face_events", ["person_id"])
    op.create_index("ix_face_events_list_status", "face_events", ["list_status"])
    op.create_index("ix_face_events_person_ts", "face_events", ["person_id", "ts"])


def downgrade():
    op.drop_table("face_events")
    op.drop_column("persons", "auto_named")
