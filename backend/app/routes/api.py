"""Auth, ingest, events, statistics and live updates."""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lpr_reader.normalize import compact, search_keys

from .. import schemas
from ..config import settings
from ..db import SessionLocal, get_db
from ..live import broadcaster
from ..models import AuditLog, Event, Person, User
from .lists import resolve_status
from ..security import (admin, any_role, create_token, hash_password, ingest_key, operator, user_from_token,
                        verify_password)

router = APIRouter(prefix="/api/v1")


# --- auth ------------------------------------------------------------------------------------------------------------
@router.post("/auth/login", response_model=schemas.Token, tags=["auth"])
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.username == form.username))).scalars().first()
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
    return schemas.Token(access_token=create_token(user.username, user.role), role=user.role,
                         must_change_password=user.must_change_password)


@router.get("/auth/me", response_model=schemas.UserOut, tags=["auth"])
async def me(user: User = Depends(any_role)):
    return schemas.UserOut(username=user.username, role=user.role, is_active=user.is_active,
                           must_change_password=user.must_change_password)


@router.post("/auth/change-password", response_model=schemas.UserOut, tags=["auth"])
async def change_password(body: schemas.PasswordChange, user: User = Depends(any_role),
                          db: AsyncSession = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "current password is wrong")
    if body.new_password == body.current_password:
        raise HTTPException(422, "the new password must differ from the current one")
    row = await db.get(User, user.id)
    row.password_hash = hash_password(body.new_password)
    row.must_change_password = False
    db.add(AuditLog(username=user.username, action="password_change", target=user.username))
    await db.commit()
    return schemas.UserOut(username=row.username, role=row.role, is_active=row.is_active, must_change_password=False)


@router.post("/users", response_model=schemas.UserOut, status_code=201, tags=["auth"])
async def create_user(body: schemas.UserCreate, _: User = Depends(admin), db: AsyncSession = Depends(get_db)):
    db.add(User(username=body.username, password_hash=hash_password(body.password), role=body.role))
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(409, "username exists") from None
    return schemas.UserOut(username=body.username, role=body.role, is_active=True)


@router.get("/users", response_model=list[schemas.UserOut], tags=["auth"])
async def list_users(_: User = Depends(admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User).order_by(User.username))).scalars().all()
    return [schemas.UserOut(username=u.username, role=u.role, is_active=u.is_active) for u in rows]


# --- ingest (consumer) -------------------------------------------------------------------------------------------------
def _row(e: schemas.EventIn) -> Event:
    return Event(event_id=e.event_id, event_type=e.event_type, camera_id=e.camera_id, source_type=e.source.type,
                 source_uri=e.source.uri_redacted, source_file=e.source.file_name, ts=e.timestamp,
                 processed_at=e.processed_at, track_id=e.track_id, model_version=e.model.version,
                 model_sha256=e.model.sha256, engine_sha256=e.model.engine_sha256, precision=e.model.precision,
                 batch_profile=e.model.batch_profile, plate_type=e.plate_type, plate_string_fa=e.plate_string_fa,
                 plate_string_latin=e.plate_string_latin, plate_key=e.plate_key, zone=e.zone, expiry=e.expiry,
                 markers=e.markers, characters=e.characters, confidence=e.confidence, is_valid=e.is_valid,
                 invalid_reason=e.invalid_reason, frames_voted=e.frames_voted, plate_bbox=e.plate_bbox,
                 frame_size=e.frame_size, crop_path=e.best_frame_crop_path)


async def _enriched(db: AsyncSession, e: schemas.EventIn) -> Event:
    row = _row(e)
    row.list_status, row.person_id = await resolve_status(db, e.plate_key if e.is_valid else "")
    return row


