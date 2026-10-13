#!/usr/bin/env python3
"""Synthesize test videos from labelled test images (run in the DeepStream image: hardware H.264/H.265 encoder).

    python3 tools/make_test_video.py --out tests/data/private/videos/test_h264.mp4 --codec h264 --n 6
    python3 tools/make_test_video.py --out tests/data/private/videos/test_h265.mp4 --codec h265 --n 6 --size 2560x1440

Each clip takes one real test image with a single standard plate (known ground truth in manifest.json) and moves a
virtual camera window over it: the window shrinks and drifts, so the plate grows and moves across the frame like an
approaching car (``--seconds`` per clip, ``--fps``). Clips are separated by a short black gap so each plate forms its
own track. A JSON sidecar lists, per clip, the image, the ground-truth string and the frame range.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
SET = REPO / "tests/data/private/agent_testset_v2"


def pick_images(n: int, min_width_px: float):
    manifest = json.loads((SET / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for e in manifest:
        if e["group"] not in ("real_day", "real_night") or len(e["plates"]) != 1:
            continue
        p = e["plates"][0]
        if p["standard_8_chars"] and p["width_px"] >= min_width_px and e["width"] >= 1000:
            out.append(e)
    step = max(1, len(out) // n)
    return out[::step][:n]


def main(argv=None) -> int:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--codec", choices=["h264", "h265"], default="h264")
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--gap", type=float, default=1.0, help="black seconds between clips")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--min-plate-px", type=float, default=110)
    a = ap.parse_args(argv)
    W, H = (int(v) for v in a.size.split("x"))
    Gst.init(None)
    enc = "nvv4l2h264enc" if a.codec == "h264" else "nvv4l2h265enc"
    parse = "h264parse" if a.codec == "h264" else "h265parse"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    pipe = Gst.parse_launch(
        f"appsrc name=src is-live=false format=time caps=video/x-raw,format=BGR,width={W},height={H},"
        f"framerate={a.fps}/1 ! videoconvert ! video/x-raw,format=I420 ! nvvideoconvert ! "
        f"video/x-raw(memory:NVMM),format=I420 ! {enc} bitrate=8000000 iframeinterval={a.fps} insert-sps-pps=1 ! "
        f"{parse} ! qtmux ! filesink location={a.out}")
    src = pipe.get_by_name("src")
    pipe.set_state(Gst.State.PLAYING)
    frame_no, clips = 0, []

    def push(img):
        nonlocal frame_no
        buf = Gst.Buffer.new_wrapped(img.tobytes())
        buf.pts = frame_no * Gst.SECOND // a.fps
        buf.duration = Gst.SECOND // a.fps
        src.emit("push-buffer", buf)
        frame_no += 1

    black = np.zeros((H, W, 3), np.uint8)
    for e in pick_images(a.n, a.min_plate_px):
        img = cv2.imread(str(SET / e["file"]))
        ih, iw = img.shape[:2]
        x1, y1, x2, y2 = e["plates"][0]["plate_xyxy"]
        pcx, pcy = (x1 + x2) / 2, (y1 + y2) / 2
        start = frame_no
        n = int(a.seconds * a.fps)
        for k in range(n):
            t = k / max(1, n - 1)
            # window: starts as the whole image (plate small), ends at ~55 % around the plate (plate large)
            scale = 1.0 - 0.45 * t
            ww, wh = iw * scale, ih * scale
            cx = iw / 2 + (pcx - iw / 2) * t
            cy = ih / 2 + (pcy - ih / 2) * t + (1 - t) * 0.05 * ih   # slight upward drift
            l = int(np.clip(cx - ww / 2, 0, iw - ww))
            tp = int(np.clip(cy - wh / 2, 0, ih - wh))
            crop = img[tp:tp + int(wh), l:l + int(ww)]
            frame = cv2.resize(crop, (W, H), interpolation=cv2.INTER_LINEAR)
            push(frame)
        clips.append({"image": e["file"], "gt_string_latin": e["plates"][0]["gt_string_latin"],
                      "first_frame": start, "last_frame": frame_no - 1})
        for _ in range(int(a.gap * a.fps)):
            push(black)
    src.emit("end-of-stream")
    bus = pipe.get_bus()
    msg = bus.timed_pop_filtered(Gst.CLOCK_TIME_NONE, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    pipe.set_state(Gst.State.NULL)
    if msg.type == Gst.MessageType.ERROR:
        print("encode failed:", msg.parse_error()[0].message)
        return 1
    side = a.out.with_suffix(".json")
    side.write_text(json.dumps({"video": a.out.name, "size": [W, H], "fps": a.fps, "codec": a.codec,
                                "frames": frame_no, "clips": clips}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {a.out} ({frame_no} frames, {len(clips)} clips) and {side.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
