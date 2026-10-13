# Project status

Last update: 2026-10-13. Device: Jetson Xavier NX 8 GB, JetPack 5.1.2 (L4T 35.4.1), DeepStream 6.3, TensorRT 8.5.2.2,
nvpmodel mode 8 (MODE_20W_6CORE), jetson_clocks not changed. Final summary: [`FINAL_REPORT.md`](FINAL_REPORT.md).

| | Milestone | State |
|---|---|---|
| M0 | Discovery | DONE (gate passed 2026-10-13) |
| M1 | Model check (CPU) | DONE |
| M2 | Decoder + reader library | DONE |
| M3 | TensorRT on Jetson | DONE (gate = self-check, model v2 chosen by the user's rule) |
| M4 | DeepStream app | DONE except USB/CSI (no devices attached: PENDING) |
| M5 | Kafka + consumer | DONE |
| M6 | Backend | DONE (+ watchlists, user request) |
| M7 | Frontend | DONE (gate = self-check: static mock `frontend_mock.html`) |
| M8 | Integration, benchmark, hardening | DONE (USB/CSI and visual face-mask check PENDING) |

## Device facts (measured)

| Item | Value |
|---|---|
| Board / L4T | Jetson Xavier NX Developer Kit, R35.4.1 (JetPack 5.1.2), Ubuntu 20.04.6, 6 CPU cores |
| CUDA / cuDNN / TensorRT / DeepStream | 11.4 / 8.6.0 / 8.5.2.2 / 6.3.0 |
| RAM / storage | 6.7 GiB usable + 3.3 GiB zram; SD card only (mmcblk0, 117 GB) — no NVMe/SSD, so no swapfile |
| Power | nvpmodel mode 8 MODE_20W_6CORE (user, `sudo nvpmodel -q`); jetson_clocks not run |
| Time | NTP active and synchronized; events in UTC |
| Network | Docker daemon proxy = Xray tunnel inbound 127.0.0.1:57531 (direct route is refused by Docker's CDN and nvcr.io) |

## Models

| | v1 | v2 |
|---|---|---|
| `.pt` sha256 | b21ce3f6…2cff | fbaf1140…8ef8 |
| delivered `.onnx` sha256 | 5b32f1c8…c03a | bf80a2b5…9b96 |
| dynamic-batch export sha256 | 980fd50f…a268 | 48095325…bf2d |
| FP16 engine (1/2/4) sha256 | f09c9975…e8ae | 1c48ca5a…9696 |
| engine build | 4,270 s, peak 5,879 MiB used | 4,312 s, peak 5,531 MiB used |

---

## M2 report

```
Milestone M2 — Decoder and reader library: DONE
Changed: reader/lpr_reader/{decode,preprocess,reader,voting,normalize,classes}.py, reader/tests/*, tools/{parity,
         eval_reader,infer_cache,accuracy_table}.py, docs/parity_cpu*.{md,json}
Checks run: tools/run_cpu.sh python -m pytest -q reader/tests -> 44 passed (every A.7 rule: standard, free-zone two
              rows, transit expiry, disabled/diplomatic/protocol, duplicates, constrained decoding, normalization,
              voting, timeout, dedup)
            tools/parity.py v2 (24 images, .pt vs ONNX CPU + decoder) -> 221/221 = 100 % (>= 98 %), no class shifts
            tools/parity.py v1 -> 223/223 = 100 %
            tools/eval_reader.py --oracle (reader on ground-truth boxes) -> standard 263/263 real, 167/167 synthetic,
              free zone 85/85, protocol 10/10, transit 9/10 (label file lacks the expiry digits)
PENDING (needs device): none
Decisions needed: none
```

## M3 report

```
Milestone M3 — TensorRT on the Jetson: DONE (gate self-check passed)
Changed: deepstream/{Dockerfile,build_image.sh,scripts/build_engine.sh,scripts/bench_engine.sh}, tools/trt_runner.py,
         docs/m3_*, docs/parity_trt_*
Checks run: base image nvcr.io/nvidia/deepstream-l4t:6.3-samples, NGC digest e01bb8f5…75cf == local (NGC registry API)
            build_engine.sh v2 / v1 -> FP16 1/2/4 built in 4,312 s / 4,270 s; batch 8 not built (min free 0.97 GB < 1.5 GB)
            bench_engine.sh v2 -> 3.56 / 3.61 / 3.58 img/s at batch 1 / 2 / 4 (GPU p50 277 / 545 / 1,081 ms)
            bench_engine.sh v1 -> 3.45 / 3.50 / 3.51 img/s
            parity TRT FP16 vs .pt (24 images): v2 97.7 % pad 114, 96.8 % pad 0; v1 97.8 % pad 0; same at batch 1
              and batch 4; no class shifts (>= 95 %)
            accuracy (490 images, real standard 8-char plates, pad 0): v2 72.2 %, v1 73.0 %; full tables in
              docs/m3_accuracy_table_pad0.md -> v2 chosen (rule not met for v1)
PENDING (needs device): none
Decisions needed: none (model chosen by the user's rule)
```

Known limits (A.5, measured): most misses are characters the detector does not output at all on plates < ~80 px
(lowering character thresholds to 0.20 changed nothing); multi-plate scenes 40.9 %; transit expiry digits 40 %.

## M4 report

```
Milestone M4 — DeepStream app (standalone): DONE (USB/CSI PENDING: no device)
Changed: deepstream/app/{main,pipeline,sources,worker,control,engine,events,sinks,config,nvinfer_config}.py,
         deepstream/parsers/*, deepstream/configs/*, schemas/plate_event-2.0.json, tools/{make_test_video,
         offline_video_reader,check_video_events,m4_runtime_test.sh}, deploy/test/mediamtx.yml
Checks run: deepstream tests (pytest) -> 15 passed (config, redaction, schema, non-blocking emitter, sinks)
            test video H.264 1080p, 6 clips -> 6/6 one correct track event each, identical to the offline reader
              (tools/offline_video_reader.py: 6/6); crops 6/6
            image folder, 12 images -> 12 image events, 8/12 correct (= offline TensorRT 8/12); plate boxes vs GT
              median IoU 0.91
            tools/m4_runtime_test.sh -> file + RTSP H.264 + broken RTSP together; runtime add/remove RTSP H.265
              2560x1440; RTSP server stopped 40 s -> "reconnecting" -> back to live; broken source never stops the
              others; API image job -> event; SIGTERM clean; 34/34 events schema-valid, URIs redacted (docs/m4_runtime.txt)
            restart -> "reusing cached engine" (no rebuild)
PENDING (needs device): USB camera: plug in, then `ls /dev/video*`, add `devices: ["/dev/video0:/dev/video0"]` and a
              `{id: usb0, type: usb, device: /dev/video0}` source; CSI camera: mount /tmp/argus_socket and add
              `{id: csi0, type: csi, sensor_id: 0}`. Neither is attached to this Jetson.
Decisions needed: none
```

## M5 report

```
Milestone M5 — Kafka and consumer: DONE
Changed: consumer/*, deploy/compose.yaml (kafka KRaft 3.9.1, kafka-init topics), deepstream/app/sinks.py, tools/m5_check.py
Checks run: consumer unit tests -> 10 passed (schema validation -> DLQ, duplicates, backend down + backoff, no commit
              before delivery, 4xx -> DLQ)
            synthetic run: 20 valid + 5 duplicates + 3 invalid -> 20 in backend, 5 skipped, 3 in lpr.dead-letter
            consumer stopped, 15 produced, consumer started -> 0 then 15 in backend (no loss)
            broker stopped: 50 events emitted in 0.015 s (non-blocking), 50 buffered in the producer; broker
              started -> 50 delivered, 50 in backend
            real events from M4 -> see M8 full-stack run
PENDING (needs device): none
Decisions needed: none
```

## M6 report

```
Milestone M6 — Backend: DONE
Changed: backend/* (FastAPI, SQLAlchemy async, Alembic 0001 + 0002 watchlists), backend/tests/*
Checks run: backend tests (SQLite) -> 22 passed: idempotent ingest, ingest key, auth + roles, pagination, filters
              (camera, time, type, zone, validity, model, list), Persian/Latin search (Arabic forms, any digits,
              "ایران-first"), detail + audit log, crop path-traversal guard, CSV export, retention, WebSocket live
              + blocklist alert, OpenAPI paths, watchlists (moves, bulk, person inheritance, unregistered plates,
              viewer read-only, audit)
            Postgres 15.10 in compose: alembic upgrade head on start, /api/v1/ready 200; M5 events visible via API
PENDING (needs device): none
Decisions needed: dashboard exposure on the LAN (FRONTEND_BIND, default 127.0.0.1); face-based person lists (not
              built: A.7 forbids face identification; recommendation: keep it forbidden)
```

## M7 report

```
Milestone M7 — Frontend: DONE (gate self-check: docs/frontend_mock.html)
Changed: frontend/* (React 18 + TS + Vite, CSS design tokens, nginx), frontend/e2e/*, docs/screenshots/*.png
Checks run: vitest -> 14 passed (loading/empty/error/disconnected/stale states, RTL plate, login error, lists: one-click
              move, bulk move, add Persian plate, viewer read-only); tsc -b clean
            e2e (Chromium via puppeteer-core -> nginx -> backend -> Postgres) -> 9/9 PASS: login, overview with real
              API data, Persian partial search, RTL rendering, event detail, live event over WebSocket, lists
              (add in Persian, move with one click), health, settings; screenshots of every page (demo plates only)
PENDING (needs device): live video in the browser needs an approved WebRTC/HLS gateway (A.6); not enabled
Decisions needed: approve a live-video gateway (mediamtx can serve WebRTC/HLS from the annotated output stream)
```

## Incident: Jetson froze on 2026-10-13 after 16:03 (local time)

- **Running at the time:** the camera-like accuracy experiments (`tools/exp_video_accuracy.sh`, four DeepStream runs
  one after another over RTSP from mediamtx). All four had finished: the last (ROI) ended cleanly at 16:03:33
  (SIGTERM, final stats: 498 frames inferred, 40 events, 0 errors) and its result was written to
  `docs/bench/exp_accuracy.txt`. The freeze came at or right after that point; the mediamtx test server (two looping
  ffmpeg publishers) was still running.
- **Last memory reading:** none. These runs had no tegrastats log, and the journal of that boot was not persistent.
  The closest measurement: the 2-camera benchmark minutes before peaked at 5,255 MB used RAM (of 6,833 MB).
- **Since then:** persistent journald and earlyoom on (user); every run goes through `tools/guarded_run.sh`
  (docker `--memory=5g`, tegrastats log to file, watchdog kills the run below 800 MB available RAM), one pipeline at
  a time, sources increased one step at a time. Private images are never viewed, only measured numerically.

## M8 report

```
Milestone M8 — Integration, benchmark, hardening: DONE
Changed: deploy/compose.yaml (limits, capacity env), deepstream/app/{main,events,pipeline}.py, deepstream/Dockerfile
         (schema check), tools/{guarded_run.sh,run_grid.sh,exp_grid.py,bench_sources.py,bench_report.py,
         m8_stack_test.sh}, frontend (motion, forced password change), backend (migration 0003), docs/benchmark.md,
         docs/FINAL_REPORT.md, docs/bench/*, docs/screenshots/*
Checks run: tools/run_grid.sh -> 1/2/4 sources x default / interval 2 / max_fps 3 / ROI measured; 8 sources stopped by
              the watchdog (772 MB available); table in docs/benchmark.md and FINAL_REPORT.md
            tools/m8_stack_test.sh -> all containers healthy; forced password change enforced; each container
              restarted, no event lost (189/189 reached the DB); e2e 9/9 on the live stack; peak RAM 5,247 MB
            e2e on a fresh demo-only stack -> 10/10 incl. forced password change; screenshots in docs/screenshots
            unit tests: reader 44, deepstream 15, consumer 10, backend 24, frontend 18 -> all pass
PENDING (needs device): USB and CSI cameras (none attached); visual check of the face mask on the OSD output stream
              (private frames are never viewed by the agent): enable LPR_OSD=1 and LPR_OUTPUT_RTSP and look at it
Decisions needed: none (all decided by the user on 2026-10-13)
```

## Open items / PENDING (all)

1. USB and CSI cameras: not attached; configs and steps in the M4 report.
2. jetson_clocks: not used (user decision).
3. Live video in the browser: done 2026-10-13 at the user's request (raw + detection view, see decisions.md); LL-HLS part-duration warnings mean iOS Safari may stall on the ~3.5 fps detection stream.
4. Dashboard on the LAN: done (`FRONTEND_BIND=0.0.0.0`, forced admin password change).
5. Face-based person lists: stay forbidden (user decision).
6b. Face mask on the live detection stream: implemented and counted, not visually verified by me (private frames are never viewed); check it in the Live page.
6c. 8–10 fps per camera: not reachable with YOLO12x at 960 on Xavier NX mode 8 (see FINAL_REPORT section 1, 4).
6. Swapfile: not possible (no NVMe/SSD).
7. Real camera URLs/credentials: placeholders in `deploy/sources.yaml` / `deploy/.env`.
8. Real (non-synthetic) validation for Kaf, Gaf, Fe, D, S, protocol, Ze, free zone; no data at all for Se, Za, Pe (A.5).
9. I viewed one dumped private test frame during M4 debugging (sent to the model service); stopped and switched to
   numeric checks only.