def _out(r: Event) -> schemas.EventOut:
    return schemas.EventOut(event_id=r.event_id, event_type=r.event_type, camera_id=r.camera_id,
                            source_type=r.source_type, source_file=r.source_file, timestamp=r.ts,
                            track_id=r.track_id, model_version=r.model_version, plate_type=r.plate_type,
                            plate_string_fa=r.plate_string_fa, plate_string_latin=r.plate_string_latin, zone=r.zone,
                            expiry=r.expiry, markers=r.markers or [], confidence=r.confidence, is_valid=r.is_valid,
                            invalid_reason=r.invalid_reason, frames_voted=r.frames_voted,
                            has_crop=bool(r.crop_path), list_status=r.list_status or "unknown",
                            person_id=r.person_id)


@router.post("/ingest/events", response_model=schemas.IngestResult, tags=["ingest"],
             dependencies=[Depends(ingest_key)])
async def ingest(body: schemas.EventIn, db: AsyncSession = Depends(get_db)):
    """Idempotent: the same event_id twice creates one row (200 with created=false the second time)."""
    if await db.get(Event, body.event_id) is not None:
        return schemas.IngestResult(event_id=body.event_id, created=False)
    row = await _enriched(db, body)
    out = _out(row).model_dump(mode="json")
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:  # a concurrent delivery of the same event won the race
        await db.rollback()
        return schemas.IngestResult(event_id=body.event_id, created=False)
    broadcaster.publish({"type": "event", "event": out})
    if out["list_status"] == "blocklist":
        broadcaster.publish({"type": "alert", "event": out})
    return schemas.IngestResult(event_id=body.event_id, created=True)


# --- events ------------------------------------------------------------------------------------------------------------
def _filters(camera_id, since, until, plate_type, zone, is_valid, model_version, event_type, q, list_status=None):
    conds = []
    if list_status:
        conds.append(Event.list_status == list_status)
    if camera_id:
        conds.append(Event.camera_id == camera_id)
    if since:
        conds.append(Event.ts >= since)
    if until:
        conds.append(Event.ts < until)
    if plate_type:
        conds.append(Event.plate_type == plate_type)
    if zone:
        conds.append(Event.zone == zone)
    if is_valid is not None:
        conds.append(Event.is_valid.is_(is_valid))
    if model_version:
        conds.append(Event.model_version == model_version)
    if event_type:
        conds.append(Event.event_type == event_type)
    if q:
        # Persian or Latin, any digit script/spacing: match the normalized plate key, or the raw strings.
        alts = [Event.plate_key.ilike(f"%{k}%") for k in search_keys(q)]
        raw = compact(q)
        alts += [func.replace(Event.plate_string_fa, " ", "").ilike(f"%{raw}%"),
                 func.replace(Event.plate_string_latin, " ", "").ilike(f"%{raw}%")]
        conds.append(or_(*alts))
    return and_(*conds) if conds else None


