"""ORM models: events (schema 2.0, one row per event_id), users, audit log."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Event(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32))
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(16))
    source_uri: Mapped[str] = mapped_column(String(512), default="")
    source_file: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    processed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    track_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_version: Mapped[str] = mapped_column(String(8), index=True)
    model_sha256: Mapped[str] = mapped_column(String(64))
    engine_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    precision: Mapped[str] = mapped_column(String(8))
    batch_profile: Mapped[list] = mapped_column(JSON)
    plate_type: Mapped[str] = mapped_column(String(16), index=True)
    plate_string_fa: Mapped[str] = mapped_column(String(64), default="")
    plate_string_latin: Mapped[str] = mapped_column(String(96), default="")
    plate_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    zone: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    expiry: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    markers: Mapped[list] = mapped_column(JSON, default=list)
    characters: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    is_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, index=True)
    invalid_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    frames_voted: Mapped[int] = mapped_column(Integer)
    plate_bbox: Mapped[list] = mapped_column(JSON)
    frame_size: Mapped[list] = mapped_column(JSON)
    crop_path: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    list_status: Mapped[str] = mapped_column(String(16), default="unknown", index=True)  # at ingest time
    person_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_events_camera_ts", "camera_id", "ts"),)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="viewer")   # admin | operator | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)   # bootstrap admin: True
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Views and exports of personal data (A.7 privacy)."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    username: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))          # view_event | view_crop | export | search ...
    target: Mapped[str] = mapped_column(Text, default="")


LIST_STATUSES = ("whitelist", "blocklist", "unknown")


class Person(Base):
    """A person record (name, notes) linked to plates. Never identified by face (AGENTS.md privacy)."""
    __tablename__ = "persons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128))
    notes: Mapped[str] = mapped_column(Text, default="")
    list_status: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    onupdate=func.now())


class Plate(Base):
    """A registered plate, keyed by the normalized plate_key."""
    __tablename__ = "plates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_key: Mapped[str] = mapped_column(String(64), unique=True)
    plate_string_fa: Mapped[str] = mapped_column(String(64), default="")
    plate_string_latin: Mapped[str] = mapped_column(String(96), default="")
    list_status: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True,
                                                     index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    onupdate=func.now())
