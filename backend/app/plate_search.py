"""Position-based plate search (dashboard plate editor) -> condition on the stored ``plate_key``.

``slots`` holds one token per plate position, empty = any value:
  standard  8 tokens: d d L d d d d d  (L = letter class name, e.g. ``Be``; the key is ``12Be34567``)
  freezone  5 digit tokens             (key = the 5-digit number)
  protocol  1-5 digit tokens           (key = the digits read; no validated format rule)
``match``: ``exact`` needs every position and compares the whole key; ``partial`` turns empty digit positions into
``_`` and an empty letter into ``%`` (letter names differ in length). Tokens are validated against the model's class
names, so the LIKE pattern never contains user-supplied wildcards.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from lpr_reader.classes import CLASS_NAMES, LETTER_IDS

DIGITS = {str(i) for i in range(10)}
# Letter position of standard-layout plates: the plate letters incl. Zhe (disabled) and D/S (diplomatic). Object,
# region and marker labels (plate, face, freezone, fz_*, protocol) are not in LETTER_IDS and never characters.
LETTERS = {CLASS_NAMES[i] for i in LETTER_IDS}
SIZES = {"standard": (8, 8), "freezone": (5, 5), "protocol": (1, 5)}


class SlotError(ValueError):
    pass


def parse_slots(raw: str, layout: str) -> List[str]:
    if layout not in SIZES:
        raise SlotError(f"unknown layout {layout!r}")
    toks = [t.strip() for t in raw.split(",")]
    lo, hi = SIZES[layout]
    if not lo <= len(toks) <= hi:
        raise SlotError(f"layout {layout} takes {lo if lo == hi else f'{lo}-{hi}'} positions, got {len(toks)}")
    for i, t in enumerate(toks):
        allowed = LETTERS if layout == "standard" and i == 2 else DIGITS
        if t and t not in allowed:
            raise SlotError(f"position {i + 1}: {t!r} is not a {'letter' if allowed is LETTERS else 'digit'}")
    return toks


def slot_condition(raw: str, layout: str, match: str) -> Optional[Tuple[str, str]]:
    """-> ("eq", key) | ("like", pattern) | None (nothing to filter on). Raises SlotError."""
    toks = parse_slots(raw, layout)
    if not any(toks):
        if match == "exact":
            raise SlotError("exact match needs every position")
        return None
    if match == "exact":
        if not all(toks):
            raise SlotError("exact match needs every position")
        return "eq", "".join(toks)
    if layout == "protocol":  # unknown length: the filled run of digits anywhere in the number
        return "like", "%" + "".join(t or "_" for t in _trim(toks)) + "%"
    return "like", "".join(t or ("%" if layout == "standard" and i == 2 else "_") for i, t in enumerate(toks))


def _trim(toks: List[str]) -> List[str]:
    idx = [i for i, t in enumerate(toks) if t]
    return toks[idx[0]:idx[-1] + 1]
