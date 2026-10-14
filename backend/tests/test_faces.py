"""Face recognition: matching to persons, new unnamed persons, rename/move/merge, snapshot library, retention."""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import uuid

import numpy as np

KEY = {"X-Ingest-Key": "ingest-test-key"}
rng = np.random.default_rng(7)


def unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


def face(env, emb=None, cam="door", width=80, score=0.9, ts=None, snapshot=True, yaw=0.0):
    eid = str(uuid.uuid4())
    rel = f"faces/{cam}/2026-10-13/{eid}.jpg"
    if snapshot:
        p = env / "crops" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xff\xd8jpeg")
    ev = {"schema_version": "1.0", "event_id": eid, "event_type": "face.detected",
          "source": {"id": cam, "type": "rtsp", "uri_redacted": "rtsp://cam/1", "file_name": None}, "camera_id": cam,
          "timestamp": (ts or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "track_id": 3,
          "face_bbox": [100, 100, 100 + width, 100 + width * 1.2], "frame_size": [1920, 1080], "det_score": 0.8,
          "frames_seen": 5, "snapshot_path": rel, "snapshot_face_box": [10, 10, 60, 70], "model": {"version": "v2"}}
    return {"event": ev, "embed_model": "arcface_r50_w600k", "embed_det_score": score, "sharpness": 80.0, "yaw": yaw,
            "embedding_b64": base64.b64encode(emb.tobytes()).decode() if emb is not None else None}


def test_faces_are_matched_to_persons(client, auth, env):
    alice = unit(rng.normal(size=512))
    r = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, alice)).json()
    assert r["created"] and r["match"] == "new_person"
    pid = r["person_id"]
    same = unit(alice + 0.03 * rng.normal(size=512))                 # same person, another frame
    r2 = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, same)).json()
    assert r2["match"] == "matched" and r2["person_id"] == pid
    other = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, unit(rng.normal(size=512)))).json()
    assert other["match"] == "new_person" and other["person_id"] != pid
    small = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, unit(rng.normal(size=512)), width=20)).json()
    assert small["person_id"] is None and small["match"] == "none"   # too small to start a person
    none = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, None)).json()
    assert none["person_id"] is None                                  # no face found by the landmark detector
    body = face(env, alice)
    assert client.post("/api/v1/ingest/faces", headers=KEY, json=body).json()["created"]
    assert client.post("/api/v1/ingest/faces", headers=KEY, json=body).json()["created"] is False   # idempotent
    assert client.post("/api/v1/ingest/faces", json=body).status_code in (401, 403)

    # the new person is unnamed until an operator names it; then it is found by name
    p = client.get(f"/api/v1/persons/{pid}", headers=auth).json()["person"]
    assert p["auto_named"] and p["faces"] == 3 and p["cover_face"]
    client.patch(f"/api/v1/persons/{pid}", headers=auth, json={"full_name": "علی رضایی"})
    hits = client.get("/api/v1/persons", headers=auth, params={"q": "رضایی"}).json()["items"]
    assert [h["id"] for h in hits] == [pid] and not hits[0]["auto_named"]
    assert client.get("/api/v1/persons", headers=auth, params={"q": f"#{pid}"}).json()["items"][0]["id"] == pid
    faces = client.get("/api/v1/faces", headers=auth, params={"person_id": pid}).json()
    assert faces["total"] == 3 and faces["items"][0]["person_name"] == "علی رضایی"
    assert client.get(f"/api/v1/faces/{faces['items'][0]['id']}/snapshot", headers=auth).status_code == 200

    # a blocklisted person's next face carries the list status
    client.patch(f"/api/v1/persons/{pid}", headers=auth, json={"list_status": "blocklist"})
    r3 = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, unit(alice + 0.02 * rng.normal(size=512)))).json()
    got = client.get("/api/v1/faces", headers=auth, params={"person_id": pid}).json()["items"]
    assert r3["person_id"] == pid and got[0]["list_status"] == "blocklist"


