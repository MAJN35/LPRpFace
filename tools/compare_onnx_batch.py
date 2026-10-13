#!/usr/bin/env python3
"""Check that a batched ONNX export gives the same detections per image as the delivered batch-1 ONNX (CPU).

    python tools/compare_onnx_batch.py --ref models/v2/<stem>.onnx --cand models/v2/export/<stem>_dynbatch.onnx \
        --images 'tests/data/private/agent_testset_v2/images/test/*.jpg' --n 16 --batch-sizes 1 2 4 8

Both models see identical letterboxed inputs (Ultralytics geometry, pad 114). For every image the candidate's
output is taken from a batch that mixes it with other images (dynamic batch: each size in --batch-sizes; fixed
batch N: chunks of N, the last chunk padded by repeating images). Detections are decoded with lpr_reader.decode
(conf 0.25, IoU 0.5, no per-class thresholds) and matched one-to-one: same class, IoU >= --min-iou,
|score difference| <= --max-score-diff. Exit 0 only if every image has identical detection sets for every size.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "reader"))

from lpr_reader.decode import decode, iou_matrix  # noqa: E402
from lpr_reader.preprocess import letterbox_bgr, to_tensor  # noqa: E402


def match(ref, cand, min_iou, max_score_diff):
    """Greedy one-to-one matching of two detection lists. Returns (matched, unmatched_ref, unmatched_cand)."""
    used, matched = set(), 0
    for r in sorted(ref, key=lambda d: -d.score):
        best, best_iou = None, min_iou
        for j, c in enumerate(cand):
            if j in used or c.class_id != r.class_id or abs(c.score - r.score) > max_score_diff:
                continue
            iou = float(iou_matrix(r.box, c.box)[0, 0])
            if iou >= best_iou:
                best, best_iou = j, iou
        if best is not None:
            used.add(best)
            matched += 1
    return matched, len(ref) - matched, len(cand) - matched


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", type=Path, required=True)
    ap.add_argument("--cand", type=Path, required=True)
    ap.add_argument("--images", required=True, help="glob")
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--batch-sizes", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--min-iou", type=float, default=0.99)
    ap.add_argument("--max-score-diff", type=float, default=1e-3)
    ap.add_argument("--threads", type=int, default=0, help="onnxruntime intra-op threads (0 = default)")
    ap.add_argument("--json-out", type=Path)
    a = ap.parse_args(argv)

    import cv2
    import onnxruntime as ort

    files = sorted(glob.glob(a.images))[: a.n]
    if not files:
        print(f"FAIL: no images match {a.images}")
        return 1
    tensors, lbs = [], []
    for f in files:
        img = cv2.imread(f)
        if img is None:
            print(f"FAIL: cannot read {f}")
            return 1
        lbimg, lb = letterbox_bgr(img)
        tensors.append(to_tensor(lbimg))
        lbs.append(lb)
    x = np.stack(tensors)

    so = ort.SessionOptions()
    if a.threads:
        so.intra_op_num_threads = a.threads
    ref = ort.InferenceSession(str(a.ref), so, providers=["CPUExecutionProvider"])
    cand = ort.InferenceSession(str(a.cand), so, providers=["CPUExecutionProvider"])
    cin = cand.get_inputs()[0]
    fixed = cin.shape[0] if isinstance(cin.shape[0], int) else None
    sizes = [fixed] if fixed else a.batch_sizes
    print(f"ref {a.ref.name} input {ref.get_inputs()[0].shape}; cand {a.cand.name} input {cin.shape}; "
          f"{len(files)} images; batch sizes {sizes}")

    ref_out = np.concatenate([ref.run(None, {"images": x[i:i + 1]})[0] for i in range(len(x))])
    ref_dets = decode(ref_out, lbs, conf=0.25, iou=0.5)
    n_ref = sum(len(d) for d in ref_dets)

    report, ok = {"images": len(files), "ref_detections": n_ref, "sizes": {}}, True
    for bs in sizes:
        outs = []
        for s in range(0, len(x), bs):
            chunk = x[s:s + bs]
            real = len(chunk)
            if fixed and real < bs:  # pad a fixed-batch chunk by repeating images
                chunk = np.concatenate([chunk, x[: bs - real]])
            outs.append(cand.run(None, {"images": chunk})[0][:real])
        cand_out = np.concatenate(outs)
        max_abs = float(np.abs(cand_out - ref_out).max())
        cand_dets = decode(cand_out, lbs, conf=0.25, iou=0.5)
        m = ur = uc = bad_imgs = 0
        for rd, cd in zip(ref_dets, cand_dets):
            mi, ri, ci = match(rd, cd, a.min_iou, a.max_score_diff)
            m, ur, uc = m + mi, ur + ri, uc + ci
            bad_imgs += bool(ri or ci)
        same = ur == 0 and uc == 0
        ok &= same
        report["sizes"][bs] = {"max_abs_output_diff": max_abs, "matched": m, "unmatched_ref": ur,
                               "unmatched_cand": uc, "images_with_differences": bad_imgs, "identical": same}
        print(f"batch {bs}: max |Δ output| {max_abs:.3g}; detections matched {m}/{n_ref}, "
              f"unmatched ref {ur}, unmatched cand {uc}, images with differences {bad_imgs} -> "
              f"{'SAME' if same else 'DIFFERENT'}")
    if a.json_out:
        a.json_out.write_text(json.dumps(report, indent=2) + "\n")
    print("RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
