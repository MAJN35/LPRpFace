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

## 2026-10-13: Production model v2 (M3 gate, user rule)

- **Decision:** deploy **v2** (FP16, profile 1/2/4). Rule: v1 only if it beats v2 on exact plate-string accuracy by
  ≥ 2 points overall or ≥ 5 points on a group with ≥ 20 plates. Measured (TensorRT FP16, pad 0 = DeepStream
  preprocessing, real standard plates): v2 72.2 % (190/263), v1 73.0 % (192/263), +0.8; groups ≥ 20 plates: day
  +0.9, night 0, multi-plate 0, Shahab close-ups +2.5 (40 plates); synthetic standard −1.2, free zone −1.2. No
  threshold reached. v1 stays buildable (`MODEL_VERSION=v1`, engine cached). Tables: `docs/m3_accuracy_table_pad0.md`.
- **Parity:** CPU `.pt` vs ONNX + decoder: v2 221/221, v1 223/223 (100 %). TensorRT FP16 vs `.pt`: v2 97.7 % (pad
  114) / 96.8 % (pad 0); v1 97.8 % (pad 0); identical at batch 1 and batch 4; no class shifts. Pad 0 vs 114 changes
  real accuracy by −0.4 (v2) / 0.0 (v1) points, so DeepStream's black padding is kept.
- **Throughput:** v1 3.45–3.51 img/s, v2 3.56–3.61 img/s (batch 1–4).

## 2026-10-13: DeepStream app design findings (M4)

- **Two probes.** NvSORT does not output targets in their first (tentative) frame, so detections read after the
  tracker lost every image frame and the first frame of each track. Probe A (nvinfer src) reads all detections and
  class-score vectors; probe B (tracker src) joins track ids by box and copies crops. Images: 0 → 12 of 12 read.
- **Square mux canvas (1920×1920).** A 16:9 canvas shrank portrait/4:3 images to ~56 % before nvinfer's letterbox;
  the pipeline then read 5/12 test images vs 8/12 offline. With a square canvas it reads 8/12, the same as offline
  TensorRT. 16:9 cameras keep the same scale. Undo: `AppConfig.mux_height`.
- **Legacy nvstreammux centers padded frames** (measured: offsets = (mux − size×scale)/2). Box mapping fixed; event
  plate boxes vs ground truth: median IoU 0.91 (min 0.77) on the 12 test images.
- **RTSP back-pressure.** nvvideoconvert has 4 output buffers by default; a 4-deep leaky queue could hold all of
  them, blocking the decoder and rtspsrc (mediamtx: "connection is too slow, discarding frames"), and the stream
  broke every ~40 s. Now: converter `output-buffers=8`, leaky queue 2, decoder `num-extra-surfaces=4`; cameras are
  received at full rate (25/20 fps) while inference takes what it can.
- **Reconnect rule.** nvurisrcbin's own RTSP reconnect (every 5 s) recovers streams that were connected; replacing
  its bin while the camera is down defeated it (a bin attached at runtime whose first connection fails never
  retries). So: a source that has produced frames is left to nvurisrcbin (health shows "reconnecting"); only a source
  that never produced a frame is rebuilt with backoff (2 s → 60 s; authentication errors 5 min → 1 h).
- **Evidence crops on the CPU.** pyds 1.1.8 has no object-encoder (`nvds_obj_enc_*`) bindings, so the GPU encoder of
  A.7 is not reachable from Python. The probe copies only the plate region from the mapped RGBA frame, and only when
  a track gets a larger plate (or once per image); the worker encodes it with OpenCV. Alternative: a C++ probe.
- **Images decoded on the CPU** (OpenCV, JPEG and PNG) into an appsrc, one buffer per image with its own caps;
  `nvjpegdec` would need a per-image decoder renegotiation. Image jobs are not real-time, so this is acceptable.
- **Face blur = opaque mask** drawn by nvdsosd on the output stream (fill colour, alpha 1), the strongest privacy
  setting; only active when the OSD/RTSP output is enabled. No face crops are stored.
