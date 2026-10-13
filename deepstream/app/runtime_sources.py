"""Persist source changes made at runtime (control API / dashboard) so a restart keeps them.

Overlay file (default /data/sources.runtime.json, on the data volume):
    {"added": {"<id>": {<source as posted>}}, "removed": ["<id>"], "enabled": {"<id>": true|false}}
At startup the overlay is applied on top of sources.yaml: removed ids are dropped, added sources are appended (or
replace a yaml entry with the same id), enabled flags override. A source posted with credentials in its URI keeps
them in this file: the file is written with mode 600 on the data volume, never logged.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

from .config import ConfigError, Source, parse_source

log = logging.getLogger("lpr.runtime_sources")


class RuntimeSources:
    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.data: Dict[str, Any] = {"added": {}, "removed": [], "enabled": {}}
        if self.path.is_file():
            try:
                self.data.update(json.loads(self.path.read_text()))
            except ValueError:
                log.error("ignoring unreadable %s", self.path)

    def _save(self) -> None:
        """Never raises: a failed save is logged; the runtime change itself still applies."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1))
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)
        except OSError as e:
            log.error("cannot save runtime sources to %s: %s (the change applies until restart)", self.path, e)

    def added(self, raw: Dict[str, Any]) -> None:
        with self._lock:
            sid = str(raw["id"])
            self.data["added"][sid] = raw
            self.data["removed"] = [r for r in self.data["removed"] if r != sid]
            self.data["enabled"].pop(sid, None)
            self._save()

    def removed(self, sid: str) -> None:
        with self._lock:
            self.data["added"].pop(sid, None)
            self.data["enabled"].pop(sid, None)
            if sid not in self.data["removed"]:
                self.data["removed"].append(sid)
            self._save()

    def enabled(self, sid: str, flag: bool) -> None:
        with self._lock:
            if sid in self.data["added"]:
                self.data["added"][sid]["enabled"] = flag
            else:
                self.data["enabled"][sid] = flag
            self._save()

    def apply(self, sources: List[Source], env: Dict[str, str]) -> List[Source]:
        out = [s for s in sources if s.id not in self.data["removed"] and s.id not in self.data["added"]]
        for s in out:
            if s.id in self.data["enabled"]:
                s.enabled = bool(self.data["enabled"][s.id])
        for sid, raw in self.data["added"].items():
            try:
                out.append(parse_source(raw, {}, env))
            except ConfigError as e:
                log.error("runtime source %s skipped: %s", sid, e)
        return out
