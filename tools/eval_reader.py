#!/usr/bin/env python3
"""Plate-reading accuracy of reader + detections on agent_testset_v2 (ground truth: manifest.json).

    python tools/eval_reader.py --cache tests/data/private/cache/v2_onnx_cpu.jsonl --name "v2 ONNX CPU FP32"
    python tools/eval_reader.py --oracle --name "GT labels"          # reader rules alone on the labelled boxes

Each ground-truth plate is matched to a read (plate IoU >= 0.5) and judged by its type:
  * standard 8-character plates (``standard_8_chars``): ``plate_string_latin == gt_string_latin`` (exact string);
  * free-zone plates (``rows_left_to_right``): number equals the row text, and zone equals ``zone_label``;
  * transit main plates: number equals the generator code and ``expiry`` equals the generator expiry;
  * protocol main plates: digits equal the generator code;
  * any other plate: the character sequence equals ``chars_left_to_right``.
Real and synthetic images are reported separately (synthetic results are optimistic).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "reader"))

from lpr_reader import classes as C  # noqa: E402
from lpr_reader.decode import iou_matrix  # noqa: E402
from lpr_reader.reader import read_frame  # noqa: E402

DEFAULT_SET = REPO / "tests/data/private/agent_testset_v2"


def oracle_dets(entry, set_dir: Path):
    """Ground-truth label boxes as detections with one-hot scores of 1.0."""
    out = []
    for line in (set_dir / entry["label_file"]).read_text().splitlines():
        if not line.strip():
            continue
        c, x, y, w, h = line.split()
        W, H = entry["width"], entry["height"]
        x, y, w, h = float(x) * W, float(y) * H, float(w) * W, float(h) * H
        scores = np.zeros(C.NUM_CLASSES, np.float32)
        scores[int(c)] = 1.0
        out.append(SimpleNamespace(box=[x - w / 2, y - h / 2, x + w / 2, y + h / 2], class_id=int(c), score=1.0,
                                   scores=scores))
    return out


def cached_dets(rec):
    return [SimpleNamespace(box=d["box"], class_id=d["cls"], score=d["score"], scores=np.array(d["scores"], np.float32))
            for d in rec["dets"]]


def judge(entry, k, gt, read):
    """-> (kind, correct: bool, detail)."""
    gen = entry.get("generator") or {}
    main = k == 0
    if read is None:
        kind = "standard8" if gt["standard_8_chars"] else "other"
        return kind, False, "plate not detected"
    if gt["standard_8_chars"]:
        return "standard8", read.plate_string_latin == gt["gt_string_latin"], read.plate_string_latin
    if gt.get("rows_left_to_right"):
        want = gt["rows_left_to_right"][0].replace(" ", "")
        ok = read.plate_string_latin == want and (read.zone or None) == gt.get("zone_label")
        return "freezone", ok, f"{read.plate_string_latin} zone={read.zone} (want {want} zone={gt.get('zone_label')})"
    if main and entry["plate_type"] == "transit" and gen.get("code"):
        code = gen["code"]
        want = f"{code[0:2]} Gaf {code[3:6]} | {code[6:8]}"
        ok = read.plate_string_latin == want and read.expiry == gen.get("expiry")
        return "transit", ok, f"{read.plate_string_latin} exp={read.expiry} (want {want} exp={gen.get('expiry')})"
    if main and entry["plate_type"] == "protocol" and gen.get("code"):
        got = read.plate_string_latin.replace(" ", "")
        return "protocol", got == gen["code"], got
    seq = [c.name for c in sorted(read.characters, key=lambda c: c.box[0])]
    return "other", seq == gt["chars_left_to_right"], " ".join(seq)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--cache", type=Path)
    src.add_argument("--oracle", action="store_true")
    ap.add_argument("--set", type=Path, default=DEFAULT_SET)
    ap.add_argument("--name", default="")
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--errors", type=int, default=0, help="print up to N wrong reads")
    a = ap.parse_args(argv)

    manifest = json.loads((a.set / "manifest.json").read_text(encoding="utf-8"))
    recs = {}
    if a.cache:
        recs = {r["file"]: r for r in map(json.loads, a.cache.read_text().splitlines()) if r}
    stats = defaultdict(lambda: [0, 0])  # key -> [correct, total]
    errors, n_images, infer_ms = [], 0, []
    for e in manifest:
        if a.cache and e["file"] not in recs:
            continue
        n_images += 1
        dets = oracle_dets(e, a.set) if a.oracle else cached_dets(recs[e["file"]])
        if a.cache:
            infer_ms.append(recs[e["file"]].get("infer_ms", 0))
        reads = read_frame(dets)
        real = not e["file"].startswith("images/synthetic")
        used = set()
        for k, gt in enumerate(e["plates"]):
            best, best_iou = None, 0.5
            for j, r in enumerate(reads):
                if j in used:
                    continue
                iou = float(iou_matrix(gt["plate_xyxy"], r.plate_bbox)[0, 0])
                if iou >= best_iou:
                    best, best_iou = j, iou
            read = reads[best] if best is not None else None
            if best is not None:
                used.add(best)
            kind, ok, detail = judge(e, k, gt, read)
            split = "real" if real else "synthetic"
            group = e["group"].split(":")[0] if not real else e["group"]
            for key in [(split, "all", kind), (split, "group", group, kind), (split, "type", e["plate_type"], kind),
                        (split, "detected", kind)]:
                if key[1] == "detected":
                    stats[key][0] += read is not None
                else:
                    stats[key][0] += ok
                stats[key][1] += 1
            if not ok:
                errors.append((e["file"], kind, gt.get("gt_string_latin") or gt["chars_left_to_right"], detail))

    def pct(c, t):
        return f"{100.0 * c / t:.1f} % ({c}/{t})" if t else "n/a"

    print(f"# {a.name or (a.cache.name if a.cache else 'oracle')}: {n_images} images"
          + (f", mean inference {np.mean(infer_ms):.0f} ms/img" if infer_ms else ""))
    for split in ("real", "synthetic"):
        print(f"\n## {split}")
        for kind in ("standard8", "freezone", "transit", "protocol", "other"):
            if (split, "all", kind) in stats:
                c, t = stats[(split, "all", kind)]
                d = stats[(split, "detected", kind)]
                print(f"  {kind:10s} exact {pct(c, t):22s} plate detected {pct(*d)}")
        for dim in ("group", "type"):
            rows = sorted(k for k in stats if k[0] == split and k[1] == dim)
            print(f"  by {dim}: " + "; ".join(f"{k[2]}/{k[3]} {pct(*stats[k])}" for k in rows))
    for err in errors[: a.errors]:
        print("  WRONG", err)
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps({"name": a.name, "images": n_images,
                                          "mean_infer_ms": float(np.mean(infer_ms)) if infer_ms else None,
                                          "stats": {"|".join(k): v for k, v in sorted(stats.items())}},
                                         indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