def test_move_merge_and_delete(client, auth, env):
    a, b = unit(rng.normal(size=512)), unit(rng.normal(size=512))
    pa = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, a, cam="yard")).json()["person_id"]
    fb = face(env, b, cam="yard")
    pb = client.post("/api/v1/ingest/faces", headers=KEY, json=fb).json()["person_id"]
    fid = fb["event"]["event_id"]
    # move B's face to A: from now on B-like faces match A
    moved = client.patch(f"/api/v1/faces/{fid}", headers=auth, json={"person_id": pa}).json()
    assert moved["person_id"] == pa and moved["match"] == "manual"
    again = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, unit(b + 0.02 * rng.normal(size=512)), cam="yard")).json()
    assert again["person_id"] == pa
    # merge: everything of pb goes to pa, pb disappears
    client.patch(f"/api/v1/persons/{pa}", headers=auth, json={"full_name": "Sara"})
    assert client.post(f"/api/v1/persons/{pb}/merge", headers=auth, json={"into": pa}).status_code == 200
    assert client.get(f"/api/v1/persons/{pb}", headers=auth).status_code == 404
    assert client.post(f"/api/v1/persons/{pa}/merge", headers=auth, json={"into": pa}).status_code == 400
    # delete a face: record and snapshot file go
    snap = env / "crops" / fb["event"]["snapshot_path"]
    assert snap.exists() and client.delete(f"/api/v1/faces/{fid}", headers=auth).status_code == 200
    assert not snap.exists() and client.get(f"/api/v1/faces/{fid}/snapshot", headers=auth).status_code == 404


def test_snapshot_library_lists_and_deletes(client, auth, env):
    f = face(env, unit(rng.normal(size=512)), cam="lib")
    client.post("/api/v1/ingest/faces", headers=KEY, json=f)
    lib = client.get("/api/v1/snapshots", headers=auth, params={"camera_id": "lib"}).json()
    assert lib["total"] == 1 and lib["items"][0]["kind"] == "face"
    assert client.get("/api/v1/snapshots", headers=auth, params={"camera_id": "lib", "kind": "plate"}).json()["total"] == 0
    r = client.request("DELETE", "/api/v1/snapshots", headers=auth,
                       json={"items": [{"kind": "face", "id": f["event"]["event_id"]}]})
    assert r.json()["deleted"] == 1 and not (env / "crops" / f["event"]["snapshot_path"]).exists()
    assert client.get("/api/v1/snapshots", headers=auth, params={"camera_id": "lib"}).json()["total"] == 0


def test_viewer_cannot_change_faces(client, auth, env):
    client.post("/api/v1/users", headers=auth, json={"username": "faceviewer", "password": "viewer-password-1", "role": "viewer"})
    tok = client.post("/api/v1/auth/login", data={"username": "faceviewer", "password": "viewer-password-1"}).json()["access_token"]
    v = {"Authorization": f"Bearer {tok}"}
    f = face(env, unit(rng.normal(size=512)), cam="v")
    client.post("/api/v1/ingest/faces", headers=KEY, json=f)
    assert client.get("/api/v1/faces", headers=v).status_code == 200
    assert client.patch(f"/api/v1/faces/{f['event']['event_id']}", headers=v, json={"new_person": True}).status_code == 403
    assert client.request("DELETE", "/api/v1/snapshots", headers=v, json={"items": [{"kind": "face", "id": f["event"]["event_id"]}]}).status_code == 403


def test_retention_purges_old_faces(client, auth, env):
    old = face(env, unit(rng.normal(size=512)), cam="old", ts=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))
    client.post("/api/v1/ingest/faces", headers=KEY, json=old)
    from app.main import retention_once
    asyncio.run(retention_once(dt.datetime.now(dt.timezone.utc)))
    assert client.get("/api/v1/faces", headers=auth, params={"camera_id": "old"}).json()["total"] == 0
    assert not (env / "crops" / old["event"]["snapshot_path"]).exists()


