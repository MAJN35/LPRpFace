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
