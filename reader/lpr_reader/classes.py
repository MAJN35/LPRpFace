"""Class table of the YOLO12x LPR+face model (AGENTS.md A.4).

The ids are fixed: never renumber, merge or reorder. Every labels file and class dictionary is generated from the
model's ``class_names.json`` and checked against ``CLASS_NAMES`` here; ``parse_agents_md_a4`` re-reads the table from
AGENTS.md so a drift between this module and the rulebook is caught by the tests and by ``tools/check_model.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CLASS_NAMES: Tuple[str, ...] = (
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "Alef", "Be", "Te", "Se", "Jim", "Dal", "Sin", "Shin", "Sad", "Ta",
    "Za", "Eyn", "Ghaf", "Lam", "Mim", "Nun", "He", "Vav", "Pe", "Zhe",
    "plate", "Ye", "Ze", "face", "freezone",
    "fz_KISH", "fz_QESHM", "fz_CHABAHAR", "fz_ARVAND", "fz_ARAS", "fz_ANZALI", "fz_MAKU",
    "Kaf", "Gaf", "Fe", "D", "S", "protocol",
)
NUM_CLASSES = len(CLASS_NAMES)  # 48

# Persian glyphs given in A.4 (digits and plate letters). Zhe (29) is the wheelchair symbol on disabled plates;
# A.4 gives no glyph for it, so it is not listed here.
GLYPHS: Dict[int, str] = {i: "۰۱۲۳۴۵۶۷۸۹"[i] for i in range(10)}
GLYPHS.update({
    10: "الف", 11: "ب", 12: "ت", 13: "ث", 14: "ج", 15: "د", 16: "س", 17: "ش", 18: "ص", 19: "ط",
    20: "ظ", 21: "ع", 22: "ق", 23: "ل", 24: "م", 25: "ن", 26: "ه", 27: "و", 28: "پ",
    31: "ی", 32: "ز", 42: "ک", 43: "گ", 44: "ف",
})

DIGIT_IDS: Tuple[int, ...] = tuple(range(10))
LETTER_IDS: Tuple[int, ...] = tuple(range(10, 29)) + (29, 31, 32, 42, 43, 44, 45, 46)
PLATE_ID = 30
FACE_ID = 33
FREEZONE_ID = 34
FZ_ZONE_IDS: Tuple[int, ...] = tuple(range(35, 42))
PROTOCOL_ID = 47


class ClassMapError(ValueError):
    """class_names.json does not match the fixed A.4 table."""


def load_class_names(path: Path) -> Tuple[List[str], Dict[int, str]]:
    """Read ``class_names.json``: either ``{"names": {...}, "char_glyphs": {...}}`` or a flat ``{"0": "0", ...}``."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    names_raw = data.get("names", data) if isinstance(data, dict) else None
    if not isinstance(names_raw, dict):
        raise ClassMapError(f"{path}: expected a JSON object with 'names'")
    try:
        ids = sorted(int(k) for k in names_raw)
    except ValueError as e:
        raise ClassMapError(f"{path}: non-integer class id ({e})") from None
    if ids != list(range(len(ids))):
        raise ClassMapError(f"{path}: class ids are not contiguous from 0: {ids}")
    names = [str(names_raw[str(i)]) for i in ids]
    glyphs = {int(k): str(v) for k, v in (data.get("char_glyphs") or {}).items()}
    return names, glyphs


def compare_names(names: List[str], expected: Tuple[str, ...] = CLASS_NAMES) -> List[str]:
    """Return a list of human-readable mismatches (empty = identical)."""
    errors = []
    if len(names) != len(expected):
        errors.append(f"class count {len(names)} != expected {len(expected)}")
    for i in range(max(len(names), len(expected))):
        got = names[i] if i < len(names) else None
        exp = expected[i] if i < len(expected) else None
        if got != exp:
            errors.append(f"id {i}: got {got!r}, expected {exp!r}")
    return errors


def compare_glyphs(glyphs: Dict[int, str]) -> Tuple[List[str], List[str]]:
    """Compare ``char_glyphs`` with A.4. Returns (errors, warnings): a different glyph is an error, a missing or
    extra glyph is a warning (the reader takes missing glyphs from A.4)."""
    errors, warnings = [], []
    for cid, g in sorted(GLYPHS.items()):
        if cid not in glyphs:
            warnings.append(f"id {cid} ({CLASS_NAMES[cid]}): no glyph in class_names.json, using A.4 {g!r}")
        elif glyphs[cid] != g:
            errors.append(f"id {cid} ({CLASS_NAMES[cid]}): glyph {glyphs[cid]!r} != A.4 {g!r}")
    for cid in sorted(set(glyphs) - set(GLYPHS)):
        name = CLASS_NAMES[cid] if 0 <= cid < NUM_CLASSES else "?"
        warnings.append(f"id {cid} ({name}): glyph {glyphs[cid]!r} has no A.4 counterpart (not used by the reader)")
    return errors, warnings


def labels_txt(names: List[str]) -> str:
    """DeepStream labels file: one name per line, line number = class id."""
    return "".join(n + "\n" for n in names)


_RANGE = re.compile(r"^(\d+)\s*[–-]\s*(\d+)$")
_INLINE = re.compile(r"^(\d+)\s+(\S+)(?:\s+(\S+))?$")


def parse_agents_md_a4(path: Path) -> Tuple[List[Optional[str]], Dict[int, str]]:
    """Parse the A.4 class table out of AGENTS.md. Returns (names by id, glyphs by id)."""
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(r"^## A\.4.*?$(.*?)^## A\.5", text, re.S | re.M)
    if not m:
        raise ClassMapError(f"{path}: section A.4 not found")
    names: Dict[int, str] = {}
    glyphs: Dict[int, str] = {}
    for line in m.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        first = cells[0]
        if first in ("id", "") or set(first) <= set("-: "):
            continue
        second = cells[1].replace("`", "") if len(cells) > 1 else ""
        rng = _RANGE.match(first)
        if first.isdigit():
            names[int(first)] = second
        elif rng:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if "…" in second:  # `0`…`9`
                items = [str(i) for i in range(lo, hi + 1)]
            else:
                items = [s.strip() for s in second.split(",")]
            if len(items) != hi - lo + 1:
                raise ClassMapError(f"A.4 row {first!r}: {len(items)} names for {hi - lo + 1} ids")
            names.update({lo + k: n for k, n in enumerate(items)})
        else:  # inline "10 Alef الف · 11 Be ب · ..."
            for seg in first.split("·"):
                mm = _INLINE.search(re.sub(r"\(.*?\)", "", seg).strip())  # drop notes like "(transit)"
                if not mm:
                    raise ClassMapError(f"A.4: cannot parse {seg!r}")
                cid = int(mm.group(1))
                names[cid] = mm.group(2)
                if mm.group(3):
                    glyphs[cid] = mm.group(3)
    n = max(names) + 1 if names else 0
    return [names.get(i) for i in range(n)], glyphs
