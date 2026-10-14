"""LPR backend API.  uvicorn app.main:app"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select

from .config import settings
from .db import SessionLocal
from .models import Event, User
from .routes import api, faces, lists, system, videos
from .security import hash_password

log = logging.getLogger("lpr.backend")


async def bootstrap_admin() -> None:
    if not settings.ADMIN_PASSWORD:
        return
    async with SessionLocal() as db:
        if (await db.execute(select(func.count()).select_from(User))).scalar_one() == 0:
            db.add(User(username=settings.ADMIN_USERNAME, password_hash=hash_password(settings.ADMIN_PASSWORD),
                        role="admin", must_change_password=True))   # forced change before first use
            await db.commit()
            log.info("bootstrap admin %r created", settings.ADMIN_USERNAME)


async def retention_once(now: dt.datetime) -> int:
    """Delete events (and their crops) older than RETENTION_DAYS. Returns the number of events deleted."""
    cutoff = now - dt.timedelta(days=settings.RETENTION_DAYS)
    root = Path(settings.CROPS_DIR).resolve()
    async with SessionLocal() as db:
        old = (await db.execute(select(Event.event_id, Event.crop_path).where(Event.ts < cutoff))).all()
        for _, crop in old:
            if crop:
                p = (root / crop).resolve()
                if root in p.parents:
                    with contextlib.suppress(FileNotFoundError):
                        p.unlink()
        await db.execute(delete(Event).where(Event.ts < cutoff))
        n_faces = await faces.purge_faces(db, cutoff)       # face snapshots and embeddings (biometric data)
        await db.commit()
    return len(old) + n_faces


async def retention_loop() -> None:
    while True:
        try:
            n = await retention_once(dt.datetime.now(dt.timezone.utc))
            if n:
                log.info("retention: deleted %d events older than %d days", n, settings.RETENTION_DAYS)
        except Exception:  # noqa: BLE001
            log.exception("retention failed")
        await asyncio.sleep(settings.RETENTION_INTERVAL_S)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.SECRET_KEY == "change-me" and settings.AUTH_ENABLED:
        log.warning("SECRET_KEY is the default; set it in the environment")
    await bootstrap_admin()
    task = asyncio.create_task(retention_loop())
    yield
    task.cancel()


app = FastAPI(title="LPR backend", version="1.0", lifespan=lifespan,
              description="Plate events (schema 2.0), search, cameras and image jobs. Persian plates are personal data.")
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False)
app.include_router(api.router)
app.include_router(system.router)
app.include_router(lists.router)
app.include_router(faces.router)
app.include_router(videos.router)
