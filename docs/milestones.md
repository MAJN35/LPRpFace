# Milestones (Part B of the original agentic coding package, verbatim)

You are working in this repository. Read `AGENTS.md` completely before doing anything, and follow it for the whole
session. Then work through the milestones below in order. After each milestone: run its acceptance checks, update
`docs/STATUS.md` and `docs/decisions.md`, commit, and report in this format:

```
Milestone Mx — <name>: DONE | PARTIAL | BLOCKED
Changed: <files>
Checks run: <command> -> <actual result>  (one line each)
PENDING (needs device): <items + exact commands for me>
Decisions needed: <questions with your recommendation>
```

Stop at every **GATE** and wait for my reply.

### M0 — Discovery (GATE)
Inspect the repository (existing code, stacks, CI, Docker files) and the `models/` folder. Then ask me, in one message:
Jetson model; `cat /etc/nv_tegra_release`; JetPack/CUDA/TensorRT/DeepStream versions; RAM and storage; how you can
reach the device (SSH host/user, or I run commands and paste output); sources (RTSP/USB/CSI/files/images, resolution, fps, count,
maximum number of simultaneous cameras, target fps per camera) and a sample frame or typical plate width in pixels; where backend/frontend/Kafka run; Python `pyds` or C/C++ (give a short
trade-off and your recommendation); external outputs needed (MQTT/HTTP/none); face blur default; first model version
(default v2). Include a short summary of what already exists in the repo and your proposed placement of services.

### M1 — Model check (x86, no GPU needed)
`tools/check_model.py models/<ver>`: verifies SHA-256 against `SHA256SUMS`, loads `class_names.json` and compares it with
`AGENTS.md` A.4, checks the ONNX input/output shapes with onnxruntime (CPU), prints a summary. Generate `labels.txt`.
Add `tools/export_onnx.py`: re-export from the `.pt` with the A.3 method and a fixed batch N or a dynamic batch axis
(record exact command and versions; weights unchanged).
**Accept:** runs for v1 and v2, exits non-zero on any mismatch (prove it with a test using a deliberately wrong mapping);
the batched ONNX gives the same detections per image as the batch-1 ONNX on CPU (onnxruntime).

### M2 — Decoder and reader library (x86)
Implement the numpy decoder for the raw ONNX output (thresholds, class-aware NMS, letterbox inverse) and the reader
library (A.7). Parity tool: run 20+ images through Ultralytics on the `.pt` and through onnxruntime + your decoder.
**Accept:** unit tests for every reader rule in A.7 (standard, free-zone two rows, transit expiry, special plates,
duplicates, constrained decoding, normalization, voting, dedup) pass; decoder parity ≥ 98 % of `.pt` detections matched
(same class, IoU ≥ 0.9) on CPU FP32; report written to `docs/parity_cpu.md`. Ask me for test images if none exist
(store them under the git-ignored `tests/data/private/`).

### M3 — TensorRT on the Jetson (GATE afterwards)
Verified base image and tag (cite source), engine build script with a cache keyed by checksum and batch profile
(min 1 / opt / max from M0), TensorRT parity using the M2 tool at batch 1 and at the max batch (same preprocessing
as DeepStream, measure pad 0 vs 114), FP16, quick throughput table for batch 1, 2, 4, max. **Accept:** engine builds on the device (record
time and memory); parity ≥ 95 % matched detections, no systematic class shift; plate-string accuracy of reader +
engine on labeled images reported for v1 and v2. If parsing fails, diagnose and propose the fix before changing export.
Stop and show me the results; I choose the model version to deploy.

### M4 — DeepStream app (standalone)
Container, nvinfer config, custom parser with class-score metadata, tracker config, probe calling the reader library,
JSON events to stdout and local crop storage, every source type from A.7 (RTSP, USB, CSI, video file, single image,
image folder, API image job), `sources.yaml` plus runtime add/remove, multi-source batching, ROI, `max_fps`,
`interval`, non-blocking reader worker, OSD in Latin, optional face blur.
**Accept:** a test video produces correct track-level events (compared with the reader running on the same frames
offline); an image folder produces one correct image event per image; at least 2 sources of different types run at the
same time with correct per-source ids; adding/removing a source at runtime does not interrupt the others; RTSP
disconnect/reconnect and file EOS handled; one broken source does not stop the pipeline; container restart reuses the
cached engine.

### M5 — Kafka and consumer
Broker (KRaft), topic init, producer adapter with bounded queue, consumer with validation, idempotency, retries, DLQ.
**Accept:** tests for schema validation, duplicate events, broker down (inference keeps running, counters rise),
consumer restart without loss; synthetic events first, then real ones from M4.

### M6 — Backend
API, storage, retention, search with Persian/Latin normalization, live updates, auth if exposed. **Accept:** API tests
(pagination, filters, search, idempotent writes, auth), OpenAPI generated, events from M5 visible through the API.

### M7 — Frontend (GATE before starting: show me a static mock of one page in the Neumorphism style)
All pages and states from A.7, real API data only, RTL Persian rendering, accessible. **Accept:** component tests for
states, an end-to-end test against the running backend, screenshots of each page in `docs/`.

### M8 — Integration, benchmark, hardening
Full compose deployment, restart recovery of each container, standalone mode, privacy settings, multi-camera load.
Benchmarks on the device (960 default; 640, ROI, `max_fps` and `interval` only as labeled experiments with accuracy
impact; DLA only if it helps; INT8 only if FP16 is insufficient and only with calibration and measured accuracy).
Multi-source scaling curve (1, 2, 4, … sources) with per-camera fps, latency p50/p95, GPU/CPU/RAM, temperature, and the
resulting maximum number of cameras at the target fps; recommended per-camera settings. **Accept:** `docs/benchmark.md` with measured
FPS, latency percentiles, GPU/CPU/RAM/temperature, power mode; all tests green; README complete (install, deploy,
configure, switch model v1/v2, rebuild engine, backup/restore, troubleshooting, AGPL note).

Start with M0 now.
