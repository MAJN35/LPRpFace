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

## 2026-10-13: Image downloads on this network (M1)

- **Finding:** Docker's CDN (CloudFront) answers 403 to requests leaving through the Xray `directSocks` inbound
  (127.0.0.1:57556, routed to the `direct` outbound), which the daemon used as its proxy; nvcr.io answers 403 to
  direct requests. Through the VLESS tunnel inbound (127.0.0.1:57531) Docker Hub blobs download (200, 3.4 MB/s)
  and nvcr.io answers 401 (normal auth challenge). Download speed is the same direct and tunnelled (~4–5 MB/s).
- **Decision:** The user switched the daemon proxy to `http://127.0.0.1:57531` (2026-10-13 05:36 +0330); pulls work
  (`docker pull python:3.10.22-slim-bookworm@sha256:5be5…` → up to date, RepoDigest recorded).
  `tools/fetch_image.py` stays as a fallback: it downloads a digest-pinned Docker Hub image directly, verifies the
  manifest, config and every layer by SHA-256 and `docker load`s it; `tools/build_cpu_image.sh` accepts the plain
  tag only when its image ID equals the verified config digest.
- **Lock file:** `pip-compile --generate-hashes` downloads every platform's wheel of every pin to hash it (1.5 GB in
  49 min without finishing). Replaced by `tools/docker/make_lock.py`: downloads only the wheels for this platform,
  installs them offline to prove they resolve, and pins each with version + SHA-256. The lock is therefore
  platform-specific (linux/aarch64, CPython 3.10); regenerate it with `tools/build_cpu_image.sh --lock` on x86.
- **Source:** curl measurements on the device; Xray `~/config.json` (structure only, secrets not recorded).

## 2026-10-13: M1 accepted: dynamic-batch ONNX for the engine

- **Decision:** Use `models/<ver>/export/*_dynbatch.onnx` (batch axis dynamic, output dims pinned to 52 × 18900)
  as the input for the TensorRT engine with profile min 1 / opt 2 / max 8 (M3). The pinned output dims are a
  shape annotation only (measured with onnxruntime; `onnx.checker` passes); nodes and weights are unchanged
  (59,193,334 initializer values in the delivered ONNX vs 59,193,339 in the export, +5 shape constants; +8 Reshape,
  +16 Transpose for the dynamic batch).
- **Reason:** identical detections to the delivered batch-1 ONNX at batch 1/2/4/8 on CPU (see STATUS.md).
- **Note:** `opencv-python` 4.11.0.86 is installed alongside the pinned headless 4.10.0.84 because Ultralytics
  depends on it; `cv2` resolves to 4.11.0 in the tools image. Harmless for CPU tooling.
- **Source:** `docs/m1_batch_parity_v{1,2}.json`, `models/v{1,2}/export/*.json`.

## 2026-10-13: Standing autonomy for M2–M8 (user instruction)

- **Decision:** Run M2–M8 without pausing; decide with the user's defaults and record here (what, why, how to undo).
  The "extra M2 (v1 vs v2) and M3 (batch, swap, FP16 parity) items from my previous message" were not in this
  session; interpreted as: M2 parity and accuracy for both v1 and v2; M3 batch profile 1/2/4 (8 only if 4 builds
  with ≥ 1.5 GB free), swapfile, FP16 parity with FP32 fallback for failing layers.
- **Swapfile:** not created. The only storage is the SD card (`lsblk`: mmcblk0, no NVMe/SSD) and the user allows a
  swapfile only on NVMe/SSD. Existing zram swap (3.3 GB) unchanged. Undo/redo: attach an NVMe/SSD, then create it.
- **Source:** user message 2026-10-13.

## 2026-10-13: Reader output conventions (M2)

- **Latin transliteration = class names** (`12 Be 345 | 67`, `98 Zhe 594 | 32`, `98 D 750 | 69`): unambiguous
  (single letters D and S are the diplomatic markers, so Dal/Sin cannot be "D"/"S") and identical to the test-set
  ground truth (`gt_string_latin`). A.7's example `12 B 345 | 67` is accepted as input: `plate_key()` maps short
  aliases (B→Be, J→Jim, …; see `LATIN_ALIASES`). Undo: change `_read_standard`/`format_standard` formatting.
- **Persian form:** `۱۲ ب ۳۴۵ | ۶۷` (physical left-to-right order); Zhe is shown as ♿ (as in the ground truth);
  D/S stay Latin. `plate_key` (`12Be34567`) is the formatting-independent search key.
- **Validity:** standard/disabled/diplomatic use the 8-character rule (2 digits + letter + 3 digits + 2 digits);
  transit = Gaf letter + 3–4 expiry digits; free zone = both rows equal, 5 digits; protocol = `is_valid: null`,
  `invalid_reason: "not_applicable"` (no validated format rule, A.7). Invalid reads are returned with a reason.
- **Plate type** is derived from layout and letter only (standard, disabled, diplomatic, transit, freezone,
  protocol). Colour-based types (taxi, police, government…) cannot be told from classes and are reported as
  `standard`.
- **Transit:** the right box's top row is the code, the bottom row the expiry (`YY/M[M]`), from the test-set layout;
  the earlier "two tallest" rule misread 1/10 synthetic transit plates and was replaced.
