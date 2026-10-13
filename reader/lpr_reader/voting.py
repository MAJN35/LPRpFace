"""Track-level voting, track timeout and event deduplication (AGENTS.md A.7). Pure Python, no DeepStream.

Per track, every frame's ``PlateRead`` votes per character position of its layout. A vote weighs
``confidence x size factor`` where the size factor grows with plate width up to ``full_width_px`` (reading needs
~120 px in the network input). A frame nearly identical to the previous vote of the same track (same string, plate
box IoU >= ``same_box_iou``) only gets ``repeat_weight`` of its weight, so a parked car does not out-vote a few
good frames of a passing one. The layout with the most total weight wins; each of its positions takes the class
with the most weight. The best frame (largest plate x sharpness) is kept as the evidence crop reference.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import classes as C
from .decode import iou_matrix
from .normalize import LETTER_GLYPH, to_persian_digits
from .reader import PlateRead


@dataclass
class VoteConfig:
    full_width_px: float = 120.0     # plate width (network-input px) that gets the full size weight
    min_size_factor: float = 0.2
    same_box_iou: float = 0.9
    repeat_weight: float = 0.25
    track_timeout_s: float = 1.5     # finalize a track this long after its last read
    min_frames: int = 1


@dataclass
class TrackResult:
    track_id: Any
    plate_type: str
    plate_string_fa: str
    plate_string_latin: str
    characters: List[Dict]
    zone: Optional[str]
    expiry: Optional[str]
    markers: List[str]
    confidence: float
    is_valid: Optional[bool]
    invalid_reason: Optional[str]
    frames_voted: int
    first_seen: float
    last_seen: float
    best: Dict = field(default_factory=dict)  # {"t", "frame_id", "plate_bbox", "score", "extra"}


def size_factor(width: float, cfg: VoteConfig) -> float:
    return max(cfg.min_size_factor, min(1.0, width / cfg.full_width_px))


def _layout(read: PlateRead) -> Tuple:
    return (read.plate_type, len(read.characters))


class TrackVoter:
    """Accumulates the reads of one track."""

    def __init__(self, track_id: Any, cfg: Optional[VoteConfig] = None):
        self.track_id = track_id
        self.cfg = cfg or VoteConfig()
        self.layout_weight: Dict[Tuple, float] = defaultdict(float)
        self.slot_votes: Dict[Tuple, List[Dict[int, float]]] = {}
        self.slot_boxes: Dict[Tuple, List[List[float]]] = {}
        self.extra_votes: Dict[str, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))
        self.template: Dict[Tuple, PlateRead] = {}
        self.frames = 0
        self.first_seen: Optional[float] = None
        self.last_seen: Optional[float] = None
        self._prev: Optional[PlateRead] = None
        self.best: Dict = {}

    def add(self, read: PlateRead, t: float, frame_id: Any = None, sharpness: float = 1.0,
            width_px: Optional[float] = None, extra: Any = None) -> float:
        """Add one frame's read. ``width_px`` = plate width in network-input pixels (default: box width).
        Returns the weight the vote got."""
        cfg = self.cfg
        w = read.confidence * size_factor(width_px if width_px is not None else read.width, cfg)
        if self._prev is not None and self._prev.plate_string_latin == read.plate_string_latin and \
                float(iou_matrix(self._prev.plate_bbox, read.plate_bbox)[0, 0]) >= cfg.same_box_iou:
            w *= cfg.repeat_weight
        self._prev = read
        self.frames += 1
        self.first_seen = t if self.first_seen is None else min(self.first_seen, t)
        self.last_seen = t if self.last_seen is None else max(self.last_seen, t)
        quality = read.width * max(sharpness, 1e-6)
        if not self.best or quality > self.best["quality"]:
            self.best = {"quality": quality, "t": t, "frame_id": frame_id, "plate_bbox": read.plate_bbox,
                         "score": read.plate_score, "extra": extra}
        if not read.characters or w <= 0:
            return 0.0
        key = _layout(read)
        self.layout_weight[key] += w
        if key not in self.slot_votes:
            self.slot_votes[key] = [defaultdict(float) for _ in read.characters]
            self.slot_boxes[key] = [c.box for c in read.characters]
            self.template[key] = read
        for slot, c in enumerate(read.characters):
            self.slot_votes[key][slot][c.class_id] += w * c.confidence / max(read.confidence, 1e-6)
            for alt in c.alternatives:  # runner-up classes keep a small share
                self.slot_votes[key][slot][alt["class_id"]] += w * alt["score"] / max(read.confidence, 1e-6) * 0.5
        if read.zone:
            self.extra_votes["zone"][read.zone] += w
        if read.expiry:
            self.extra_votes["expiry"][read.expiry] += w
        return w

    def result(self) -> Optional[TrackResult]:
        if self.frames < self.cfg.min_frames:
            return None
        best_frame = {k: v for k, v in self.best.items() if k != "quality"}
        if not self.layout_weight:
            return TrackResult(self.track_id, "unknown", "", "", [], None, None, [], 0.0, False, "no characters",
                               self.frames, self.first_seen, self.last_seen, best_frame)
        key = max(self.layout_weight, key=lambda k: self.layout_weight[k])
        tpl = self.template[key]
        chars, ids = [], []
        for slot, votes in enumerate(self.slot_votes[key]):
            total = sum(votes.values())
            cid = max(votes, key=lambda k: votes[k])
            ids.append(cid)
            chars.append({"class_id": cid, "name": C.CLASS_NAMES[cid], "confidence": round(votes[cid] / total, 4),
                          "box": self.slot_boxes[key][slot]})
        zone = max(self.extra_votes["zone"].items(), key=lambda kv: kv[1])[0] if self.extra_votes["zone"] else tpl.zone
        expiry = (max(self.extra_votes["expiry"].items(), key=lambda kv: kv[1])[0]
                  if self.extra_votes["expiry"] else tpl.expiry)
        fa, latin = _format(tpl, ids)
        conf = min(c["confidence"] for c in chars)
        return TrackResult(self.track_id, tpl.plate_type, fa, latin, chars, zone, expiry, list(tpl.markers), conf,
                           tpl.is_valid, tpl.invalid_reason, self.frames, self.first_seen, self.last_seen, best_frame)


def _format(tpl: PlateRead, ids: List[int]) -> Tuple[str, str]:
    """Rebuild the strings of a voted layout in the template's format."""
    def fa(cid):
        return to_persian_digits(str(cid)) if cid < 10 else LETTER_GLYPH.get(cid, C.CLASS_NAMES[cid])

    def la(cid):
        return str(cid) if cid < 10 else C.CLASS_NAMES[cid]

    t = tpl.plate_type
    if t in ("standard", "disabled", "diplomatic") and len(ids) == 8 and tpl.is_valid:
        return (f"{fa(ids[0])}{fa(ids[1])} {fa(ids[2])} {''.join(fa(i) for i in ids[3:6])} | {fa(ids[6])}{fa(ids[7])}",
                f"{la(ids[0])}{la(ids[1])} {la(ids[2])} {''.join(la(i) for i in ids[3:6])} | {la(ids[6])}{la(ids[7])}")
    if t == "transit" and len(ids) >= 8 and tpl.expiry is not None:
        return (f"{fa(ids[0])}{fa(ids[1])} {fa(ids[2])} {''.join(fa(i) for i in ids[3:6])} | {fa(ids[6])}{fa(ids[7])}",
                f"{la(ids[0])}{la(ids[1])} {la(ids[2])} {''.join(la(i) for i in ids[3:6])} | {la(ids[6])}{la(ids[7])}")
    if t == "freezone" and tpl.rows and len(tpl.rows[0]) == len(tpl.rows[1]) == len(ids) // 2:
        n = len(ids) // 2  # each position of both rows was voted separately; report the voted Persian (top) row
        number = "".join(str(a) for a in ids[:n])
        return to_persian_digits(number), number
    return " ".join(fa(i) for i in ids), " ".join(la(i) for i in ids)


