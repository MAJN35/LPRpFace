# Benchmark (measured on the device)

Device: Jetson Xavier NX 8 GB (6.7 GiB usable), JetPack 5.1.2 / L4T 35.4.1, DeepStream 6.3, TensorRT 8.5.2.2.
**Power: nvpmodel mode 8 (MODE_20W_6CORE), jetson_clocks not run** (user decision). Model **v2**, TensorRT FP16,
engine profile 1/2/4, input 960×960. All numbers below were measured on 2026-10-13; nothing is estimated unless the
row says so. Raw data: `docs/bench/*.jsonl`, `docs/m3_throughput_v*.jsonl`.

## Engine only (trtexec, GPU compute)

| Model | Batch 1 | Batch 2 | Batch 4 |
|---|---|---|---|
| v2 images/s (GPU p50 / p95 ms) | 3.56 (277 / 281) | 3.61 (545 / 549) | 3.58 (1,081 / 1,089) |
| v1 images/s | 3.45 | 3.50 | 3.51 |

The GPU is saturated at batch 1 (GR3D ≈ 99 %): batching does not add throughput on this device; ~3.6 inferences/s
is the ceiling for YOLO12x at 960, shared by all cameras.

## How the configurations were measured

- Sources: camera-like RTSP streams from a local mediamtx server replaying the synthetic 6-clip test video
  (1920×1080 H.264 25 fps; each clip = one real test image with a known plate, zoomed like an approaching car).
- Output fps per source = frames inferred per second for that source (control API, every 10 s). Latency = muxer
  arrival → after the tracker (camera/network/decode delay not included). Peak RAM = whole board (tegrastats).
- Accuracy = correct plate-string events / clip appearances in a 150 s window, capped per clip (a split track cannot
  count twice), dedup window 5 s so every loop counts.
- Every run under the memory rules: docker `--memory=5g`, tegrastats logged, watchdog kills the run below 800 MB
  available RAM, one pipeline at a time, sources stepped 1 → 2 → 4 → 8 and stopped at the first step that crossed.

### Configuration table (camera-like RTSP sources, each streaming the 6-clip test video; v2 FP16, mode 8)

| Sources | max_fps | interval | ROI | Output fps per source (mean / min) | Plate-string accuracy per source (mean / min) | Wrong events | Latency p50 / p95 (ms, worst source) | Peak RAM (board) | Result |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 0 | no | 3.5 / 3.5 | 98 % / 98 % | 0 | 835.2 / 848.2 | 4672 MB | ok |
| 2 | 10 | 0 | no | 1.66 / 1.64 | 97 % / 97 % | 0 | 1656.1 / 1713.3 | 4877 MB | ok |
| 4 | 10 | 0 | no | 0.8 / 0.79 | 81 % / 81 % | 0 | 3379.7 / 3550.6 | 5368 MB | ok |
| 1 | 3 | 0 | no | 3.57 / 3.57 | 98 % / 98 % | 0 | 833.9 / 847.8 | 4606 MB | ok |
| 2 | 3 | 0 | no | 1.66 / 1.64 | 96 % / 96 % | 2 | 1652.1 / 1708.1 | 4814 MB | ok |
| 4 | 3 | 0 | no | 0.89 / 0.89 | 80 % / 79 % | 0 | 3370.4 / 3484.5 | 5253 MB | ok |
| 8 | | | | – | – | – | – | – | **stopped: watchdog: MemAvailable < 800 MB** (default_n8) |
| 1 | 10 | 0 | central 60 % | 3.5 / 3.5 | 81 % / 81 % | 12 | 834.9 / 850.6 | 4620 MB | ok |
| 2 | 10 | 0 | central 60 % | 1.71 / 1.71 | 86 % / 85 % | 28 | 1658.5 / 1700.1 | 4816 MB | ok |
| 4 | 10 | 0 | central 60 % | 0.89 / 0.89 | 59 % / 58 % | 30 | 3360.2 / 3487.3 | 5223 MB | ok |
| 1 | 10 | 2 | no | 2.64 / 2.64 | 92 % / 92 % | 0 | 344.9 / 424.7 | 4502 MB | ok |
| 2 | 10 | 2 | no | 1.46 / 1.46 | 96 % / 96 % | 0 | 654.5 / 733.1 | 4955 MB | ok |
| 4 | 10 | 2 | no | 0.75 / 0.75 | 80 % / 80 % | 0 | 1251.0 / 1352.7 | 5051 MB | ok |

### Scaling curve, default settings (RTSP cam-01/cam-02 mix, max_fps 10, interval 0; earlier run without the guarded runner)

| Sources | fps per camera (mean / min) | Total inferred fps | Latency p50 / p95 (ms) | GPU % | CPU % | RAM max | GPU / CPU °C max |
|---|---|---|---|---|---|---|---|
| 1 | 3.5 / 3.5 | 3.5 | 835.6 / 853.2 | 99.0 | 45.0 | 5175 MB | 63.5 / 61.0 |
| 2 | 1.82 / 1.82 | 3.64 | 1655.7 / 1704.3 | 99 | 46.9 | 5458 MB | 64.0 / 62.0 |
| 4 | 0.9 / 0.86 | 3.59 | 3349.2 / 3467.5 | 99 | 53.6 | 5914 MB | 64.0 / 62.0 |
| 8 | 0.34 / 0.32 | 2.72 | 3558.8 / 4203.8 | 99 | 66.5 | 6200 MB | 64.0 / 62.5 |

## Notes on the experiments

- **max_fps** (3 vs 10): no measurable change in output fps, accuracy or latency, because inference (not decoding)
  is the limit; it lowers decode/CPU work only. Use it to cap a fast camera, not to gain throughput.
- **interval 2** (infer every 3rd frame, tracker between): latency drops by ~2.5× (p95 0.42 s at 1 camera), GPU
  load drops; output fps per source is lower (2.64 vs 3.5 at 1 camera) and accuracy drops at 1 camera (92 % vs 98 %),
  is unchanged at 2 and 4 cameras.
- **ROI** (fixed central 60 % width × lower 70 %): worse here (59 % at 4 cameras, many wrong events), because the
  test clips move the plate across the frame and a fixed crop cuts plates at its edges. An ROI must be drawn per
  camera around the road area where plates actually pass; it is not a generic speed-up.
- **8 cameras**: the default run crossed the memory limit (772 MB available) and was stopped by the watchdog; the
  earlier unguarded run had reached 6.2 GB used, 0.34 fps per camera.
- **DLA**: not tested (would need a separate engine build of ~70 min; YOLO12's attention layers are expected to fall
  back to the GPU). **INT8**: out of scope (user decision).
