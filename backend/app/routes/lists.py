"""Watchlists (AGENTS.md A.7 "Watchlists"): persons and plates on whitelist | blocklist | unknown.

Moving an entry between lists is one call: PATCH the entry, or POST /lists/move for several at once.
Plates are keyed by lpr_reader.normalize.plate_key, so "۱۲ ب ۳۴۵ | ۶۷", "12 Be 345 67" and "12B34567" are one entry.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lpr_reader.normalize import format_standard, normalize_text, parse_standard, plate_key, search_keys

from ..db import get_db
from ..models import AuditLog, Event, Person, Plate, User
from ..security import any_role, operator

router = APIRouter(prefix="/api/v1", tags=["watchlists"])
ListStatus = Literal["whitelist", "blocklist", "unknown"]


# --- schemas ---------------------------------------------------------------------------------------------------------
class PersonIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=128)
    notes: str = Field("", max_length=2000)
    list_status: ListStatus = "unknown"


class PersonPatch(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=128)
    notes: Optional[str] = Field(None, max_length=2000)
    list_status: Optional[ListStatus] = None


class PlateIn(BaseModel):
    plate: str = Field(min_length=2, max_length=64, description="any Persian/Latin form, e.g. ۱۲ ب ۳۴۵ | ۶۷ or 12B34567")
    list_status: ListStatus = "unknown"
    person_id: Optional[int] = None
    notes: str = Field("", max_length=2000)
    upsert: bool = Field(False, description="if the plate exists, update its list (and person/notes) instead of 409")


class PlatePatch(BaseModel):
    list_status: Optional[ListStatus] = None
    person_id: Optional[int] = Field(None, description="link to a person; 0 unlinks")
    notes: Optional[str] = Field(None, max_length=2000)


class Move(BaseModel):
    kind: Literal["plate", "person"]
    ids: List[int] = Field(min_length=1, max_length=500)
    list_status: ListStatus


class PersonOut(BaseModel):
    id: int
    full_name: str
    notes: str
    list_status: str
    plates: int = 0


class PlateOut(BaseModel):
    id: int
    plate_key: str
    plate_string_fa: str
    plate_string_latin: str
    list_status: str
    effective_status: str
    person_id: Optional[int]
    person_name: Optional[str]
    notes: str
    last_seen: Optional[dt.datetime] = None


# --- helpers ---------------------------------------------------------------------------------------------------------
def effective(plate_status: str, person: Optional[Person]) -> str:
    if plate_status != "unknown" or person is None:
        return plate_status
    return person.list_status


async def resolve_status(db: AsyncSession, key: str):
    """-> (effective list status, person_id) for a recognized plate key (used at event ingest)."""
    if not key:
        return "unknown", None
    p = (await db.execute(select(Plate).where(Plate.plate_key == key))).scalars().first()
    if p is None:
        return "unknown", None
    person = await db.get(Person, p.person_id) if p.person_id else None
    return effective(p.list_status, person), p.person_id


def _strings(text: str):
    sp = parse_standard(text)
    if sp is not None:
        return format_standard(sp)
    t = normalize_text(text)
    return t, t


async def _plate_out(db: AsyncSession, p: Plate) -> PlateOut:
    person = await db.get(Person, p.person_id) if p.person_id else None
    last = (await db.execute(select(func.max(Event.ts)).where(Event.plate_key == p.plate_key))).scalar_one()
    return PlateOut(id=p.id, plate_key=p.plate_key, plate_string_fa=p.plate_string_fa,
                    plate_string_latin=p.plate_string_latin, list_status=p.list_status,
                    effective_status=effective(p.list_status, person), person_id=p.person_id,
                    person_name=person.full_name if person else None, notes=p.notes, last_seen=last)


def _audit(db, user: User, action: str, target: str):
    db.add(AuditLog(username=user.username, action=action, target=target[:500]))


async def _person_or_404(db, pid: int) -> Person:
    p = await db.get(Person, pid)
    if p is None:
        raise HTTPException(404, "person not found")
    return p


# --- persons ---------------------------------------------------------------------------------------------------------
@router.get("/persons")
async def list_persons(list_status: Optional[ListStatus] = None, q: Optional[str] = Query(None, max_length=64),
                       limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                       _: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    stmt, count = select(Person), select(func.count()).select_from(Person)
    conds = []
    if list_status:
        conds.append(Person.list_status == list_status)
    if q:
        conds.append(Person.full_name.ilike(f"%{q.strip()}%"))
    for c in conds:
        stmt, count = stmt.where(c), count.where(c)
    total = (await db.execute(count)).scalar_one()
    rows = (await db.execute(stmt.order_by(Person.full_name).limit(limit).offset(offset))).scalars().all()
    n = dict((await db.execute(select(Plate.person_id, func.count()).where(Plate.person_id.in_([r.id for r in rows]))
                                .group_by(Plate.person_id))).all()) if rows else {}
    return {"items": [PersonOut(id=r.id, full_name=r.full_name, notes=r.notes, list_status=r.list_status,
                                plates=n.get(r.id, 0)) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/persons", response_model=PersonOut, status_code=201)
async def create_person(body: PersonIn, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    p = Person(full_name=body.full_name.strip(), notes=body.notes, list_status=body.list_status)
    db.add(p)
    await db.flush()
    _audit(db, user, "list_change", f"person:{p.id} created on {p.list_status}")
    await db.commit()
    return PersonOut(id=p.id, full_name=p.full_name, notes=p.notes, list_status=p.list_status)


@router.get("/persons/{pid}")
async def get_person(pid: int, user: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    p = await _person_or_404(db, pid)
    plates = (await db.execute(select(Plate).where(Plate.person_id == pid).order_by(Plate.plate_key))).scalars().all()
    _audit(db, user, "view_person", f"person:{pid}")
    await db.commit()
    return {"person": PersonOut(id=p.id, full_name=p.full_name, notes=p.notes, list_status=p.list_status,
                                plates=len(plates)),
            "plates": [await _plate_out(db, x) for x in plates]}


@router.patch("/persons/{pid}", response_model=PersonOut)
async def update_person(pid: int, body: PersonPatch, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    p = await _person_or_404(db, pid)
    if body.list_status and body.list_status != p.list_status:
        _audit(db, user, "list_change", f"person:{pid} {p.list_status}->{body.list_status}")
        p.list_status = body.list_status
    if body.full_name is not None:
        p.full_name = body.full_name.strip()
    if body.notes is not None:
        p.notes = body.notes
    await db.commit()
    return PersonOut(id=p.id, full_name=p.full_name, notes=p.notes, list_status=p.list_status)


@router.delete("/persons/{pid}")
async def delete_person(pid: int, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    p = await _person_or_404(db, pid)
    for pl in (await db.execute(select(Plate).where(Plate.person_id == pid))).scalars():
        pl.person_id = None
    await db.delete(p)
    _audit(db, user, "list_change", f"person:{pid} deleted")
    await db.commit()
    return {"id": pid, "deleted": True}


# --- plates ----------------------------------------------------------------------------------------------------------
@router.get("/plates")
async def list_plates(list_status: Optional[ListStatus] = None, person_id: Optional[int] = None,
                      q: Optional[str] = Query(None, max_length=64), limit: int = Query(50, ge=1, le=500),
                      offset: int = Query(0, ge=0), _: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    stmt, count = select(Plate), select(func.count()).select_from(Plate)
    conds = []
    if list_status:
        conds.append(Plate.list_status == list_status)
    if person_id is not None:
        conds.append(Plate.person_id == person_id)
    if q:
        conds.append(or_(*[Plate.plate_key.ilike(f"%{k}%") for k in search_keys(q)]))
    for c in conds:
        stmt, count = stmt.where(c), count.where(c)
    total = (await db.execute(count)).scalar_one()
    rows = (await db.execute(stmt.order_by(Plate.updated_at.desc(), Plate.id).limit(limit).offset(offset))).scalars()
    return {"items": [await _plate_out(db, r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/plates/unregistered")
async def unregistered(days: int = Query(7, ge=1, le=90), limit: int = Query(50, ge=1, le=200),
                       _: User = Depends(any_role), db: AsyncSession = Depends(get_db)):
    """Plates recognized recently (valid reads) that are on no list yet: one click puts them on a list."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    registered = select(Plate.plate_key)
    rows = (await db.execute(
        select(Event.plate_key, func.max(Event.plate_string_fa), func.max(Event.plate_string_latin), func.count(),
               func.max(Event.ts))
        .where(Event.ts >= since, Event.plate_key != "", Event.is_valid.is_(True), Event.plate_key.not_in(registered))
        .group_by(Event.plate_key).order_by(func.max(Event.ts).desc()).limit(limit))).all()
    return [{"plate_key": k, "plate_string_fa": fa, "plate_string_latin": la, "sightings": n, "last_seen": t}
            for k, fa, la, n, t in rows]


