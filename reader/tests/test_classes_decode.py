"""Class table vs AGENTS.md A.4, letterbox geometry, and basic decoder behaviour."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "reader"))

from lpr_reader import classes as C  # noqa: E402
from lpr_reader.decode import decode, default_thresholds, nms  # noqa: E402
from lpr_reader.preprocess import letterbox_params, unletterbox_boxes  # noqa: E402


def test_builtin_table_matches_agents_md():
    names, glyphs = C.parse_agents_md_a4(REPO / "AGENTS.md")
    assert names == list(C.CLASS_NAMES)
    assert {k: v for k, v in C.GLYPHS.items() if k >= 10} == glyphs


def test_id_groups_are_consistent():
    assert C.NUM_CLASSES == 48
    assert [C.CLASS_NAMES[i] for i in (C.PLATE_ID, C.FACE_ID, C.FREEZONE_ID, C.PROTOCOL_ID)] == \
        ["plate", "face", "freezone", "protocol"]
    assert all(C.CLASS_NAMES[i].startswith("fz_") for i in C.FZ_ZONE_IDS)
    assert not set(C.DIGIT_IDS) & set(C.LETTER_IDS)


@pytest.mark.parametrize("w,h", [(1920, 1080), (2560, 1440), (640, 480), (416, 416), (720, 1280), (401, 173)])
def test_letterbox_roundtrip(w, h):
    lb, (nw, nh), (top, bottom, left, right) = letterbox_params(w, h)
    assert nw + left + right == 960 and nh + top + bottom == 960
    assert (lb.pad_x, lb.pad_y) == (left, top)
    src = np.array([[0, 0, w, h], [w * 0.25, h * 0.5, w * 0.5, h * 0.75]], np.float32)
    net = src * lb.gain + np.array([lb.pad_x, lb.pad_y, lb.pad_x, lb.pad_y], np.float32)
    np.testing.assert_allclose(unletterbox_boxes(net, lb), src, atol=1e-3)


def raw_from(boxes_cls_score, n_anchors=50):
    """Build a (1, 52, n) raw tensor from [(cx, cy, w, h, class_id, score), ...]."""
    raw = np.zeros((1, 52, n_anchors), np.float32)
    for k, (cx, cy, w, h, c, s) in enumerate(boxes_cls_score):
        raw[0, :4, k] = (cx, cy, w, h)
        raw[0, 4 + c, k] = s
    return raw


def test_nms_is_class_aware():
    # A plate and a character with the same box must both survive; two overlapping plates collapse to one.
    raw = raw_from([(100, 100, 80, 20, C.PLATE_ID, 0.9), (100, 100, 80, 20, 5, 0.8), (102, 100, 80, 20, C.PLATE_ID, 0.7)])
    dets = decode(raw, conf=0.25, iou=0.5)[0]
    assert sorted((d.class_id, round(d.score, 2)) for d in dets) == [(5, 0.8), (C.PLATE_ID, 0.9)]


def test_per_class_thresholds():
    raw = raw_from([(100, 100, 80, 20, C.PLATE_ID, 0.38), (300, 100, 10, 20, 7, 0.36), (500, 100, 10, 20, 43, 0.45)])
    dets = decode(raw, conf=0.25, class_thresholds=default_thresholds())[0]
    assert [d.class_id for d in dets] == [7]  # plate < 0.40 and Gaf (synthetic-only) < 0.50 are dropped


def test_score_vector_kept():
    raw = raw_from([(100, 100, 10, 20, 2, 0.6)])
    raw[0, 4 + 3, 0] = 0.5  # runner-up ۳ for constrained decoding
    d = decode(raw)[0][0]
    assert d.class_id == 2 and d.scores.shape == (48,) and d.scores[3] == pytest.approx(0.5)


def test_nms_order_and_threshold():
    boxes = np.array([[0, 0, 10, 10], [1, 0, 11, 10], [20, 20, 30, 30]], np.float32)
    keep = nms(boxes, np.array([0.5, 0.9, 0.4], np.float32), 0.5)
    assert keep.tolist() == [1, 2]