@router.get("/events", response_model=schemas.Page, tags=["events"])
async def list_events(camera_id: Optional[str] = None, since: Optional[dt.datetime] = Query(None, alias="from"),
                      until: Optional[dt.datetime] = Query(None, alias="to"), plate_type: Optional[str] = None,
                      zone: Optional[str] = None, is_valid: Optional[bool] = None,
                      model_version: Optional[str] = None, event_type: Optional[str] = None,
                      q: Optional[str] = Query(None, max_length=64),
                      list_status: Optional[str] = Query(None, pattern="^(whitelist|blocklist|unknown)$"),
                      limit: int = Query(50, ge=1, le=200),
                      offset: int = Query(0, ge=0), user: User = Depends(any_role),
                      db: AsyncSession = Depends(get_db)):
    where = _filters(camera_id, since, until, plate_type, zone, is_valid, model_version, event_type, q, list_status)
    base = select(Event)
    count = select(func.count()).select_from(Event)
    if where is not None:
        base, count = base.where(where), count.where(where)
    total = (await db.execute(count)).scalar_one()
    rows = (await db.execute(base.order_by(Event.ts.desc(), Event.event_id).limit(limit).offset(offset))).scalars()
    if q:
        db.add(AuditLog(username=user.username, action="search", target=q[:64]))
        await db.commit()
    return schemas.Page(items=[_out(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/events/export.csv", tags=["events"])
async def export_csv(camera_id: Optional[str] = None, since: Optional[dt.datetime] = Query(None, alias="from"),
                     until: Optional[dt.datetime] = Query(None, alias="to"), q: Optional[str] = None,
                     user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    where = _filters(camera_id, since, until, None, None, None, None, None, q)
    stmt = select(Event).order_by(Event.ts.desc()).limit(100000)
    if where is not None:
        stmt = stmt.where(where)
    rows = (await db.execute(stmt)).scalars().all()
    db.add(AuditLog(username=user.username, action="export", target=f"{len(rows)} rows camera={camera_id} q={q}"))
    await db.commit()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp", "camera_id", "plate_string_fa", "plate_string_latin", "plate_type", "zone", "is_valid", "list_status",
                "confidence", "event_id"])
    for r in rows:
        w.writerow([r.ts.isoformat(), r.camera_id, r.plate_string_fa, r.plate_string_latin, r.plate_type, r.zone,
                    r.is_valid, r.list_status, f"{r.confidence:.3f}", r.event_id])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=lpr_events.csv"})


@router.get("/events/{event_id}", response_model=schemas.EventDetail, tags=["events"])
async def get_event(event_id: str, user: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    r = await db.get(Event, event_id)
    if r is None:
        raise HTTPException(404, "event not found")
    db.add(AuditLog(username=user.username, action="view_event", target=event_id))
    await db.commit()
    person = await db.get(Person, r.person_id) if r.person_id else None
    return schemas.EventDetail(**_out(r).model_dump(), characters=r.characters, plate_bbox=r.plate_bbox,
                               frame_size=r.frame_size, model_sha256=r.model_sha256, engine_sha256=r.engine_sha256,
                               precision=r.precision, processed_at=r.processed_at, plate_key=r.plate_key,
                               person={"id": person.id, "full_name": person.full_name,
                                       "list_status": person.list_status} if person else None)


@router.get("/events/{event_id}/crop", tags=["events"], response_class=FileResponse)
async def get_crop(event_id: str, user: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    r = await db.get(Event, event_id)
    if r is None or not r.crop_path:
        raise HTTPException(404, "no crop")
    root = Path(settings.CROPS_DIR).resolve()
    path = (root / r.crop_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "no crop")
    db.add(AuditLog(username=user.username, action="view_crop", target=event_id))
    await db.commit()
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/stats", tags=["events"])
async def stats(hours: int = Query(24, ge=1, le=24 * 90), _: User = Depends(any_role),
                db: AsyncSession = Depends(get_db)):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    w = Event.ts >= since
    total = (await db.execute(select(func.count()).select_from(Event).where(w))).scalar_one()
    valid = (await db.execute(select(func.count()).select_from(Event).where(w, Event.is_valid.is_(True)))).scalar_one()
    by_cam = (await db.execute(select(Event.camera_id, func.count()).where(w).group_by(Event.camera_id))).all()
    by_type = (await db.execute(select(Event.plate_type, func.count()).where(w).group_by(Event.plate_type))).all()
    last = (await db.execute(select(func.max(Event.ts)))).scalar_one()
    return {"hours": hours, "total": total, "valid": valid, "valid_rate": (valid / total) if total else None,
            "by_camera": {k: v for k, v in by_cam}, "by_plate_type": {k: v for k, v in by_type},
            "last_event_at": last.isoformat() if last else None}


# --- live -------------------------------------------------------------------------------------------------------------
@router.websocket("/ws/events")
async def ws_events(ws: WebSocket, token: Optional[str] = None):
    async with SessionLocal() as db:
        try:
            u = await user_from_token(token, db)
            if u.must_change_password:
                raise HTTPException(403)
        except HTTPException:
            await ws.close(code=4401)
            return
    await ws.accept()
    q = broadcaster.subscribe()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20)
            except asyncio.TimeoutError:
                msg = {"type": "ping"}
            await ws.send_json(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        broadcaster.unsubscribe(q)
