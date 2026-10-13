"""Face recognition (AGENTS.md privacy, changed by the user on 2026-10-13) and the snapshot library.

* POST /ingest/faces (face service): store the face, match its ArcFace embedding against every person's reference
  faces (cosine >= FACE_MATCH_THRESHOLD), or start a new unnamed person for an unmatched good-quality face. The
  person's list status is stored with the face; a blocklisted person raises an alert like a plate.
* Operators fix the matcher: rename a person, move a face to another (or a new) person, merge two persons, delete a
  face. Every change and every person/face view is written to the audit log.
* Snapshot library: plate crops and face snapshots in one list; deleting removes the image file (the event stays).
"""
from __future__ import annotations

import base64
import datetime as dt
import uuid
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import httpx
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..live import broadcaster
from ..models import AuditLog, Event, FaceEvent, Person, Plate, User
from ..security import any_role, ingest_key, operator

router = APIRouter(prefix="/api/v1", tags=["faces"])
DIM = 512


# --- schemas -----------------------------------------------------------------------------------------------------------
class FaceSource(BaseModel):
    id: str
    type: str
    uri_redacted: str
    file_name: Optional[str] = None


class FaceEventIn(BaseModel):
    schema_version: Literal["1.0"]
    event_id: str = Field(min_length=36, max_length=36)
    event_type: Literal["face.detected", "face.detected.image"]
    source: FaceSource
    camera_id: str
    timestamp: dt.datetime
    track_id: Optional[int] = None
    face_bbox: List[float] = Field(min_length=4, max_length=4)
    frame_size: List[int] = Field(min_length=2, max_length=2)
    det_score: float
    frames_seen: int = 1
    snapshot_path: str
    snapshot_face_box: List[int]
    model: dict


class FaceIngest(BaseModel):
    event: FaceEventIn
    embed_model: str = ""
    embedding_b64: Optional[str] = None
    embed_det_score: Optional[float] = None
    landmarks: Optional[list] = None
    sharpness: Optional[float] = None


class FaceOut(BaseModel):
    id: str
    timestamp: dt.datetime
    camera_id: str
    track_id: Optional[int]
    person_id: Optional[int]
    person_name: Optional[str]
    person_auto: bool = False
    similarity: Optional[float]
    match: str
    det_score: float
    list_status: str
    has_snapshot: bool
    has_embedding: bool


class FacePatch(BaseModel):
    person_id: Optional[int] = Field(None, description="move the face to this person; 0 = unassign")
    new_person: bool = Field(False, description="move the face to a new unnamed person")


class Merge(BaseModel):
    into: int


class SnapshotRef(BaseModel):
    kind: Literal["plate", "face"]
    id: str


class SnapshotDelete(BaseModel):
    items: List[SnapshotRef] = Field(min_length=1, max_length=500)


# --- matcher -----------------------------------------------------------------------------------------------------------
def decode(b: Optional[bytes]) -> Optional[np.ndarray]:
    if not b:
        return None
    v = np.frombuffer(b, np.float32)
    return v if v.shape == (DIM,) else None


def best_match(emb: np.ndarray, gallery: Dict[int, np.ndarray]) -> Tuple[Optional[int], float]:
    """-> (person id, cosine) of the closest person (max over that person's reference faces)."""
    best, best_s = None, -1.0
    for pid, refs in gallery.items():
        s = float(np.max(refs @ emb))
        if s > best_s:
            best, best_s = pid, s
    return best, best_s


class Gallery:
    """Reference embeddings per person, cached in memory; reloaded after any change to faces or persons."""

    def __init__(self):
        self.refs: Optional[Dict[int, np.ndarray]] = None

    def invalidate(self) -> None:
        self.refs = None

    async def get(self, db: AsyncSession) -> Dict[int, np.ndarray]:
        if self.refs is None:
            rows = (await db.execute(select(FaceEvent.person_id, FaceEvent.embedding)
                                     .where(FaceEvent.anchor.is_(True), FaceEvent.person_id.is_not(None)))).all()
            g: Dict[int, List[np.ndarray]] = {}
            for pid, b in rows:
                v = decode(b)
                if v is not None:
                    g.setdefault(pid, []).append(v)
            self.refs = {pid: np.stack(vs) for pid, vs in g.items()}
        return self.refs


gallery = Gallery()


