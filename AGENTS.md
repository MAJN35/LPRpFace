# AGENTS.md: Jetson DeepStream LPR platform (YOLO12x, model round 2)

Standing rules and facts. Reread at the start of every session. (Part A of the original agentic coding package.)

## A.1 Mission

Build a reproducible, containerized license plate recognition (LPR) platform: a fine-tuned YOLO12x detector running
in DeepStream/TensorRT on an NVIDIA Jetson, track-level Persian plate reading, events through Kafka, a backend API
with history, and a Neumorphism web dashboard. Inference stays on the Jetson. Everything else may run on the Jetson
or on a separate server (decided in milestone M0).

## A.2 Operating rules for the agent

1. **Work in milestones (Part B).** Finish one, verify it with its acceptance checks, write the report, then stop at
   every milestone marked **GATE** until I reply. Without a gate, continue to the next milestone.
2. **Ask before:** installing system packages on the Jetson, changing JetPack/driver/firmware, anything that sends data
   off the device (MQTT, HTTP, external Kafka, cloud), deleting files you did not create, exposing new ports,
   changing a class id, or changing input resolution/preprocessing defaults. Never do these silently.
3. **Never fabricate.** Do not claim a test, engine build, benchmark, camera or compatibility result you did not
   actually obtain. If something needs the Jetson and you cannot reach it, write the script, mark the result
   `PENDING (needs device)`, and give me the exact command to run and what output to paste back.
4. **Verify versions from primary sources** (NVIDIA docs, NGC tags, release notes, upstream repos) before relying on
   them, and cite the source in `docs/decisions.md`. Do not assume a DeepStream/TensorRT/YOLO12 integration works
   until you have run it.
5. **Keep a living status:** `docs/STATUS.md` (milestone checklist, current state, open questions, PENDING items) and
   `docs/decisions.md` (date, decision, reason, alternatives, source). Update both at the end of every milestone.
6. **Small, reviewable changes.** One logical change per commit, with a clear message. Never commit model weights,
   engines, crops, recordings, test images of real vehicles, `.env` files or secrets (add them to `.gitignore`).
7. **Tests first for logic.** Plate reading, decoding and event handling are pure functions with unit tests that run
   on an ordinary x86 machine without a GPU. Hardware-dependent checks are separate scripts.
8. **Pin everything:** base images by exact tag (never `latest`), Python/npm dependencies with lock files.
9. **Prefer the simplest reliable solution.** Reuse what already exists in the repository; do not add services,
   frameworks or abstractions that the requirements do not need.
10. **When blocked** (missing access, ambiguous requirement, contradictory facts), stop and ask one concrete question
    with your recommended answer, instead of guessing.

## A.3 Model artifacts (immutable)

Expected layout (create it if missing, ask me for the files):

```
models/
  v1/ yolo12x_lpr_face_ft_v1_best.pt  yolo12x_lpr_face_ft_v1_best.onnx  class_names.json  SHA256SUMS
  v2/ yolo12x_lpr_face_ft_v2_best.pt  yolo12x_lpr_face_ft_v2_best.onnx  class_names.json  SHA256SUMS
```

- Source bundles: `deliverables_yolo12x_lpr_face_ft_v1.zip`, `deliverables_yolo12x_lpr_face_ft_v2.zip`.
- **Default model: v2.** v1 must stay selectable (`MODEL_VERSION=v1|v2`) for A/B comparison and rollback.
- SHA-256: no reference checksums were supplied. They were computed from the files placed in `models/` on first use
  (2026-10-13) and written to `models/<ver>/SHA256SUMS`; those are the reference from then on and any later change
  must fail the check. The checksum, not the file name, is the model identity; verify it at startup.
- Never retrain, fine-tune, prune or otherwise modify the weights.

Facts (identical for v1 and v2):

