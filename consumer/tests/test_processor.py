"""Consumer core: schema validation, duplicates, backend down, rejects -> DLQ, no commit before delivery."""
from __future__ import annotations

import copy
import json
import sys
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import lpr_consumer as lc  # noqa: E402

lc.SCHEMA = HERE.parent / "schemas" / "plate_event-2.0.json"

EVENT = {
    "schema_version": "2.0", "event_id": "", "event_type": "plate.recognized",
    "source": {"id": "cam-01", "type": "rtsp", "uri_redacted": "rtsp://10.0.0.11/ch1", "file_name": None},
    "camera_id": "cam-01", "timestamp": "2026-10-13T08:00:00.000Z", "track_id": 3,
    "model": {"version": "v2", "sha256": "f" * 64, "engine_sha256": "e" * 64, "precision": "fp16",
              "batch_profile": [1, 2, 4]},
    "plate_type": "standard", "plate_string_fa": "۱۲ ب ۳۴۵ | ۶۷", "plate_string_latin": "12 Be 345 | 67",
    "plate_key": "12Be34567", "zone": None, "expiry": None, "markers": [],
    "characters": [{"class_id": 1, "name": "1", "confidence": 0.9, "box": [1, 2, 3, 4]}],
    "confidence": 0.9, "is_valid": True, "invalid_reason": None, "frames_voted": 4,
    "plate_bbox": [10, 20, 110, 50], "frame_size": [1920, 1080], "best_frame_crop_path": "cam-01/x.jpg",
}


def event(**kw):
    e = copy.deepcopy(EVENT)
    e["event_id"] = str(uuid.uuid4())
    e.update(kw)
    return e


class Msg:
    def __init__(self, payload):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def value(self):
        return self.payload


class Harness:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.delivered, self.dlq, self.commits, self.sleeps = [], [], [], []
        self.p = lc.Processor(self.deliver, lambda m, r: self.dlq.append(r), self.commits.append,
                              sleep=self.sleeps.append)

    def deliver(self, ev):
        status = self.responses.pop(0) if self.responses else ("ok", "200")
        if status[0] == "ok":
            self.delivered.append(ev["event_id"])
        if status[0] == "stop":  # simulate a shutdown while the backend is down
            self.p.stopping = True
            return "retry", "connection refused"
        return status


def test_valid_event_delivered_then_committed():
    h = Harness()
    m = Msg(event())
    h.p.handle(m)
    assert len(h.delivered) == 1 and h.commits == [m] and not h.dlq


@pytest.mark.parametrize("payload", [b"not json", {"schema_version": "2.0"},
                                     {**EVENT, "event_id": str(uuid.uuid4()), "plate_type": "spaceship"},
                                     {**EVENT, "event_id": str(uuid.uuid4()), "extra": 1}])
def test_invalid_messages_go_to_dlq_and_are_committed(payload):
    h = Harness()
    m = Msg(payload)
    h.p.handle(m)
    assert h.delivered == [] and len(h.dlq) == 1 and h.dlq[0].startswith("invalid") and h.commits == [m]


def test_duplicate_event_is_skipped_but_committed():
    h = Harness()
    e = event()
    h.p.handle(Msg(e))
    h.p.handle(Msg(e))
    assert len(h.delivered) == 1 and h.p.stats["duplicates_skipped"] == 1 and len(h.commits) == 2


def test_backend_down_retries_with_backoff_and_commits_only_after_delivery():
    h = Harness([("retry", "connection refused")] * 4 + [("ok", "200")])
    m = Msg(event())
    h.p.handle(m)
    assert h.p.stats["backend_retries"] == 4 and h.sleeps == [1.0, 2.0, 4.0, 8.0]
    assert len(h.delivered) == 1 and h.commits == [m]


def test_shutdown_while_backend_down_does_not_commit():
    """Restart without loss: the uncommitted message is re-read by the next consumer."""
    h = Harness([("retry", "503"), ("stop", "")])
    h.p.handle(Msg(event()))
    assert h.commits == [] and h.delivered == []


def test_backend_reject_goes_to_dlq():
    h = Harness([("reject", "422 bad")])
    h.p.handle(Msg(event()))
    assert h.dlq == ["backend rejected: 422 bad"] and len(h.commits) == 1


def test_delivery_classifies_http_status(monkeypatch):
    import urllib.error

    d = lc.Delivery("http://backend:8000", "k")

    def raise_(code):
        def f(*a, **kw):
            raise urllib.error.HTTPError(d.url, code, "x", {}, None)
        return f

    monkeypatch.setattr(lc.urllib.request, "urlopen", raise_(422))
    assert d(event())[0] == "reject"
    monkeypatch.setattr(lc.urllib.request, "urlopen", raise_(503))
    assert d(event())[0] == "retry"
    monkeypatch.setattr(lc.urllib.request, "urlopen", raise_(429))
    assert d(event())[0] == "retry"
