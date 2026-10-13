"""Model identity check and TensorRT engine cache (AGENTS.md A.3, A.7).

Engine file name = <ver>_<onnx sha256[:16]>_trt<TensorRT version>_<precision>_b<min>-<opt>-<max>.engine, the same
scheme as deepstream/scripts/build_engine.sh, so a model, TensorRT, precision or profile change can never reuse a
stale engine. A <engine>.json sidecar records build time and memory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, Tuple

from lpr_reader import classes as C

log = logging.getLogger("lpr.engine")
TRTEXEC = "/usr/src/tensorrt/bin/trtexec"


class ModelCheckError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_model_meta(meta_dir: Path) -> Dict[str, str]:
    """class_names.json == A.4 and the export record matches SHA256SUMS. Returns {pt_sha256, onnx_sha256}."""
    names, glyphs = C.load_class_names(meta_dir / "class_names.json")
    errs = C.compare_names(names) + C.compare_glyphs(glyphs)[0]
    if errs:
        raise ModelCheckError(f"{meta_dir}/class_names.json does not match A.4: {errs[:3]}")
    sums = {}
    for line in (meta_dir / "SHA256SUMS").read_text().splitlines():
        if line.strip():
            h, name = line.split()
            sums[name] = h
    if sums.get("class_names.json") != sha256(meta_dir / "class_names.json"):
        raise ModelCheckError("class_names.json checksum differs from SHA256SUMS")
    exports = sorted((meta_dir / "export").glob("*_dynbatch.json"))
    if not exports:
        raise ModelCheckError(f"no export record in {meta_dir}/export")
    rec = json.loads(exports[0].read_text())
    pt = next((n for n in sums if n.endswith(".pt")), None)
    if pt is None or rec["source_pt_sha256"] != sums[pt]:
        raise ModelCheckError("export record does not come from the .pt listed in SHA256SUMS")
    return {"pt_sha256": sums[pt], "onnx_sha256": rec["output_sha256"], "onnx_name": rec["output"]}


def trt_version() -> str:
    import tensorrt

    return tensorrt.__version__


def engine_name(ver: str, onnx_sha: str, precision: str, profile: Tuple[int, int, int]) -> str:
    return f"{ver}_{onnx_sha[:16]}_trt{trt_version()}_{precision}_b{profile[0]}-{profile[1]}-{profile[2]}.engine"


def ensure_engine(ver: str, meta_dir: Path, onnx_dir: Path, engine_dir: Path, precision: str,
                  profile: Tuple[int, int, int], workspace_mib: int = 2048) -> Tuple[Path, Dict]:
    ident = check_model_meta(meta_dir)
    name = engine_name(ver, ident["onnx_sha256"], precision, profile)
    engine, side = engine_dir / name, engine_dir / (name + ".json")
    if engine.exists() and side.exists():
        info = json.loads(side.read_text())
        if info.get("onnx_sha256") == ident["onnx_sha256"]:
            log.info("reusing cached engine %s", name)
            return engine, dict(info, pt_sha256=ident["pt_sha256"])
    onnx = onnx_dir / ident["onnx_name"]
    if not onnx.exists():
        raise ModelCheckError(f"engine {name} not cached and {onnx} not available to build it")
    got = sha256(onnx)
    if got != ident["onnx_sha256"]:
        raise ModelCheckError(f"{onnx} sha256 {got} != export record {ident['onnx_sha256']}")
    engine_dir.mkdir(parents=True, exist_ok=True)
    shape = lambda b: f"images:{b}x3x960x960"  # noqa: E731
    cmd = [TRTEXEC, f"--onnx={onnx}", f"--saveEngine={engine}.tmp", f"--minShapes={shape(profile[0])}",
           f"--optShapes={shape(profile[1])}", f"--maxShapes={shape(profile[2])}",
           f"--memPoolSize=workspace:{workspace_mib}", "--buildOnly"]
    if precision == "fp16":
        cmd.append("--fp16")
    log.info("building engine %s (this takes several minutes)", name)
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise ModelCheckError(f"trtexec failed: {res.stdout[-2000:]}{res.stderr[-2000:]}")
    Path(f"{engine}.tmp").rename(engine)
    info = {"engine": name, "engine_sha256": sha256(engine), "onnx": onnx.name, "onnx_sha256": ident["onnx_sha256"],
            "tensorrt": trt_version(), "precision": precision, "batch_profile": list(profile),
            "workspace_mib": workspace_mib, "build_seconds": round(time.time() - t0),
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    side.write_text(json.dumps(info, indent=2) + "\n")
    return engine, dict(info, pt_sha256=ident["pt_sha256"])