- **Free zone:** top row = Persian, bottom = Latin (same digit classes); per position the more confident row wins;
  zone = most confident `fz_*` within the plate (margin 25 %, the panel sits at the plate's left edge).
- **Overall confidence** = weakest character confidence (constrained-decoding score).
- **Voting:** weight = confidence × size factor (plate width in network input / 120 px, floor 0.2); a frame with the
  same string and plate IoU ≥ 0.9 as the previous vote gets 0.25 of its weight; runner-up classes add half their
  score; track timeout 1.5 s; dedup window 30 s per camera and plate key (only valid reads).
- **Reuse:** `reader/lpr_reader/normalize.py` adapts digit/Arabic-letter normalization and the "ایران-first or
  physical order" parser from `/home/edgetec/EdgetecLPR/PlateDetector/backend/app/core/plate_format.py` (commit
  c8c9740). `deepstream/app/config.py` and `pipeline.py` reuse that project's RTSP lessons
  (`deepstream/src/sources.py`, `deepstream_lpr_app.py`, same commit): split credentials at the last '@', leaky
  queue per source, drop a live source's EOS and rebuild only that source, backoff 2 s→60 s (auth 5 min→1 h),
  never reuse a released mux pad index, 20 s no-frame stall detection.
- **Check:** reader on the ground-truth label boxes (`tools/eval_reader.py --oracle`): standard 8-character plates
  100 % (263/263 real, 167/167 synthetic), free zone 85/85, protocol 10/10, transit 9/10 (the miss has unlabelled
  expiry digits in its label file).

## 2026-10-13: TensorRT engine and batch profile (M3)

- **Decision:** FP16 engine, profile min 1 / opt 2 / max 4 (user default). Batch 8 **not built**: the rule is "try 8
  only if 4 builds with ≥ 1.5 GB free"; the batch-4 build left at least 966 MiB available (host peak 5,531 MiB
  used; my image builds ran at the same time, so this is conservative). Undo: `MAX_BATCH=8 OPT_BATCH=4
  deepstream/scripts/build_engine.sh v2` with nothing else running.
- **Build:** `trtexec` 8.5.2.2 inside `deepstream-l4t:6.3-samples`, workspace 2048 MiB, 4,312 s (72 min) for v2.
  TensorRT 8.5 has `--buildOnly`, not `--skipInference` (8.6+). `build_engine.sh` had a `sort | head` SIGPIPE
  under `pipefail` after the build; fixed (single awk pass); the v2 record was finalized from the build log.
- **Throughput (v2, nvpmodel mode 8, jetson_clocks not run, trtexec GPU compute):** batch 1: 3.56 img/s (p50 277 ms);
  batch 2: 3.61 img/s (p50 545 ms); batch 4: 3.58 img/s (p50 1,081 ms). The GPU is saturated at batch 1, so batching
  gives no throughput, only flexibility for several sources.
- **Consequence:** YOLO12x at 960 delivers ~3.6 inferences/s in total on this Xavier NX, below the 8–10 fps per
  camera target even for one camera. Mitigations are measured as labeled experiments in M8 (`max_fps`, `interval`,
  ROI); 640 input and INT8 are out of the default per the user's rules.
- **Source:** `docs/m3_throughput_v2.jsonl`, `engine_cache/*.json`.

## 2026-10-13: Per-class thresholds unchanged after a measured experiment (M3)

- **Decision:** keep the A.7 thresholds (characters 0.35). On v2 TensorRT FP16 (pad 0), real standard plates read
  190/263 exactly at a character threshold of 0.35, 0.30, 0.25 and 0.20 alike: the missing characters of the failing
  plates are not weak detections, they are absent (small plates, ~60 px in the network input; A.5 limit).
- **Reader fix found on real detections:** `_Det` compared by value (numpy arrays) in `list.remove` when a plate had
  > 8 character boxes → now identity comparison (`@dataclass(eq=False)`), with a unit test.

## 2026-10-13: Watchlists for persons and plates (user request)

- **Decision:** New requirement added to AGENTS.md A.7 ("Watchlists"). Plates (keyed by the normalized
  `plate_key`, so any Persian/Latin form is one entry) and persons each sit on exactly one list: `whitelist`,
  `blocklist` or `unknown` (default). A plate may link to one person. Effective status = the plate's list, or the
  person's list when the plate is `unknown`; unregistered plates are `unknown`. Each event stores the effective
  status and person at ingest (only valid reads are matched, to avoid false hits from partial reads); a blocklist hit
  is pushed to the dashboard as a WebSocket `alert`. Nothing leaves the device (no gate control, no notification).
- **Ease of change:** one PATCH per entry (dashboard: a three-button Whitelist/Blocklist/Unknown control on every
  row, also on the event detail page), `POST /api/v1/lists/move` for bulk moves (checkbox selection), and a
  "seen in the last 7 days, not on any list" table with one-click list buttons. Operators/admins edit, viewers read.
  Every list change and every person view is audited.
- **Persons are records, not biometric identities.** A.7 Privacy forbids face identification, matching and
  enrollment; a person is a name + notes linked to plates. Face-based person lists need an explicit change of the
  privacy rule (asked of the user; recommendation: keep it forbidden).
- **Schema:** migration `0002_watchlists` (tables `persons`, `plates`; columns `events.list_status`,
  `events.person_id`). Undo: `alembic downgrade 0001` and remove `backend/app/routes/lists.py`, `frontend/src/pages/Lists.tsx`.
- **Checks:** backend 22/22 tests (8 new watchlist tests), frontend 14/14 (4 new), e2e extended.
