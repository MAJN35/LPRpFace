"""API tests: idempotent ingest, auth/roles, pagination, filters, Persian/Latin search, detail + audit, crops,
retention, live updates, OpenAPI, inference proxy errors."""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import uuid

BASE = {
    "schema_version": "2.0", "event_type": "plate.recognized",
    "source": {"id": "cam-01", "type": "rtsp", "uri_redacted": "rtsp://10.0.0.11/ch1", "file_name": None},
    "camera_id": "cam-01", "track_id": 3,
    "model": {"version": "v2", "sha256": "f" * 64, "engine_sha256": "e" * 64, "precision": "fp16",
              "batch_profile": [1, 2, 4]},
    "plate_type": "standard", "plate_string_fa": "۱۲ ب ۳۴۵ | ۶۷", "plate_string_latin": "12 Be 345 | 67",
    "plate_key": "12Be34567", "zone": None, "expiry": None, "markers": [],
    "characters": [{"class_id": 1, "name": "1", "confidence": 0.9, "box": [1, 2, 3, 4]}],
    "confidence": 0.9, "is_valid": True, "invalid_reason": None, "frames_voted": 4,
    "plate_bbox": [10, 20, 110, 50], "frame_size": [1920, 1080], "best_frame_crop_path": None,
}
KEY = {"X-Ingest-Key": "ingest-test-key"}


