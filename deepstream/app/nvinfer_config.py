"""Writes the nvinfer config for a model version/engine (AGENTS.md A.7 preprocessing and thresholds)."""
from __future__ import annotations

from pathlib import Path

from lpr_reader.decode import default_thresholds


def write(path: str, engine: str, labels: str, parser_lib: str, batch: int, precision: str = "fp16",
          interval: int = 0) -> str:
    th = default_thresholds()
    mode = {"fp32": 0, "int8": 1, "fp16": 2}[precision]
    lines = [
        "[property]",
        "gpu-id=0",
        "net-scale-factor=0.00392156862745098",   # pixels / 255, no mean/std (A.3)
        "model-color-format=0",                   # RGB
        f"model-engine-file={engine}",
        f"labelfile-path={labels}",
        "infer-dims=3;960;960",
        f"batch-size={batch}",
        f"network-mode={mode}",
        "num-detected-classes=48",
        f"interval={interval}",
        "gie-unique-id=1",
        "process-mode=1",
        "maintain-aspect-ratio=1",                # letterbox like Ultralytics (pad value differs: 0 vs 114, see M3)
        "symmetric-padding=1",
        "network-type=3",                         # boxes + per-object 'mask' = the 48 class scores
        "output-instance-mask=1",
        "cluster-mode=4",                         # NMS is done in the parser (class-aware)
        "output-blob-names=output0",
        f"custom-lib-path={parser_lib}",
        "parse-bbox-instance-mask-func-name=NvDsInferParseYolo12Lpr",
        "",
        "[class-attrs-all]",
        "pre-cluster-threshold=0.35",
        "topk=300",
    ]
    for cid, t in enumerate(th):
        if abs(float(t) - 0.35) > 1e-6:
            lines += ["", f"[class-attrs-{cid}]", f"pre-cluster-threshold={float(t):.2f}"]
    Path(path).write_text("\n".join(lines) + "\n")
    return path