def _width(bbox) -> float:
    return float(bbox[2] - bbox[0]) if bbox else 0.0


async def _anchors(db: AsyncSession, pid: int) -> int:
    return (await db.execute(select(func.count()).select_from(FaceEvent)
                             .where(FaceEvent.person_id == pid, FaceEvent.anchor.is_(True)))).scalar_one()


async def _face_out(db: AsyncSession, f: FaceEvent, person: Optional[Person] = None) -> FaceOut:
    if person is None and f.person_id:
        person = await db.get(Person, f.person_id)
    return FaceOut(id=f.event_id, timestamp=f.ts, camera_id=f.camera_id, track_id=f.track_id, person_id=f.person_id,
                   person_name=person.full_name if person else None, person_auto=bool(person and person.auto_named),
                   similarity=f.similarity, match=f.match, det_score=f.det_score, list_status=f.list_status,
                   has_snapshot=bool(f.snapshot_path), has_embedding=f.embedding is not None)


def _audit(db, user: User, action: str, target: str):
    db.add(AuditLog(username=user.username, action=action, target=target[:500]))


def _file(rel: Optional[str]) -> Optional[Path]:
    if not rel:
        return None
    root = Path(settings.CROPS_DIR).resolve()
    p = (root / rel).resolve()
    return p if root in p.parents else None


def _unlink(rel: Optional[str]) -> bool:
    """True when the image is gone (deleted now or already missing)."""
    p = _file(rel)
    if p is None:
        return True
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


# --- ingest ------------------------------------------------------------------------------------------------------------
@router.post("/ingest/faces", dependencies=[Depends(ingest_key)])
async def ingest_face(body: FaceIngest, db: AsyncSession = Depends(get_db)):
    """Idempotent by event_id. Matching: closest person >= threshold -> that person (the face becomes one of their
    references while they have fewer than FACE_MAX_ANCHORS); else, for a good-quality face, a new unnamed person."""
    e = body.event
    if await db.get(FaceEvent, e.event_id) is not None:
        return {"event_id": e.event_id, "created": False}
    emb = decode(base64.b64decode(body.embedding_b64)) if body.embedding_b64 else None
    f = FaceEvent(event_id=e.event_id, event_type=e.event_type, camera_id=e.camera_id, source_type=e.source.type,
                  source_file=e.source.file_name, ts=e.timestamp, track_id=e.track_id, face_bbox=e.face_bbox,
                  frame_size=e.frame_size, det_score=e.det_score, frames_seen=e.frames_seen,
                  snapshot_path=e.snapshot_path or None, embed_model=body.embed_model,
                  embedding=emb.astype(np.float32).tobytes() if emb is not None else None,
                  embed_det_score=body.embed_det_score, sharpness=body.sharpness)
    person: Optional[Person] = None
    if emb is not None:
        good = _width(e.face_bbox) >= settings.FACE_NEW_PERSON_MIN_PX and \
            (body.embed_det_score or 0.0) >= settings.FACE_NEW_PERSON_MIN_SCORE
        pid, sim = best_match(emb, await gallery.get(db))
        if pid is not None and sim >= settings.FACE_MATCH_THRESHOLD:
            person = await db.get(Person, pid)
            f.person_id, f.similarity, f.match = pid, round(sim, 4), "matched"
            f.anchor = good and await _anchors(db, pid) < settings.FACE_MAX_ANCHORS
        elif good:
            person = Person(full_name="", auto_named=True, list_status="unknown")
            db.add(person)
            await db.flush()
            f.person_id, f.match, f.anchor = person.id, "new_person", True
            f.similarity = round(sim, 4) if pid is not None else None
    f.list_status = person.list_status if person else "unknown"
    db.add(f)
    await db.commit()
    if f.anchor:
        gallery.invalidate()
    out = (await _face_out(db, f, person)).model_dump(mode="json")
    broadcaster.publish({"type": "face", "face": out})
    if out["list_status"] == "blocklist":
        broadcaster.publish({"type": "face_alert", "face": out})
    return {"event_id": e.event_id, "created": True, "person_id": f.person_id, "match": f.match}


