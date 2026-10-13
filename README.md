# LPR platform: YOLO12x on Jetson DeepStream

License plate recognition for Persian plates on an NVIDIA Jetson Xavier NX (JetPack 5.1.2): a fine-tuned YOLO12x
detector in DeepStream 6.3 / TensorRT 8.5 (FP16), track-level plate reading, events through Kafka, a FastAPI +
Postgres backend with history and search, and a Neumorphism web dashboard. Everything runs on the Jetson.

Status, open items and measured results: [`docs/STATUS.md`](docs/STATUS.md) ·
decisions: [`docs/decisions.md`](docs/decisions.md) · benchmarks: [`docs/benchmark.md`](docs/benchmark.md) ·
final report: [`docs/FINAL_REPORT.md`](docs/FINAL_REPORT.md) · rules: [`AGENTS.md`](AGENTS.md).

```
Sources (RTSP/RTMP/HTTP/HLS, USB, CSI, video files, images, image folders, API uploads)
  -> nvstreammux (batch 1..4) -> nvinfer (YOLO12x FP16, custom parser + class scores) -> nvtracker (NvSORT)
  -> probe (metadata) -> reader worker (read, vote, dedup, crop) -> JSONL / Kafka -> consumer -> backend + Postgres
  -> dashboard (nginx, same origin, WebSocket live updates)
```

| Component | Path | Image |
|---|---|---|
| Plate-reading library (pure Python, unit-tested) | `reader/` | (copied into images) |
| DeepStream app, parser, configs | `deepstream/` | `lpr-deepstream:6.3` (base `nvcr.io/nvidia/deepstream-l4t:6.3-samples`, digest-pinned) |
| Kafka consumer | `consumer/` | `lpr-consumer:1.0` |
| Backend API | `backend/` | `lpr-backend:1.0` |
| Dashboard | `frontend/` | `lpr-frontend:1.0` |
| Deployment | `deploy/` (`compose.yaml`, `.env.example`, `sources.yaml`) | Kafka 3.9.1 (KRaft), Postgres 15.10 |
| Model tools (CPU) | `tools/` | `lpr-tools:cpu` |
| Models | `models/v1`, `models/v2` (weights git-ignored; `SHA256SUMS`, `class_names.json`, `labels.txt`, export records committed) | |

## Install (on the Jetson)

Requirements: JetPack 5.1.2 (L4T 35.4.1), Docker with the `nvidia` runtime, about 20 GB free disk. Docker must be
able to pull from Docker Hub (on this network: daemon proxy = the Xray tunnel inbound, see `docs/decisions.md`;
fallback `python3 tools/fetch_image.py <image>@sha256:...`).

```bash
# 1. model files: put the delivered .pt/.onnx/class_names.json into models/v1 and models/v2, then verify
tools/build_cpu_image.sh                             # CPU tools image (once)
tools/run_cpu.sh python tools/check_model.py models/v2   # checksums, A.4 classes, ONNX shapes -> labels.txt
# 2. batch-capable ONNX (once per model; weights unchanged)
tools/run_cpu.sh python tools/export_onnx.py models/v2 --dynamic-batch
# 3. images
deepstream/build_image.sh                            # lpr-deepstream:6.3 (copies the host TensorRT/CUDA headers for the parser)
tools/build_service_image.sh backend
tools/build_service_image.sh consumer
docker build -f frontend/Dockerfile -t lpr-frontend:1.0 .
# 4. TensorRT engine (cached by ONNX sha256 + TensorRT version + precision + batch profile)
deepstream/scripts/build_engine.sh v2                # FP16, profile 1/2/4 -> engine_cache/
```

## Deploy

```bash
cp deploy/.env.example deploy/.env          # fill in POSTGRES_PASSWORD, SECRET_KEY, INGEST_KEY, ADMIN_PASSWORD
$EDITOR deploy/sources.yaml                 # cameras (credentials as ${CAM01_USER} etc. from .env)
docker compose -f deploy/compose.yaml --env-file deploy/.env up -d
docker compose -f deploy/compose.yaml --env-file deploy/.env ps
```

Dashboard: `http://127.0.0.1:8080` (set `FRONTEND_BIND=0.0.0.0` in `.env` to publish it on the LAN; this is the
only published port). Sign in with `ADMIN_USERNAME`/`ADMIN_PASSWORD`; create more users with
`POST /api/v1/users` (admin). API docs: `http://127.0.0.1:8080/docs`.

**Standalone mode (no Kafka/backend):** events go to stdout and `/data/events/events.jsonl`:

```bash
deepstream/run.sh env LPR_EVENT_SINKS=stdout,jsonl LPR_SOURCES_FILE=/work/deepstream/configs/sources.test.yaml \
  ENGINE_DIR=/engines META_DIR=/work/models/v2 ONNX_DIR=/work/models/v2/export LPR_EVENTS_JSONL=/work/out/events.jsonl \
  LPR_CROPS_DIR=/work/out/crops LPR_JOBS_DIR=/work/out/jobs LPR_TRACKER_CONFIG=/work/deepstream/configs/tracker_nvsort_lpr.yml \
  python3 -m app.main
```

## Configure sources (`sources.yaml`)

One entry per source: `id`, `name`, `type`, `uri`, `enabled`, `max_fps`, `roi` (normalized polygon), `min_plate_px`,
`face_blur`, `record`; type-specific `rtsp_transport` (tcp|udp), `loop`/`realtime` (files), `device`/`width`/`height`/`fps`
(USB), `sensor_id` (CSI). `${VAR}` is taken from the environment. Override `enabled` with
`LPR_SOURCE_<ID>_ENABLED=0|1`.

