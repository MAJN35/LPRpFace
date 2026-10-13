"""watchlists: persons, plates (whitelist | blocklist | unknown); list status on events

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "persons",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("full_name", sa.String(128), nullable=False),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("list_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_persons_list_status", "persons", ["list_status"])
    op.create_table(
        "plates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plate_key", sa.String(64), nullable=False, unique=True),
        sa.Column("plate_string_fa", sa.String(64), nullable=False, server_default=""),
        sa.Column("plate_string_latin", sa.String(96), nullable=False, server_default=""),
        sa.Column("list_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("person_id", sa.Integer, sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_plates_list_status", "plates", ["list_status"])
    op.create_index("ix_plates_person_id", "plates", ["person_id"])
    op.add_column("events", sa.Column("list_status", sa.String(16), nullable=False, server_default="unknown"))
    op.add_column("events", sa.Column("person_id", sa.Integer))
    op.create_index("ix_events_list_status", "events", ["list_status"])
    op.create_index("ix_events_person_id", "events", ["person_id"])


def downgrade():
    op.drop_index("ix_events_person_id", "events")
    op.drop_index("ix_events_list_status", "events")
    op.drop_column("events", "person_id")
    op.drop_column("events", "list_status")
    op.drop_table("plates")
    op.drop_table("persons")
