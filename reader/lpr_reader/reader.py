"""Single-frame plate reading (AGENTS.md A.7, reader library).

Input: decoded detections of one frame (``lpr_reader.decode.Detection`` or anything with ``box``, ``class_id``,
``score``, ``scores``). Output: one ``PlateRead`` per plate, invalid reads included (never dropped).

Rules:
  * per-class thresholds (A.7) are applied first;
  * duplicate/partial plate boxes are merged: of two overlapping plates keep the one containing more character
    centers, then the higher score;
  * every character goes to the plate containing its center (smallest such plate); one character -> one plate;
    duplicate boxes on the same glyph are merged, keeping the alternative class (score vectors are max-merged);
  * layouts: standard ``2 digits + letter + 3 digits | 2-digit code`` (disabled = Zhe letter, diplomatic = D/S
    letter), transit (Gaf letter; small digits in the right box are the expiry, not part of the number),
    free zone (two rows with the same number, split, read and cross-checked; zone from the best ``fz_*``),
    protocol (badge; digits reported, no validated format -> ``not_applicable``);
  * constrained decoding: digit slots choose only among digit classes, the letter slot only among letter
    classes, from the 48-score vector; the winning score is the character confidence, the gap to the runner-up
    in the same group is the margin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from . import classes as C
from .decode import default_thresholds, iou_matrix
from .normalize import LETTER_GLYPH, to_persian_digits

DIGITS = np.array(C.DIGIT_IDS)
LETTERS = np.array(C.LETTER_IDS)
MARKER_IDS = (C.FREEZONE_ID, C.PROTOCOL_ID) + C.FZ_ZONE_IDS
CHAR_IDS = set(C.DIGIT_IDS) | set(C.LETTER_IDS)
GAF, ZHE, DIPLO_D, DIPLO_S = 43, 29, 45, 46

PLATE_DUP_IOU = 0.5          # two plate boxes with IoU above this are the same plate
PLATE_DUP_CONTAIN = 0.7      # ... or when this share of the smaller box lies inside the larger one
CHAR_DUP_IOU = 0.6           # two character boxes above this IoU are the same glyph
PLATE_MARGIN = 0.06          # plate box grown by this fraction for center tests (boxes are slightly tight)
MARKER_MARGIN = 0.25         # free-zone panel / protocol badge sit at the plate's edge


@dataclass
class Char:
    class_id: int
    confidence: float
    margin: float
    box: List[float]
    alternatives: List[Dict] = field(default_factory=list)
    scores: Optional[np.ndarray] = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return C.CLASS_NAMES[self.class_id]

    def to_dict(self) -> Dict:
        return {"class_id": self.class_id, "name": self.name, "confidence": round(self.confidence, 4),
                "margin": round(self.margin, 4), "box": [round(v, 1) for v in self.box],
                "alternatives": self.alternatives}


@dataclass
class PlateRead:
    plate_bbox: List[float]
    plate_score: float
    plate_type: str = "unknown"          # standard | disabled | diplomatic | transit | freezone | protocol | unknown
    plate_string_fa: str = ""
    plate_string_latin: str = ""
    characters: List[Char] = field(default_factory=list)
    zone: Optional[str] = None
    expiry: Optional[str] = None
    markers: List[str] = field(default_factory=list)
    is_valid: Optional[bool] = False     # None = not_applicable (no validated format rule)
    invalid_reason: Optional[str] = None
    rows: Optional[List[str]] = None     # free zone: [Persian row, Latin row] as ASCII digits

    @property
    def confidence(self) -> float:
        """Weakest character confidence (0 without characters)."""
        return min((c.confidence for c in self.characters), default=0.0)

    @property
    def width(self) -> float:
        return self.plate_bbox[2] - self.plate_bbox[0]

    def to_dict(self) -> Dict:
        return {"plate_type": self.plate_type, "plate_string_fa": self.plate_string_fa,
                "plate_string_latin": self.plate_string_latin, "zone": self.zone, "expiry": self.expiry,
                "markers": self.markers, "characters": [c.to_dict() for c in self.characters],
                "confidence": round(self.confidence, 4), "plate_score": round(self.plate_score, 4),
                "is_valid": self.is_valid, "invalid_reason": self.invalid_reason,
                "plate_bbox": [round(v, 1) for v in self.plate_bbox]}


@dataclass(eq=False)  # identity: detections hold numpy arrays
class _Det:
    box: np.ndarray
    class_id: int
    score: float
    scores: np.ndarray

    @property
    def center(self):
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2

    @property
    def h(self) -> float:
        return float(self.box[3] - self.box[1])


def _as_dets(dets) -> List[_Det]:
    out = []
    for d in dets:
        scores = np.asarray(d.scores if getattr(d, "scores", None) is not None else np.eye(C.NUM_CLASSES)[d.class_id]
                            * d.score, np.float32)
        out.append(_Det(np.asarray(d.box, np.float32), int(d.class_id), float(d.score), scores))
    return out


def _inside(pt, box, margin: float) -> bool:
    w, h = box[2] - box[0], box[3] - box[1]
    return (box[0] - w * margin <= pt[0] <= box[2] + w * margin) and (box[1] - h * margin <= pt[1] <= box[3] + h * margin)


def _containment(a: np.ndarray, b: np.ndarray) -> float:
    """Share of the smaller box's area that lies inside the other box."""
    tl, br = np.maximum(a[:2], b[:2]), np.minimum(a[2:], b[2:])
    inter = float(np.prod(np.clip(br - tl, 0, None)))
    small = min(float(np.prod(a[2:] - a[:2])), float(np.prod(b[2:] - b[:2])))
    return inter / max(small, 1e-9)