- **ROI = rectangular crop** (bounding box of the polygon) with nvvideoconvert `src-crop` before the muxer; boxes are
  mapped back to full-frame pixels. nvdspreprocess was not used (it needs a custom tensor-preparation library to
  reproduce the letterbox).
- **max_fps** = `videorate drop-only` after decode; **interval** = nvinfer `interval`.
- **Control API** binds 0.0.0.0 inside the container network only (never published); dev runs bind 127.0.0.1.

## 2026-10-13: Real-time file playback (M8)

- **Finding:** a video file with `realtime: true` as the only source (non-live muxer, synced sink) stalled after 4
  frames. Tried: (1) without `videorate` — still stalled; (2) sink `async` default — still stalled; (3) muxer
  `live-source=1` whenever a real-time file is present — runs. Kept (3); `sink async=false` also removed.
- A file is still pulled as fast as inference allows (no frame drops), so camera-like accuracy experiments use the
  test video served as RTSP by mediamtx instead (`tools/exp_video_accuracy.sh`).

## 2026-10-13: User decisions after the freeze

- **Dashboard on the LAN:** `FRONTEND_BIND=0.0.0.0` (port 8080 published on all interfaces; the only published
  port). Precondition implemented first: the bootstrap admin must change its password before any other API call
  (`users.must_change_password`, migration 0003 also flags the existing admin; every endpoint except `/auth/me` and
  `/auth/change-password` answers 403 `password_change_required`, the WebSocket is refused; new password ≥ 12
  characters, different from the old one; audited). Dashboard: change-password screen after sign-in. Undo:
  `FRONTEND_BIND=127.0.0.1`.
- **Live-video gateway:** not now (Live page shows events only).
- **jetson_clocks:** no. All measurements in nvpmodel mode 8 without jetson_clocks.
- **Face-based person lists:** stay forbidden (A.7 privacy unchanged).
- **Memory rules for every run** (after the freeze): cached engines only (rebuild only on ONNX change, then workspace
  1024 MB and nothing else running); `docker --memory=5g` (`deepstream/run.sh`); tegrastats logged to a file;
  watchdog kills the run below 800 MB available RAM (`tools/guarded_run.sh`); one pipeline at a time; sources
  increased one step at a time, stopping at the first step that crosses the limit (`tools/run_grid.sh`).
  `build_engine.sh` default workspace changed to 1024 MiB accordingly.
- **Privacy:** private images and frames derived from them are never opened or viewed; numeric checks only.

## 2026-10-13: Bugs found by the compose deployment test (M8)

- **Event schema path inside the image:** `events.py` resolved `<code>/../../schemas`, which is the repo root in a
  checkout but `/schemas` in the image (`/app/app/events.py`), so every event failed validation and was not emitted.
  Earlier runs mounted the repo and hid it. Fix: search `LPR_SCHEMA_PATH`, `/app/schemas`, repo path; the
  Dockerfile now fails the build if the schema is not found.
- **Empty env values:** compose passed `LPR_MAX_CAMERAS=""`; `int("")` crashed the service in a restart loop. Fix: empty
  means default; capacity is now a block in `/health` (`max_cameras_memory_safe` 4, `max_cameras_at_target_fps` 0,
  `target_fps_per_camera` 8) shown on the System health page.
- **Deployment:** test volumes wiped; fresh stack with `deploy/sources.yaml` (camera placeholders disabled),
  `FRONTEND_BIND=0.0.0.0`, bootstrap admin forced to change its password.

## 2026-10-13: Live view in the browser (raw + detections)

- **Decision:** built at the user's request ("add live OSD for detections and also add live view (raw and with OSD)"),
  which replaces the earlier "live-video gateway: not now".
- **Gateway:** mediamtx 1.12.3 (`bluenviron/mediamtx:1.12.3-ffmpeg`, digest pinned), internal only, 512 MB limit. The
  browser gets LL-HLS through nginx `/hls/` (not `/live/`, which nginx would turn into a redirect of the dashboard page `/live`), guarded by `auth_request` → `GET /api/v1/auth/check`; no new port.
  Browsers cannot play RTSP; WebRTC would need UDP ports, which LL-HLS over the existing port does not.
