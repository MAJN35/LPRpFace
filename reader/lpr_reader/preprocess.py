"""Letterbox preprocessing identical to Ultralytics 8.3.141 ``LetterBox(auto=False, center=True)`` for a square
network input, plus the inverse mapping (``scale_boxes``). The pad value is a parameter so the DeepStream variant
(nvinfer symmetric padding with 0) can be measured against Ultralytics' gray 114.
"""
from __future__ import annotations

from typing import NamedTuple, Tuple

import numpy as np

IMGSZ = 960
PAD_ULTRALYTICS = 114


class Letterbox(NamedTuple):
    gain: float  # network pixels per source pixel
    pad_x: int   # left padding in network pixels
    pad_y: int   # top padding in network pixels
    src_w: int
    src_h: int


def letterbox_params(src_w: int, src_h: int, imgsz: int = IMGSZ) -> Tuple[Letterbox, Tuple[int, int], Tuple[int, int, int, int]]:
    """Returns (geometry for the inverse mapping, resized (w, h), (top, bottom, left, right) borders)."""
    r = min(imgsz / src_h, imgsz / src_w)
    new_w, new_h = int(round(src_w * r)), int(round(src_h * r))
    dw, dh = (imgsz - new_w) / 2, (imgsz - new_h) / 2
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    # scale_boxes() recomputes the pad from the gain with the same rounding; use that form so both directions agree.
    pad_x = int(round((imgsz - src_w * r) / 2 - 0.1))
    pad_y = int(round((imgsz - src_h * r) / 2 - 0.1))
    return Letterbox(r, pad_x, pad_y, src_w, src_h), (new_w, new_h), (top, bottom, left, right)


def letterbox_bgr(img_bgr: np.ndarray, imgsz: int = IMGSZ, pad_value: int = PAD_ULTRALYTICS) -> Tuple[np.ndarray, Letterbox]:
    """BGR uint8 HxWx3 -> letterboxed BGR uint8 imgsz x imgsz x 3."""
    import cv2

    h, w = img_bgr.shape[:2]
    lb, (new_w, new_h), (top, bottom, left, right) = letterbox_params(w, h, imgsz)
    if (w, h) != (new_w, new_h):
        img_bgr = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    img_bgr = cv2.copyMakeBorder(img_bgr, top, bottom, left, right, cv2.BORDER_CONSTANT,
                                 value=(pad_value, pad_value, pad_value))
    return img_bgr, lb


def to_tensor(letterboxed_bgr: np.ndarray) -> np.ndarray:
    """Letterboxed BGR uint8 -> 3xHxW float32 RGB in [0, 1] (no mean/std), as the model expects."""
    rgb = letterboxed_bgr[:, :, ::-1].transpose(2, 0, 1)
    return np.ascontiguousarray(rgb, dtype=np.float32) / 255.0


def unletterbox_boxes(boxes_xyxy: np.ndarray, lb: Letterbox) -> np.ndarray:
    """Network-input xyxy -> source-image xyxy, clipped to the image (Ultralytics ``scale_boxes``)."""
    b = np.array(boxes_xyxy, dtype=np.float32, copy=True).reshape(-1, 4)
    b[:, [0, 2]] -= lb.pad_x
    b[:, [1, 3]] -= lb.pad_y
    b /= lb.gain
    b[:, [0, 2]] = b[:, [0, 2]].clip(0, lb.src_w)
    b[:, [1, 3]] = b[:, [1, 3]].clip(0, lb.src_h)
    return b