def test_register_people_with_photos(client, auth, env):
    """Manual registration: each photo's face (from the face service) becomes a reference, so later camera faces of
    that person are recognized; a photo without a face is reported; an already seen face is offered for merging."""
    from app.routes import faces as F
    bob = unit(rng.normal(size=512))
    seen = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, unit(bob + 0.03 * rng.normal(size=512)), cam="gate")).json()

    async def fake(data: bytes):
        if data == b"noface":
            return 422, {"detail": "no face found in the photo"}
        v = unit(bob + 0.02 * rng.normal(size=512))
        return 200, {"embed_model": "arcface_r50_w600k", "embedding_b64": base64.b64encode(v.tobytes()).decode(),
                     "det_score": 0.95, "sharpness": 90.0, "faces": 1, "box": [10, 10, 90, 110], "size": [200, 200],
                     "crop_jpeg_b64": base64.b64encode(b"\xff\xd8crop").decode()}
    F.EmbedFn = fake
    try:
        r = client.post("/api/v1/persons/register", headers=auth, data={"full_name": "Bob Karimi", "list_status": "whitelist"},
                        files=[("photos", ("bob1.jpg", b"jpg1", "image/jpeg")), ("photos", ("bob2.jpg", b"jpg2", "image/jpeg")),
                               ("photos", ("empty.jpg", b"noface", "image/jpeg"))])
        assert r.status_code == 201, r.text
        body = r.json()
        assert [p["ok"] for p in body["photos"]] == [True, True, False]
        assert body["similar"]["id"] == seen["person_id"]          # the camera already saw Bob as an unknown person
        pid = body["person"]["id"]
        p = client.get(f"/api/v1/persons/{pid}", headers=auth).json()["person"]
        assert p["faces"] == 2 and p["list_status"] == "whitelist" and not p["auto_named"]
        # without the old unknown person, Bob's next camera face goes to the registered Bob
        client.post(f"/api/v1/persons/{seen['person_id']}/merge", headers=auth, json={"into": pid})
        nxt = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, unit(bob + 0.03 * rng.normal(size=512)), cam="gate")).json()
        assert nxt["person_id"] == pid and nxt["match"] == "matched"
        # only faceless photos: nothing is created
        bad = client.post("/api/v1/persons/register", headers=auth, data={"full_name": "Nobody"},
                          files=[("photos", ("x.jpg", b"noface", "image/jpeg"))])
        assert bad.status_code == 422
        assert not client.get("/api/v1/persons", headers=auth, params={"q": "Nobody"}).json()["items"]
        # a name without photos is allowed (e.g. to link plates)
        assert client.post("/api/v1/persons/register", headers=auth, data={"full_name": "Plate Owner"}).status_code == 201
        more = client.post(f"/api/v1/persons/{pid}/photos", headers=auth, files=[("photos", ("bob3.jpg", b"jpg3", "image/jpeg"))]).json()
        assert more["added"] == 1
    finally:
        F.EmbedFn = None


def test_turned_faces_do_not_start_persons_and_same_visit_links(client, auth, env):
    """A turned head gives a poor embedding: it must not become a new "Unknown" person; within the same visit (same
    camera, a few seconds later) it is linked to the person just recognised."""
    t0 = dt.datetime(2026, 10, 14, 12, 0, 0, tzinfo=dt.timezone.utc)
    reza = unit(rng.normal(size=512))
    first = client.post("/api/v1/ingest/faces", headers=KEY, json=face(env, reza, cam="hall", ts=t0)).json()
    assert first["match"] == "new_person"
    # same person, head turned: embedding only loosely similar (cos ~0.3), 4 s later on the same camera
    o = rng.normal(size=512)
    o = unit(o - (o @ reza) * reza)                       # orthogonal to reza
    turned = unit(0.35 * reza + np.sqrt(1 - 0.35 ** 2) * o)
    sim = float(turned @ reza)
    assert 0.25 <= sim < 0.45, sim
    r = client.post("/api/v1/ingest/faces", headers=KEY,
                    json=face(env, turned, cam="hall", ts=t0 + dt.timedelta(seconds=4), yaw=0.45)).json()
    assert r["person_id"] == first["person_id"] and r["match"] == "linked"
    # a turned stranger with no recent recognised face: stored, but no new person
    lone = client.post("/api/v1/ingest/faces", headers=KEY,
                       json=face(env, unit(rng.normal(size=512)), cam="yard2", ts=t0, yaw=0.5)).json()
    assert lone["person_id"] is None and lone["match"] == "none"
    # long after the visit, the same loosely similar face is not linked
    late = client.post("/api/v1/ingest/faces", headers=KEY,
                       json=face(env, turned, cam="hall", ts=t0 + dt.timedelta(minutes=5), yaw=0.45)).json()
    assert late["person_id"] is None