def merge_plates(plates: List[_Det], chars: List[_Det]) -> List[_Det]:
    """Drop duplicate/partial plate boxes: keep the one containing more character centers, then higher score."""
    def n_inside(p):
        return sum(_inside(c.center, p.box, PLATE_MARGIN) for c in chars)

    ranked = sorted(plates, key=lambda p: (n_inside(p), p.score), reverse=True)
    kept: List[_Det] = []
    for p in ranked:
        if any(float(iou_matrix(p.box, k.box)[0, 0]) > PLATE_DUP_IOU or _containment(p.box, k.box) > PLATE_DUP_CONTAIN
               for k in kept):
            continue
        kept.append(p)
    return kept


def dedup_chars(chars: List[_Det]) -> List[_Det]:
    """Merge boxes on the same glyph (any class). Keeps the higher-scoring box; the score vectors are max-merged so
    the other class stays available to constrained decoding."""
    out: List[_Det] = []
    for c in sorted(chars, key=lambda d: -d.score):
        for k in out:
            if float(iou_matrix(c.box, k.box)[0, 0]) > CHAR_DUP_IOU:
                k.scores = np.maximum(k.scores, c.scores)
                break
        else:
            out.append(_Det(c.box.copy(), c.class_id, c.score, c.scores.copy()))
    return out


def decode_char(d: _Det, allowed: np.ndarray) -> Char:
    """Constrained decoding of one character among ``allowed`` class ids."""
    s = d.scores[allowed]
    order = np.argsort(-s)
    best = int(allowed[order[0]])
    conf = float(s[order[0]])
    second = float(s[order[1]]) if len(order) > 1 else 0.0
    alts = [{"class_id": int(allowed[j]), "name": C.CLASS_NAMES[int(allowed[j])], "score": round(float(s[j]), 4)}
            for j in order[1:3] if s[j] > 0.05]
    return Char(best, conf, conf - second, [float(v) for v in d.box], alts, d.scores)


def _letter_score(d: _Det) -> float:
    return float(d.scores[LETTERS].max())


def _split_rows(chars: List[_Det]) -> Optional[List[List[_Det]]]:
    """Split characters into two rows by the largest vertical gap (None if they form one row)."""
    if len(chars) < 4:
        return None
    ys = sorted(chars, key=lambda d: d.center[1])
    gaps = [ys[i + 1].center[1] - ys[i].center[1] for i in range(len(ys) - 1)]
    i = int(np.argmax(gaps))
    med_h = float(np.median([d.h for d in chars]))
    if gaps[i] < 0.6 * med_h or i == 0 or i == len(ys) - 2:
        return None
    return [sorted(ys[:i + 1], key=lambda d: d.center[0]), sorted(ys[i + 1:], key=lambda d: d.center[0])]