# --- faces -------------------------------------------------------------------------------------------------------------
@router.get("/faces")
async def list_faces(person_id: Optional[int] = None, camera_id: Optional[str] = None,
                     since: Optional[dt.datetime] = Query(None, alias="from"),
                     until: Optional[dt.datetime] = Query(None, alias="to"), unassigned: bool = False,
                     list_status: Optional[str] = Query(None, pattern="^(whitelist|blocklist|unknown)$"),
                     limit: int = Query(48, ge=1, le=200), offset: int = Query(0, ge=0),
                     user: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    conds = []
    if person_id is not None:
        conds.append(FaceEvent.person_id == person_id)
    if unassigned:
        conds.append(FaceEvent.person_id.is_(None))
    if camera_id:
        conds.append(FaceEvent.camera_id == camera_id)
    if since:
        conds.append(FaceEvent.ts >= since)
    if until:
        conds.append(FaceEvent.ts < until)
    if list_status:
        conds.append(FaceEvent.list_status == list_status)
    stmt, count = select(FaceEvent), select(func.count()).select_from(FaceEvent)
    for c in conds:
        stmt, count = stmt.where(c), count.where(c)
    total = (await db.execute(count)).scalar_one()
    rows = (await db.execute(stmt.order_by(FaceEvent.ts.desc()).limit(limit).offset(offset))).scalars().all()
    persons = {p.id: p for p in (await db.execute(select(Person).where(
        Person.id.in_({r.person_id for r in rows if r.person_id})))).scalars()} if rows else {}
    if person_id is not None:
        _audit(db, user, "view_person_faces", f"person:{person_id}")
        await db.commit()
    return {"items": [await _face_out(db, r, persons.get(r.person_id)) for r in rows], "total": total,
            "limit": limit, "offset": offset}


async def _face_or_404(db, fid: str) -> FaceEvent:
    f = await db.get(FaceEvent, fid)
    if f is None:
        raise HTTPException(404, "face not found")
    return f


@router.get("/faces/{fid}/snapshot", response_class=FileResponse)
async def face_snapshot(fid: str, user: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    f = await _face_or_404(db, fid)
    p = _file(f.snapshot_path)
    if p is None or not p.is_file():
        raise HTTPException(404, "no snapshot")
    _audit(db, user, "view_face", fid)
    await db.commit()
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.patch("/faces/{fid}")
async def move_face(fid: str, body: FacePatch, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    """Correct the matcher: the face (and, if it has an embedding, its use as a reference) moves to another person."""
    f = await _face_or_404(db, fid)
    old = f.person_id
    if body.new_person:
        p = Person(full_name="", auto_named=True)
        db.add(p)
        await db.flush()
        target: Optional[int] = p.id
    elif body.person_id:
        target = (await _person_or_404(db, body.person_id)).id
    else:
        target = None
    f.person_id, f.match, f.similarity = target, "manual" if target else "none", None
    f.anchor = target is not None and f.embedding is not None
    person = await db.get(Person, target) if target else None
    _audit(db, user, "face_move", f"face:{fid} person:{old}->{target}")
    await db.commit()
    gallery.invalidate()
    return await _face_out(db, f, person)


@router.delete("/faces/{fid}")
async def delete_face(fid: str, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    f = await _face_or_404(db, fid)
    _unlink(f.snapshot_path)
    await db.delete(f)
    _audit(db, user, "face_delete", fid)
    await db.commit()
    gallery.invalidate()
    return {"id": fid, "deleted": True}


async def _person_or_404(db, pid: int) -> Person:
    p = await db.get(Person, pid)
    if p is None:
        raise HTTPException(404, "person not found")
    return p


@router.post("/persons/{pid}/merge")
async def merge_persons(pid: int, body: Merge, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    """The matcher split one person in two: move every face and plate of `pid` to `into` and delete `pid`."""
    if pid == body.into:
        raise HTTPException(400, "cannot merge a person into itself")
    src, dst = await _person_or_404(db, pid), await _person_or_404(db, body.into)
    await db.execute(update(FaceEvent).where(FaceEvent.person_id == pid).values(person_id=dst.id))
    await db.execute(update(Plate).where(Plate.person_id == pid).values(person_id=dst.id))
    await db.execute(update(Event).where(Event.person_id == pid).values(person_id=dst.id))
    if dst.auto_named and not src.auto_named:
        dst.full_name, dst.auto_named = src.full_name, False
    await db.delete(src)
    _audit(db, user, "person_merge", f"person:{pid}->{dst.id}")
    await db.commit()
    gallery.invalidate()
    return {"id": dst.id, "merged": pid}


# --- manual registration -------------------------------------------------------------------------------------------
# A person is registered with a name, a list and one or more face photos; every photo with a face becomes one of the
# person's reference faces, so the cameras recognize them from then on. Several people are registered one request
# each (the dashboard's "Register people" page sends them in turn).
MAX_PHOTO = 10 * 1024 * 1024
EmbedFn = None   # tests replace this with a fake face service: async (bytes) -> (status, body)


async def _embed_photo(data: bytes) -> Tuple[int, dict]:
    if EmbedFn is not None:
        return await EmbedFn(data)
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{settings.FACE_SERVICE_URL}/embed", content=data,
                             headers={"X-Ingest-Key": settings.INGEST_KEY, "Content-Type": "application/octet-stream"})
        return r.status_code, r.json()
    except (httpx.HTTPError, ValueError) as e:
        return 503, {"detail": f"face service unavailable ({type(e).__name__})"}


async def _add_photos(db: AsyncSession, person: Person, files: List[UploadFile]) -> Tuple[list, Optional[np.ndarray]]:
    """Embed each photo and store it as a reference face of `person`. -> (per-photo results, first embedding)."""
    results, first = [], None
    root = Path(settings.CROPS_DIR).resolve()
    for f in files:
        data = await f.read(MAX_PHOTO + 1)
        name = (f.filename or "photo")[:120]
        if len(data) > MAX_PHOTO:
            results.append({"file": name, "ok": False, "error": "photo larger than 10 MB"})
            continue
        status, body = await _embed_photo(data)
        if status != 200:
            results.append({"file": name, "ok": False, "error": str(body.get("detail", status))[:200]})
            continue
        emb = decode(base64.b64decode(body["embedding_b64"]))
        if emb is None:
            results.append({"file": name, "ok": False, "error": "bad embedding"})
            continue
        eid = str(uuid.uuid4())
        rel = f"faces/enrolled/{person.id}/{eid}.jpg"
        out = root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(body["crop_jpeg_b64"]))
        db.add(FaceEvent(event_id=eid, event_type="face.enrolled", camera_id="manual", source_type="upload",
                         source_file=name, ts=dt.datetime.now(dt.timezone.utc), track_id=None, face_bbox=body.get("box", [0, 0, 0, 0]),
                         frame_size=body.get("size", [0, 0]), det_score=float(body.get("det_score") or 0.0), frames_seen=1,
                         snapshot_path=rel, embed_model=body.get("embed_model", ""), embedding=emb.astype(np.float32).tobytes(),
                         embed_det_score=body.get("det_score"), sharpness=body.get("sharpness"), anchor=True,
                         person_id=person.id, match="manual", list_status=person.list_status))
        first = emb if first is None else first
        results.append({"file": name, "ok": True, "faces_in_photo": body.get("faces", 1), "face_id": eid})
    return results, first


async def _similar(db: AsyncSession, emb: Optional[np.ndarray], exclude: int):
    """An existing person this face already matches (e.g. an "Unknown #n" the cameras saw): offer a merge."""
    if emb is None:
        return None
    g = {k: v for k, v in (await gallery.get(db)).items() if k != exclude}
    pid, sim = best_match(emb, g)
    if pid is None or sim < settings.FACE_MATCH_THRESHOLD:
        return None
    p = await db.get(Person, pid)
    return {"id": pid, "full_name": p.full_name if p else "", "auto_named": bool(p and p.auto_named), "similarity": round(sim, 4)}


@router.post("/persons/register", status_code=201)
async def register_person(full_name: str = Form(..., min_length=1, max_length=128),
                          list_status: Literal["whitelist", "blocklist", "unknown"] = Form("unknown"),
                          notes: str = Form("", max_length=2000), photos: List[UploadFile] = File(default=[]),
                          user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    """Register one person with face photos. Photos without a face are reported, not stored; if photos were given and
    none has a face, nothing is created (422)."""
    person = Person(full_name=full_name.strip(), notes=notes, list_status=list_status, auto_named=False)
    db.add(person)
    await db.flush()
    results, first = await _add_photos(db, person, photos)
    if photos and first is None:
        await db.rollback()
        raise HTTPException(422, {"message": "no usable face in the photos", "photos": results})
    similar = await _similar(db, first, person.id)
    _audit(db, user, "person_register", f"person:{person.id} on {list_status}, {sum(r['ok'] for r in results)} photos")
    await db.commit()
    gallery.invalidate()
    return {"person": {"id": person.id, "full_name": person.full_name, "list_status": person.list_status},
            "photos": results, "similar": similar}


@router.post("/persons/{pid}/photos")
async def add_person_photos(pid: int, photos: List[UploadFile] = File(...), user: User = Depends(operator),
                            db: AsyncSession = Depends(get_db)):
    """More reference photos for an existing person (better recognition from other angles/lighting)."""
    person = await _person_or_404(db, pid)
    results, first = await _add_photos(db, person, photos)
    _audit(db, user, "person_photos", f"person:{pid} +{sum(r['ok'] for r in results)} photos")
    await db.commit()
    gallery.invalidate()
    return {"photos": results, "added": sum(r["ok"] for r in results)}


# --- snapshot library --------------------------------------------------------------------------------------------------
@router.get("/snapshots")
async def list_snapshots(kind: Literal["all", "plate", "face"] = "all", camera_id: Optional[str] = None,
                         since: Optional[dt.datetime] = Query(None, alias="from"),
                         until: Optional[dt.datetime] = Query(None, alias="to"),
                         limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0),
                         user: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    """Newest first; plates and faces merged by time."""
    items, total = [], 0
    n = limit + offset
    if kind in ("all", "plate"):
        c = [Event.crop_path.is_not(None)]
        c += [Event.camera_id == camera_id] if camera_id else []
        c += [Event.ts >= since] if since else []
        c += [Event.ts < until] if until else []
        total += (await db.execute(select(func.count()).select_from(Event).where(*c))).scalar_one()
        for r in (await db.execute(select(Event).where(*c).order_by(Event.ts.desc()).limit(n))).scalars():
            items.append({"kind": "plate", "id": r.event_id, "timestamp": r.ts, "camera_id": r.camera_id,
                          "plate_type": r.plate_type, "plate_string_fa": r.plate_string_fa,
                          "plate_string_latin": r.plate_string_latin, "zone": r.zone, "is_valid": r.is_valid,
                          "list_status": r.list_status, "person_id": r.person_id, "person_name": None})
    if kind in ("all", "face"):
        c = [FaceEvent.snapshot_path.is_not(None)]
        c += [FaceEvent.camera_id == camera_id] if camera_id else []
        c += [FaceEvent.ts >= since] if since else []
        c += [FaceEvent.ts < until] if until else []
        total += (await db.execute(select(func.count()).select_from(FaceEvent).where(*c))).scalar_one()
        rows = (await db.execute(select(FaceEvent, Person).outerjoin(Person, Person.id == FaceEvent.person_id)
                                 .where(*c).order_by(FaceEvent.ts.desc()).limit(n))).all()
        for f, p in rows:
            items.append({"kind": "face", "id": f.event_id, "timestamp": f.ts, "camera_id": f.camera_id,
                          "list_status": f.list_status, "person_id": f.person_id,
                          "person_name": p.full_name if p else None, "person_auto": bool(p and p.auto_named)})
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"items": items[offset:offset + limit], "total": total, "limit": limit, "offset": offset}


@router.delete("/snapshots")
async def delete_snapshots(body: SnapshotDelete, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    """Delete the image files; plate events and face records stay (without an image)."""
    done = 0
    for ref in body.items:
        row = await db.get(Event if ref.kind == "plate" else FaceEvent, ref.id)
        if row is None:
            continue
        rel = row.crop_path if ref.kind == "plate" else row.snapshot_path
        if not rel or not _unlink(rel):
            continue
        if ref.kind == "plate":
            row.crop_path = None
        else:
            row.snapshot_path = None
        done += 1
    _audit(db, user, "snapshot_delete", f"{done} snapshots: " + ",".join(f"{r.kind}:{r.id[:8]}" for r in body.items[:40]))
    await db.commit()
    return {"deleted": done}


# --- retention (called from main.retention_once) -----------------------------------------------------------------------
async def purge_faces(db: AsyncSession, cutoff: dt.datetime) -> int:
    old = (await db.execute(select(FaceEvent.event_id, FaceEvent.snapshot_path).where(FaceEvent.ts < cutoff))).all()
    for _, rel in old:
        _unlink(rel)
    if old:
        await db.execute(FaceEvent.__table__.delete().where(FaceEvent.ts < cutoff))
        gallery.invalidate()
    return len(old)

