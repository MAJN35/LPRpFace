"""Inference control API (stdlib HTTP; reachable on the internal Docker network only, never published).

  GET    /health                       pipeline + per-source health, counters, model, capacity
  GET    /sources                      configured sources (URIs redacted)
  POST   /sources                      add a source at runtime (JSON body, same keys as sources.yaml)
  DELETE /sources/{id}                 remove a source at runtime
  POST   /sources/{id}/enable|disable  enable/disable without forgetting the config
  POST   /images?name=<file name>      image job: raw JPEG/PNG body (<= 10 MB) -> {"job_id"}
  GET    /images/{job_id}              {"status": "queued|done|error", "events": [...]}
  POST   /live/{id}/start|stop         detection stream on demand (called by the media gateway)
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from .config import ConfigError, parse_source

log = logging.getLogger("lpr.control")
MAX_IMAGE_BYTES = 10 << 20
JOB_SOURCE_ID = "api-images"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ControlServer:
    def __init__(self, app, host: str, port: int, jobs_dir: str, info: Dict[str, Any], store=None):
        self.app, self.info, self.store = app, info, store
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: Dict[str, str] = {}   # job id -> image path
        handler = self._handler()
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.t = threading.Thread(target=self.httpd.serve_forever, name="control-api", daemon=True)

    def start(self):
        self.t.start()
        log.info("control API on %s:%d", *self.httpd.server_address)

    def stop(self):
        self.httpd.shutdown()

    def _handler(self):
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                log.debug("%s %s", self.address_string(), fmt % args)

            def _send(self, code, body):
                data = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _json(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}") if n <= 65536 else None

            def do_GET(self):
                p = self.path.split("?")[0].rstrip("/")
                if p == "/health":
                    return self._send(200, dict(srv.info, **srv.app.health()))
                if p == "/sources":
                    return self._send(200, [_public(s) for s in srv.app.configs.values()])
                m = re.fullmatch(r"/images/([0-9a-f-]{36})", p)
                if m:
                    path = srv.jobs.get(m.group(1))
                    if path is None:
                        return self._send(404, {"error": "unknown job"})
                    res = srv.app.worker.image_results.get(path)
                    return self._send(200, res or {"status": "queued", "events": []})
                return self._send(404, {"error": "not found"})

            def do_POST(self):
                p, _, qs = self.path.partition("?")
                p = p.rstrip("/")
                try:
                    if p == "/sources":
                        body = self._json()
                        src = parse_source(body or {}, {}, dict(__import__("os").environ))
                        srv.app.add_source(src)
                        if srv.store is not None:
                            srv.store.added(body)
                        return self._send(201, _public(src))
                    m = re.fullmatch(r"/sources/([^/]+)/(enable|disable)", p)
                    if m:
                        if m.group(1) not in srv.app.configs:
                            return self._send(404, {"error": "unknown source"})
                        srv.app.set_enabled(m.group(1), m.group(2) == "enable")
                        if srv.store is not None:
                            srv.store.enabled(m.group(1), m.group(2) == "enable")
                        return self._send(200, {"id": m.group(1), "enabled": m.group(2) == "enable"})
                    if p == "/images":
                        return self._image(qs)
                    m = re.fullmatch(r"/live/([^/]+)/(start|stop)", p)
                    if m:   # called by the media gateway when a viewer opens / leaves <id>-osd
                        fn = srv.app.live_start if m.group(2) == "start" else srv.app.live_stop
                        return self._send(200, {"id": m.group(1), "state": fn(m.group(1))})
                except (ConfigError, ValueError) as e:
                    return self._send(400, {"error": str(e)})
                except KeyError as e:
                    return self._send(409, {"error": f"not available: {e}"})
                return self._send(404, {"error": "not found"})

            def do_DELETE(self):
                m = re.fullmatch(r"/sources/([^/]+)", self.path.rstrip("/"))
                if not m or m.group(1) not in srv.app.configs:
                    return self._send(404, {"error": "unknown source"})
                srv.app.remove_source(m.group(1))
                if srv.store is not None:
                    srv.store.removed(m.group(1))
                return self._send(200, {"id": m.group(1), "removed": True})

            def _image(self, qs):
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > MAX_IMAGE_BYTES:
                    return self._send(413, {"error": f"image must be 1 B .. {MAX_IMAGE_BYTES} B"})
                data = self.rfile.read(n)
                kind = "jpg" if data[:3] == b"\xff\xd8\xff" else "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else None
                if kind is None:
                    return self._send(415, {"error": "only JPEG and PNG are accepted"})
                name = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv).get("name", f"upload.{kind}")
                job = str(uuid.uuid4())
                path = srv.jobs_dir / f"{job}_{_SAFE_NAME.sub('_', name)[-100:]}"
                path.write_bytes(data)
                srv.jobs[job] = str(path)
                srv.app.add_image(JOB_SOURCE_ID, str(path))
                return self._send(202, {"job_id": job})

        return H


def _public(src) -> Dict[str, Any]:
    return {"id": src.id, "name": src.name, "type": src.type, "uri": src.uri_redacted, "enabled": src.enabled,
            "max_fps": src.max_fps, "roi": src.roi, "min_plate_px": src.min_plate_px, "face_blur": src.face_blur,
            "record": src.record}
