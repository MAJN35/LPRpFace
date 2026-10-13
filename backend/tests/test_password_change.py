"""Forced password change of the default admin (before the dashboard is exposed on the LAN)."""
from __future__ import annotations

import asyncio


def _user(name, pw, flag):
    async def make():
        from app.db import SessionLocal
        from app.models import User
        from app.security import hash_password

        async with SessionLocal() as db:
            db.add(User(username=name, password_hash=hash_password(pw), role="admin", must_change_password=flag))
            await db.commit()
    asyncio.run(make())


def test_pending_change_blocks_everything_but_me_and_change(client):
    _user("fresh-admin", "initial-password-1", True)
    tok = client.post("/api/v1/auth/login", data={"username": "fresh-admin", "password": "initial-password-1"}).json()
    assert tok["must_change_password"] is True
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    for path in ("/api/v1/events", "/api/v1/status", "/api/v1/plates", "/api/v1/users"):
        r = client.get(path, headers=h)
        assert r.status_code == 403 and r.json()["detail"] == "password_change_required", path
    assert client.get("/api/v1/auth/me", headers=h).json()["must_change_password"] is True
    # websocket refused too
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/ws/events?token={tok['access_token']}") as ws:
            ws.receive_json()


def test_change_rules_and_unlock(client):
    _user("fresh-admin2", "initial-password-1", True)
    tok = client.post("/api/v1/auth/login", data={"username": "fresh-admin2", "password": "initial-password-1"}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    change = lambda cur, new: client.post("/api/v1/auth/change-password", headers=h,  # noqa: E731
                                          json={"current_password": cur, "new_password": new})
    assert change("wrong-password", "brand-new-password-1").status_code == 403
    assert change("initial-password-1", "short").status_code == 422
    assert change("initial-password-1", "initial-password-1").status_code == 422
    assert change("initial-password-1", "brand-new-password-1").status_code == 200
    assert client.get("/api/v1/events", headers=h).status_code == 200      # same token works after the change
    assert client.post("/api/v1/auth/login", data={"username": "fresh-admin2", "password": "initial-password-1"}).status_code == 401
    assert client.post("/api/v1/auth/login", data={"username": "fresh-admin2", "password": "brand-new-password-1"}).status_code == 200


def test_auth_check_for_live_video(client, auth):
    assert client.get("/api/v1/auth/check", headers=auth).status_code == 204
    assert client.get("/api/v1/auth/check").status_code == 401
    _user("fresh-admin3", "initial-password-1", True)
    tok = client.post("/api/v1/auth/login", data={"username": "fresh-admin3", "password": "initial-password-1"}).json()
    assert client.get("/api/v1/auth/check", headers={"Authorization": f"Bearer {tok['access_token']}"}).status_code == 403