- **Raw:** DeepStream registers each network camera as an on-demand mediamtx path (pulled only while watched).
  USB, CSI and files have no raw view.
- **Detections:** one camera at a time. valve → `nvmultistreamtiler show-source` → `nvdsosd` → crop → NVENC H.264 →
  appsink → separate publisher pipeline (`rtspclientsink`), so a gateway failure never stops inference. It starts on
  the first viewer (mediamtx `runOnDemand` → control API `/live/<id>/start`) and stops 15 s after the last viewer.
- **Alternatives rejected (measured):**
  - `nvstreamdemux` cannot add src pads after the pipeline started in DS 6.3.
  - A tee per camera with its own encoder stalled the muxer buffer pool, and the watchdog fired at 786 MB free.
- **Runtime sources persist:** sources added through the API are kept in `/data/sources.runtime.json` (mode 600),
  which keeps a camera added in the dashboard across restarts.
- **Pipeline start:** waits at most 10 s for PLAYING. Before, it blocked forever when a source had no data yet,
  and the control API never answered.

## 2026-10-13: Persian-first dashboard and plate search

- **Decision (user request):** Persian is the default UI language (RTL); English stays one click away and the
  choice is stored per browser (`localStorage["lpr.lang"]`, the same mechanism as the theme). No i18n library: one
  typed dictionary (`frontend/src/i18n.tsx`; missing keys fail the TypeScript build).
- **Plate rendering:** CSS/SVG plus real text, no images. The plate keeps its physical left-to-right order inside the
  RTL page (`dir="ltr"` on the plate), which matches the reader's `plate_string_fa` order. Only the standard layout
  follows a verified rule. The other types are drawn from the reader's rules (`reader/lpr_reader/reader.py`) and
  labelled approximate; no regional codes, symbols or format rules were invented.
- **Character lists** come from the model's class table: digits 0–9, letters 10–28/31/32/42–44, Zhe 29, D/S 45/46.
  `frontend/src/test/plate_charset.test.ts` checks them against `models/v2/class_names.json`. plate, face, freezone,
  fz_* and protocol are never selectable; the backend also refuses them (422). Zones (fz_*) are a separate selector.
- **Search API:** the existing `GET /events` gains `slots` (one token per position), `layout`
  (standard|freezone|protocol) and `match` (exact|partial), which become a condition on the indexed `plate_key`:
  - exact compares for equality;
  - partial turns an empty digit position into `_` and an empty letter position into `%`, because letter names
    differ in length;
  - protocol (unknown length) matches the filled run anywhere.

  No schema change and no migration; the free-text `q` search is unchanged.
- **Plate type filter:** applied only when the plate says something (a position filled, exact match, a zone) or a
  non-standard type is chosen, so the untouched form lists every event. Colour variants (taxi, government, …) share
  the standard layout and are stored as `standard`, because the model cannot see colours.
- **Combobox:** each position follows the WAI-ARIA select-only combobox pattern (button + listbox). Typing works with
  a physical keyboard (keydown); on phones the list is used, since buttons do not open a virtual keyboard.
- **HLS path:** the nginx proxy moved from `/live/` to `/hls/`. A prefix location with proxy_pass makes nginx answer
  `/live` with a redirect to `/live/`, which broke reloading the dashboard's Live page (found by the e2e).

## 2026-10-13: Branding, icons, button motion (user request)

- **Brand:** the user's EdgeTech logo (attached image: "Edge" in the text colour, "Tech" in blue, italic heavy;
  "VIDEO ANALYTICS"). It is redrawn as an HTML wordmark plus an SVG mark: a licence plate inside a scan viewfinder,
  crossed by a scan line. Theme tokens (`--brand`, `--text`, `--plate-*`) keep it legible in light and dark mode
  (`components/Logo.tsx`).
- **Favicons:** `public/favicon.svg`, the same mark on a fixed dark tile, legible on any tab colour. PNGs at
  32/180/192/512 (+ maskable) are rasterized from it with the e2e Chromium; `favicon.ico` is 16/32/48. Also
  `manifest.webmanifest`, apple-touch-icon and theme-color. nginx serves the manifest as `application/manifest+json`.