class TrackManager:
    """Feeds reads into per-track voters and finalizes tracks after ``track_timeout_s`` without a read."""

    def __init__(self, cfg: Optional[VoteConfig] = None):
        self.cfg = cfg or VoteConfig()
        self.voters: Dict[Any, TrackVoter] = {}

    def add(self, track_id: Any, read: PlateRead, t: float, **kw) -> None:
        v = self.voters.get(track_id)
        if v is None:
            v = self.voters[track_id] = TrackVoter(track_id, self.cfg)
        v.add(read, t, **kw)

    def expire(self, now: float) -> List[TrackResult]:
        done = [k for k, v in self.voters.items() if v.last_seen is not None and now - v.last_seen >= self.cfg.track_timeout_s]
        return [r for r in (self.voters.pop(k).result() for k in done) if r is not None]

    def flush(self) -> List[TrackResult]:
        """End of stream: finalize every open track."""
        out = [r for r in (v.result() for v in self.voters.values()) if r is not None]
        self.voters.clear()
        return out


class Deduplicator:
    """Suppresses the same plate string from the same camera within ``window_s`` seconds."""

    def __init__(self, window_s: float = 30.0):
        self.window_s = window_s
        self.last: Dict[Tuple[str, str], float] = {}

    def is_duplicate(self, camera_id: str, plate_key: str, t: float) -> bool:
        if not plate_key:
            return False
        k = (camera_id, plate_key)
        prev = self.last.get(k)
        self.last[k] = t
        # prune old keys occasionally
        if len(self.last) > 10000:
            self.last = {kk: tt for kk, tt in self.last.items() if t - tt < self.window_s}
        return prev is not None and t - prev < self.window_s
