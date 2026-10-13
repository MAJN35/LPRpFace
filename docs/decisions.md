# Decisions

Format: date, decision, reason, alternatives, source.

## 2026-10-13: Platform baseline taken from the device, not assumed

- **Decision:** Target JetPack 5.1.2 (L4T 35.4.1), CUDA 11.4, TensorRT 8.5.2, DeepStream 6.3 on Jetson Xavier NX 8 GB.
  This is the A.7 Xavier path (JetPack 5.1.x → DeepStream 6.3 / TensorRT 8.5).
- **Reason:** Read from the device: `/etc/nv_tegra_release` (R35.4.1), `dpkg -l` (nvidia-l4t-core 35.4.1,
  tensorrt 8.5.2.2, deepstream-6.3 6.3.0-1).
- **Alternatives:** none. Changing JetPack is not allowed without approval (A.2.2).
- **Source:** device output (see STATUS.md); the container tag gets verified against NGC and the DeepStream 6.3
  release notes in M3.

## 2026-10-13: Part A of CLAUDE.md is the AGENTS.md rulebook

- **Decision:** Treat Part A of the existing `CLAUDE.md` as `AGENTS.md` until the user decides on the file split.
- **Reason:** `AGENTS.md` does not exist; `CLAUDE.md` contains Part A + Part B verbatim.
- **Alternatives:** create `AGENTS.md` from Part A (proposed in the M0 questions).
- **Source:** repo inspection.

## 2026-10-13: Large model files stay out of git

- **Decision:** `.pt`, `.onnx` and `.engine` files are git-ignored; `SHA256SUMS` will be committed.
- **Reason:** A.2.6, A.8.
- **Source:** AGENTS.md.

## 2026-10-13: M0 answers from the user (gate passed)

| # | Decision |
|---|---|
| Access | Agent runs commands directly on the Jetson; `sudo` commands are run by the user and pasted back. |
| Power | Deploy and benchmark in nvpmodel mode 8 (MODE_20W_6CORE) + `jetson_clocks`; record both in `docs/benchmark.md`. `sudo nvpmodel -q` → `MODE_20W_6CORE 8` (user, 2026-10-13). |
| Sources | cam-01 RTSP 1920×1080 25 fps H.264; cam-02 RTSP 2560×1440 20 fps H.265; MP4 files for tests; image folders + API uploads. Max 8 simultaneous cameras; target 8–10 fps per camera for reading (voting over frames). |
| Engine batch profile | min 1 / opt 2 (current cameras) / max 8 (configured maximum), subject to the M3 memory measurement on 8 GB. |
| Test data | `tests/data/private/agent_testset_v2` (git-ignored), ground truth `manifest.json`; real and synthetic results reported separately. Sample frame `rw_001677.jpg`: 640×480, plate 95 px wide. |
| Placement | No server: all containers on the Jetson; Kafka heap capped; effect on camera count measured in M8. |
| App language | Python (pyds) DeepStream app; C++ nvinfer bbox parser. |
| Reuse | Copy selectively from `/home/edgetec/EdgetecLPR/PlateDetector` (plate format/normalization, RTSP reconnect, FastAPI + Postgres, React + TS + Vite + Tailwind); old stack stays untouched and stopped; retired after M8. Each copy is recorded here with its source path and commit. |
| Database | Postgres 15, exact 15.x tag, persistent volume, not exposed outside the Docker network. |
| External outputs | None (no MQTT/HTTP/HikCentral). HikCentral may be added later as a separate approved step. |
| Face blur | On by default on the output stream; no face crops stored. |
| Model | v2 tentatively, v1 selectable; final choice at the M3 gate from measured plate-string accuracy. |
| Checksums | No reference supplied: computed on first use, written to `SHA256SUMS`, reference from then on. |
| CPU tooling | Pinned `python:3.10` arm64 container on the Jetson (image digest pinned), CPU onnxruntime + Ultralytics 8.3.141 with a lock file; nothing installed on the host. |
| Rulebook | `AGENTS.md` = Part A (TODOs replaced by the checksum and accuracy decisions above); `CLAUDE.md` = `@AGENTS.md`; Part B kept in `docs/milestones.md`. |

- **Source:** user reply to the M0 report, 2026-10-13.

## 2026-10-13: Reference checksums written on first use (M1)

- **Decision:** `tools/check_model.py models/<ver> --init-sums` wrote `models/v1/SHA256SUMS` and `models/v2/SHA256SUMS`
  (`.pt`, `.onnx`, `class_names.json`). They equal the values measured in M0. `--init-sums` refuses to overwrite an
  existing file; every later run fails (exit 2) on any changed, missing or unlisted model file.
- **Reason:** user decision (M0 answer 12): no reference checksums were supplied.
- **Source:** user, 2026-10-13; tool output in the M1 report.

## 2026-10-13: Class table check (M1)