- **Icons:** lucide-react 0.469.0 (ISC, tree-shaken, about 1 KB per icon used). The project had no icon library;
  lucide has every icon the request names. No emoji icons.
- **Button motion:** one shared `Btn` (`components/Button.tsx`) and CSS only, no animation library:
  - press scale 0.97 and a ripple from the pointer position;
  - busy spinner; check or error mark that appears only after the request resolved (`useActions`, one run per
    key, so no double submits);
  - icon-only buttons get an aria-label and a tooltip.

  Tokens: `--press`, `--dur-press`, `--dur-nav`. Everything is off under `prefers-reduced-motion`.
- **Sidebar:** icons before labels (inline start, so right in Persian), an animated active marker, and a collapse
  toggle (`localStorage["lpr.nav"]`) with tooltips while collapsed. Directional icons (back, sign out, pagination)
  are mirrored in RTL; others are not.
- Menu entries that do not exist in this app (datasets, model management, users, analytics) were not added.

## 2026-10-13: Video emit policy, live view fixes, notifications (user request)

- **Emit policy:** events in the dashboard looked like per-frame noise: 77 of 88 phone events in a day had no or too
  few characters, 42 came from a single frame, and tracks were split. The reader worker now emits one event per
  tracker track and only when:
  - the track was read in at least `LPR_MIN_TRACK_FRAMES` = 3 frames;
  - the result is plausible: a valid plate, or a protocol-type read with at least 4 digits.

  The track timeout went from 1.5 s to `LPR_TRACK_TIMEOUT_S` = 3 s; at about 3.5 inferred frames/s, 1.5 s split one
  car into several tracks.

  This deliberately departs from A.7 "invalid reads are returned, never dropped" for video, at the user's request.
  The reader library still returns every read, `LPR_EMIT_INVALID=1` restores the old behaviour, and dropped reads are
  counted (`dropped_implausible` in /health). Image jobs (uploads) still return whatever was read.
- **Live view did not play in the user's browser.** nginx logged aborted playlist requests (499). There were two
  causes:
  1. The real one: the detection-stream publisher copied encoded frames with the inference pipeline's timestamps
     (its running time). A publisher started minutes after DeepStream therefore waited that long before sending
     anything. The RTSP session received only keepalive bytes, measured: 1428 bytes and then +60 in 5 s. Timestamps
     are now cleared and appsrc stamps the frames: 3 MB received, and the browser fetched segments continuously.
  2. Slow start: LL-HLS parts at the inference rate, and a keyframe every 10 frames (about 5 s per segment at
     ~2 fps), took longer than the player's 10 s timeout. The fix:
     - standard fMP4 HLS;
     - a keyframe every 2 frames;
     - player timeouts of 30 s and runOnDemandStartTimeout of 30 s;
     - raw camera paths pulled continuously, so the first raw playlist arrives in about 4–5 s.

     `hlsAlwaysRemux` stays off: with it, mediamtx answers the on-demand detection path with 404 (measured).
  The gateway sync loop now checks a path with GET before adding it (no "path already exists" log every 10 s).