| Property | Value |
|---|---|
| Framework | Ultralytics 8.3.141 |
| Architecture | YOLO12x (A2C2f area-attention), ~59 M parameters |
| Input | 1×3×960×960, RGB, letterboxed (Ultralytics pads with gray 114), pixels /255, no mean/std |
| ONNX | opset 17, static shape, exported with `export(format="onnx", imgsz=960, opset=17, simplify=True, dynamic=False)`, torch classic exporter (`dynamo=False`), onnxslim |
| ONNX output | `(1, 52, 18900)`: per anchor `cx, cy, w, h` (input pixels) + 48 sigmoid class scores; **no NMS inside** |
| Batch size | the delivered ONNX is **static batch 1**. Multi-source batching needs a re-export from the `.pt` with a fixed batch N or a dynamic batch axis (same export method, weights unchanged), followed by the parity check |
| History | v1: original 32-class `best.pt` with the head expanded to 48 and fine-tuned. v2: v1 + 4 epochs with ±8° rotation, more synthetic plates, more face proposals |

## A.4 Class ids (never renumber, merge or reorder)

| id | name | meaning |
|---|---|---|
| 0–9 | `0`…`9` | Persian digits ۰–۹ (also Latin digits on free-zone plates) |
| 10 Alef الف · 11 Be ب · 12 Te ت · 13 Se ث · 14 Jim ج · 15 Dal د · 16 Sin س · 17 Shin ش · 18 Sad ص · 19 Ta ط · 20 Za ظ · 21 Eyn ع · 22 Ghaf ق · 23 Lam ل · 24 Mim م · 25 Nun ن · 26 He ه · 27 Vav و · 28 Pe پ | | plate letters |
| 29 | Zhe | wheelchair symbol (disabled plates) |
| 30 | `plate` | whole plate |
| 31 Ye ی · 32 Ze ز | | plate letters |
| 33 | `face` | face (detection only, never identification) |
| 34 | `freezone` | free-zone plate panel |
| 35–41 | `fz_KISH`, `fz_QESHM`, `fz_CHABAHAR`, `fz_ARVAND`, `fz_ARAS`, `fz_ANZALI`, `fz_MAKU` | free-zone name text |
| 42 Kaf ک · 43 Gaf گ (transit) · 44 Fe ف | | letters |
| 45 D · 46 S | | diplomatic markers |
| 47 | `protocol` | protocol-plate badge |

All labels files and class dictionaries are generated from `class_names.json`. A startup check compares it with this
table and refuses to run on any mismatch.

## A.5 Known accuracy and limits (design around them, never hide them)

- Round 1, real test set, FP32 at 960: plate recall 0.97–0.99 (plates ≥ 60 px wide in the network input), 0.85
  below; characters recall 0.98 (≥ 24 px tall), 0.86 (12–24 px), ~0.22 (< 12 px); faces recall 0.94 (≥ 64 px),
  0.74 (24–64 px), 0.26 (< 24 px); exact plate string 63 % (original model 54 %).
- v2 vs v1 (per-class mAP50, same images): Lam +0.06, Zhe +0.03, Eyn +0.02, Jim/Be/He/Ye ≈ +0.01, **Sin −0.05**,
  digit 0 −0.015, plate and face unchanged. v2 exact plate string: unknown; measured for v1 and v2 on `agent_testset_v2` in M3 (see `docs/`).
- Common confusions: ۲↔۳ (~1 %), س→ص (~7 % on blurry plates), on rotated close-ups ع→ج and د→ل.
- Validated **only on synthetic plates** (real accuracy unknown): Kaf, Gaf, Fe, D, S, protocol, Ze, `freezone`, `fz_*`.
  No real validation data at all for Se, Za, Pe.
- Most plate false positives are a second, partial box on an already-detected plate.
- Reliable reading needs plates ≥ ~120 px wide in the 960 network input (≈ 240 px in a 1920-px-wide frame).
- License: Ultralytics YOLO is AGPL-3.0. Flag distribution obligations; do not assume private use removes them.

## A.6 Architecture (logical; placement decided in M0)

```
Sources (RTSP/RTMP/HTTP streams, USB, CSI, video files, still images, image folders, images uploaded via the API)
  -> source manager (sources.yaml + runtime add/remove) -> HW decode (NVDEC / NVJPG) -> nvstreammux (batch N)
  -> [optional nvdspreprocess: per-camera ROI] -> nvinfer (YOLO12x, TensorRT FP16, batch N) -> nvtracker (video only)
  -> probe (metadata only) -> reader worker -> event emitter -> (stdout JSON | Kafka) -> consumer -> backend + DB -> frontend
```

