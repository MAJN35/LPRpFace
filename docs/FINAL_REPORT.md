# Final report: Jetson DeepStream LPR platform (YOLO12x, model round 2)

Date: 2026-10-13. Device: Jetson Xavier NX 8 GB (6.7 GiB usable), JetPack 5.1.2 (L4T 35.4.1), DeepStream 6.3,
TensorRT 8.5.2.2, **nvpmodel mode 8 (MODE_20W_6CORE), jetson_clocks not run**. Everything below was measured on this
device unless a line says "estimate". Details: `docs/STATUS.md` (milestone reports, PENDING), `docs/decisions.md`,
`docs/benchmark.md`, raw data in `docs/bench/` and `docs/m3_*`.

## 1. Bottom line

- **The platform works end to end** on the Jetson: RTSP/file/image/API sources → DeepStream + TensorRT FP16 →
  track-level Persian plate reading → Kafka → consumer → FastAPI + Postgres → Neumorphism dashboard (with
  whitelist/blocklist/unknown watchlists and a forced admin password change).
- **Capacity is set by the model, not the software.** YOLO12x at 960 runs at **~3.6 inferences per second in total**
  on this Xavier NX in mode 8 (GPU 99 %), whatever the batch size. That budget is shared by all cameras.
- **How many cameras v2 supports in this power mode:**
  - at the requested **8–10 inferred fps per camera: none** (one camera alone gets 3.5 fps);
  - **reliably: 1–2 cameras** (3.5 / 1.66 inferred fps per camera, 98 % / 97 % plate-string accuracy on the
    camera-like test stream, ≤ 4.9 GB board RAM);
  - **at most 4 cameras** (0.8 fps per camera, accuracy drops to ~80 %, 5.4 GB); **8 cameras crossed the memory
    limit** (< 800 MB free) and were stopped by the watchdog.
- **Production model: v2** (user rule: v1 only if ≥ 2 points better overall or ≥ 5 points on a group with ≥ 20 plates;
  measured +0.8 overall, largest group gain +2.5). v1 stays switchable (`MODEL_VERSION=v1`, engine cached).

## 2. Model choice and accuracy (v1 vs v2)

TensorRT FP16, DeepStream preprocessing (letterbox pad 0), reader library, 490 held-out images of
`agent_testset_v2`. Exact string = all 8 characters of a standard plate right. Synthetic results are optimistic.

**Real images (exact plate string, standard 8-character plates)**

| Group | Plates | v2 | v1 | v1 − v2 |
|---|---|---|---|---|
| All real | 263 | **72.2 %** (190) | 73.0 % (192) | +0.8 |
| Day | 116 | 81.9 % | 82.8 % | +0.9 |
| Night | 63 | 74.6 % | 74.6 % | 0 |
| Multi-plate scenes | 44 | 40.9 % | 40.9 % | 0 |
| Shahab close-ups | 40 | 75.0 % | 77.5 % | +2.5 |
| Disabled (real) | 1 | 0 % | 100 % | (1 plate) |

**Synthetic images (by plate type)**

| Plate type | Plates | v2 | v1 |
|---|---|---|---|
| All standard-format | 167 | 79.6 % | 78.4 % |
| Free zone (number + zone) | 85 | 100 % | 98.8 % |
| Transit (number + expiry) | 10 | 40 % | 30 % |
| Protocol | 10 | 70 % | 80 % |
| Police | 12 | 100 % | 100 % |
| Disabled | 12 | 91.7 % | 91.7 % |
| Government | 12 | 91.7 % | 91.7 % |
| Private | 11 | 90.9 % | 90.9 % |
| Defense | 14 | 85.7 % | 85.7 % |
| Sepah | 13 | 84.6 % | 84.6 % |
| Military | 12 | 83.3 % | 83.3 % |
| Taxi | 12 | 83.3 % | 83.3 % |
| Public | 12 | 83.3 % | 75.0 % |
| He | 11 | 81.8 % | 81.8 % |
| Army | 10 | 80.0 % | 80.0 % |
| Leader | 11 | 63.6 % | 63.6 % |
| Service | 10 | 60.0 % | 50.0 % |
| Diplomatic (D/S) | 12 | 41.7 % | 41.7 % |

