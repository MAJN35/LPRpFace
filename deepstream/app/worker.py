"""Reader worker: turns per-frame metadata from the probe into plate events, off the streaming thread."""
from __future__ import annotations

import datetime as _dt
import logging
import os
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import numpy as np

from lpr_reader import classes as C
from lpr_reader.decode import iou_matrix
from lpr_reader.normalize import plate_key
from lpr_reader.reader import PlateRead, read_frame
from lpr_reader.voting import Deduplicator, TrackManager, TrackResult, VoteConfig

from . import events

log = logging.getLogger("lpr.worker")


class ReaderWorker:
    def __init__(self, emitter, model: Dict[str, Any], crops_dir: str, dedup_s: float = 30.0,
                 vote_cfg: Optional[VoteConfig] = None, max_queue: int = 64, validate_events: bool = True,
                 net_size: int = 960, emit_invalid: bool = False):
        self.emitter = emitter
        self.model = model
        self.crops_dir = Path(crops_dir)
        self.dedup = Deduplicator(dedup_s)
        self.tracks = TrackManager(vote_cfg or VoteConfig())
        self.q: "queue.Queue" = queue.Queue(maxsize=max_queue)
        self.validate_events = validate_events
        self.net_size = net_size
        self.emit_invalid = emit_invalid
        self.sources: Dict[int, Any] = {}           # mux pad index -> SourceBin
        self.osd: Dict[tuple, str] = {}             # (source id, track id) -> current Latin string
        self.image_results: Dict[str, Dict[str, Any]] = {}   # image path -> {"status", "events"}
        self.stats = {"frames": 0, "reads": 0, "events": 0, "dedup_suppressed": 0, "small_plates_skipped": 0,
                      "invalid_events": 0, "errors": 0,
                      "dropped_implausible": 0}
        self._last_expire = time.time()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, name="reader-worker", daemon=True)
        self._t.start()

    # --- called from the pipeline --------------------------------------------------------------------------------
    def register(self, sb) -> None:
        self.sources[sb.index] = sb

    def offer(self, item) -> bool:
        try:
            self.q.put_nowait(("frame", item))
            return True
        except queue.Full:
            return False

    def source_ended(self, sb) -> None:
        self.q.put(("flush_source", sb.index))

    def image_failed(self, sb, path: str, error: str) -> None:
        self.image_results[path] = {"status": "error", "error": error, "events": []}

    def osd_text(self, sid: str, tid: int) -> str:
        return self.osd.get((sid, tid), "")

    def tick(self) -> None:
        pass  # expiry runs in the worker thread

    def stats_snapshot(self) -> Dict[str, Any]:
        return dict(self.stats, queue=self.q.qsize(), open_tracks=len(self.tracks.voters),
                    emitter=dict(self.emitter.stats))

    def finish(self, timeout: float = 30.0) -> None:
        self.q.put(("finish", None))
        self._t.join(timeout)
        self.emitter.close()

    # --- worker thread -------------------------------------------------------------------------------------------
    def _run(self):
        while True:
            try:
                kind, payload = self.q.get(timeout=0.25)
            except queue.Empty:
                kind, payload = "idle", None
            try:
                if kind == "frame":
                    self._frame(payload)
                elif kind == "flush_source":
                    self._finalize([v for k, v in list(self.tracks.voters.items()) if k[0] == payload], pop=True)
                elif kind == "finish":
                    self._finalize(list(self.tracks.voters.values()), pop=True)
                    return
                if time.time() - self._last_expire > 0.25:
                    self._last_expire = time.time()
                    self._expire()
            except Exception:
                self.stats["errors"] += 1
                log.exception("worker failed on %s", kind)

    def _frame(self, item):
        sb = self.sources.get(item.source_index)
        if sb is None:
            return
        self.stats["frames"] += 1
        dets = [SimpleNamespace(box=d["box"], class_id=d["cls"], score=d["score"],
                                scores=d["scores"] if d["scores"] is not None else _onehot(d["cls"], d["score"]))
                for d in item.dets]
        reads = read_frame(dets)
        self.stats["reads"] += len(reads)
        if sb.src.is_image:
            self._image(sb, item, reads)
            return
        plates = [d for d in item.dets if d["cls"] == C.PLATE_ID and d["track_id"] >= 0]
        net_scale = self.net_size / max(item.frame_size)
        for r in reads:
            tid = _match_track(r, plates)
            if tid is None:
                continue
            if r.width < sb.src.min_plate_px:
                self.stats["small_plates_skipped"] += 1
                continue
            crop = item.crops.get(tid)
            self.tracks.add((item.source_index, tid), r, item.t, frame_id=item.frame_num,
                            width_px=r.width * net_scale, extra=crop)
            v = self.tracks.voters[(item.source_index, tid)]
            v.frame_size = item.frame_size
            if r.plate_string_latin:
                self.osd[(sb.src.id, tid)] = r.plate_string_latin

    def _expire(self):
        now = time.time()
        timeout = self.tracks.cfg.track_timeout_s
        # last_seen is the frame's arrival time at the muxer (wall clock), so it compares with time.time().
        done = [v for v in self.tracks.voters.values() if v.last_seen is not None and now - v.last_seen >= timeout]
        self._finalize(done, pop=True)

    def _finalize(self, voters, pop: bool):
        for v in voters:
            if pop:
                self.tracks.voters.pop(v.track_id, None)
            res = v.result()                      # None for tracks shorter than VoteConfig.min_frames
            if res is None:
                continue
            if not self.emit_invalid and not plausible(res):
                self.stats["dropped_implausible"] += 1
                continue
            idx, tid = v.track_id
            sb = self.sources.get(idx)
            if sb is None:
                continue
            self.osd.pop((sb.src.id, tid), None)
            key = plate_key(res.plate_string_latin) if res.is_valid else ""
            if key and self.dedup.is_duplicate(sb.src.id, key, res.last_seen):
                self.stats["dedup_suppressed"] += 1
                continue
            res.track_id = tid
            crop = res.best.get("extra")
            res.best["extra"] = None
            ev = events.from_track(res, sb.src, self.model, getattr(v, "frame_size", sb.frame_size), None,
                                   res.best.get("t") or res.last_seen)
            ev["best_frame_crop_path"] = self._save_crop(crop, sb.src.id, ev["event_id"], ev["timestamp"])
            self._emit(ev)

    def _image(self, sb, item, reads: List[PlateRead]):
        path = item.image_file or ""
        name = os.path.basename(path)
        try:
            ftime = os.path.getmtime(path)
        except OSError:
            ftime = time.time()
        evs = []
        crops = list(item.crops.values())
        boxes = [d["box"] for d in item.dets if d["cls"] == C.PLATE_ID]
        if not reads:
            r = PlateRead([0, 0, 0, 0], 0.0, invalid_reason="no plate detected")
            reads = [r]
        for r in reads:
            ev = events.from_image(r, sb.src, self.model, item.frame_size, name, None, ftime)
            crop = _crop_for(r, boxes, crops)
            ev["best_frame_crop_path"] = self._save_crop(crop, sb.src.id, ev["event_id"], ev["timestamp"])
            if self._emit(ev):
                evs.append(ev)
        self.image_results[path] = {"status": "done", "events": evs}

    def _emit(self, ev) -> bool:
        if self.validate_events:
            try:
                events.validate(ev)
            except Exception as e:  # noqa: BLE001
                self.stats["invalid_events"] += 1
                log.error("event failed schema validation, not emitted: %s", str(e)[:300])
                return False
        self.stats["events"] += 1
        self.emitter.emit(ev)
        return True

    def _save_crop(self, crop: Optional[np.ndarray], sid: str, event_id: str, ts: str) -> Optional[str]:
        if crop is None or crop.size == 0:
            return None
        import cv2

        rel = Path(sid) / ts[:10] / f"{event_id}.jpg"
        out = self.crops_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        bgr = cv2.cvtColor(crop, cv2.COLOR_RGBA2BGR) if crop.ndim == 3 and crop.shape[2] == 4 else crop
        ok = cv2.imwrite(str(out), bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return str(rel) if ok else None


def plausible(res) -> bool:
    """A read worth an event: a valid plate, or a plate type without a validated rule (protocol) whose read has at
    least 4 digits. Reads without characters or with a wrong character count are not plates to report."""
    if res.is_valid:
        return True
    if res.is_valid is None:
        return sum(1 for c in res.characters if c.get("class_id", 99) < 10) >= 4
    return False


def _onehot(cls: int, score: float) -> np.ndarray:
    s = np.zeros(C.NUM_CLASSES, np.float32)
    s[cls] = score
    return s


def _match_track(read: PlateRead, plates: List[Dict[str, Any]]) -> Optional[int]:
    best, best_iou = None, 0.5
    for p in plates:
        iou = float(iou_matrix(read.plate_bbox, p["box"])[0, 0])
        if iou >= best_iou:
            best, best_iou = p["track_id"], iou
    return best


def _crop_for(read: PlateRead, boxes: List[List[float]], crops: List[np.ndarray]) -> Optional[np.ndarray]:
    if not boxes or not crops or len(boxes) != len(crops):
        return None
    ious = [float(iou_matrix(read.plate_bbox, b)[0, 0]) for b in boxes]
    k = int(np.argmax(ious))
    return crops[k] if ious[k] > 0.5 else None
