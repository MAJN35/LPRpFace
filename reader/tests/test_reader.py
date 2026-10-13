"""Unit tests for every A.7 reader rule, on synthetic detections (no images, no GPU)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "reader"))

from lpr_reader import classes as C  # noqa: E402
from lpr_reader.normalize import (normalize_text, parse_standard, plate_key, search_keys,  # noqa: E402
                                  to_persian_digits)
from lpr_reader.reader import read_frame  # noqa: E402
from lpr_reader.voting import Deduplicator, TrackManager, TrackVoter, VoteConfig  # noqa: E402

N = {n: i for i, n in enumerate(C.CLASS_NAMES)}


def det(name, x, y, w=10.0, h=20.0, score=0.9, alt=None):
    """Detection centred at (x, y); ``alt`` = {class_name: score} for runner-up classes."""
    cid = N[name]
    s = np.zeros(C.NUM_CLASSES, np.float32)
    s[cid] = score
    for k, v in (alt or {}).items():
        s[N[k]] = v
    return SimpleNamespace(box=[x - w / 2, y - h / 2, x + w / 2, y + h / 2], class_id=cid, score=score, scores=s)


def plate(x0=100, y=50, w=150, h=34, score=0.9):
    return det("plate", x0 + w / 2, y, w, h, score)


def row(names, x0=110, y=50, step=16, **kw):
    return [det(n, x0 + i * step, y, **kw) for i, n in enumerate(names)]


STD = ["1", "2", "Be", "3", "4", "5", "6", "7"]


# --- standard --------------------------------------------------------------------------------------------------

def test_standard_plate():
    r = read_frame([plate()] + row(STD))[0]
    assert r.plate_type == "standard" and r.is_valid and r.invalid_reason is None
    assert r.plate_string_latin == "12 Be 345 | 67"
    assert r.plate_string_fa == "۱۲ ب ۳۴۵ | ۶۷"
    assert [c.name for c in r.characters] == STD


def test_order_follows_x_not_input_order():
    chars = row(STD)
    r = read_frame([plate()] + chars[::-1])[0]
    assert r.plate_string_latin == "12 Be 345 | 67"


def test_invalid_reads_are_returned_not_dropped():
    r = read_frame([plate()] + row(STD[:6]))[0]
    assert r.is_valid is False and "found 6" in r.invalid_reason
    assert r.plate_string_latin == "1 2 Be 3 4 5"


def test_extra_boxes_dropped_smallest_then_weakest():
    # 8 real characters + a tiny noise box + a weak full-size spurious box (seen on real TensorRT output)
    chars = row(STD) + [det("4", 225, 50, 3, 4, score=0.9), det("9", 238, 50, score=0.36)]
    r = read_frame([plate(w=160)] + chars)[0]
    assert r.is_valid and r.plate_string_latin == "12 Be 345 | 67"


def test_plate_without_characters_is_reported():
    r = read_frame([plate()])[0]
    assert r.is_valid is False and r.invalid_reason == "no characters"


def test_per_class_thresholds_drop_weak_plate():
    assert read_frame([plate(score=0.38)] + row(STD)) == []


# --- constrained decoding ----------------------------------------------------------------------------------------

def test_digit_slot_only_chooses_digits():
    chars = row(STD)
    # slot 0: the model's top class is the letter Alef, but ۷ is the best digit -> the slot reads 7
    chars[0] = det("Alef", 110, 50, score=0.6, alt={"7": 0.5})
    r = read_frame([plate()] + chars)[0]
    c0 = r.characters[0]
    assert c0.class_id == 7 and c0.confidence == pytest.approx(0.5)
    assert r.plate_string_latin == "72 Be 345 | 67"


def test_letter_slot_only_chooses_letters_and_keeps_margin():
    chars = row(STD)
    chars[2] = det("3", 142, 50, score=0.7, alt={"Sad": 0.55, "Sin": 0.4})
    r = read_frame([plate()] + chars)[0]
    c = r.characters[2]
    assert c.name == "Sad" and c.confidence == pytest.approx(0.55) and c.margin == pytest.approx(0.15)
    assert [a["name"] for a in c.alternatives][:1] == ["Sin"]


# --- duplicates ----------------------------------------------------------------------------------------------

def test_partial_duplicate_plate_box_is_merged():
    # A second, partial plate box (left half) on the same plate: the full box contains more character centers.
    full = plate()
    partial = det("plate", 140, 50, 80, 34, score=0.95)
    reads = read_frame([full, partial] + row(STD))
    assert len(reads) == 1 and reads[0].plate_bbox[2] == pytest.approx(full.box[2])
    assert reads[0].plate_string_latin == "12 Be 345 | 67"


def test_duplicate_glyph_boxes_merged_keeping_alternative():
    chars = row(STD)
    # second box on the letter glyph with another class (class-aware NMS kept both)
    chars.append(det("Sad", 142, 50, score=0.5))
    r = read_frame([plate()] + chars)[0]
    assert r.is_valid and r.characters[2].name == "Be"
    assert "Sad" in [a["name"] for a in r.characters[2].alternatives]


def test_character_goes_to_one_plate_only():
    # Two plates side by side; each character belongs to the plate containing its center.
    p1, p2 = plate(100), plate(400)
    reads = read_frame([p1, p2] + row(STD, x0=110) + row(["9", "8", "Mim", "7", "6", "5", "4", "3"], x0=410))
    assert sorted(r.plate_string_latin for r in reads) == ["12 Be 345 | 67", "98 Mim 765 | 43"]


# --- special plates -------------------------------------------------------------------------------------------

def test_disabled_plate():
    r = read_frame([plate()] + row(["9", "8", "Zhe", "5", "9", "4", "3", "2"]))[0]
    assert r.plate_type == "disabled" and r.is_valid
    assert r.plate_string_fa == "۹۸ ♿ ۵۹۴ | ۳۲" and r.plate_string_latin == "98 Zhe 594 | 32"


@pytest.mark.parametrize("marker", ["D", "S"])
def test_diplomatic_plate(marker):
    r = read_frame([plate()] + row(["9", "8", marker, "7", "5", "0", "6", "9"]))[0]
    assert r.plate_type == "diplomatic" and r.markers == [marker]
    assert r.plate_string_latin == f"98 {marker} 750 | 69"


def test_protocol_plate_is_not_applicable():
    r = read_frame([plate(), det("protocol", 95, 50, 40, 30)] + row(["6", "0", "6", "6"], x0=130, step=25))[0]
    assert r.plate_type == "protocol" and "protocol" in r.markers
    assert r.is_valid is None and r.invalid_reason == "not_applicable"
    assert r.plate_string_latin == "6 0 6 6"


def test_transit_expiry_not_in_number():
    # 17 گ 185 | 24, expiry 00/2 in small digits under the code (layout from the synthetic test set).
    p = det("plate", 352, 126, 564, 147)
    main = [det("1", 125, 102, 20, 46), det("7", 166, 106, 37, 47), det("Gaf", 251, 111, 77, 55),
            det("1", 329, 123, 17, 51), det("8", 379, 129, 44, 51), det("5", 433, 134, 46, 53)]
    right = [det("2", 536, 136, 20, 24), det("4", 562, 138, 23, 26),
             det("0", 503, 172, 8, 7), det("0", 523, 174, 7, 7), det("2", 564, 176, 17, 20)]
    r = read_frame([p] + main + right)[0]
    assert r.plate_type == "transit" and r.is_valid
    assert r.plate_string_latin == "17 Gaf 185 | 24" and r.expiry == "00/2"
    assert r.plate_string_fa == "۱۷ گ ۱۸۵ | ۲۴"


def test_freezone_two_rows_cross_checked_with_zone():
    p = det("plate", 812, 544, 164, 76)
    top = [det(d, x, 525, 12, 18) for d, x in zip("96213", (805, 822, 837, 855, 871))]
    bottom = [det(d, x, 562, 14, 20) for d, x in zip("96213", (802, 820, 837, 856, 874))]
    marks = [det("freezone", 759, 546, 56, 70), det("fz_KISH", 757, 571, 31, 11, score=0.8),
             det("fz_ARVAND", 757, 590, 31, 11, score=0.6)]
    r = read_frame([p] + top + bottom + marks)[0]
    assert r.plate_type == "freezone" and r.is_valid
    assert r.plate_string_latin == "96213" and r.plate_string_fa == "۹۶۲۱۳"
    assert r.zone == "KISH" and r.rows == ["96213", "96213"]


def test_freezone_rows_disagree_is_invalid_but_returned():
    p = det("plate", 812, 544, 164, 76)
    top = [det(d, x, 525, 12, 18) for d, x in zip("96213", (805, 822, 837, 855, 871))]
    bottom = [det(d, x, 562, 14, 20, score=0.5) for d, x in zip("96218", (802, 820, 837, 856, 874))]
    r = read_frame([p, det("freezone", 759, 546, 56, 70)] + top + bottom)[0]
    assert r.is_valid is False and "disagree" in r.invalid_reason
    assert r.plate_string_latin == "96213"  # the more confident row wins per position


# --- normalization -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["۱۲ ب ۳۴۵ | ۶۷", "12 Be 345 | 67", "12B34567", "١٢ب٣٤٥٦٧", "ایران ۶۷ - ۳۴۵ ب ۱۲",
                                  "12 b 345 67"])
def test_plate_key_is_formatting_independent(text):
    assert plate_key(text) == "12Be34567"


def test_arabic_letters_and_digits_normalized():
    assert normalize_text("ي ك ٣") == "ی ک 3"
    assert parse_standard("۱۲ ي ۳۴۵ ۶۷").letter == N["Ye"]
    assert parse_standard("۱۲ ك ۳۴۵ ۶۷").letter == N["Kaf"]
    assert to_persian_digits("12") == "۱۲"


def test_search_keys_partial():
    assert search_keys("ب۳۴۵") == ["Be345"]
    assert search_keys("۳۴۵") == ["345"]
    assert search_keys("12 B 345 | 67") == ["12Be34567"]


# --- voting, timeout, dedup ------------------------------------------------------------------------------------

def _read(names, score=0.9, x0=110, w=150):
    return read_frame([plate(x0 - 10, w=w)] + row(names, x0=x0, score=score))[0]


def test_voting_per_position_beats_single_bad_frame():
    v = TrackVoter(1)
    for t in range(3):
        v.add(_read(STD), t=float(t), width_px=130)
    bad = list(STD)
    bad[3] = "8"  # ۳ misread as ۸ in one frame
    v.add(_read(bad, score=0.95), t=3.0, width_px=130)
    res = v.result()
    assert res.plate_string_latin == "12 Be 345 | 67" and res.frames_voted == 4


def test_small_plates_weigh_less():
    v = TrackVoter(1)
    bad = list(STD)
    bad[3] = "8"
    for t in range(3):
        v.add(_read(bad), t=float(t), width_px=25)     # tiny plate, 3 frames
    v.add(_read(STD), t=3.0, width_px=150)             # one large, clear frame
    assert v.result().plate_string_latin == "12 Be 345 | 67"


def test_near_identical_frames_have_limited_weight():
    v = TrackVoter(1, VoteConfig(repeat_weight=0.25))
    w1 = v.add(_read(STD), 0.0, width_px=150)
    w2 = v.add(_read(STD), 0.1, width_px=150)
    assert w2 == pytest.approx(w1 * 0.25)


def test_best_frame_is_largest_sharpest():
    v = TrackVoter(1)
    v.add(_read(STD, w=100), 0.0, frame_id=1, sharpness=1.0)
    v.add(_read(STD, w=150), 0.1, frame_id=2, sharpness=0.5)
    v.add(_read(STD, w=140), 0.2, frame_id=3, sharpness=1.0)
    assert v.result().best["frame_id"] == 3


def test_track_timeout_and_flush():
    m = TrackManager(VoteConfig(track_timeout_s=1.0))
    m.add("a", _read(STD), 0.0)
    m.add("b", _read(["9", "8", "Mim", "7", "6", "5", "4", "3"]), 0.8)
    assert [r.track_id for r in m.expire(1.5)] == ["a"]
    assert [r.track_id for r in m.flush()] == ["b"]
    assert m.flush() == []


def test_dedup_same_plate_same_camera_within_window():
    d = Deduplicator(window_s=30)
    assert not d.is_duplicate("cam-01", "12Be34567", 0.0)
    assert d.is_duplicate("cam-01", "12Be34567", 10.0)
    assert not d.is_duplicate("cam-02", "12Be34567", 10.0)
    assert not d.is_duplicate("cam-01", "12Be34567", 50.0)