| Type | Example | Notes |
|---|---|---|
| RTSP H.264/H.265 | `{id: cam-01, type: rtsp, uri: "rtsp://${CAM01_USER}:${CAM01_PASS}@10.0.0.11:554/Streaming/Channels/101", rtsp_transport: tcp}` | `nvurisrcbin`, reconnect every 5 s; credentials never logged (URIs are redacted) |
| RTMP / HTTP(S) / HLS | `{id: s1, type: hls, uri: "https://host/live/index.m3u8"}` | via `nvurisrcbin` / GStreamer |
| USB (UVC, MJPEG) | `{id: usb0, type: usb, device: /dev/video0, width: 1280, height: 720, fps: 30}` | map the device in compose (`devices:`) |
| CSI | `{id: csi0, type: csi, sensor_id: 0, width: 1920, height: 1080, fps: 30}` | mount `/tmp/argus_socket` |
| Video file | `{id: v1, type: file, uri: /data/videos/a.mp4, loop: false, realtime: false}` | MP4/MKV/MOV/TS; `realtime: true` plays at real time |
| Single image | `{id: img1, type: image, uri: /data/images/a.jpg}` | one `plate.recognized.image` event per plate |
| Image folder / glob | `{id: imgs, type: image_folder, uri: "/data/images/*.jpg"}` | JPEG and PNG |
| API upload | `POST /api/v1/images` (multipart `file`) then `GET /api/v1/images/{job_id}` | dashboard: Settings → Recognize an image |

Runtime add/remove/enable/disable: dashboard Settings, or `POST/DELETE /api/v1/cameras[/{id}[/enable|disable]]`
(forwarded to the DeepStream control API, which requests/releases `nvstreammux` pads without restarting).

## Switch model v1/v2

`MODEL_VERSION=v1` (or `v2`) in `deploy/.env`, make sure `models/v1/export/*_dynbatch.onnx` exists
(`tools/export_onnx.py`), then `docker compose ... up -d deepstream`. The engine for that model is built on first
start (or ahead with `deepstream/scripts/build_engine.sh v1`) and cached; events carry `model.version/sha256`.

## Rebuild the engine

Engines are keyed by ONNX sha256 + TensorRT version + precision + batch profile, so a changed model can never reuse
a stale engine. To force a rebuild delete the matching files in `engine_cache/` and run
`deepstream/scripts/build_engine.sh <ver>` (`PRECISION=fp32`, `MIN_BATCH/OPT_BATCH/MAX_BATCH`, `WORKSPACE_MIB`).

## Backup / restore

```bash
docker compose -f deploy/compose.yaml exec -T db pg_dump -U lpr -Fc lpr > backup_$(date +%F).dump
docker run --rm -v lpr_lpr-data:/data -v "$PWD":/b alpine tar czf /b/crops_$(date +%F).tgz -C /data crops
# restore
docker compose -f deploy/compose.yaml exec -T db pg_restore -U lpr -d lpr --clean < backup_YYYY-MM-DD.dump
docker run --rm -v lpr_lpr-data:/data -v "$PWD":/b alpine tar xzf /b/crops_YYYY-MM-DD.tgz -C /data
```

Backups contain personal data (plates, crops): store them encrypted and apply the same retention.

## Tests

```bash
tools/run_cpu.sh python -m pytest                                   # reader + model-check (CPU)
deepstream/run.sh python3 -m pytest -p no:cacheprovider deepstream/tests consumer/tests
docker run --rm -v "$PWD":/work -w /work/backend lpr-backend:1.0 python -m pytest -q -p no:cacheprovider tests
docker run --rm -v "$PWD/frontend":/app -w /app node:20.18.1-bookworm-slim npx vitest run
```

Hardware checks (Jetson): `tools/parity.py`, `tools/infer_cache.py --backend trt`, `tools/eval_reader.py`,
`deepstream/scripts/bench_engine.sh`, `tools/check_video_events.py`, `tools/m5_check.py`, `frontend/e2e/run.mjs`.

## Troubleshooting

- **`docker pull` fails / CloudFront 403:** the daemon proxy must be the Xray tunnel inbound (127.0.0.1:57531);
  `docker info | grep -i proxy`. Fallback: `tools/fetch_image.py`.
- **`NvRmMemInit failed ... Permission denied`:** the container user lacks the `video`/`render` groups; use
  `deepstream/run.sh` (adds them) or run as root.
- **Engine build slow / out of memory:** a YOLO12x 960 engine takes about an hour on Xavier NX and most of the 8 GB;
  stop other containers while building. Use the cached engine afterwards.
- **No events:** `GET /api/v1/status` (inference reachable? sources live? `worker.frames`), plates below
  `min_plate_px`, dedup window `LPR_DEDUP_S`.
- **RTSP camera reconnects:** check `last_error` per source in System health; wrong passwords back off 5 min → 1 h.

## License (AGPL-3.0)

The detector is an Ultralytics YOLO model; Ultralytics YOLO is licensed under **AGPL-3.0**. Distributing this
system (or offering it over a network) can oblige you to make the corresponding source available under AGPL-3.0, or
to obtain an Ultralytics Enterprise license. Private or internal use does not by itself remove these obligations;
get legal advice before distribution. NVIDIA DeepStream/TensorRT containers are under the NVIDIA Deep Learning
Container License; Vazirmatn is under the SIL Open Font License 1.1.
