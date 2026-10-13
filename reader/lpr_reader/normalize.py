"""Plate-text normalization shared by the reader, the consumer and the backend search.

Digit/letter normalization and the standard-plate parser are adapted from the earlier project
(/home/edgetec/EdgetecLPR/PlateDetector, backend/app/core/plate_format.py at commit c8c9740), extended with the
Latin letter names this model uses (class names, e.g. ``Be``) and made Python 3.8 compatible.

Forms:
  * ``plate_string_fa``    ``۱۲ ب ۳۴۵ | ۶۷``   (reader output, physical left-to-right order)
  * ``plate_string_latin`` ``12 Be 345 | 67``  (letter = class name, see LATIN_ALIASES for accepted short forms)
  * ``plate_key``          ``12Be34567``        (formatting-independent comparison/search key)
"""
from __future__ import annotations

import re
from typing import List, NamedTuple, Optional

from .classes import CLASS_NAMES, GLYPHS, LETTER_IDS

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_FA = str.maketrans({**{str(i): FA_DIGITS[i] for i in range(10)}, **{AR_DIGITS[i]: FA_DIGITS[i] for i in range(10)}})
_TO_EN = str.maketrans({**{FA_DIGITS[i]: str(i) for i in range(10)}, **{AR_DIGITS[i]: str(i) for i in range(10)}})
# Arabic code points that sneak in from keyboards/OCR in place of their Persian equivalents.
_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه"})
IRAN_WORD = "ایران"
WHEELCHAIR = "♿"  # Zhe (29) on disabled plates, as in the test-set ground truth
_SEPARATORS_RE = re.compile(r"[\s\-_|/\\,،:‌​‎‏]+")

# Persian glyph and Latin name of every letter class.
LETTER_GLYPH = {cid: GLYPHS.get(cid, CLASS_NAMES[cid]) for cid in LETTER_IDS}
LETTER_GLYPH[29] = WHEELCHAIR
GLYPH_TO_LETTER = {g: cid for cid, g in LETTER_GLYPH.items()}
GLYPH_TO_LETTER["ژ"] = 29
NAME_TO_LETTER = {CLASS_NAMES[cid].lower(): cid for cid in LETTER_IDS}
# Short Latin forms people type. Single letters D and S are the diplomatic markers, so Dal and Sin have no
# single-letter alias.
LATIN_ALIASES = {"a": 10, "b": 11, "t": 12, "j": 14, "sh": 17, "q": 22, "gh": 22, "l": 23, "m": 24, "n": 25,
                 "h": 26, "v": 27, "p": 28, "y": 31, "z": 32, "k": 42, "g": 43, "f": 44, "ein": 21, "d": 45, "s": 46}


def to_persian_digits(text: str) -> str:
    return (text or "").translate(_TO_FA)


def to_ascii_digits(text: str) -> str:
    return (text or "").translate(_TO_EN)


def normalize_text(text: str) -> str:
    """Arabic letter forms -> Persian, Persian/Arabic-Indic digits -> ASCII, whitespace collapsed."""
    return " ".join(to_ascii_digits((text or "").translate(_ARABIC_TO_PERSIAN)).split())


class StandardPlate(NamedTuple):
    part1: str      # 2 digits (ASCII)
    letter: int     # letter class id
    part2: str      # 3 digits
    code: str       # 2-digit province code


_LETTER_TOKEN = r"(الف|[ء-يپچژکگی♿]|[A-Za-z]+)"
_RE_PHYSICAL = re.compile(rf"^(\d{{2}}){_LETTER_TOKEN}(\d{{3}})(?:{IRAN_WORD})?(\d{{2}})$")
_RE_IRAN_FIRST = re.compile(rf"^{IRAN_WORD}(\d{{2}})(\d{{3}}){_LETTER_TOKEN}(\d{{2}})$")


def letter_id(token: str) -> Optional[int]:
    """Persian glyph, class name or Latin alias -> letter class id."""
    t = (token or "").translate(_ARABIC_TO_PERSIAN)
    if t in GLYPH_TO_LETTER:
        return GLYPH_TO_LETTER[t]
    t = t.lower()
    return NAME_TO_LETTER.get(t, LATIN_ALIASES.get(t))


def compact(text: str) -> str:
    return _SEPARATORS_RE.sub("", normalize_text(text))


def parse_standard(text: str) -> Optional[StandardPlate]:
    """Parse a standard-layout plate in any accepted form (physical order, 'ایران' first, Persian/Latin)."""
    c = compact(text)
    m = _RE_PHYSICAL.match(c)
    if m:
        p1, tok, p2, code = m.groups()
    else:
        m = _RE_IRAN_FIRST.match(c)
        if not m:
            return None
        code, p2, tok, p1 = m.groups()
    lid = letter_id(tok)
    return StandardPlate(p1, lid, p2, code) if lid is not None else None


def format_standard(p: StandardPlate) -> tuple:
    """-> (plate_string_fa, plate_string_latin)."""
    fa = f"{to_persian_digits(p.part1)} {LETTER_GLYPH[p.letter]} {to_persian_digits(p.part2)} | {to_persian_digits(p.code)}"
    latin = f"{p.part1} {CLASS_NAMES[p.letter]} {p.part2} | {p.code}"
    return fa, latin


def plate_key(text: str) -> str:
    """Formatting-independent key: '12Be34567' for any form of a standard plate; otherwise the compacted text
    (ASCII digits, Persian letters, upper-cased Latin)."""
    p = parse_standard(text)
    if p is not None:
        return f"{p.part1}{CLASS_NAMES[p.letter]}{p.part2}{p.code}"
    return compact(text).replace(IRAN_WORD, "").upper()


def search_keys(query: str) -> List[str]:
    """Substring keys to match against stored ``plate_key`` values: the full key for a complete plate, else the
    query's digits and letters normalized (Persian letters -> class names) so '345' / '۳۴۵' / 'ب۳۴۵' all match."""
    q = compact(query)
    if not q:
        return []
    p = parse_standard(query)
    if p is not None:
        return [plate_key(query)]
    out, i = [], 0
    while i < len(q):
        if q.startswith("الف", i):
            out.append(CLASS_NAMES[10])
            i += 3
            continue
        ch = q[i]
        lid = GLYPH_TO_LETTER.get(ch)
        out.append(CLASS_NAMES[lid] if lid is not None else ch)
        i += 1
    return ["".join(out)]
