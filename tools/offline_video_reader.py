#!/usr/bin/env python3
"""Offline reference for M4: read a synthetic test video frame by frame with the same engine and the reader
library, vote per clip, and write {image: voted plate_string_latin}. Runs in the DeepStream image.

    deepstream/run.sh python3 tools/offline_video_reader.py --engine engine_cache/<name>.engine \
        --video tests/data/private/videos/test_h264.mp4 --out tests/data/private/videos/test_h264.offline.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "reader"), str(REPO / "tools")]

from lpr_reader.decode import decode, default_thresholds  # noqa: E402
from lpr_reader.preprocess import letterbox_bgr, to_tensor  # noqa: E402
from lpr_reader.reader import read_frame  # noqa: E402
from lpr_reader.voting import TrackVoter  # noqa: E402
from trt_runner import TrtRunner  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pad", type=int, default=0, help="letterbox pad (0 = DeepStream)")
    a = ap.parse_args(argv)
    side = json.loads(a.video.with_suffix(".json").read_text())
    clip_of = {}
    for k, c in enumerate(side["clips"]):
        for f in range(c["first_frame"], c["last_frame"] + 1):
            clip_of[f] = k
    run = TrtRunner(a.engine)
    voters = {k: TrackVoter(k) for k in range(len(side["clips"]))}
    cap = cv2.VideoCapture(str(a.video))
    th = default_thresholds()
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        k = clip_of.get(n)
        if k is not None:
            img, lb = letterbox_bgr(frame, pad_value=a.pad)
            dets = decode(run(to_tensor(img)[None]), [lb], conf=0.25, class_thresholds=th)[0]
            reads = read_frame(dets)
            if reads:
                r = max(reads, key=lambda r: r.width)
                voters[k].add(r, t=n / side["fps"], width_px=r.width * 960 / max(frame.shape[:2]))
        n += 1
    res = {side["clips"][k]["image"]: (v.result().plate_string_latin if v.result() else "") for k, v in voters.items()}
    a.out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    good = sum(res[c["image"]] == c["gt_string_latin"] for c in side["clips"])
    print(f"{n} frames decoded; offline voted reads correct: {good}/{len(side['clips'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