def _read_standard(read: PlateRead, chars: List[_Det]) -> None:
    """2 digits + letter + 3 digits | 2-digit code. Too many boxes: drop the smallest (noise), then the weakest."""
    chars = sorted(chars, key=lambda d: d.center[0])
    if len(chars) > 8:
        med_h = float(np.median([d.h for d in chars]))
        keep = [d for d in chars if d.h >= 0.5 * med_h]
        if len(keep) >= 8:
            chars = keep
        while len(chars) > 8:
            chars.remove(min(chars, key=lambda d: d.score))
    if len(chars) != 8:
        read.characters = [decode_char(d, LETTERS if _letter_score(d) > d.scores[DIGITS].max() else DIGITS)
                           for d in chars]
        read.invalid_reason = f"expected 8 characters, found {len(chars)}"
        _fallback_strings(read)
        return
    slots = [DIGITS, DIGITS, LETTERS] + [DIGITS] * 5
    read.characters = [decode_char(d, a) for d, a in zip(chars, slots)]
    letter = read.characters[2].class_id
    read.plate_type = {ZHE: "disabled", DIPLO_D: "diplomatic", DIPLO_S: "diplomatic"}.get(letter, "standard")
    if letter in (DIPLO_D, DIPLO_S):
        read.markers.append(C.CLASS_NAMES[letter])
    if letter == GAF:  # transit letter but no expiry digits found: report as transit, number only
        read.plate_type = "transit"
    d = [str(c.class_id) for c in read.characters]
    p1, p2, code = "".join(d[0:2]), "".join(d[3:6]), "".join(d[6:8])
    read.plate_string_fa = (f"{to_persian_digits(p1)} {LETTER_GLYPH[letter]} {to_persian_digits(p2)} | "
                            f"{to_persian_digits(code)}")
    read.plate_string_latin = f"{p1} {C.CLASS_NAMES[letter]} {p2} | {code}"
    read.is_valid, read.invalid_reason = True, None


def _read_transit(read: PlateRead, chars: List[_Det]) -> None:
    """Gaf plates: main row 2 digits + Gaf + 3 digits; right box: 2-digit code (tall) and small expiry digits."""
    chars = sorted(chars, key=lambda d: d.center[0])
    gi = max(range(len(chars)), key=lambda i: chars[i].scores[GAF])
    main, right = chars[max(0, gi - 2):gi + 4], chars[gi + 4:]
    read.plate_type = "transit"
    if gi != 2 or len(main) != 6 or len(right) < 2:
        _read_standard(read, chars)
        read.plate_type = "transit"
        return
    # The right box holds the code on top and the small expiry digits below it: split by the largest vertical gap.
    ys = sorted(right, key=lambda d: d.center[1])
    gaps = [ys[i + 1].center[1] - ys[i].center[1] for i in range(len(ys) - 1)]
    cut = int(np.argmax(gaps)) + 1 if gaps else len(ys)
    if gaps and gaps[cut - 1] >= 0.3 * float(np.median([d.h for d in right])):
        code, expiry = ys[:cut], ys[cut:]
    else:  # one row: the two tallest are the code
        code = sorted(right, key=lambda d: -d.h)[:2]
        expiry = [d for d in right if all(d is not c for c in code)]
    code = sorted(code, key=lambda d: d.center[0])
    slots = [DIGITS, DIGITS, LETTERS, DIGITS, DIGITS, DIGITS]
    main_c = [decode_char(d, a) for d, a in zip(main, slots)]
    code_c = [decode_char(d, DIGITS) for d in code]
    exp_rows = _split_rows(expiry) if len(expiry) >= 4 else None
    exp_sorted = [d for row in exp_rows for d in row] if exp_rows else sorted(expiry, key=lambda d: d.center[0])
    exp_c = [decode_char(d, DIGITS) for d in exp_sorted]
    read.characters = main_c + code_c + exp_c
    dg = [str(c.class_id) for c in main_c]
    p1, p2 = "".join(dg[0:2]), "".join(dg[3:6])
    cd = "".join(str(c.class_id) for c in code_c)
    ex = "".join(str(c.class_id) for c in exp_c)
    read.expiry = f"{ex[:2]}/{ex[2:]}" if len(ex) >= 3 else (ex or None)
    letter = main_c[2].class_id
    read.plate_string_fa = (f"{to_persian_digits(p1)} {LETTER_GLYPH[letter]} {to_persian_digits(p2)} | "
                            f"{to_persian_digits(cd)}")
    read.plate_string_latin = f"{p1} {C.CLASS_NAMES[letter]} {p2} | {cd}"
    ok = letter == GAF and len(ex) in (3, 4)
    read.is_valid = ok
    read.invalid_reason = None if ok else ("transit letter is not Gaf" if letter != GAF
                                           else f"expiry has {len(ex)} digits, expected 3-4")


