#!/usr/bin/env python3
"""Detection parity: Ultralytics on the .pt (reference) vs onnxruntime + lpr_reader.decode, or vs any detection
cache (e.g. TensorRT from tools/infer_cache.py).

    python tools/parity.py --model-dir models/v2 --sample 24 --report docs/parity_cpu.md          # .pt vs ONNX CPU
    python tools/parity.py --model-dir models/v2 --cand-cache tests/data/private/cache/v2_trt_fp16_b1.jsonl ...

Reference: ``YOLO(pt).predict(imgsz=960, conf=0.25, iou=0.5, rect=False, device='cpu')``. ``rect=False`` gives the
same full 960x960 letterbox (pad 114) as the ONNX/TensorRT path; Ultralytics' default rect=True would pad only to
a stride-32 rectangle. Reference detections are cached in tests/data/private/cache/<ver>_pt_ref.jsonl, so later
comparisons (M3) need no torch. A reference detection is matched when a candidate box has the same class and
IoU >= 0.9 (one-to-one, greedy by score). Class shifts = reference boxes whose best IoU >= 0.9 partner has
another class.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("YOLO_OFFLINE", "true")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "reader"))

from lpr_reader import classes as C  # noqa: E402
from lpr_reader.decode import decode, iou_matrix  # noqa: E402
from lpr_reader.preprocess import letterbox_bgr, to_tensor  # noqa: E402

SET = REPO / "tests/data/private/agent_testset_v2"
CACHE = REPO / "tests/data/private/cache"
CONF, IOU = 0.25, 0.5


def stratified_sample(manifest, n):
    """Deterministic sample spread over groups: round-robin over groups, evenly spaced inside each group."""
    groups = defaultdict(list)
    for e in manifest:
        groups[e["group"].split(":")[0] if e["group"].startswith("synthetic") else e["group"]].append(e["file"])
    order, i = [], 0
    names = sorted(groups)
    while len(order) < n and any(groups.values()):
        g = groups[names[i % len(names)]]
        if g:
            order.append(g.pop(len(g) // 2 if len(order) % 2 else 0))
        i += 1
    return order


def load_cache(path: Path):
    if not path.exists():
        return {}
    return {r["file"]: r for r in map(json.loads, path.read_text().splitlines()) if r}


def run_reference(pt: Path, files, cache_path: Path):
    cache = load_cache(cache_path)
    todo = [f for f in files if f not in cache]
    if todo:
        from ultralytics import YOLO

        model = YOLO(str(pt))
        with open(cache_path, "a") as fout:
            for k, f in enumerate(todo):
                r = model.predict(str(SET / f), imgsz=960, conf=CONF, iou=IOU, rect=False, device="cpu",
                                  verbose=False, max_det=300)[0]
                b = r.boxes
                rec = {"file": f, "dets": [{"box": [round(float(v), 2) for v in xyxy], "cls": int(c),
                                             "score": round(float(s), 5)}
                                            for xyxy, c, s in zip(b.xyxy.tolist(), b.cls.tolist(), b.conf.tolist())]}
                fout.write(json.dumps(rec) + "\n")
                fout.flush()
                cache[f] = rec
                print(f"ref {k + 1}/{len(todo)} {f}: {len(rec['dets'])} dets", flush=True)
        del model
        gc.collect()
    return cache


def run_onnx(onnx_path: Path, files):
    import cv2
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.enable_cpu_mem_arena = False
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    out = {}
    for k, f in enumerate(files):
        img, lb = letterbox_bgr(cv2.imread(str(SET / f)))
        raw = sess.run(None, {"images": to_tensor(img)[None]})[0]
        dets = decode(raw, [lb], conf=CONF, iou=IOU)[0]
        out[f] = {"file": f, "dets": [{"box": d.box.tolist(), "cls": d.class_id, "score": d.score} for d in dets]}
        print(f"onnx {k + 1}/{len(files)} {f}: {len(dets)} dets", flush=True)
    return out


def compare(ref, cand, files):
    tot = matched = 0
    per_class = defaultdict(lambda: [0, 0])
    shifts, extra, score_diffs = Counter(), 0, []
    for f in files:
        rd = [d for d in ref[f]["dets"] if d["score"] > CONF]
        cd = [d for d in cand[f]["dets"] if d["score"] > CONF]
        used = set()
        for r in sorted(rd, key=lambda d: -d["score"]):
            tot += 1
            per_class[r["cls"]][1] += 1
            best, best_iou, best_any, best_any_iou = None, 0.9, None, 0.9
            for j, c in enumerate(cd):
                if j in used:
                    continue
                iou = float(iou_matrix(r["box"], c["box"])[0, 0])
                if c["cls"] == r["cls"] and iou >= best_iou:
                    best, best_iou = j, iou
                if iou >= best_any_iou:
                    best_any, best_any_iou = j, iou
            if best is not None:
                used.add(best)
                matched += 1
                per_class[r["cls"]][0] += 1
                score_diffs.append(abs(cd[best]["score"] - r["score"]))
            elif best_any is not None:
                shifts[(C.CLASS_NAMES[r["cls"]], C.CLASS_NAMES[cd[best_any]["cls"]])] += 1
        extra += len(cd) - len(used)
    return {"ref_dets": tot, "matched": matched, "rate": matched / tot if tot else 0.0, "extra_cand": extra,
            "class_shifts": {f"{a}->{b}": n for (a, b), n in shifts.most_common()},
            "max_score_diff": max(score_diffs) if score_diffs else 0.0,
            "mean_score_diff": float(np.mean(score_diffs)) if score_diffs else 0.0,
            "unmatched_by_class": {C.CLASS_NAMES[k]: v[1] - v[0] for k, v in sorted(per_class.items()) if v[1] > v[0]}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--sample", type=int, default=24)
    ap.add_argument("--cand-cache", type=Path, help="compare against this detection cache instead of ONNX CPU")
    ap.add_argument("--cand-name", default="onnxruntime CPU FP32 + lpr_reader.decode")
    ap.add_argument("--ref-cache", type=Path, help="reference = this detection cache (e.g. the static ONNX on CPU) instead "
                    "of Ultralytics on the .pt; needs --cand-cache; compares the images both caches contain")
    ap.add_argument("--ref-name", default="Ultralytics .pt")
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--min-rate", type=float, default=0.98)
    a = ap.parse_args(argv)
    ver = a.model_dir.name
    manifest = json.loads((SET / "manifest.json").read_text(encoding="utf-8"))
    CACHE.mkdir(parents=True, exist_ok=True)
    if a.cand_cache:
        cand = load_cache(a.cand_cache)
        files = [f for f in stratified_sample(manifest, a.sample) if f in cand]
    else:
        files = stratified_sample(manifest, a.sample)
    if a.ref_cache:
        if not a.cand_cache:
            ap.error("--ref-cache needs --cand-cache")
        ref = load_cache(a.ref_cache)
        files = sorted(set(ref) & set(cand))
    else:
        ref = run_reference(next(a.model_dir.glob("*.pt")), files, CACHE / f"{ver}_pt_ref.jsonl")
    if not a.cand_cache:
        cand = run_onnx(next(a.model_dir.glob("*.onnx")), files)
    res = compare(ref, cand, files)
    res.update({"model": ver, "images": len(files), "files": files, "candidate": a.cand_name,
                "reference": a.ref_name if a.ref_cache else "Ultralytics .pt"})
    ok = res["rate"] >= a.min_rate
    print(json.dumps({k: v for k, v in res.items() if k != "files"}, indent=1))
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({100 * res['rate']:.2f} % matched, threshold {100 * a.min_rate:.0f} %)")
    if a.json_out:
        a.json_out.write_text(json.dumps(res, indent=1) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
