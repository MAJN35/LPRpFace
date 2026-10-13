# Decoder parity on CPU (M2)

Date: 2026-10-13. Device: Jetson Xavier NX CPU (tools container `lpr-tools:cpu`, Python 3.10.22, torch 2.11.0+cpu,
Ultralytics 8.3.141, onnxruntime 1.23.2). Command:

```
tools/run_cpu.sh python -u tools/parity.py --model-dir models/<ver> --sample 24 --json-out docs/parity_cpu_<ver>.json
```

- **Reference:** Ultralytics `YOLO(<ver>.pt).predict(imgsz=960, conf=0.25, iou=0.5, rect=False, device='cpu')`.
  `rect=False` gives the full 960×960 letterbox (pad 114) used by the ONNX/TensorRT path.
- **Candidate:** the delivered batch-1 ONNX on onnxruntime CPU FP32 + `lpr_reader.decode` (conf 0.25, class-aware
  NMS IoU 0.5, letterbox inverse).
- **Images:** 24, a deterministic sample spread over the test-set groups (`stratified_sample`): synthetic_test, test.
- **Match rule:** same class and IoU ≥ 0.9, one-to-one, greedy by score. Acceptance: ≥ 98 % of reference detections.

| Model | Reference detections | Matched | Rate | Extra candidate boxes | Class shifts | Max \|Δscore\| |
|---|---|---|---|---|---|---|
| v2 | 221 | 221 | 100.00 % | 0 | 0 | 6.0e-06 |
| v1 | see below | | | | | |

Result: **v2 PASS** (100 %).