def _read_freezone(read: PlateRead, chars: List[_Det]) -> None:
    """Two rows with the same number (top = Persian, bottom = Latin), same digit classes; cross-checked."""
    read.plate_type = "freezone"
    rows = _split_rows(chars)
    if rows is None:
        read.characters = [decode_char(d, DIGITS) for d in sorted(chars, key=lambda d: d.center[0])]
        read.invalid_reason = "free-zone plate without two character rows"
        _fallback_strings(read)
        return
    rc = [[decode_char(d, DIGITS) for d in row] for row in rows]
    read.characters = rc[0] + rc[1]
    s = ["".join(str(c.class_id) for c in row) for row in rc]
    read.rows = s
    if len(s[0]) == len(s[1]):
        # Same length: per position the more confident row wins (they should agree).
        number = "".join(str(a.class_id) if a.confidence >= b.confidence else str(b.class_id)
                         for a, b in zip(rc[0], rc[1]))
    else:
        number = max(zip(s, rc), key=lambda t: (len(t[0]) == 5, min((c.confidence for c in t[1]), default=0)))[0]
    read.plate_string_fa = to_persian_digits(number)
    read.plate_string_latin = number
    if s[0] != s[1]:
        read.invalid_reason = f"free-zone rows disagree ({s[0]} / {s[1]})"
    elif len(number) != 5:
        read.invalid_reason = f"free-zone number has {len(number)} digits, expected 5"
    else:
        read.is_valid, read.invalid_reason = True, None


def _read_protocol(read: PlateRead, chars: List[_Det]) -> None:
    read.plate_type = "protocol"
    read.characters = [decode_char(d, DIGITS) for d in sorted(chars, key=lambda d: d.center[0])]
    _fallback_strings(read)
    read.is_valid, read.invalid_reason = None, "not_applicable"


def _fallback_strings(read: PlateRead) -> None:
    parts_fa, parts_lat = [], []
    for c in read.characters:
        if c.class_id < 10:
            parts_fa.append(to_persian_digits(str(c.class_id)))
            parts_lat.append(str(c.class_id))
        else:
            parts_fa.append(LETTER_GLYPH.get(c.class_id, c.name))
            parts_lat.append(c.name)
    read.plate_string_fa = " ".join(parts_fa)
    read.plate_string_latin = " ".join(parts_lat)


def read_frame(dets: Sequence, class_thresholds: Optional[np.ndarray] = None) -> List[PlateRead]:
    """Read every plate in one frame. ``class_thresholds`` defaults to the A.7 per-class thresholds."""
    th = default_thresholds() if class_thresholds is None else np.asarray(class_thresholds, np.float32)
    ds = [d for d in _as_dets(dets) if d.score >= th[d.class_id]]
    plates = [d for d in ds if d.class_id == C.PLATE_ID]
    chars = [d for d in ds if d.class_id in CHAR_IDS]
    markers = [d for d in ds if d.class_id in MARKER_IDS]
    plates = merge_plates(plates, chars)

    # One character -> the smallest plate containing its center.
    by_plate: Dict[int, List[_Det]] = {i: [] for i in range(len(plates))}
    for c in chars:
        owners = [i for i, p in enumerate(plates) if _inside(c.center, p.box, PLATE_MARGIN)]
        if owners:
            i = min(owners, key=lambda i: float(np.prod(plates[i].box[2:] - plates[i].box[:2])))
            by_plate[i].append(c)

    reads = []
    for i, p in enumerate(plates):
        pc = dedup_chars(by_plate[i])
        mk = [m for m in markers if _inside(m.center, p.box, MARKER_MARGIN)]
        read = PlateRead([float(v) for v in p.box], p.score)
        zones = [m for m in mk if m.class_id in C.FZ_ZONE_IDS]
        is_fz = bool(zones) or any(m.class_id == C.FREEZONE_ID for m in mk)
        if is_fz:
            read.markers.append("freezone")
        if zones:
            read.zone = C.CLASS_NAMES[max(zones, key=lambda m: m.score).class_id][3:]
        if any(m.class_id == C.PROTOCOL_ID for m in mk):
            read.markers.append("protocol")
        if not pc:
            read.invalid_reason = "no characters"
            read.plate_type = "freezone" if is_fz else "unknown"
        elif is_fz or (not any(_letter_score(d) > 0.35 for d in pc) and _split_rows(pc) is not None):
            _read_freezone(read, pc)
        elif "protocol" in read.markers:
            _read_protocol(read, pc)
        elif max(d.scores[GAF] for d in pc) >= 0.35 and len(pc) > 8:
            _read_transit(read, pc)
        else:
            _read_standard(read, pc)
        reads.append(read)
    return reads
