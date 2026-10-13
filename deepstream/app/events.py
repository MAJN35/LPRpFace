"""Plate events, schema 2.0 (schemas/plate_event-2.0.json). No images inside events; crops are referenced by path."""
from __future__ import annotations

import datetime as _dt
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from lpr_reader.normalize import plate_key
from lpr_reader.reader import PlateRead
from lpr_reader.voting import TrackResult

SCHEMA_VERSION = "2.0"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "plate_event-2.0.json"


def iso_utc(t: float) -> str:
    return _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _source(src, file_name: Optional[str]) -> Dict[str, Any]:
    return {"id": src.id, "type": src.type, "uri_redacted": src.uri_redacted, "file_name": file_name}


def _num(v: Sequence[float]) -> List[float]:
    return [round(float(x), 1) for x in v]


def from_track(res: TrackResult, src, model: Dict[str, Any], frame_size: Sequence[int],
               crop_path: Optional[str], capture_time: float) -> Dict[str, Any]:
    """One final event per plate track (video sources)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "event_type": "plate.recognized",
        "source": _source(src, None),
        "camera_id": src.id,
        "timestamp": iso_utc(capture_time),
        "processed_at": iso_utc(_dt.datetime.now(_dt.timezone.utc).timestamp()),
        "track_id": int(res.track_id),
        "model": model,
        "plate_type": res.plate_type,
        "plate_string_fa": res.plate_string_fa,
        "plate_string_latin": res.plate_string_latin,
        "plate_key": plate_key(res.plate_string_latin) if res.plate_string_latin else "",
        "zone": res.zone,
        "expiry": res.expiry,
        "markers": res.markers,
        "characters": [dict(c, box=_num(c["box"])) for c in res.characters],
        "confidence": round(float(res.confidence), 4),
        "is_valid": res.is_valid,
        "invalid_reason": res.invalid_reason,
        "frames_voted": int(res.frames_voted),
        "plate_bbox": _num(res.best.get("plate_bbox") or [0, 0, 0, 0]),
        "frame_size": [int(frame_size[0]), int(frame_size[1])],
        "best_frame_crop_path": crop_path,
    }


def from_image(read: PlateRead, src, model: Dict[str, Any], frame_size: Sequence[int], file_name: str,
               crop_path: Optional[str], file_time: float) -> Dict[str, Any]:
    """Image mode: one read, no tracker, no voting."""
    d = read.to_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "event_type": "plate.recognized.image",
        "source": _source(src, file_name),
        "camera_id": src.id,
        "timestamp": iso_utc(file_time),
        "processed_at": iso_utc(_dt.datetime.now(_dt.timezone.utc).timestamp()),
        "track_id": None,
        "model": model,
        "plate_type": d["plate_type"],
        "plate_string_fa": d["plate_string_fa"],
        "plate_string_latin": d["plate_string_latin"],
        "plate_key": plate_key(d["plate_string_latin"]) if d["plate_string_latin"] else "",
        "zone": d["zone"],
        "expiry": d["expiry"],
        "markers": d["markers"],
        "characters": d["characters"],
        "confidence": d["confidence"],
        "is_valid": d["is_valid"],
        "invalid_reason": d["invalid_reason"],
        "frames_voted": 1,
        "plate_bbox": d["plate_bbox"],
        "frame_size": [int(frame_size[0]), int(frame_size[1])],
        "best_frame_crop_path": crop_path,
    }


_validator = None


def validate(event: Dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if the event does not match schema 2.0."""
    global _validator
    if _validator is None:
        import jsonschema

        _validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    _validator.validate(event)