- Separate containers: `deepstream`, `kafka` (KRaft single broker unless more is needed), `consumer`, `backend`,
  `frontend`, and only if approved: a database and a WebRTC/HLS gateway for live video in the browser.
- Kafka is optional: standalone mode prints/stores JSON events without Kafka.
- One Docker network, only necessary ports exposed, Kafka never public, configuration through environment variables,
  `.env.example` without secrets, health checks, restart policies, graceful shutdown, persistent volumes
  (Kafka, DB, crops, engine cache), logs to stdout.

## A.7 Hard technical requirements

**DeepStream / TensorRT**
- Base image: official `nvcr.io/nvidia/deepstream-l4t` with the tag verified for the confirmed JetPack
  (Xavier: JetPack 5.1.x → DeepStream 6.3 / TensorRT 8.5; Nano: JetPack 4.6.x → DeepStream 6.0.1 / TensorRT 8.2,
  warn that YOLO12x at 960 may run < 1 FPS and opset 17 may not parse). Never an x86 image on the Jetson.
- Build the TensorRT engine on the Jetson (FP16 default). Name/cache it by model SHA-256 + TensorRT version + precision
  so a model change can never reuse a stale engine. Record build time and peak memory.
- If the ONNX does not parse: identify the exact operator, then re-export from the `.pt` with the method in A.3 at a
  verified opset, or use a DeepStream-YOLO integration only after verifying YOLO12/A2C2f support. Document it.
- Custom bbox parser for `(1, 52, 18900)`; class-aware NMS (IoU ≈ 0.5, plates and characters never suppress each
  other); per-class thresholds (plate 0.40, characters 0.35, face 0.35, synthetic-only classes 0.50); attach the
  per-box class-score vector (or top-k digit/letter scores) as user metadata for constrained decoding.
- Verify, do not assume, that preprocessing matches Ultralytics (RGB order, /255, letterbox geometry; DeepStream pads 0
  vs Ultralytics 114: measure the effect).
- Tracker tuned for small fast plates; configurable `interval`; RTSP reconnect and file EOS handling. The on-screen
  display may not shape Persian: draw the Latin form on the OSD, show Persian in the frontend.

**Input sources (all must work; each documented with its exact URI/config and tested)**
- Live: RTSP (H.264/H.265; TCP/UDP selectable; credentials from env, never logged), RTMP/HTTP(S)/HLS where GStreamer
  supports them, USB/UVC (V4L2: MJPEG and raw formats), CSI (`nvarguscamerasrc`), optional ONVIF discovery (approval).
- Recorded: video files (MP4/MKV/MOV/TS, H.264/H.265; optional loop for testing; play at real time or as fast as
  possible for batch analysis).
- Still images: single JPEG/PNG, a folder or glob of images, and images posted to the backend API (`POST /images` →
  forwarded to the inference service as an "image job"). Image mode = one frame per image, **no tracker and no
  temporal voting**: the reader runs once, the event type is `plate.recognized.image` and the event references the
  source file name. JPEG decode on the hardware decoder (`nvjpegdec`/NVJPG) where available, PNG via CPU decode.
- One `sources.yaml` (and env overrides) per deployment: `id`, `name`, `type`, `uri`, `enabled`, `max_fps`, `roi`
  (polygon), `min_plate_px`, `face_blur`, `record` (off by default). Sources can be **added, removed, enabled and
  disabled at runtime** (backend API → inference service) without restarting the pipeline; use the DeepStream
  mechanism verified for the confirmed version (for example `nvmultiurisrcbin` with its REST interface, or
  `nvstreammux` pad add/remove), and document it.
- Robustness per source: reconnect with backoff for live streams, EOS handling for files and image jobs, per-source
  health (connected, fps in/out, last frame time, errors), one failing source never stops the others.