- **Decision:** `reader/lpr_reader/classes.py` holds the A.4 table as code. `check_model.py` compares `class_names.json`
  with it and with the A.4 table parsed from `AGENTS.md` (a drift fails too). `labels.txt` is generated from
  `class_names.json` only after the check passes. Missing glyphs are warnings (Gaf has none in `class_names.json`;
  the reader takes گ from A.4); a different glyph is an error. `class_names.json` gives ژ for Zhe (29); A.4 defines
  Zhe as the wheelchair symbol, so the reader does not use that glyph (how disabled plates are written: M2).
- **Source:** AGENTS.md A.4; `models/v*/class_names.json`.

## 2026-10-13: CPU tooling container pins (M1)

- **Decision:** `python:3.10.22-slim-bookworm@sha256:5be5aaec…b370` (multi-arch index digest, arm64 manifest
  `sha256:f3902572…1b8b`); `torch==2.11.0+cpu`, `torchvision==0.26.0+cpu` (PyTorch CPU index), `ultralytics==8.3.141`,
  `onnx==1.17.0`, `onnxslim==0.1.53`, `onnxruntime==1.23.2`, `numpy==1.26.4`, `opencv-python-headless==4.10.0.84`;
  hash-locked in `tools/docker/requirements.lock` (pip-compile inside the pinned base image).
- **Reason:** both delivered ONNX files embed producer `pytorch 2.11.0` and Ultralytics metadata `version 8.3.141`,
  `args {'batch': 1, 'half': False, 'dynamic': False, 'simplify': True, 'opset': 17, 'nms': False}`, so the re-export
  uses the same torch. Ultralytics 8.3.141 `export_onnx` requires `onnx>=1.12.0,<1.18.0` and `onnxslim>=0.1.53`.
  PyPI's aarch64 `torch==2.11.0` depends on CUDA 13 packages (`nvidia-cudnn-cu13` …), the `+cpu` build does not.
  onnxruntime ≥ 1.24 has no cp310 wheels (1.31.0 requires Python ≥ 3.11). `YOLO_AUTOINSTALL=false` stops Ultralytics
  from pip-installing at runtime; the run wrapper uses `--network none`.
- **Alternatives:** an x86 machine (none available); host install (not allowed).
- **Source:** ONNX metadata strings of the delivered files; Ultralytics 8.3.141 wheel `ultralytics/engine/exporter.py`
  lines 555–600 and `ultralytics/utils/export.py`; PyPI JSON API (`/pypi/<pkg>/json`); download.pytorch.org/whl/cpu
  index; Docker Hub registry API (image config `PYTHON_VERSION=3.10.22`, created 2026-10-06).

## 2026-10-13: Batched ONNX export method (M1)

- **Decision:** `tools/export_onnx.py` calls Ultralytics `export(format="onnx", imgsz=960, opset=17, simplify=True,
  dynamic=False, batch=N)` on a temporary copy of the `.pt`, with `torch.onnx.export` wrapped to force `dynamo=False`,
  and for `--dynamic-batch` to set `dynamic_axes` to the batch axis only (`images[0]`, `output0[0]`). The engine
  profile from M0 (min 1 / opt 2 / max 8) needs the dynamic batch axis; fixed batch N stays available.
- **Reason:** A.3 requires the classic exporter, but Ultralytics 8.3.141 does not pass `dynamo` and torch ≥ 2.9
  defaults to the dynamo exporter. Ultralytics' `dynamic=True` also makes height, width and the anchor count
  dynamic, which nvinfer does not need. Exporting from a temporary copy keeps Ultralytics from writing next to the
  delivered `.onnx` (it saves `<pt>.with_suffix('.onnx')`); the `.pt` checksum is verified before and after.
- **Source:** Ultralytics 8.3.141 `exporter.py` (`dynamic = {"images": {0: "batch", 2: "height", 3: "width"}}`,
  `output0: {0: "batch", 2: "anchors"}`).

## 2026-10-13: Decoder follows Ultralytics NMS (M1/M2)

- **Decision:** `lpr_reader.decode` reproduces Ultralytics 8.3.141 `non_max_suppression` (argmax label per anchor,
  `score > conf`, top 30000, class offset 7680 → class-aware NMS, `max_det` 300) plus the A.7 per-class thresholds,
  and keeps each anchor's 48 class scores. The letterbox follows `LetterBox(auto=False, center=True)` and
  `scale_boxes` (pad rounding `round(d ± 0.1)`, pad value configurable: 114 Ultralytics, 0 DeepStream).
- **Note for M2:** `Model.predict` defaults to `rect=True` (minimal-rectangle padding), so the `.pt` parity run must
  use `rect=False` to see the same 960×960 input as the ONNX/TensorRT path.
- **Source:** Ultralytics 8.3.141 `utils/ops.py` (`non_max_suppression`, `scale_boxes`), `data/augment.py` (`LetterBox`).
