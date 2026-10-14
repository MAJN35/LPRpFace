"""Video files for file sources, uploaded from the dashboard.

PUT /videos/{name} streams the request body straight to VIDEOS_DIR on the shared data volume (no multipart
parsing, no temporary copy: the board's only storage is the SD card). The inference container reads the same volume,
so a stored video becomes a source with type "file" and uri /data/videos/<name>. Limits: VIDEO_MAX_MB per file, and
an upload is refused if it would leave less than VIDEO_MIN_FREE_MB free on the disk. A video used by a source cannot
be deleted (remove the source first).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import settings
from ..db import SessionLocal
from ..models import AuditLog, User
from ..security import any_role, operator
from .system import _inference

router = APIRouter(prefix="/api/v1", tags=["videos"])
EXTS = (".mp4", ".mkv", ".mov", ".ts")
NAME_RE = re.compile(r"^[\w؀-ۿ][\w؀-ۿ .()+-]{0,118}$")   # Persian names allowed, no paths


def _dir() -> Path:
    d = Path(settings.VIDEOS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    """A plain file name with a video extension (no directories, no hidden files)."""
    name = name.strip()
    if not NAME_RE.match(name) or not name.lower().endswith(EXTS) or name != Path(name).name:
        raise HTTPException(422, f"file name must be letters/digits/space/._-()+ and end in {', '.join(EXTS)}")
    return name


def _info(p: Path) -> dict:
    st = p.stat()
    return {"name": p.name, "size": st.st_size, "path": f"{settings.VIDEOS_SOURCE_PREFIX.rstrip('/')}/{p.name}",
            "uploaded_at": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat()}


async def _audit(user: User, action: str, target: str) -> None:
    async with SessionLocal() as db:
        db.add(AuditLog(username=user.username, action=action, target=target[:500]))
        await db.commit()


@router.get("/videos")
async def list_videos(_: User = Depends(any_role)):
    d = _dir()
    items = sorted((_info(p) for p in d.iterdir() if p.is_file() and p.suffix.lower() in EXTS),
                   key=lambda x: x["uploaded_at"], reverse=True)
    usage = shutil.disk_usage(d)
    return {"items": items, "free_bytes": usage.free, "max_bytes": settings.VIDEO_MAX_MB * 1024 * 1024}


@router.put("/videos/{name}", status_code=201)
async def upload_video(name: str, request: Request, user: User = Depends(operator)):
    """Body = the video file itself (Content-Type application/octet-stream or video/*)."""
    name = safe_name(name)
    d = _dir()
    target = d / name
    if target.exists():
        raise HTTPException(409, "a video with this name exists; delete it first or choose another name")
    limit = settings.VIDEO_MAX_MB * 1024 * 1024
    declared = int(request.headers.get("content-length") or 0)
    if declared > limit:
        raise HTTPException(413, f"video larger than {settings.VIDEO_MAX_MB} MB")
    reserve = settings.VIDEO_MIN_FREE_MB * 1024 * 1024
    if shutil.disk_usage(d).free - declared < reserve:
        raise HTTPException(507, f"not enough free disk space (keeping {settings.VIDEO_MIN_FREE_MB} MB free)")
    part = d / f".{name}.part"
    size = 0
    try:
        with open(part, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"video larger than {settings.VIDEO_MAX_MB} MB")
                f.write(chunk)
        if size == 0:
            raise HTTPException(422, "empty upload")
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()
    await _audit(user, "video_upload", f"{name} ({size} bytes)")
    return _info(target)


@router.delete("/videos/{name}")
async def delete_video(name: str, user: User = Depends(operator)):
    name = safe_name(name)
    p = _dir() / name
    if not p.is_file():
        raise HTTPException(404, "no such video")
    try:
        sources = await _inference("GET", "/sources")
    except HTTPException:
        sources = []
    used = [s.get("id") for s in sources if str(s.get("uri", "")).endswith("/" + name)]
    if used:
        raise HTTPException(409, f"used by source {', '.join(map(str, used))}; remove the source first")
    p.unlink()
    await _audit(user, "video_delete", name)
    return {"name": name, "deleted": True}
