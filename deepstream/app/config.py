"""Source configuration: sources.yaml + environment overrides (AGENTS.md A.7 "Input sources").

    defaults: {max_fps: 10, min_plate_px: 60, face_blur: true, record: false, rtsp_transport: tcp}
    sources:
      - {id: cam-01, name: Gate 1, type: rtsp, uri: "rtsp://${CAM01_USER}:${CAM01_PASS}@10.0.0.11:554/ch1",
         enabled: true, max_fps: 10, roi: [[0, 0.4], [1, 0.4], [1, 1], [0, 1]]}

``${VAR}`` in any string is replaced from the environment (credentials never live in the file); a missing
variable is an error for enabled sources. ``LPR_SOURCES_FILE`` selects the file, ``LPR_SOURCE_<ID>_ENABLED=0|1``
overrides ``enabled`` per source (ID upper-cased, ``-`` -> ``_``). URIs are redacted (no userinfo) wherever they
are logged or put in events.
"""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

import yaml

URI_TYPES = ("rtsp", "rtmp", "http", "hls", "file")       # nvurisrcbin
LIVE_TYPES = ("rtsp", "rtmp", "http", "hls", "usb", "csi")
IMAGE_TYPES = ("image", "image_folder", "image_job")
ALL_TYPES = URI_TYPES + ("usb", "csi") + IMAGE_TYPES
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class ConfigError(ValueError):
    pass


@dataclass
class Source:
    id: str
    type: str
    uri: str = ""
    name: str = ""
    enabled: bool = True
    max_fps: float = 0.0                # 0 = no limit
    roi: Optional[List[Tuple[float, float]]] = None  # normalized polygon (x, y in 0..1)
    min_plate_px: int = 60              # plate width (source px) below which reads are not voted/emitted
    face_blur: bool = True
    record: bool = False
    rtsp_transport: str = "tcp"         # tcp | udp
    loop: bool = False                  # files: loop for testing
    realtime: bool = True               # files: play at real time (False = as fast as possible)
    device: str = "/dev/video0"         # usb
    sensor_id: int = 0                  # csi
    width: int = 0                      # usb/csi capture size (0 = device default)
    height: int = 0
    fps: int = 0
    files: List[str] = field(default_factory=list)  # resolved image list (image / image_folder)

    @property
    def is_live(self) -> bool:
        return self.type in LIVE_TYPES

    @property
    def is_image(self) -> bool:
        return self.type in IMAGE_TYPES

    @property
    def uri_redacted(self) -> str:
        return redact_uri(self.uri)


def redact_uri(uri: str) -> str:
    """Drop userinfo: rtsp://user:pass@host/x -> rtsp://host/x (the password never reaches logs or events)."""
    if "://" not in (uri or ""):
        return uri or ""
    scheme, rest = uri.split("://", 1)
    slash = rest.find("/")
    authority, path = (rest, "") if slash == -1 else (rest[:slash], rest[slash:])
    return f"{scheme}://{authority.rsplit('@', 1)[-1]}{path}"


def split_credentials(uri: str) -> Tuple[str, Optional[str], Optional[str]]:
    """rtsp://user:p@ss@host/x -> (rtsp://host/x, user, p@ss). Splits at the LAST '@' of the authority so passwords
    containing '@' work (from the earlier project's sources.py)."""
    if "://" not in uri:
        return uri, None, None
    scheme, rest = uri.split("://", 1)
    slash = rest.find("/")
    authority, path = (rest, "") if slash == -1 else (rest[:slash], rest[slash:])
    if "@" not in authority:
        return uri, None, None
    userinfo, host = authority.rsplit("@", 1)
    user, _, password = userinfo.partition(":")
    return f"{scheme}://{host}{path}", unquote(user), unquote(password)


