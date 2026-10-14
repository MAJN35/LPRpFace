"""Health/readiness, system status, cameras (sources) and image jobs: proxied to the DeepStream control API."""
from __future__ import annotations

from typing import Any, Dict

import httpx
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import Event, User
from ..security import any_role, operator

router = APIRouter(prefix="/api/v1")
PUBLIC_SOURCE_KEYS = ("id", "name", "type", "uri", "enabled", "max_fps", "roi", "min_plate_px", "face_blur", "record",
                      "copy_of")


async def _inference(method: str, path: str, **kw) -> Any:
    try:
        async with httpx.AsyncClient(base_url=settings.INFERENCE_URL, timeout=10) as c:
            r = await c.request(method, path, **kw)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"inference service unavailable ({type(e).__name__})") from None
    if r.status_code >= 400:
        try:
            detail = r.json().get("error", r.text[:200])
        except ValueError:
            detail = r.text[:200]
        raise HTTPException(r.status_code if r.status_code < 500 else 502, detail)
    return r.json()


@router.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}


@router.get("/ready", tags=["system"])
async def ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "database unavailable") from None
    return {"status": "ready"}


@router.get("/status", tags=["system"])
async def status(_: User = Depends(any_role), db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    events = (await db.execute(select(func.count()).select_from(Event))).scalar_one()
    last = (await db.execute(select(func.max(Event.ts)))).scalar_one()
    try:
        inf = await _inference("GET", "/health")
        inference = {"reachable": True, "model": inf.get("model"), "engine": inf.get("engine"),
                     "max_cameras": inf.get("max_cameras"), "capacity": inf.get("capacity"), "pipeline": inf.get("pipeline"),
                     "worker": inf.get("worker"), "sources": inf.get("sources")}
    except HTTPException as e:
        inference = {"reachable": False, "error": e.detail}
    return {"database": {"events": events, "last_event_at": last.isoformat() if last else None},
            "inference": inference, "retention_days": settings.RETENTION_DAYS}


@router.get("/cameras", tags=["cameras"])
async def cameras(_: User = Depends(any_role)):
    return await _inference("GET", "/sources")


@router.post("/cameras", tags=["cameras"], status_code=201)
async def add_camera(body: Dict[str, Any] = Body(...), _: User = Depends(operator)):
    return await _inference("POST", "/sources", json=body)


@router.delete("/cameras/{sid}", tags=["cameras"])
async def remove_camera(sid: str, _: User = Depends(operator)):
    return await _inference("DELETE", f"/sources/{sid}")


@router.post("/cameras/{sid}/{action}", tags=["cameras"])
async def toggle_camera(sid: str, action: str, _: User = Depends(operator)):
    if action not in ("enable", "disable"):
        raise HTTPException(404, "unknown action")
    return await _inference("POST", f"/sources/{sid}/{action}")


@router.post("/images", tags=["images"], status_code=202)
async def upload_image(file: UploadFile = File(...), _: User = Depends(operator)):
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(415, "only JPEG and PNG")
    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"image must be at most {settings.MAX_UPLOAD_BYTES} bytes")
    return await _inference("POST", "/images", params={"name": (file.filename or "upload")[-100:]}, content=data,
                            headers={"Content-Type": "application/octet-stream"})


@router.get("/images/{job_id}", tags=["images"])
async def image_result(job_id: str, _: User = Depends(any_role)):
    return await _inference("GET", f"/images/{job_id}")
