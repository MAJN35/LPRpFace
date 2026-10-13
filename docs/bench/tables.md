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
