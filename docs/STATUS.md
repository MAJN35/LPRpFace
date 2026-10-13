# Project status

Last update: 2026-10-13 (M0)

## Milestones

| | Milestone | State |
|---|---|---|
| M0 | Discovery | DONE, **GATE: waiting for answers** |
| M1 | Model check (CPU) | not started |
| M2 | Decoder + reader library | not started |
| M3 | TensorRT on Jetson | not started (GATE after) |
| M4 | DeepStream app (standalone) | not started |
| M5 | Kafka + consumer | not started |
| M6 | Backend | not started |
| M7 | Frontend | not started (GATE before: static mock) |
| M8 | Integration, benchmark, hardening | not started |

## Device facts (measured 2026-10-13, by running commands on the device)

| Item | Value | Command |
|---|---|---|
| Board | NVIDIA Jetson Xavier NX Developer Kit | `cat /proc/device-tree/model` |
| L4T | R35 (release), REVISION 4.1 → L4T 35.4.1 = JetPack 5.1.2 | `cat /etc/nv_tegra_release`, `dpkg -l nvidia-l4t-core` (35.4.1-20230801124926) |
| OS | Ubuntu 20.04.6, kernel 5.10.120-tegra, aarch64, 6 CPU cores | `uname -a`, `/etc/os-release` |
| CUDA | 11.4 (cuda-toolkit-11-4 11.4.19-1) | `dpkg -l` |
| cuDNN | 8.6.0.166 | `dpkg -l` |
| TensorRT | 8.5.2.2 (host) | `dpkg -l`, `python3 -c "import tensorrt"` |
| DeepStream (host) | 6.3.0-1 (also /opt/nvidia/deepstream/deepstream-6.2 dir present) | `dpkg -l` |
| RAM | 6.7 GiB usable (8 GB module), 3.3 GiB swap (zram) | `free -h` |
| Storage | mmcblk0 119 GB; root 117 GB, 57 GB free | `df -h /` |
| Power mode | current ID 8 = MODE_20W_6CORE; default ID 5 | `/var/lib/nvpmodel/status`, `/etc/nvpmodel.conf` |
| Time | NTP active, clock synchronized, TZ Asia/Tehran (store UTC) | `timedatectl` |
| Docker | 26.1.3, compose plugin 2.35.1, `nvidia` runtime registered (not default) | `docker info` |
| Cameras attached | no `/dev/video*` (no USB/CSI camera connected now) | `ls /dev/video*` |
| Network | eth0 192.168.1.131/24 | `ip addr` |
| Host Python | 3.8.10; no onnxruntime; host torch import fails (libopenblas missing) | |
| sudo | needs a password (agent cannot run `nvpmodel -q`, `jetson_clocks`) | |

## Models (checked 2026-10-13)

Computed with `sha256sum`; **not yet confirmed against the source bundles** (zips not on the device).

| File | SHA-256 |
|---|---|
| v1 .pt | b21ce3f64667c431b98ba82bb0eda008ec42672d4de686bf61fecd2268aa2cff |
| v1 .onnx | 5b32f1c8a1265004c1fa548ba9ad378d70db62a8f7144baf64eb5766f173c03a |
| v2 .pt | fbaf11408e5be67ffdd3423d439ef4e239c28bd435387f9692a1fb4ee3048ef8 |
| v2 .onnx | bf80a2b544d865b44943fb4596791852a209523ccd4481084d83312646429b96 |
| class_names.json (v1 = v2) | fac415707bf654fafa8bc28899f81caf97bee611ac1aab3ac15161c81c9aee90 |

- `SHA256SUMS` files are missing in `models/v1`, `models/v2` (to be created in M1 after confirmation).
- `class_names.json` `names` match A.4 ids 0–47 by inspection (formal check in M1).
- `char_glyphs` has no entry for 43 Gaf (گ); the reader will take it from A.4.

## Existing code

- This repo: only `CLAUDE.md` (Parts A+B) and `models/`. No `AGENTS.md`, no code, no CI, no Docker files.
- Earlier project on the same device: `/home/edgetec/EdgetecLPR/PlateDetector` (separate git repo; containers stopped).
  It has a DeepStream 6.3 pyds app (`nvcr.io/nvidia/deepstream-l4t:6.3-samples`, image present locally), a DeepStream-Yolo
  parser, Kafka with ZooKeeper (cp-kafka 7.5.0), a kafka-consumer, a FastAPI + Postgres 15 backend, a React 19 + TypeScript +
  Vite + Tailwind + Radix frontend with Vazirmatn, and HikCentral integration. Not touched.

## Open questions

See the M0 report (asked 2026-10-13): device access, sources, target fps, placement, pyds vs C++, outputs, face blur,
first model, reuse of the earlier project, AGENTS.md file, CPU tooling environment, test images, checksum confirmation.

## PENDING (needs device / user)

- `sudo nvpmodel -q` and `sudo jetson_clocks --show` output (sudo needs a password).
