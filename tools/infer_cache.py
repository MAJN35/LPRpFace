#!/usr/bin/env python3
"""Run a model over the test-set manifest once and cache the decoded detections (with 48-score vectors) as JSONL.

    python tools/infer_cache.py --backend onnx --model models/v2/<stem>.onnx --out tests/data/private/cache/v2_onnx.jsonl
    python tools/infer_cache.py --backend trt  --model <engine> --out tests/data/private/cache/v2_trt_fp16.jsonl  (M3)

Detections are stored at a low candidate threshold (``--conf``, default 0.10) without per-class thresholds, so the
reader and the evaluation can apply thresholds later without re-running inference (class-aware NMS makes
thresholding after NMS equivalent). The run resumes: images already in the output file are skipped.
The cache lives under the git-ignored tests/data/private/ because it is derived from private images.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "reader"))

from lpr_reader.decode import decode  # noqa: E402
from lpr_reader.preprocess import PAD_ULTRALYTICS, letterbox_bgr, to_tensor  # noqa: E402

DEFAULT_SET = REPO / "tests/data/private/agent_testset_v2"


class OnnxBackend:
    def __init__(self, path: Path, threads: int = 0):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.enable_cpu_mem_arena = False
        if threads:
            so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.max_batch = 1 if isinstance(self.sess.get_inputs()[0].shape[0], int) else 8

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return self.sess.run(None, {"images": x})[0]


def make_backend(kind: str, model: Path, threads: int):
    if kind == "onnx":
        return OnnxBackend(model, threads)
    if kind == "trt":
        sys.path.insert(0, str(REPO / "tools"))
        from trt_runner import TrtRunner  # M3; needs TensorRT (DeepStream container)

        return TrtRunner(model)
    raise ValueError(kind)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["onnx", "trt"], required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--set", type=Path, default=DEFAULT_SET, help="test-set folder with manifest.json")
    ap.add_argument("--conf", type=float, default=0.10)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--pad", type=int, default=PAD_ULTRALYTICS, help="letterbox pad value (114 Ultralytics, 0 DeepStream)")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--threads", type=int, default=0)
    a = ap.parse_args(argv)

    import cv2

    manifest = json.loads((a.set / "manifest.json").read_text(encoding="utf-8"))
    files = [m["file"] for m in manifest][: a.limit or None]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if a.out.exists():
        done = {json.loads(line)["file"] for line in a.out.read_text().splitlines() if line.strip()}
    todo = [f for f in files if f not in done]
    print(f"{len(files)} images, {len(done)} cached, {len(todo)} to run; backend {a.backend} {a.model.name} "
          f"batch {a.batch} pad {a.pad}", flush=True)
    backend = make_backend(a.backend, a.model, a.threads)
    t0, n = time.time(), 0
    with open(a.out, "a") as fout:
        for s in range(0, len(todo), a.batch):
            chunk = todo[s:s + a.batch]
            tensors, lbs, sizes = [], [], []
            for f in chunk:
                img = cv2.imread(str(a.set / f))
                lbimg, lb = letterbox_bgr(img, pad_value=a.pad)
                tensors.append(to_tensor(lbimg))
                lbs.append(lb)
                sizes.append(img.shape[1::-1])
            t = time.time()
            raw = backend(np.stack(tensors))
            dt = (time.time() - t) / len(chunk)
            for f, (w, h), dets in zip(chunk, sizes, decode(raw, lbs, conf=a.conf, iou=a.iou)):
                rec = {"file": f, "width": int(w), "height": int(h), "infer_ms": round(dt * 1000, 1),
                       "dets": [{"box": [round(float(v), 2) for v in d.box], "cls": d.class_id,
                                 "score": round(d.score, 5), "scores": [round(float(v), 4) for v in d.scores]}
                                for d in dets]}
                fout.write(json.dumps(rec) + "\n")
            fout.flush()
            n += len(chunk)
            if n % 20 < len(chunk) or n == len(todo):
                el = time.time() - t0
                print(f"{n}/{len(todo)} images, {el / n:.1f} s/img, ETA {el / n * (len(todo) - n) / 60:.0f} min",
                      flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