def ev(ts=None, **kw):
    e = copy.deepcopy(BASE)
    e["event_id"] = str(uuid.uuid4())
    e["timestamp"] = (ts or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    e.update(kw)
    return e


def test_ingest_requires_key(client):
    assert client.post("/api/v1/ingest/events", json=ev()).status_code == 401
    assert client.post("/api/v1/ingest/events", json=ev(), headers={"X-Ingest-Key": "wrong"}).status_code == 401


def test_ingest_is_idempotent(client, auth):
    e = ev(camera_id="cam-idem", source={**BASE["source"], "id": "cam-idem"})
    r1 = client.post("/api/v1/ingest/events", json=e, headers=KEY)
    r2 = client.post("/api/v1/ingest/events", json=e, headers=KEY)
    assert r1.json()["created"] is True and r2.json()["created"] is False
    page = client.get("/api/v1/events", params={"camera_id": "cam-idem"}, headers=auth).json()
    assert page["total"] == 1


def test_ingest_rejects_invalid(client):
    bad = ev(confidence=1.5)
    assert client.post("/api/v1/ingest/events", json=bad, headers=KEY).status_code == 422


def test_auth_required_and_roles(client, auth):
    assert client.get("/api/v1/events").status_code == 401
    assert client.post("/api/v1/auth/login", data={"username": "admin", "password": "nope"}).status_code == 401
    r = client.post("/api/v1/users", json={"username": "viewer1", "password": "viewer-password", "role": "viewer"},
                    headers=auth)
    assert r.status_code == 201
    tok = client.post("/api/v1/auth/login", data={"username": "viewer1", "password": "viewer-password"}).json()
    vh = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get("/api/v1/events", headers=vh).status_code == 200
    assert client.post("/api/v1/users", json={"username": "x" * 5, "password": "p" * 12, "role": "admin"},
                       headers=vh).status_code == 403
    assert client.post("/api/v1/cameras", json={"id": "x"}, headers=vh).status_code == 403
    assert client.get("/api/v1/events/export.csv", headers=vh).status_code == 403
    assert client.get("/api/v1/events", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_pagination(client, auth):
    t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    for i in range(25):
        client.post("/api/v1/ingest/events", headers=KEY,
                    json=ev(ts=t0 + dt.timedelta(minutes=i), camera_id="cam-page",
                            source={**BASE["source"], "id": "cam-page"}))
    p = client.get("/api/v1/events", params={"camera_id": "cam-page", "limit": 10, "offset": 20}, headers=auth).json()
    assert p["total"] == 25 and len(p["items"]) == 5
    first = client.get("/api/v1/events", params={"camera_id": "cam-page", "limit": 1}, headers=auth).json()
    assert first["items"][0]["timestamp"].startswith("2026-01-01T00:24")   # newest first
    assert client.get("/api/v1/events", params={"limit": 500}, headers=auth).status_code == 422


def test_filters(client, auth):
    t = dt.datetime(2026, 2, 1, 12, tzinfo=dt.timezone.utc)
    src = {**BASE["source"], "id": "cam-f"}
    client.post("/api/v1/ingest/events", headers=KEY, json=ev(ts=t, camera_id="cam-f", source=src, plate_type="freezone",
                zone="KISH", plate_string_latin="96213", plate_string_fa="۹۶۲۱۳", plate_key="96213"))
    client.post("/api/v1/ingest/events", headers=KEY, json=ev(ts=t, camera_id="cam-f", source=src, is_valid=False,
                invalid_reason="expected 8 characters, found 6"))
    client.post("/api/v1/ingest/events", headers=KEY, json=ev(ts=t, camera_id="cam-f", source=src,
                model={**BASE["model"], "version": "v1"}))
    q = lambda **p: client.get("/api/v1/events", params={"camera_id": "cam-f", **p}, headers=auth).json()["total"]  # noqa: E731
    assert q() == 3
    assert q(plate_type="freezone") == 1 and q(zone="KISH") == 1
    assert q(is_valid="false") == 1 and q(model_version="v1") == 1
    assert q(**{"from": "2026-02-01T11:00:00Z", "to": "2026-02-01T13:00:00Z"}) == 3
    assert q(**{"from": "2026-02-01T13:00:00Z"}) == 0


def test_search_persian_and_latin(client, auth):
    src = {**BASE["source"], "id": "cam-s"}
    client.post("/api/v1/ingest/events", headers=KEY, json=ev(camera_id="cam-s", source=src,
                plate_string_fa="۴۵ ی ۲۹۹ | ۳۱", plate_string_latin="45 Ye 299 | 31", plate_key="45Ye29931"))
    hits = lambda q: client.get("/api/v1/events", params={"camera_id": "cam-s", "q": q}, headers=auth).json()["total"]  # noqa: E731
    for query in ("۴۵ ی ۲۹۹ | ۳۱", "45 Ye 299 | 31", "45Y29931", "۴۵ي۲۹۹۳۱", "ایران ۳۱ - ۲۹۹ ی ۴۵", "۲۹۹", "299",
                  "ی۲۹۹", "45ye"):
        assert hits(query) == 1, query
    assert hits("۸۸۸") == 0


def test_event_detail_audit_and_crop(client, auth, env):
    crop_rel = "cam-c/2026-03-01/x.jpg"
    (env / "crops" / "cam-c" / "2026-03-01").mkdir(parents=True)
    (env / "crops" / crop_rel).write_bytes(b"\xff\xd8\xff fake jpeg")
    e = ev(camera_id="cam-c", source={**BASE["source"], "id": "cam-c"}, best_frame_crop_path=crop_rel)
    client.post("/api/v1/ingest/events", headers=KEY, json=e)
    d = client.get(f"/api/v1/events/{e['event_id']}", headers=auth).json()
    assert d["characters"][0]["class_id"] == 1 and d["has_crop"] and d["model_sha256"] == "f" * 64
    r = client.get(f"/api/v1/events/{e['event_id']}/crop", headers=auth)
    assert r.status_code == 200 and r.content.startswith(b"\xff\xd8\xff")
    assert client.get(f"/api/v1/events/{e['event_id']}/crop", params={"token": auth["Authorization"][7:]}).status_code == 200
    bad = ev(best_frame_crop_path="../../etc/passwd")
    client.post("/api/v1/ingest/events", headers=KEY, json=bad)
    assert client.get(f"/api/v1/events/{bad['event_id']}/crop", headers=auth).status_code == 404
    assert client.get(f"/api/v1/events/{uuid.uuid4()}", headers=auth).status_code == 404

    async def audit():
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import AuditLog

        async with SessionLocal() as db:
            return [(a.action, a.target) for a in (await db.execute(select(AuditLog))).scalars()]

    rows = asyncio.run(audit())
    assert ("view_event", e["event_id"]) in rows and ("view_crop", e["event_id"]) in rows


def test_export_csv(client, auth):
    r = client.get("/api/v1/events/export.csv", params={"camera_id": "cam-s"}, headers=auth)
    assert r.status_code == 200 and "45 Ye 299 | 31" in r.text and r.text.startswith("timestamp,")


def test_retention_deletes_old_events_and_crops(client, auth, env):
    from app.main import retention_once

    old_crop = "cam-r/old.jpg"
    (env / "crops" / "cam-r").mkdir()
    (env / "crops" / old_crop).write_bytes(b"x")
    old = ev(ts=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc), camera_id="cam-r",
             source={**BASE["source"], "id": "cam-r"}, best_frame_crop_path=old_crop)
    new = ev(camera_id="cam-r", source={**BASE["source"], "id": "cam-r"})
    for e in (old, new):
        client.post("/api/v1/ingest/events", headers=KEY, json=e)
    n = asyncio.run(retention_once(dt.datetime.now(dt.timezone.utc)))
    assert n >= 1 and not (env / "crops" / old_crop).exists()
    left = client.get("/api/v1/events", params={"camera_id": "cam-r"}, headers=auth).json()
    assert [i["event_id"] for i in left["items"]] == [new["event_id"]]


def test_live_websocket_receives_ingested_event(client, admin_token):
    with client.websocket_connect(f"/api/v1/ws/events?token={admin_token}") as ws:
        e = ev(camera_id="cam-ws", source={**BASE["source"], "id": "cam-ws"})
        client.post("/api/v1/ingest/events", headers=KEY, json=e)
        msg = ws.receive_json()
        assert msg["type"] == "event" and msg["event"]["event_id"] == e["event_id"]


def test_websocket_rejects_without_token(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws/events") as ws:
            ws.receive_json()


def test_stats_status_and_openapi(client, auth):
    s = client.get("/api/v1/stats", params={"hours": 24 * 90}, headers=auth).json()
    assert s["total"] >= 1 and "cam-s" in s["by_camera"]
    st = client.get("/api/v1/status", headers=auth).json()
    assert st["inference"]["reachable"] is False and st["database"]["events"] >= 1
    assert client.get("/api/v1/cameras", headers=auth).status_code == 503
    spec = client.get("/openapi.json").json()
    for path in ("/api/v1/events", "/api/v1/ingest/events", "/api/v1/images", "/api/v1/cameras", "/api/v1/stats"):
        assert path in spec["paths"]
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert client.get("/api/v1/ready").status_code == 200


def test_image_upload_validation(client, auth):
    r = client.post("/api/v1/images", headers=auth, files={"file": ("a.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 415
    r = client.post("/api/v1/images", headers=auth, files={"file": ("a.jpg", b"\xff\xd8\xff" + b"0" * 10, "image/jpeg")})
    assert r.status_code == 503   # inference service not running in unit tests


def test_slot_search_exact_and_partial(client, auth):
    src = {**BASE["source"], "id": "cam-p"}
    post = lambda **kw: client.post("/api/v1/ingest/events", headers=KEY, json=ev(camera_id="cam-p", source=src, **kw))  # noqa: E731
    post(plate_string_latin="45 Ye 299 | 31", plate_string_fa="۴۵ ی ۲۹۹ | ۳۱", plate_key="45Ye29931")
    post(plate_string_latin="45 Sad 299 | 31", plate_string_fa="۴۵ ص ۲۹۹ | ۳۱", plate_key="45Sad29931")
    post(plate_string_latin="45 S 299 | 31", plate_string_fa="۴۵ S ۲۹۹ | ۳۱", plate_key="45S29931", plate_type="diplomatic")
    post(plate_type="freezone", zone="KISH", plate_string_latin="96213", plate_string_fa="۹۶۲۱۳", plate_key="96213")
    post(plate_type="protocol", plate_string_latin="1 2 3 4", plate_string_fa="۱ ۲ ۳ ۴", plate_key="1234",
         is_valid=None, invalid_reason="not_applicable")

    def hits(slots, layout="standard", match="partial", **p):
        r = client.get("/api/v1/events", params={"camera_id": "cam-p", "slots": slots, "layout": layout, "match": match,
                                                 **p}, headers=auth)
        return r.json()["total"] if r.status_code == 200 else r.status_code

    assert hits("4,5,Ye,2,9,9,3,1", match="exact") == 1
    assert hits("4,5,S,2,9,9,3,1", match="exact") == 1          # D/S marker is not a prefix of Sad/Sin/Shin
    assert hits("4,5,,2,9,9,3,1") == 3                           # empty letter = any letter
    assert hits("4,5,,2,9,9,3,1", plate_type="standard") == 2
    assert hits(",,Sad,,,,,") == 1 and hits(",,,,9,,,") == 3 and hits(",,,,,,,") == 3 + 2
    assert hits("4,,Ye,2,9,9,3,1", match="exact") == 422         # exact needs every position
    assert hits("4,5,plate,2,9,9,3,1") == 422                    # object labels are never characters
    assert hits("4,5,fz_KISH,2,9,9,3,1") == 422 and hits("4,5,face,2,9,9,3,1") == 422
    assert hits("4,5,Ye,2,9,9,3") == 422 and hits("a,5,Ye,2,9,9,3,1") == 422
    assert hits("9,6,2,1,3", layout="freezone", match="exact", zone="KISH") == 1
    assert hits("9,,,,3", layout="freezone") == 1 and hits("9,6,2,1", layout="freezone") == 422
    assert hits(",2,3,,", layout="protocol") == 1 and hits("1,2,3,4", layout="protocol", match="exact") == 1
    assert hits("2,3,4,5", layout="protocol", match="exact") == 0


def test_video_upload_list_delete(client, auth, env, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VIDEOS_DIR", str(env / "videos"))
    monkeypatch.setattr(settings, "VIDEO_MAX_MB", 1)
    monkeypatch.setattr(settings, "VIDEO_MIN_FREE_MB", 0)
    data = b"\x00\x00\x00\x18ftypmp42" + b"x" * 5000
    r = client.put("/api/v1/videos/gate test.mp4", headers={**auth, "Content-Type": "application/octet-stream"}, content=data)
    assert r.status_code == 201, r.text
    assert r.json()["path"] == "/data/videos/gate test.mp4" and r.json()["size"] == len(data)
    assert (env / "videos" / "gate test.mp4").read_bytes() == data
    assert client.put("/api/v1/videos/gate test.mp4", headers=auth, content=data).status_code == 409
    for bad in ("../x.mp4", ".hidden.mp4", "a.exe", "a/b.mp4"):
        assert client.put(f"/api/v1/videos/{bad}", headers=auth, content=data).status_code in (404, 422), bad
    assert client.put("/api/v1/videos/big.mp4", headers=auth, content=b"x" * (1024 * 1024 + 1)).status_code == 413
    assert not list((env / "videos").glob(".*part"))                 # no partial files left behind
    listing = client.get("/api/v1/videos", headers=auth).json()
    assert [v["name"] for v in listing["items"]] == ["gate test.mp4"] and listing["free_bytes"] > 0
    assert client.delete("/api/v1/videos/gate test.mp4", headers=auth).json()["deleted"]
    assert client.get("/api/v1/videos", headers=auth).json()["items"] == []
