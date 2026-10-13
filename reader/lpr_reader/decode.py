"""Numpy decoder for the raw model output ``(B, 52, 18900)``: per anchor cx, cy, w, h (network-input pixels) and 48
sigmoid class scores, no NMS inside the graph.

``decode`` follows Ultralytics 8.3.141 ``non_max_suppression`` (one label per anchor = argmax, ``score > conf``,
top ``max_nms`` by score, class-aware greedy NMS, ``max_det``), with per-class thresholds added on top. Each detection
keeps the full 48-score vector of its anchor for constrained decoding in the reader.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from . import classes as C
from .preprocess import Letterbox, unletterbox_boxes

# AGENTS.md A.7: plate 0.40, characters 0.35, face 0.35, synthetic-only classes 0.50.
SYNTHETIC_ONLY_IDS = (42, 43, 44, 45, 46, 47, 32, C.FREEZONE_ID) + C.FZ_ZONE_IDS


def default_thresholds() -> np.ndarray:
    t = np.full(C.NUM_CLASSES, 0.35, dtype=np.float32)
    t[C.PLATE_ID] = 0.40
    t[C.FACE_ID] = 0.35
    t[list(SYNTHETIC_ONLY_IDS)] = 0.50
    return t


@dataclass
class Detection:
    box: np.ndarray            # xyxy in source-image pixels (network pixels if no letterbox was given)
    class_id: int
    score: float
    scores: np.ndarray = field(repr=False)  # all 48 class scores of the anchor

    @property
    def name(self) -> str:
        return C.CLASS_NAMES[self.class_id]


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU of xyxy boxes, shapes (N, 4) x (M, 4) -> (N, M)."""
    a = np.asarray(a, np.float32).reshape(-1, 4)
    b = np.asarray(b, np.float32).reshape(-1, 4)
    tl = np.maximum(a[:, None, :2], b[None, :, :2])
    br = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.prod(np.clip(br - tl, 0, None), axis=2)
    area_a = np.prod(a[:, 2:] - a[:, :2], axis=1)
    area_b = np.prod(b[:, 2:] - b[:, :2], axis=1)
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> np.ndarray:
    """Greedy NMS (same result as ``torchvision.ops.nms``): indices kept, by descending score."""
    order = np.argsort(-scores, kind="stable")
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        ious = iou_matrix(boxes[i:i + 1], boxes[order[1:]])[0]
        order = order[1:][ious <= iou_thres]
    return np.array(keep, dtype=np.int64)


def decode(
    raw: np.ndarray,
    letterboxes: Optional[Sequence[Optional[Letterbox]]] = None,
    conf: float = 0.25,
    class_thresholds: Optional[np.ndarray] = None,
    iou: float = 0.5,
    max_det: int = 300,
    max_nms: int = 30000,
    max_wh: float = 7680.0,
) -> List[List[Detection]]:
    """Decode a batch. ``conf`` is the global candidate threshold (Ultralytics' ``conf``); ``class_thresholds``
    (48 values, e.g. ``default_thresholds()``) is applied per class after it; ``None`` disables it."""
    raw = np.asarray(raw, dtype=np.float32)
    if raw.ndim == 2:
        raw = raw[None]
    if raw.shape[1] != 4 + C.NUM_CLASSES:
        raise ValueError(f"expected (B, {4 + C.NUM_CLASSES}, N), got {raw.shape}")
    results = []
    for b in range(raw.shape[0]):
        p = raw[b].T  # (N, 52)
        cls_scores = p[:, 4:]
        cls = cls_scores.argmax(1)
        score = cls_scores[np.arange(len(cls)), cls]
        keep = score > conf
        if class_thresholds is not None:
            keep &= score >= np.asarray(class_thresholds, np.float32)[cls]
        idx = np.nonzero(keep)[0]
        if idx.size > max_nms:
            idx = idx[np.argsort(-score[idx], kind="stable")[:max_nms]]
        cxcywh = p[idx, :4]
        boxes = np.concatenate([cxcywh[:, :2] - cxcywh[:, 2:] / 2, cxcywh[:, :2] + cxcywh[:, 2:] / 2], axis=1)
        offset = cls[idx, None].astype(np.float32) * max_wh  # class-aware: plates never suppress characters
        k = nms(boxes + offset, score[idx], iou)[:max_det]
        idx, boxes = idx[k], boxes[k]
        lb = letterboxes[b] if letterboxes is not None else None
        if lb is not None:
            boxes = unletterbox_boxes(boxes, lb)
        results.append([Detection(boxes[j], int(cls[i]), float(score[i]), cls_scores[i].copy())
                        for j, i in enumerate(idx)])
    return results


def summarize(dets: List[Detection]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for d in dets:
        counts[d.name] = counts.get(d.name, 0) + 1
    return counts
