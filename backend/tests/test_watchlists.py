"""Watchlists: whitelist / blocklist / unknown for plates and persons, easy moves, effect on events."""
from __future__ import annotations

import asyncio
import uuid

from test_api import BASE, KEY, ev


def plates(client, auth, **p):
    return client.get("/api/v1/plates", params=p, headers=auth).json()


def test_plate_any_form_is_one_entry(client, auth):
    r = client.post("/api/v1/plates", json={"plate": "۲۱ ط ۶۵۴ | ۸۷", "list_status": "blocklist"}, headers=auth)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["plate_key"] == "21Ta65487" and p["plate_string_latin"] == "21 Ta 654 | 87" and p["effective_status"] == "blocklist"
    dup = client.post("/api/v1/plates", json={"plate": "21 Ta 654 87"}, headers=auth)
    assert dup.status_code == 409
    up = client.post("/api/v1/plates", json={"plate": "۲۱ط۶۵۴۸۷", "list_status": "whitelist", "upsert": True}, headers=auth)
    assert up.status_code == 201 and up.json()["id"] == p["id"] and up.json()["list_status"] == "whitelist"


def test_move_plate_between_lists_in_one_call(client, auth):
    p = client.post("/api/v1/plates", json={"plate": "33 Mim 111 | 22"}, headers=auth).json()
    assert p["list_status"] == "unknown"
    for target in ("blocklist", "whitelist", "unknown"):
        r = client.patch(f"/api/v1/plates/{p['id']}", json={"list_status": target}, headers=auth)
        assert r.status_code == 200 and r.json()["list_status"] == target


def test_bulk_move(client, auth):
    ids = [client.post("/api/v1/plates", json={"plate": f"4{i} Nun 22{i} | 1{i}"}, headers=auth).json()["id"] for i in range(3)]
    r = client.post("/api/v1/lists/move", json={"kind": "plate", "ids": ids + [999999], "list_status": "blocklist"}, headers=auth)
    assert r.json()["moved"] == sorted(ids) and r.json()["not_found"] == [999999]
    keys = {x["id"] for x in plates(client, auth, list_status="blocklist", limit=500)["items"]}
    assert set(ids) <= keys


def test_person_lists_and_inheritance(client, auth):
    person = client.post("/api/v1/persons", json={"full_name": "Test Person A", "list_status": "blocklist"}, headers=auth).json()
    pl = client.post("/api/v1/plates", json={"plate": "55 Sad 555 | 55", "person_id": person["id"]}, headers=auth).json()
    assert pl["list_status"] == "unknown" and pl["effective_status"] == "blocklist" and pl["person_name"] == "Test Person A"
    # the plate's own list wins over the person's
    pl = client.patch(f"/api/v1/plates/{pl['id']}", json={"list_status": "whitelist"}, headers=auth).json()
    assert pl["effective_status"] == "whitelist"
    # move the person in one call; unlink the plate
    r = client.patch(f"/api/v1/persons/{person['id']}", json={"list_status": "whitelist"}, headers=auth)
    assert r.json()["list_status"] == "whitelist"
    detail = client.get(f"/api/v1/persons/{person['id']}", headers=auth).json()
    assert detail["person"]["plates"] == 1 and detail["plates"][0]["plate_key"] == "55Sad55555"
    pl = client.patch(f"/api/v1/plates/{pl['id']}", json={"person_id": 0}, headers=auth).json()
    assert pl["person_id"] is None
    bulk = client.post("/api/v1/lists/move", json={"kind": "person", "ids": [person["id"]], "list_status": "unknown"}, headers=auth)
    assert bulk.json()["moved"] == [person["id"]]
    assert client.get("/api/v1/persons", params={"list_status": "unknown", "q": "Person A"}, headers=auth).json()["total"] == 1


def test_events_get_list_status_and_blocklist_alert(client, auth, admin_token):
    client.post("/api/v1/plates", json={"plate": "77 Jim 777 | 77", "list_status": "blocklist", "upsert": True}, headers=auth)
    src = {**BASE["source"], "id": "cam-wl"}
    with client.websocket_connect(f"/api/v1/ws/events?token={admin_token}") as ws:
        hit = ev(camera_id="cam-wl", source=src, plate_string_fa="۷۷ ج ۷۷۷ | ۷۷", plate_string_latin="77 Jim 777 | 77",
                 plate_key="77Jim77777")
        client.post("/api/v1/ingest/events", headers=KEY, json=hit)
        msgs = [ws.receive_json(), ws.receive_json()]
    assert [m["type"] for m in msgs] == ["event", "alert"] and msgs[1]["event"]["list_status"] == "blocklist"
    other = ev(camera_id="cam-wl", source=src)
    client.post("/api/v1/ingest/events", headers=KEY, json=other)
    by = lambda s: client.get("/api/v1/events", params={"camera_id": "cam-wl", "list_status": s}, headers=auth).json()["total"]  # noqa: E731
    assert by("blocklist") == 1 and by("unknown") == 1
    d = client.get(f"/api/v1/events/{hit['event_id']}", headers=auth).json()
    assert d["list_status"] == "blocklist" and d["plate_key"] == "77Jim77777"


def test_unregistered_plates_for_one_click_add(client, auth):
    src = {**BASE["source"], "id": "cam-u"}
    key = f"9{uuid.uuid4().int % 10}Be12345"
    client.post("/api/v1/ingest/events", headers=KEY, json=ev(camera_id="cam-u", source=src, plate_key=key))
    keys = [u["plate_key"] for u in client.get("/api/v1/plates/unregistered", headers=auth).json()]
    assert key in keys
    client.post("/api/v1/plates", json={"plate": key, "list_status": "whitelist"}, headers=auth)
    keys = [u["plate_key"] for u in client.get("/api/v1/plates/unregistered", headers=auth).json()]
    assert key not in keys


def test_viewer_cannot_change_lists(client, auth):
    client.post("/api/v1/users", json={"username": "viewer2", "password": "viewer-password", "role": "viewer"}, headers=auth)
    tok = client.post("/api/v1/auth/login", data={"username": "viewer2", "password": "viewer-password"}).json()["access_token"]
    vh = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/v1/plates", headers=vh).status_code == 200
    assert client.post("/api/v1/plates", json={"plate": "12B34567"}, headers=vh).status_code == 403
    assert client.post("/api/v1/lists/move", json={"kind": "plate", "ids": [1], "list_status": "blocklist"}, headers=vh).status_code == 403


def test_list_changes_are_audited(client, auth):
    async def audit():
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import AuditLog

        async with SessionLocal() as db:
            return [a.target for a in (await db.execute(select(AuditLog).where(AuditLog.action == "list_change"))).scalars()]

    rows = asyncio.run(audit())
    assert any("unknown->blocklist" in t for t in rows) and any("created on blocklist" in t for t in rows)