Full tables: `docs/m3_accuracy_table_pad0.md`. Parity: `.pt` vs ONNX CPU 100 % (v1 223/223, v2 221/221);
TensorRT FP16 vs `.pt` 96.8–97.8 %, identical at batch 1 and 4, no class shifts. Black (DeepStream) vs gray
(Ultralytics) padding: −0.4 points for v2. Most errors are characters the detector does not output at all on plates
narrower than ~80 px (lowering character thresholds to 0.20 changed nothing); this is the A.5 size limit.

## 3. Usable configurations (measured)

v2 FP16, mode 8. Sources = camera-like RTSP streams (1920×1080 H.264 25 fps) replaying the 6-clip test video.
Accuracy = correct plate-string events per clip appearance (150 s window). Peak RAM = whole board.

| Sources | interval | max fps | ROI | Output fps per source | Plate-string accuracy | Wrong events | Latency p95 | Peak RAM | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 10 | no | 3.50 | 98 % | 0 | 0.85 s | 4.7 GB | **recommended** |
| 1 | 2 | 10 | no | 2.64 | 92 % | 0 | 0.42 s | 4.5 GB | low latency |
| 1 | 0 | 3 | no | 3.57 | 98 % | 0 | 0.85 s | 4.6 GB | same as default |
| 1 | 0 | 10 | central | 3.50 | 81 % | 12 | 0.85 s | 4.6 GB | ROI must fit the road |
| 2 | 0 | 10 | no | 1.66 | 97 % | 0 | 1.7 s | 4.9 GB | **recommended** |
| 2 | 2 | 10 | no | 1.46 | 96 % | 0 | 0.73 s | 5.0 GB | **recommended if latency matters** |
| 2 | 0 | 3 | no | 1.66 | 96 % | 2 | 1.7 s | 4.8 GB | ok |
| 2 | 0 | 10 | central | 1.71 | 86 % | 28 | 1.7 s | 4.8 GB | not recommended |
| 4 | 0 | 10 | no | 0.80 | 81 % | 0 | 3.6 s | 5.4 GB | maximum; slow traffic only |
| 4 | 2 | 10 | no | 0.75 | 80 % | 0 | 1.4 s | 5.1 GB | maximum, lower latency |
| 4 | 0 | 3 | no | 0.89 | 80 % | 0 | 3.5 s | 5.3 GB | maximum |
| 4 | 0 | 10 | central | 0.89 | 59 % | 30 | 3.5 s | 5.2 GB | not recommended |
| 8 | 0 | 10 | no | – | – | – | – | > limit | **stopped by the memory watchdog** |

Recommended per-camera settings: `max_fps: 10` (lower values only save decoding; inference is the limit),
`interval: 0` (or `2` when the event latency matters more than the last points of accuracy), no ROI unless it is
drawn around the actual road area of that camera, `min_plate_px` ≥ 60 (A.5: reliable reading needs ≥ ~120 px in the
network input ≈ 240 px in a 1920 px frame). Scaling curve without the guarded runner, engine benchmarks and
experiment notes: `docs/benchmark.md`.

## 4. What a smaller model would change (estimate, not measured)

Ultralytics' published figures at 640 px (docs.ultralytics.com/models/yolo12): YOLO12x 59.1 M params, 208.9 GFLOPs,
11.79 ms on T4 TensorRT; YOLO12m 20.2 M, 70.7 GFLOPs, 4.86 ms; YOLO12s 9.3 M, 23.3 GFLOPs, 2.61 ms. Scaling this
device's measured 3.6 inferences/s by the T4 latency ratios gives **estimates** at 960 of ~**8.7/s for YOLO12m** and
~**16/s for YOLO12s** in total — i.e. one camera at the 8–10 fps target with m, about two with s, and several more
cameras at the current ~1–3 fps. Accuracy of a smaller model is unknown and must be measured.