@router.post("/plates", response_model=PlateOut, status_code=201)
async def create_plate(body: PlateIn, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    key = plate_key(body.plate)
    if len(key) < 2:
        raise HTTPException(422, "not a plate")
    if body.person_id is not None:
        await _person_or_404(db, body.person_id)
    existing = (await db.execute(select(Plate).where(Plate.plate_key == key))).scalars().first()
    if existing is not None:
        if not body.upsert:
            raise HTTPException(409, f"plate {key} already registered (id {existing.id})")
        if existing.list_status != body.list_status:
            _audit(db, user, "list_change", f"plate:{key} {existing.list_status}->{body.list_status}")
            existing.list_status = body.list_status
        if body.person_id is not None:
            existing.person_id = body.person_id
        if body.notes:
            existing.notes = body.notes
        await db.commit()
        return await _plate_out(db, existing)
    fa, latin = _strings(body.plate)
    p = Plate(plate_key=key, plate_string_fa=fa, plate_string_latin=latin, list_status=body.list_status,
              person_id=body.person_id, notes=body.notes)
    db.add(p)
    _audit(db, user, "list_change", f"plate:{key} created on {body.list_status}")
    await db.commit()
    return await _plate_out(db, p)


@router.patch("/plates/{pid}", response_model=PlateOut)
async def update_plate(pid: int, body: PlatePatch, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    p = await db.get(Plate, pid)
    if p is None:
        raise HTTPException(404, "plate not found")
    if body.list_status and body.list_status != p.list_status:
        _audit(db, user, "list_change", f"plate:{p.plate_key} {p.list_status}->{body.list_status}")
        p.list_status = body.list_status
    if body.person_id is not None:
        if body.person_id == 0:
            p.person_id = None
        else:
            await _person_or_404(db, body.person_id)
            p.person_id = body.person_id
    if body.notes is not None:
        p.notes = body.notes
    await db.commit()
    return await _plate_out(db, p)


@router.delete("/plates/{pid}")
async def delete_plate(pid: int, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    p = await db.get(Plate, pid)
    if p is None:
        raise HTTPException(404, "plate not found")
    _audit(db, user, "list_change", f"plate:{p.plate_key} deleted")
    await db.delete(p)
    await db.commit()
    return {"id": pid, "deleted": True}


@router.post("/lists/move")
async def move(body: Move, user: User = Depends(operator), db: AsyncSession = Depends(get_db)):
    """Bulk move: put several plates or persons on one list in one call."""
    model = Plate if body.kind == "plate" else Person
    rows = (await db.execute(select(model).where(model.id.in_(body.ids)))).scalars().all()
    found = {r.id for r in rows}
    for r in rows:
        if r.list_status != body.list_status:
            label = r.plate_key if body.kind == "plate" else str(r.id)
            _audit(db, user, "list_change", f"{body.kind}:{label} {r.list_status}->{body.list_status}")
            r.list_status = body.list_status
    await db.commit()
    return {"moved": sorted(found), "not_found": sorted(set(body.ids) - found), "list_status": body.list_status}