- **Multiple cameras at once:** a grid with every camera's raw stream side by side (the gateway only remuxes). The
  detection overlay stays one camera at a time (one encoder; the board's memory), selectable per tile.
- **Notifications:** an in-page toast for each recognized plate on every page (live WebSocket). It can be muted with
  the bell (`localStorage["lpr.notify"]`). Blocklist alerts always show and stay until dismissed. No browser or OS
  push: nothing leaves the device, and the Notification API needs HTTPS anyway.

## 2026-10-13/14: Face recognition, person registration, snapshot library, OS notifications, OSD (user requests)

- **Privacy rule changed by the user:** face recognition is on. The AGENTS.md privacy section was rewritten to say
  so; the user chose this explicitly in answer to a question.
- **Face model (user's choice): InsightFace buffalo_l.**
  - SCRFD `det_10g` finds landmarks; ArcFace R50 `w600k_r50` gives a 512-d embedding.
  - Downloaded directly from github.com/deepinsight/insightface releases v0.7 (the Xray proxy was down; GitHub
    answered directly). Zip SHA-256 80ffe37d…; the two ONNX files are recorded in `models/face/arcface_r50/SHA256SUMS`
    and checked at start.
  - **The weights are licensed for non-commercial research only.** A commercial deployment needs a licence from
    InsightFace. The alternative offered was SFace + YuNet (Apache-2.0/MIT).
- **Where faces are processed:**
  - DeepStream saves one snapshot per face track: the largest frame, with 35 % margin. It needs at least 2 frames
    and a face at least 40 px wide.
  - The snapshot is published on `lpr.face.events` (`schemas/face_event-1.0.json`).
  - A separate `face` container (onnxruntime CPU, 1 GB, 4 CPUs) embeds it: SCRFD at 192 px about 0.11 s, ArcFace
    about 0.5 s, measured on the board. It then posts to the backend. The inference pipeline never waits for it.
- **Matching (backend):**
  - Cosine similarity against every person's reference faces (at most 30 per person). At or above 0.45 the face
    belongs to that person. Otherwise a good face (≥ 48 px, landmark score ≥ 0.6) starts an unnamed person,
    "Unknown #n", that operators can name, merge or move between lists.
  - Low-quality faces are stored unassigned.
  - Thresholds are settings (`FACE_MATCH_THRESHOLD` …). The 0.45 is a starting value, not calibrated on real data
    from these cameras.
  - A blocklisted person's face raises an alert like a plate.
- **Manual registration:**
  - `POST /persons/register` takes a name, list, notes and photos. The face service's internal `/embed` (port 8095,
    internal network, ingest key) uses the largest face per photo at 640 px.
  - Every photo with a face becomes a reference. A faceless photo is reported; if no photo has a face, nothing is
    created.
  - If the face already matches someone (e.g. an "Unknown #n" seen by a camera), a merge is offered.
  - The dashboard's "Register people" page takes many rows, or many photos at once with names from the file names.
  - `POST /persons/{id}/photos` adds references to an existing person.
- **Snapshot library:** plate crops and face snapshots in one list. Deleting removes the image file; the event or
  face record stays. Crops are now owned by the backend's uid (10001), handed over by DeepStream, so it can delete
  them. Before this, retention also could not delete crop files.
- **Notifications:**
  - On-screen toasts for plates and faces, the latter with a snapshot. Blocklist hits are kept until dismissed.
  - OS notifications through a service worker, shown when the dashboard is not in front. They need a secure
    context: HTTPS on port 8443 with a self-signed LAN certificate (`tools/make_cert.sh`, `deploy/certs/`,
    git-ignored).
  - nginx enables HTTPS only when a certificate is mounted.
  - No push service: nothing leaves the device.
- **Restream:** with the live view on, DeepStream reads network cameras through the gateway (`LPR_RESTREAM=1`):
  - **Why:** the phone camera serves a second client without stream parameters (ffprobe: width 0). DeepStream
    therefore got nothing while the gateway held the first connection.
  - **Start-up order:** DeepStream waits until the gateway has the stream before connecting. Connecting early fails,
    and DeepStream 6.3's reconnect then leaves NVDEC broken ("Surface not registered", measured).
  - **Fallback:** if the gateway is not ready within 30 s, the camera is read directly.
  - **Bug fixed:** a bin attached while the pipeline was still on its way to PLAYING was never started.
- **Model fps:** `/health` `pipeline.inference_fps` (frames inferred per second over about 10 s) and per-camera
  `fps_out`. Shown on Overview, System health, each live tile, and in the detection stream's header.
- **Plates are drawn as plate shapes everywhere:** history, overview, live, lists, event detail, library,
  notifications. Reads that fit no layout show Persian text only. The Latin form stays as the accessible name.
- **Detection stream (OSD):**
  - brand-blue plate boxes with the read above them;
  - amber outline (or the mask, with face blur) on faces;
  - a header bar with camera, model fps and local time (`TZ`, default Asia/Tehran; events stay UTC).

## 2026-10-14: Liquid motion for selection indicators and buttons (user request)

- **Not glassmorphism:** the colors, layout and components stay; only motion changed.
- **No animation library:** the project had none. One small spring simulation (`components/LiquidIndicator.tsx`,
  about 150 lines) does the effect; Framer Motion would add roughly 50 KB for one effect.
- **The drop:**
  - It is a single element carrying the selected item's inset highlight (and, in the sidebar, the accent bar). Each of
    its four edges is a spring.
  - The edge facing the destination is stiff (k 520, damping ratio 0.82) and leads; the trailing edge is soft (k 150,
    0.72) and follows. The drop therefore stretches along its path, narrows up to 18 % per side while stretched, and
    settles with a slight overshoot.
  - A new selection keeps the current position and velocity, so rapid clicks bend the motion instead of restarting it.
- **Measurement:** the active item is measured when the selection changes and whenever the group resizes
  (collapse/expand, language/direction, wrapping on phones). Physical edges, so up/down, RTL/LTR and rows all work.
  The route drives it, so back/forward and direct URLs are correct; a direct load places it without animation.
- **Cost:** requestAnimationFrame runs only while the drop moves. Under prefers-reduced-motion it jumps.
- **Where:** the sidebar menu, and every tab or segmented group: plate match mode, list kind and list tabs, people
  filter, library kind, live layout, theme, language.
- **Bug found in Chromium:** rAF timestamps can be earlier than the clock read when the frame was requested. That
  gave a negative time step and the drop briefly grew to thousands of px. The first frame now only sets the clock,
  and steps are clamped to 1–32 ms; a regression test covers it.
- **Measured in Chromium:** after every navigation the drop settles exactly on the active item: down, up, four rapid
  clicks, back button, collapsed, expanded, RTL, reduced motion. The longest jump stretches it to 198 px (item
  43 px) at about 65 % width.
- **Buttons:** a press is a quick asymmetric squeeze (scale .975 × .94, 90 ms); the release springs back over 460 ms
  with a slight overshoot (`--ease-spring`). The ripple stays only on primary actions.
- **Pages:** the content fades in 70 ms after the click, so the indicator leads and the page follows.

## 2026-10-14: Video upload, source copies, camera limit, detection-stream guard (user requests)

- **Video upload from the dashboard:**
  - Settings → Videos does `PUT /api/v1/videos/<name>`. The body is the file, streamed straight to `/data/videos` on
    the shared volume: no multipart temp copy on the SD card.
  - Limits: 2048 MB per file, and at least 4096 MB must stay free on the disk after an upload.
  - Names allow Latin and Persian characters but never a path. A video used by a source cannot be deleted.
  - "Add as source" fills the form (type `file`), with loop and "as fast as possible" switches.
  - nginx raises the body limit only for `^/api/v1/videos/[^/]+$`. It is a regex because a prefix location ending in
    `/` redirects the list URL; that broke the list and was found by the e2e.
  - DeepStream (root) creates `/data/videos` owned by the backend's uid 10001.
- **Copies:**
  - The Add source form's "Copies" (1–4) adds `<id>-2`, `<id>-3`, … with `copy_of: <id>`: the same input given to the
    pipeline several times, each with its own id and events, e.g. for load tests.
  - Network copies read the original's gateway relay, so there is one camera connection; the phone camera cannot
    serve late joiners.
  - An original with copies cannot be removed first.
- **Camera limit enforced:** DeepStream refuses an enabled video source beyond `LPR_MAX_CAMERAS` (4, the measured
  memory-safe maximum; 8 froze the board). Image jobs do not count; disabled sources do not count.
- **Detection-stream guard:** two DeepStream crashes ("free(): invalid pointer" in NVENC/NvBufSurfTransform, Docker
  restarted the container) happened when the detection stream started on a camera that delivered no frames. The
  cameras were the never-configured placeholder `cam-02` (enabled from the dashboard) and the phone, which had
  stopped serving.
  - `live_start` now answers `not_ready` unless the camera is live with a frame in the last 5 s.
  - The Live page preselects the first camera that is actually live.
- **Measured on the board** (phone off, cam-02 placeholder reconnecting): a looping test video plus one copy ran
  at 1.4 inferences/s together after a slow start. Dead cameras being rebuilt every few seconds hold up the shared
  batch; disabling sources that cannot connect is recommended.