What it would need (nothing in the software changes shape: same 48 classes, same 960 input, same output
`(B, 52, 18900)` since the strides are the same):
1. A new model **trained by the data owner** on the same data and class ids (the delivered weights must not be
   retrained or pruned, A.3) — delivered like v1/v2 as `models/v3/{.pt, .onnx, class_names.json}`.
2. M1–M3 again on the device: checksums + class check, dynamic-batch export, parity, engine build (~20–40 min for m,
   less for s), accuracy on `agent_testset_v2`, then `MODEL_VERSION=v3`. Parser, reader, events, backend and
   dashboard stay unchanged.
3. Re-run `tools/run_grid.sh` to replace the capacity numbers.

Other levers that were excluded by decision: INT8 (out of scope), jetson_clocks (no), DLA (not tested: attention
layers are expected to fall back to the GPU), a larger Jetson (Orin NX/AGX).

## 5. How to run each source type

All sources are entries in `deploy/sources.yaml` (or added at runtime in the dashboard: Settings → Sources, or
`POST /api/v1/cameras`). Credentials come from `deploy/.env` as `${VAR}`; URIs are redacted in logs and events.

| Source | Configuration | Tested |
|---|---|---|
| RTSP H.264 | `{id: cam-01, type: rtsp, uri: "rtsp://${CAM01_USER}:${CAM01_PASS}@HOST:554/Streaming/Channels/101", rtsp_transport: tcp, max_fps: 10}` | yes (mediamtx, 1920×1080 25 fps), reconnect after server stop |
| RTSP H.265 | same with the H.265 stream | yes (2560×1440 20 fps, runtime add/remove) |
| RTMP / HTTP(S) / HLS | `{id: s1, type: hls, uri: "https://host/live/index.m3u8"}` | not tested (no such source here) |
| USB (UVC, MJPEG) | `{id: usb0, type: usb, device: /dev/video0, width: 1280, height: 720, fps: 30}` + `devices: ["/dev/video0:/dev/video0"]` in compose | **PENDING: no camera attached** |
| CSI | `{id: csi0, type: csi, sensor_id: 0}` + mount `/tmp/argus_socket` | **PENDING: no camera attached** |
| Video file | `{id: v1, type: file, uri: /data/videos/a.mp4, realtime: false, loop: false}` | yes: 6/6 clips, identical to the offline reader |
| Single image | `{id: img1, type: image, uri: /data/images/a.jpg}` | yes (same code path as the folder) |
| Image folder / glob | `{id: imgs, type: image_folder, uri: "/data/images/*.jpg"}` | yes: 12/12 events, 8/12 correct = offline TensorRT |
| API upload | dashboard Settings → "Recognize an image", or `POST /api/v1/images` (multipart `file`, JPEG/PNG ≤ 10 MB), then `GET /api/v1/images/{job_id}` | yes |

Standalone (no Kafka/backend): `LPR_EVENT_SINKS=stdout,jsonl` (README "Standalone mode").

## 6. Deployment state (now)

The full stack is running on the Jetson from `deploy/compose.yaml` with `deploy/.env` (git-ignored, random secrets):
deepstream (v2 FP16, cached engine, 5 GB memory limit), kafka (KRaft), consumer, db (Postgres 15.10), backend,
frontend. **Dashboard: http://192.168.1.131:8080** (`FRONTEND_BIND=0.0.0.0`; the only published port).
Sign in as `admin` with `ADMIN_PASSWORD` from `deploy/.env`; you are forced to choose a new password (≥ 12
characters) before anything else works. The cameras in `deploy/sources.yaml` are disabled placeholders; the API
image job source is active. All test data was wiped before this deployment.

