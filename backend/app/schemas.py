"""API response/request models. Events are accepted in schema 2.0 (validated by the consumer and here)."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Source(BaseModel):
    id: str = Field(max_length=64)
    type: str
    uri_redacted: str
    file_name: Optional[str] = None


class Model(BaseModel):
    version: str
    sha256: str
    engine_sha256: Optional[str] = None
    precision: str
    batch_profile: List[int]


class EventIn(BaseModel):
    schema_version: str = Field(pattern=r"^2\.0$")
    event_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    event_type: str = Field(pattern=r"^plate\.recognized(\.image)?$")
    source: Source
    camera_id: str = Field(max_length=64)
    timestamp: dt.datetime
    processed_at: Optional[dt.datetime] = None
    track_id: Optional[int] = None
    model: Model
    plate_type: str
    plate_string_fa: str = Field(max_length=64)
    plate_string_latin: str = Field(max_length=96)
    plate_key: str = Field(max_length=64)
    zone: Optional[str] = None
    expiry: Optional[str] = None
    markers: List[str] = []
    characters: List[Dict[str, Any]] = []
    confidence: float = Field(ge=0, le=1)
    is_valid: Optional[bool] = None
    invalid_reason: Optional[str] = None
    frames_voted: int = Field(ge=1)
    plate_bbox: List[float]
    frame_size: List[int]
    best_frame_crop_path: Optional[str] = None


class EventOut(BaseModel):
    event_id: str
    event_type: str
    camera_id: str
    source_type: str
    source_file: Optional[str]
    timestamp: dt.datetime
    track_id: Optional[int]
    model_version: str
    plate_type: str
    plate_string_fa: str
    plate_string_latin: str
    zone: Optional[str]
    expiry: Optional[str]
    markers: List[str]
    confidence: float
    is_valid: Optional[bool]
    invalid_reason: Optional[str]
    frames_voted: int
    has_crop: bool
    list_status: str = "unknown"           # whitelist | blocklist | unknown, at ingest time
    person_id: Optional[int] = None


class EventDetail(EventOut):
    characters: List[Dict[str, Any]]
    plate_bbox: List[float]
    frame_size: List[int]
    model_sha256: str
    engine_sha256: Optional[str]
    precision: str
    processed_at: Optional[dt.datetime]
    plate_key: str = ""
    person: Optional[Dict[str, Any]] = None


class Page(BaseModel):
    items: List[EventOut]
    total: int
    limit: int
    offset: int


class IngestResult(BaseModel):
    event_id: str
    created: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserOut(BaseModel):
    username: str
    role: str
    is_active: bool


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=128)
    role: str = Field(pattern=r"^(admin|operator|viewer)$")