**Multi-source performance (optimize for N cameras on one Jetson)**
- **Batching:** re-export the model with batch N or a dynamic batch axis and build the engine with an optimization
  profile (min 1, opt = typical number of sources, max = configured maximum); `nvstreammux` and `nvinfer`
  `batch-size` = number of active sources (capped by the engine max); tune `batched-push-timeout` so a slow camera
  does not stall the batch; `live-source=1` for live inputs. Cache one engine per (model SHA-256, TensorRT version,
  precision, batch profile).
- **Zero-copy GPU path:** hardware decode (NVDEC/NVJPG) into NVMM buffers, no CPU copies of frames; the probe only
  reads metadata; evidence crops are encoded on the GPU (DeepStream object encoder) only for the selected best frame.
- **Do less work per source:** per-camera `max_fps` (decoder frame dropping or rate limiting), `nvinfer interval`
  (skip frames while the tracker carries boxes), and per-camera ROI via `nvdspreprocess` so only the road area is
  inferred (this also makes plates larger in the network input). Each option is measured for speed and reading accuracy.
- **Keep the pipeline non-blocking:** `queue` elements between stages; the reader, voting and event emitting run in a
  worker thread/process fed by a bounded queue; never block the GStreamer streaming thread on I/O, Kafka or disk.
- **Hardware use:** document `nvpmodel` mode and `jetson_clocks`; on Xavier test whether parts of the network can run on
  the DLA cores (YOLO12 attention layers will likely fall back to the GPU; keep the GPU engine if DLA brings no gain).
  INT8 only if FP16 cannot reach the target, with calibration on real images and a measured accuracy change.
- **Capacity plan:** measure a scaling curve (1, 2, 4, … sources up to the device limit) and report, per source count:
  per-camera fps, end-to-end latency (p50/p95), GPU/CPU/RAM, temperature; derive the maximum number of cameras at
  the target fps (to be confirmed in M0) and expose it in the docs and the health endpoint.

**Reader library (pure Python or C++, unit-tested, no DeepStream dependency)**
- Merge duplicate/partial plate boxes (keep the one containing more character centers, then higher confidence).
- Assign characters to the plate containing their center; one character → at most one plate; drop duplicate boxes on
  the same glyph but keep the alternative class for decoding.
- Layouts: standard (`2 digits + letter + 3 digits | 2-digit code`); free-zone (two rows with the same number, Persian
  and Latin, same digit classes: split rows, read both, cross-check; zone from the most confident `fz_*`); transit
  (Gaf, small expiry-date digits in the right box reported as `expiry`, not in the number); disabled (Zhe), diplomatic
  (D/S), protocol: report type and markers, `not_applicable` where no validated format rule exists.
- Constrained decoding: digit slots choose only among digit classes, the letter slot only among letter classes, using
  the class-score vector; keep the margin as per-character confidence.
- Output `plate_string_fa` (e.g. `۱۲ ب ۳۴۵ | ۶۷`), `plate_string_latin` (e.g. `12 B 345 | 67`, documented
  transliteration), ordered `characters` with class id, name, confidence and box, `is_valid` + `invalid_reason`.
  Invalid reads are returned, never dropped. Normalize ي/ی, ك/ک and Arabic-Indic/Persian/ASCII digits.
- Track-level voting per character position, weighted by confidence and plate size, limited weight for
  near-identical consecutive frames, track timeout, deduplication of the same plate from the same camera within N
  seconds; one final event per plate track; best (largest, sharpest) frame saved as the evidence crop.

**Events (schema 2.0, JSON, versioned)**
`event_id, event_type (plate.recognized | plate.recognized.image), source{id, type, uri_redacted, file_name},
camera_id, timestamp (UTC capture time, or file/upload time for images), track_id (null for images),
model{version, sha256, engine_sha256, precision, batch_profile}, plate_type, plate_string_fa, plate_string_latin, zone, expiry, markers, characters, confidence, is_valid,
invalid_reason, frames_voted, plate_bbox, frame_size, best_frame_crop_path`. No images inside events.
Kafka topics (configurable): `lpr.plate.events`, `lpr.face.events` (only if enabled), `lpr.system.events`,
`lpr.dead-letter`. Bounded producer queue, retries, idempotent consumer (event id), explicit offset commits,
dead-letter queue; inference never blocks on Kafka or the backend; no exactly-once claims.

