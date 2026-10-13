#!/usr/bin/env python3
"""Verify a model folder (AGENTS.md A.3/A.4) and generate its labels.txt.

    python tools/check_model.py models/v2                # full check (needs onnxruntime for the ONNX step)
    python tools/check_model.py models/v2 --init-sums    # first use only: write SHA256SUMS from the files present

Checks, in order: SHA-256 of every file listed in SHA256SUMS; class_names.json against the fixed A.4 table (and
against the A.4 table parsed from AGENTS.md when that file is found); ONNX input/output shapes and a dummy CPU run
with onnxruntime; the class names embedded in the ONNX metadata. Exit code 0 = all good, non-zero = mismatch.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "reader"))

from lpr_reader import classes as C  # noqa: E402

EXIT_OK, EXIT_SUMS, EXIT_CLASSES, EXIT_ONNX, EXIT_USAGE = 0, 2, 3, 4, 5
INPUT_SHAPE = [1, 3, 960, 960]
OUTPUT_SHAPE = [1, 4 + C.NUM_CLASSES, 18900]  # cx, cy, w, h + 48 class scores per anchor
SUMS = "SHA256SUMS"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_files(model_dir: Path) -> list:
    """The delivered artifacts that form the model identity (exports in sub-folders are not included)."""
    pats = ("*.pt", "*.onnx", "class_names.json")
    return sorted({p for pat in pats for p in model_dir.glob(pat) if p.is_file()})


def init_sums(model_dir: Path) -> int:
    target = model_dir / SUMS
    if target.exists():
        print(f"FAIL: {target} already exists; it is the reference and is never overwritten")
        return EXIT_SUMS
    files = model_files(model_dir)
    if not files:
        print(f"FAIL: no model files in {model_dir}")
        return EXIT_SUMS
    target.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    print(f"wrote {target}:\n{target.read_text()}", end="")
    return EXIT_OK


def check_sums(model_dir: Path) -> tuple:
    """Returns (errors, {file name: sha256})."""
    target = model_dir / SUMS
    if not target.exists():
        return [f"{target} missing (create it once with --init-sums)"], {}
    errors, sums, listed = [], {}, set()
    for n, line in enumerate(target.read_text().splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            errors.append(f"{SUMS}:{n}: malformed line {line!r}")
            continue
        want, name = parts[0].lower(), parts[1].lstrip("*")
        listed.add(name)
        path = model_dir / name
        if not path.exists():
            errors.append(f"{name}: listed in {SUMS} but missing")
            continue
        got = sha256(path)
        sums[name] = got
        if got != want:
            errors.append(f"{name}: sha256 {got} != {SUMS} {want}")
    errors += [f"{p.name}: present but not listed in {SUMS}" for p in model_files(model_dir) if p.name not in listed]
    return errors, sums


def check_classes(model_dir: Path, agents_md: Path) -> tuple:
    """Returns (errors, warnings, names)."""
    try:
        names, glyphs = C.load_class_names(model_dir / "class_names.json")
    except (OSError, ValueError) as e:
        return [str(e)], [], []
    errors = [f"class_names.json vs A.4: {e}" for e in C.compare_names(names)]
    g_err, warnings = C.compare_glyphs(glyphs)
    errors += [f"class_names.json char_glyphs vs A.4: {e}" for e in g_err]
    if agents_md.exists():
        a4_names, a4_glyphs = C.parse_agents_md_a4(agents_md)
        errors += [f"AGENTS.md A.4 vs built-in table: {e}" for e in C.compare_names(a4_names)]
        errors += [f"AGENTS.md A.4 glyph id {k}: {v!r} != built-in {C.GLYPHS.get(k)!r}"
                   for k, v in a4_glyphs.items() if C.GLYPHS.get(k) != v]
    else:
        warnings.append(f"{agents_md} not found; compared with the built-in A.4 table only")
    return errors, warnings, names


def check_onnx(path: Path, names: list, run: bool) -> tuple:
    """Returns (errors, info lines)."""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as e:
        return [f"onnxruntime/numpy not available ({e}); run inside the tools container"], []
    errors, info = [], []
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    ins, outs = sess.get_inputs(), sess.get_outputs()
    info.append(f"inputs:  {[(i.name, i.shape, i.type) for i in ins]}")
    info.append(f"outputs: {[(o.name, o.shape, o.type) for o in outs]}")
    if len(ins) != 1 or ins[0].shape != INPUT_SHAPE or ins[0].type != "tensor(float)":
        errors.append(f"input must be one float tensor {INPUT_SHAPE}")
    if len(outs) != 1 or outs[0].shape != OUTPUT_SHAPE:
        errors.append(f"output must be one tensor {OUTPUT_SHAPE}")
    meta = sess.get_modelmeta().custom_metadata_map
    info.append("metadata: " + ", ".join(f"{k}={meta[k]}" for k in ("version", "imgsz", "batch", "args") if k in meta))
    if "names" in meta:
        embedded = ast.literal_eval(meta["names"])
        if [embedded.get(i) for i in range(len(embedded))] != names:
            errors.append("class names in ONNX metadata differ from class_names.json")
    else:
        info.append("metadata has no 'names' (not checked)")
    if run and not errors:
        out = sess.run(None, {ins[0].name: np.zeros(INPUT_SHAPE, np.float32)})[0]
        info.append(f"dummy run: output {list(out.shape)} {out.dtype}, "
                    f"class scores in [{out[0, 4:].min():.3g}, {out[0, 4:].max():.3g}]")
        if list(out.shape) != OUTPUT_SHAPE:
            errors.append(f"dummy run output shape {list(out.shape)} != {OUTPUT_SHAPE}")
        elif out[0, 4:].min() < 0 or out[0, 4:].max() > 1:
            errors.append("class scores outside [0, 1]: sigmoid missing in the graph?")
    return errors, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model_dir", type=Path)
    ap.add_argument("--init-sums", action="store_true", help="write SHA256SUMS once (first use)")
    ap.add_argument("--agents-md", type=Path, default=REPO / "AGENTS.md")
    ap.add_argument("--skip-onnx", action="store_true", help="checksums and classes only (no onnxruntime needed)")
    ap.add_argument("--no-run", action="store_true", help="check ONNX shapes without a dummy inference")
    ap.add_argument("--labels-out", type=Path, help="where to write labels.txt (default: <model_dir>/labels.txt)")
    a = ap.parse_args(argv)
    d = a.model_dir
    if not d.is_dir():
        print(f"FAIL: {d} is not a directory")
        return EXIT_USAGE
    if a.init_sums:
        return init_sums(d)

    print(f"== {d}")
    errors, sums = check_sums(d)
    for name, h in sorted(sums.items()):
        print(f"sha256 {h}  {name}")
    if errors:
        print("\n".join(f"FAIL checksum: {e}" for e in errors))
        return EXIT_SUMS
    print(f"checksums: OK ({len(sums)} files match {SUMS})")

    errors, warnings, names = check_classes(d, a.agents_md)
    for w in warnings:
        print(f"WARN classes: {w}")
    if errors:
        print("\n".join(f"FAIL classes: {e}" for e in errors))
        return EXIT_CLASSES
    print(f"classes: OK ({len(names)} classes match A.4)")

    labels = a.labels_out or d / "labels.txt"
    labels.write_text(C.labels_txt(names), encoding="utf-8")
    print(f"labels: wrote {labels}")

    if a.skip_onnx:
        print("onnx: SKIPPED (--skip-onnx)")
        return EXIT_OK
    onnx_files = sorted(d.glob("*.onnx"))
    if len(onnx_files) != 1:
        print(f"FAIL onnx: expected exactly one .onnx in {d}, found {[p.name for p in onnx_files]}")
        return EXIT_ONNX
    errors, info = check_onnx(onnx_files[0], names, run=not a.no_run)
    for line in info:
        print(f"onnx {line}")
    if errors:
        print("\n".join(f"FAIL onnx: {e}" for e in errors))
        return EXIT_ONNX
    print(f"onnx: OK ({onnx_files[0].name})")
    print("RESULT: OK")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
