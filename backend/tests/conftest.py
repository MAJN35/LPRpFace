import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / "reader")]


@pytest.fixture(scope="session")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("backend")
    os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{d}/test.db", SECRET_KEY="test-secret-key-0123456789abcdef",
                      INGEST_KEY="ingest-test-key", ADMIN_USERNAME="admin", ADMIN_PASSWORD="admin-password-1",
                      CROPS_DIR=str(d / "crops"), INFERENCE_URL="http://127.0.0.1:9", AUTH_ENABLED="true",
                      RETENTION_DAYS="30", RETENTION_INTERVAL_S="3600")
    (d / "crops").mkdir()
    return d


@pytest.fixture(scope="session")
def client(env):
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app

    async def create():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)

    asyncio.run(create())
    with TestClient(app) as c:
        yield c


NEW_ADMIN_PASSWORD = "admin-password-changed-2"


@pytest.fixture(scope="session")
def admin_token(client):
    """The bootstrap admin must change its password before anything else (forced change)."""
    r = client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin-password-1"})
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    first = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.post("/api/v1/auth/change-password", headers=first,
                    json={"current_password": "admin-password-1", "new_password": NEW_ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/login", data={"username": "admin", "password": NEW_ADMIN_PASSWORD})
    assert r.json()["must_change_password"] is False
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}