def _expand(value: Any, env: Dict[str, str], missing: List[str]) -> Any:
    if isinstance(value, str):
        def sub(m):
            if m.group(1) not in env:
                missing.append(m.group(1))
                return ""
            return env[m.group(1)]
        return _ENV.sub(sub, value)
    if isinstance(value, list):
        return [_expand(v, env, missing) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, env, missing) for k, v in value.items()}
    return value


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def parse_source(raw: Dict[str, Any], defaults: Dict[str, Any], env: Dict[str, str]) -> Source:
    merged = dict(defaults)
    merged.update(raw or {})
    missing: List[str] = []
    merged = _expand(merged, env, missing)
    sid = str(merged.get("id", ""))
    if not _ID.match(sid):
        raise ConfigError(f"source id {sid!r}: 1-64 chars of letters, digits, '_', '.', '-'")
    stype = str(merged.get("type", "")).lower()
    if stype not in ALL_TYPES:
        raise ConfigError(f"source {sid}: type {stype!r} not one of {ALL_TYPES}")
    env_key = f"LPR_SOURCE_{sid.upper().replace('-', '_').replace('.', '_')}_ENABLED"
    if env_key in env:
        merged["enabled"] = env[env_key]
    known = set(Source.__dataclass_fields__) - {"files"}
    unknown = set(merged) - known
    if unknown:
        raise ConfigError(f"source {sid}: unknown keys {sorted(unknown)}")
    src = Source(id=sid, type=stype)
    for k in known - {"id", "type"}:
        if k in merged and merged[k] is not None:
            cur = getattr(src, k)
            v = merged[k]
            if isinstance(cur, bool):
                v = _bool(v)
            elif isinstance(cur, int) and not isinstance(cur, bool):
                v = int(v)
            elif isinstance(cur, float):
                v = float(v)
            setattr(src, k, v)
    src.name = src.name or sid
    if src.enabled and missing:
        raise ConfigError(f"source {sid}: environment variables not set: {sorted(set(missing))}")
    if src.rtsp_transport not in ("tcp", "udp"):
        raise ConfigError(f"source {sid}: rtsp_transport must be tcp or udp")
    if src.roi is not None:
        pts = [(float(p[0]), float(p[1])) for p in src.roi]
        if len(pts) < 3 or not all(0 <= x <= 1 and 0 <= y <= 1 for x, y in pts):
            raise ConfigError(f"source {sid}: roi must be >= 3 normalized [x, y] points in 0..1")
        src.roi = pts
    if src.enabled:
        _check_target(src)
    return src


def _check_target(src: Source) -> None:
    if src.type in URI_TYPES:
        if not src.uri:
            raise ConfigError(f"source {src.id}: uri required")
        if src.type == "file":
            path = src.uri[7:] if src.uri.startswith("file://") else src.uri
            if not Path(path).is_file():
                raise ConfigError(f"source {src.id}: file not found: {path}")
            src.uri = "file://" + str(Path(path).resolve())
    elif src.type == "image":
        if not Path(src.uri).is_file():
            raise ConfigError(f"source {src.id}: image not found: {src.uri}")
        src.files = [str(Path(src.uri).resolve())]
    elif src.type == "image_folder":
        pattern = src.uri if any(ch in src.uri for ch in "*?[") else str(Path(src.uri) / "*")
        files = sorted(f for f in glob.glob(pattern)
                       if f.lower().endswith((".jpg", ".jpeg", ".png")) and Path(f).is_file())
        if not files:
            raise ConfigError(f"source {src.id}: no JPEG/PNG images match {pattern}")
        src.files = [str(Path(f).resolve()) for f in files]


def load_sources(path: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> List[Source]:
    env = dict(os.environ if env is None else env)
    path = path or env.get("LPR_SOURCES_FILE", "/config/sources.yaml")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults") or {}
    sources = [parse_source(raw, defaults, env) for raw in data.get("sources") or []]
    ids = [s.id for s in sources]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ConfigError(f"duplicate source ids: {dup}")
    return sources