## 7. BLOCKED / PENDING and what is needed from you

| Item | State | Needed from you |
|---|---|---|
| USB camera | PENDING (none attached) | plug one in; run `ls /dev/video*`; add the source above and the `devices:` line |
| CSI camera | PENDING (none attached) | connect; add the source and mount `/tmp/argus_socket` |
| RTMP/HTTP/HLS sources | not tested | a stream URL if you use one |
| Real camera URLs/credentials | placeholders | fill `deploy/sources.yaml` (hosts) and `deploy/.env` (`CAM01_USER` …), set `enabled: true` |
| 8–10 fps per camera | **not reachable with YOLO12x at 960 on Xavier NX mode 8** | accept ~1–3.5 fps per camera (1–2 cameras), or provide a smaller model (section 4), or a faster Jetson |
| Face-mask on the output stream | implemented, counted (`faces_masked`), not visually verified (private frames are never viewed) | look at the Live page → Detections |
| Live video in the browser | **built** after your request: Live page, raw stream (network cameras) + detection stream (one camera at a time), behind the login | look at the face mask on the detection view yourself |
| Swapfile | not possible (SD card only) | an NVMe/SSD if wanted |
| Validation of Kaf, Gaf, Fe, D, S, protocol, Ze, free zone | synthetic only; no data for Se, Za, Pe (A.5) | real labelled images of these plates |
| AGPL-3.0 (Ultralytics) | flagged in README | legal review before any distribution |

## 8. Full-stack deployment test (M8)

`tools/m8_stack_test.sh` (output `docs/m8_stack_test.txt`), under the memory watchdog, one RTSP test camera:

| Check | Result |
|---|---|
| All containers healthy from `docker compose up` | yes (db, kafka, backend, frontend, deepstream, consumer) |
| Forced admin password change | before: every API call 403 `password_change_required`; after the change: unlocked |
| Events camera → DeepStream → Kafka → consumer → Postgres → API | yes (one camera: 25 fps in, 3.5 fps inferred) |
| Restart of each container (deepstream, kafka, consumer, backend, db, frontend) | each healthy again; **no loss**: every event id written by DeepStream (20 → 189 over the test) reached the database after every restart |
| e2e (Chromium → nginx → backend) on the live stack | 9/9 PASS; on a fresh demo-only stack 10/10 incl. the forced password change (screenshots `docs/screenshots/`) |
| Peak board RAM during the test | 5,247 MB |
| Standalone mode (no Kafka/backend) | yes (M4 runs: `LPR_EVENT_SINKS=stdout,jsonl`) |

Bugs this deployment test found and fixed (`docs/decisions.md`): the event schema was not found inside the image
(every event was dropped; now a build-time check), an empty `LPR_MAX_CAMERAS` crashed the service.

## 9. Added after M8 (user requests, 2026-10-13)

- **Live view:** Live page with each camera's raw stream (network cameras) and a detection stream (boxes and plate
  text drawn by DeepStream, one camera at a time). Served as LL-HLS through nginx `/hls/`, only for signed-in users.
  Details in `decisions.md`.
- **Persian-first dashboard:** Persian by default (RTL, Vazirmatn, Persian digits, Solar Hijri dates), with an
  English switch. The plate search draws a realistic Iranian plate whose positions you fill by list or by typing,
  with exact and partial match. Only the standard plate layout is verified; the other types are marked approximate
  (open item 10 in STATUS.md).
- **Branding and interaction:** EdgeTech logo, favicons, icons on all menus and buttons, and button feedback that
  reports success only after the server confirmed.
- **Fewer, better events:** one event per tracked plate (seen in at least 3 frames), plausible plates only.
- **Live grid and notifications:** every camera's raw stream at once, detections on one selected camera, and an
  on-screen notification for each recognized plate.
