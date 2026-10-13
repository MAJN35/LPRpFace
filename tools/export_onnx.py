#!/usr/bin/env python3
"""Re-export the delivered .pt to ONNX with the A.3 method, with a fixed batch N or a dynamic batch axis.

    python tools/export_onnx.py models/v2 --dynamic-batch      # -> models/v2/export/<stem>_dynbatch.onnx
    python tools/export_onnx.py models/v2 --batch 4            # -> models/v2/export/<stem>_b4.onnx

A.3 method: Ultralytics 8.3.141 ``export(format="onnx", imgsz=960, opset=17, simplify=True, dynamic=False)``,
classic TorchScript exporter (``dynamo=False``), onnxslim. Two controlled deviations, both applied by wrapping
``torch.onnx.export``:
  * ``dynamo=False`` is forced (torch >= 2.9 defaults to the dynamo exporter; Ultralytics 8.3.141 does not pass it).
  * ``--dynamic-batch`` marks only axis 0 of ``images`` and ``output0`` as dynamic. Ultralytics' own ``dynamic=True``
    would also make height, width and the anchor count dynamic, which nvinfer does not need.
The weights are never modified: the .pt is checksummed (against SHA256SUMS) before and after, and the export runs
on a temporary copy so Ultralytics cannot write next to the delivered files. Versions, the exact command and the
output checksum go to ``<output>.json``.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("YOLO_AUTOINSTALL", "false")  # never pip-install at runtime
os.environ.setdefault("YOLO_OFFLINE", "true")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_model import EXIT_SUMS, check_sums, sha256  # noqa: E402

IMGSZ, OPSET = 960, 17


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model_dir", type=Path)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--batch", type=int, help="fixed batch size N")
    g.add_argument("--dynamic-batch", action="store_true", help="dynamic batch axis only")
    ap.add_argument("--out-dir", type=Path, help="default: <model_dir>/export")
    a = ap.parse_args(argv)

    errors, sums = check_sums(a.model_dir)
    if errors:
        print("\n".join(f"FAIL checksum: {e}" for e in errors))
        return EXIT_SUMS
    pts = sorted(a.model_dir.glob("*.pt"))
    if len(pts) != 1:
        print(f"FAIL: expected one .pt in {a.model_dir}, found {[p.name for p in pts]}")
        return 1
    pt = pts[0]
    pt_sha = sums[pt.name]

    import onnx
    import onnxslim
    import torch
    import ultralytics
    from ultralytics import YOLO

    tag = "dynbatch" if a.dynamic_batch else f"b{a.batch}"
    out_dir = a.out_dir or a.model_dir / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{pt.stem}_{tag}.onnx"

    orig_export = torch.onnx.export

    @functools.wraps(orig_export)
    def classic_export(*args, **kwargs):
        kwargs["dynamo"] = False
        if a.dynamic_batch:
            kwargs["dynamic_axes"] = {"images": {0: "batch"}, "output0": {0: "batch"}}
        return orig_export(*args, **kwargs)

    torch.onnx.export = classic_export
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            work_pt = Path(tmp) / pt.name
            shutil.copy2(pt, work_pt)
            model = YOLO(str(work_pt))
            f = model.export(format="onnx", imgsz=IMGSZ, opset=OPSET, simplify=True, dynamic=False,
                             batch=a.batch or 1, half=False, nms=False, device="cpu")
            shutil.move(str(f), out)
    finally:
        torch.onnx.export = orig_export
    seconds = time.time() - t0

    if sha256(pt) != pt_sha:
        print(f"FAIL: {pt} changed during export")
        return EXIT_SUMS
    m = onnx.load(str(out))
    dims = lambda vi: [d.dim_param or d.dim_value for d in vi.type.tensor_type.shape.dim]  # noqa: E731
    # The batch-only dynamic export leaves output0 dims 1 and 2 symbolic after slimming. Pin them to the sizes a
    # real run produces (52, 18900) so TensorRT/nvinfer see a static per-image output; nodes and weights unchanged.
    out_dims = m.graph.output[0].type.tensor_type.shape.dim
    if any(d.dim_param for d in list(out_dims)[1:]):
        import numpy as np
        import onnxruntime as ort

        n = 1 if a.dynamic_batch else a.batch
        sess = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
        shape = sess.run(None, {"images": np.zeros((n, 3, IMGSZ, IMGSZ), np.float32)})[0].shape
        del sess
        for d, size in list(zip(out_dims, shape))[1:]:
            d.ClearField("dim_param")
            d.dim_value = size
        onnx.checker.check_model(m)
        onnx.save(m, str(out))
        print(f"pinned output0 dims 1..2 to {list(shape[1:])} (measured with onnxruntime)")
    info = {
        "output": out.name,
        "output_sha256": sha256(out),
        "source_pt": pt.name,
        "source_pt_sha256": pt_sha,
        "batch": "dynamic" if a.dynamic_batch else a.batch,
        "input_shape": dims(m.graph.input[0]),
        "output_shape": dims(m.graph.output[0]),
        "opset": [o.version for o in m.opset_import if o.domain in ("", "ai.onnx")][0],
        "command": " ".join([Path(sys.argv[0]).as_posix()] + sys.argv[1:]),
        "method": f"YOLO(pt).export(format='onnx', imgsz={IMGSZ}, opset={OPSET}, simplify=True, dynamic=False, "
                  f"batch={a.batch or 1}, half=False, nms=False, device='cpu') with torch.onnx.export forced to "
                  "dynamo=False" + (" and dynamic_axes={images:{0:batch}, output0:{0:batch}}" if a.dynamic_batch else ""),
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "ultralytics": ultralytics.__version__, "onnx": onnx.__version__,
                     "onnxslim": onnxslim.__version__, "machine": platform.machine()},
        "export_seconds": round(seconds, 1),
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out.with_suffix(".json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