**Backend** (reuse the existing stack; otherwise propose FastAPI and wait for my OK): health/readiness, status,
cameras/sources (list, add, remove, enable/disable, health), image
upload for one-off recognition (size and type limits, results returned when ready), recent and paginated history, search by Persian or Latin plate (normalized), filters (camera, time, type,
zone, validity, model version), event detail, statistics, live updates via WebSocket or SSE, OpenAPI docs, idempotent
writes, retention, migrations, authentication when exposed beyond a trusted LAN, CORS restricted, no secrets or
internal paths in responses.

**Watchlists (persons and plates; added 2026-10-13 at the user's request)**
- Every registered plate and every person is on exactly one list: `whitelist`, `blocklist` or `unknown` (default).
  Plates are stored by their normalized `plate_key` (any Persian/Latin form, digit script or spacing maps to the
  same entry); a plate may be linked to one person.
- Effective status of a recognized plate: the plate's own list, unless it is `unknown` and its linked person is on
  `whitelist`/`blocklist`, then the person's list. Unregistered plates are `unknown`.
- Every event stores the effective list status and the linked person at ingest time; history can be filtered by
  it; a `blocklist` hit is pushed to the dashboard as an alert. No action leaves the device (no gate control, no
  external notification) without separate approval.
- Moving an entry between lists must be one action (per row and in bulk), for operators and admins; viewers read
  only. Every list change and every person view is written to the audit log.
- A person is a record (name, optional notes) linked to plates. Persons are never identified, matched or enrolled
  by face (see Privacy); changing that needs an explicit change of the privacy rule below.

**Frontend** (reuse the existing framework; otherwise propose React + TypeScript and wait for my OK): Neumorphism
(soft UI) industrial dashboard built on design tokens (CSS variables) with high contrast and visible focus; pages:
Overview, Live, History, Event detail, System health, Settings; loading/empty/error/disconnected/stale states; no mock
data in production; responsive; keyboard accessible; reduced motion; Persian plates rendered right-to-left with a
self-hosted Persian font (e.g. Vazirmatn, check license) next to the Latin form; live video through an approved
WebRTC/HLS gateway (browsers cannot play RTSP).

**Privacy and data**: face detection only (no identification, matching or enrollment); optional face blur on the
output stream; no face crops stored by default; plates and crops are personal data: access control, retention with
automatic deletion, audit log of views/exports; nothing leaves the Jetson without my explicit approval; no telemetry.

**Time**: verify NTP sync on the Jetson; store UTC; document whether RTSP events use capture or processing time.

## A.8 Repository layout (adapt to what exists)

```
deepstream/ (Dockerfile, app/, parsers/, configs/, scripts/, tests/)
reader/     (plate-reading library + unit tests)
consumer/   backend/   frontend/   kafka/
models/     (v1/, v2/ — weights git-ignored, SHA256SUMS committed)
deploy/     (compose.yaml, compose.override.yaml, .env.example)
tools/      (check_model, parity, benchmark, export scripts)
tests/      (integration; real images git-ignored under tests/data/private/)
docs/       (STATUS.md, decisions.md, architecture.md, benchmark.md, privacy.md, README sections)
```

## A.9 Definition of done (whole project)

- `docker compose up` starts the full stack; a standalone mode runs DeepStream without Kafka.
- On the Jetson: engine built from the verified model, parity report passes, live or file input produces plate events
  that reach the dashboard; restart of any single container recovers without data loss.
- Every source type (RTSP, USB, CSI, video file, single image, image folder, API image upload) works and is documented;
  several sources run together with batched inference, and sources can be added/removed at runtime.
- The measured maximum number of cameras at the target fps is documented with the recommended per-camera settings.
- All unit and integration tests pass in CI-style commands documented in the README; hardware-only checks have
  scripts and recorded results.
- `docs/benchmark.md` contains measured numbers (no estimates presented as measurements); `docs/STATUS.md` lists all
  open items and limitations.
