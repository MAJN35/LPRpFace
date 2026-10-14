# Candidate models v3m (YOLO12m) and v3_26n (YOLO26n) vs v2 — 2026-10-14

Same 48 classes and dataset as v2, input 960. Rule from the request: keep v2 in production unless a candidate is at
least as accurate on the 2-camera test stream. **Result: v2 stays.** v3m is faster but less accurate on the stream;
v3_26n did not produce a TensorRT engine.

## Results

| | v2 (YOLO12x) | v3m (YOLO12m) | v3_26n (YOLO26n) |
|---|---|---|---|
| TensorRT 8.5 FP16 engine | yes (existing, profile 1/2/4) | yes, profile 1/2/2, 45 min build, peak 4.8 GB | **no**: build hung (see below) |
| Parity, batch-1 engine vs static ONNX (16 images) | 44/45 (97.8 %) | 50/51 (98.0 %) | — |
| Test set, real overall (exact string) | 70.6 % (190/269) | **73.2 %** (197/269) | — |
| — real night | 74.6 % (47/63) | 74.6 % (47/63) | — |
| — real multi-plate | 39.1 % (18/46) | **41.3 %** (19/46) | — |
| — real plates with ت/ع/ا | 36.4 % (4/11) | **45.5 %** (5/11) | — |
| — synthetic plates with ت/ع/ا | 84.6 % (33/39) | **92.3 %** (36/39) | — |
| **2-camera test stream** (production event policy) | **89.1 %** | 79.8 % | — |
| 2-camera test stream (M8 event policy) | **96.7 %** | 90.5 % | — |
| fps per camera (2 cameras) | 1.6 | **4.9** | — |
| inferences/s (total) | 3.3 | **9.8** | — |
| engine time per image, test set (batch 2) | 295 ms | **114 ms** | — |
| peak RAM, whole board, 2-camera run | 5.5 GB | **4.6 GB** | — |

All numbers measured on this Jetson Xavier NX (nvpmodel mode 8, no jetson_clocks), TensorRT 8.5.2.2 FP16, DeepStream
padding (0). Stream: two RTSP cameras replaying the 6-clip 1080p test video, 150 s per run, max_fps 10, interval 0;
accuracy = correct events / clip appearances; **0 wrong reads** in every run. One run per model and policy.

## Notes

- **The ت/ع/ا group has only 11 real plates** (one plate = 9 points); test-set differences of 1–3 points between v2
  and v3m are a few plates.
- **Stream vs test set:** v3m reads still images slightly better but produces fewer events on the stream (36 per
  camera-run vs 39–40 for v2 with the M8 policy; none wrong): it misses about one clip appearance in ten. The test
  set has no camera motion, compression or plate-size changes over time, which the stream has.
- **Event policy:** the production policy (track ≥ 3 read frames, 3 s track timeout, plausible plates only; added
  2026-10-13) costs 7–11 points on this video for both models, because the test clips are cut back to back and a
  track can continue across a cut. Real traffic rarely puts two different plates in the same spot within 3 s, so the
  stream number with the production policy is pessimistic; the model comparison holds under both policies.
- **Detections per frame:** the parser, nvinfer `topk` and the Python decoder keep 300 per frame. The test set has
  at most 35 labelled objects per image; the engines produced at most 34 (v2) / 33 (v3m) candidate detections per
  image at confidence 0.10, so the cap was never reached. (The request mentions images with up to 586 objects; no
  such image is in agent_testset_v2.)
- **v3_26n on TensorRT 8.5:** the ONNX parsed (no unsupported-layer errors), then trtexec stopped logging at the
  tactic timing of `/model.16/m.0/cv2` (attention block) and ran one CPU core at ~97 % with the GPU idle for 26 min
  (v2's longest pause in its 72-min build was 2 min); stopped at 11:12 as instructed. Its delivered `_dynbatch.onnx`
  also leaves height and width dynamic (Shape/Range/Expand ops). A copy with height and width pinned to 960 (graph
  otherwise identical, weights bit-identical) is in `models/v3_26n/export_fixed/` and gives the same detections as
  the static ONNX (49/49 on the 16 parity images, batch 1 and 2) — **not built yet**; the likely fix.
- **M1 checks:** v3m and v3_26n pass checksums (SHA256SUMS written on first use), the A.4 class table, ONNX shapes
  and a CPU run; variable-batch ONNX = static ONNX on the 16 parity images (v3m 51/51, v3_26n 49/49).

Files: `docs/eval_v3/` (parity, accuracy JSON, stream.jsonl); private caches under `tests/data/private/cache/eval_v3/`.
