#!/usr/bin/env python3
"""M8 multi-source scaling benchmark on the Jetson (host Python 3.8, stdlib only; drives docker).

    python3 tools/bench_sources.py --counts 1 2 4 --seconds 120 --max-fps 10 --interval 0 --out docs/bench/scaling.jsonl

For each source count N: N RTSP cameras from the local test server (mediamtx, compose profile "test"), alternating
cam-01 (1920x1080 H.264 25 fps) and cam-02 (2560x1440 H.265 20 fps); the DeepStream app runs with the cached v2
FP16 engine (profile 1/2/4). After warm-up, the control API's health (per-source fps_in, fps_out = inferred frames/s,
latency muxer -> after tracker p50/p95) is sampled every 10 s and tegrastats every 1 s (RAM, CPU, GR3D, temperatures).
One JSON line per N. Power mode is read from /var/lib/nvpmodel/status; jetson_clocks is not changed.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "deploy/compose.yaml", "--env-file", "deploy/.env", "--profile", "test"]
TEG = re.compile(r"RAM (\d+)/(\d+)MB.*CPU \[([^\]]+)\].*GR3D_FREQ (\d+)%.*CPU@([\d.]+)C.*GPU@([\d.]+)C")


def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, **kw)


def health():
    r = sh(["docker", "exec", "lpr-ds-bench", "python3", "-c",
            "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8090/health',timeout=5).read().decode())"])
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def tegra_sampler(samples, stop):
    p = subprocess.Popen(["tegrastats", "--interval", "1000"], stdout=subprocess.PIPE, text=True)
    for line in p.stdout:
        if stop.is_set():
            break
        m = TEG.search(line)
        if m:
            cpus = [int(c.split("%")[0]) for c in m.group(3).split(",") if "%" in c]
            samples.append({"ram_mb": int(m.group(1)), "cpu_pct": sum(cpus) / len(cpus), "gpu_pct": int(m.group(4)),
                            "cpu_c": float(m.group(5)), "gpu_c": float(m.group(6))})
    p.terminate()


def run_one(n, a):
    srcs = [{"id": f"cam-{k + 1:02d}", "type": "rtsp", "uri": f"rtsp://mediamtx:8554/cam-0{1 + k % 2}",
             "max_fps": a.max_fps, "min_plate_px": 40} for k in range(n)]
    if a.roi:
        for s in srcs:
            s["roi"] = [[0.2, 0.3], [0.8, 0.3], [0.8, 1], [0.2, 1]]   # experiment: central 60 % width, lower 70 %
    cfg = REPO / "out" / f"bench_sources_{n}.yaml"
    cfg.parent.mkdir(exist_ok=True)
    cfg.write_text(json.dumps({"sources": srcs}))
    out = f"out/bench_{n}"
    cmd = ["deepstream/run.sh", "env", "LPR_EVENT_SINKS=jsonl", f"LPR_SOURCES_FILE=/work/{cfg.relative_to(REPO)}",
           "ENGINE_DIR=/engines", "META_DIR=/work/models/v2", "ONNX_DIR=/work/models/v2/export",
           f"LPR_EVENTS_JSONL=/work/{out}/events.jsonl", f"LPR_CROPS_DIR=/work/{out}/crops",
           f"LPR_JOBS_DIR=/work/{out}/jobs", "LPR_IMAGE_API=0", f"LPR_INTERVAL={a.interval}", "python3", "-m", "app.main"]
    env = dict(__import__("os").environ, LPR_DOCKER_NETWORK="lpr", LPR_DOCKER_ARGS="--name lpr-ds-bench")
    log = open(REPO / "out" / f"bench_{n}.log", "w")
    app = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 180:
        h = health()
        if h and all(v.get("status") == "live" for k, v in h["sources"].items()):
            break
        time.sleep(3)
    time.sleep(a.warmup)
    teg, stop = [], threading.Event()
    th = threading.Thread(target=tegra_sampler, args=(teg, stop), daemon=True)
    th.start()
    hs, t1 = [], time.time()
    while time.time() - t1 < a.seconds:
        time.sleep(10)
        h = health()
        if h:
            hs.append(h)
    stop.set()
    sh(["docker", "stop", "-t", "20", "lpr-ds-bench"])
    app.wait(timeout=120)
    per = {}
    for sid in [s["id"] for s in srcs]:
        vals = [h["sources"].get(sid, {}) for h in hs]
        per[sid] = {"fps_in": round(statistics.mean(v.get("fps_in", 0) for v in vals), 2),
                    "fps_out": round(statistics.mean(v.get("fps_out", 0) for v in vals), 2),
                    "latency_ms_p50": vals[-1].get("latency_ms_p50") if vals else None,
                    "latency_ms_p95": vals[-1].get("latency_ms_p95") if vals else None,
                    "status": vals[-1].get("status") if vals else None}
    fo = [p["fps_out"] for p in per.values()]
    res = {"sources": n, "max_fps": a.max_fps, "interval": a.interval, "roi": a.roi, "seconds": a.seconds,
           "per_camera_fps_out_mean": round(statistics.mean(fo), 2), "per_camera_fps_out_min": min(fo),
           "total_fps_out": round(sum(fo), 2),
           "latency_ms_p50_max": max((p["latency_ms_p50"] or 0) for p in per.values()),
           "latency_ms_p95_max": max((p["latency_ms_p95"] or 0) for p in per.values()),
           "gpu_pct_mean": round(statistics.mean(t["gpu_pct"] for t in teg), 1) if teg else None,
           "cpu_pct_mean": round(statistics.mean(t["cpu_pct"] for t in teg), 1) if teg else None,
           "ram_mb_max": max(t["ram_mb"] for t in teg) if teg else None,
           "gpu_c_max": max(t["gpu_c"] for t in teg) if teg else None,
           "cpu_c_max": max(t["cpu_c"] for t in teg) if teg else None,
           "events": (hs[-1]["worker"]["events"] if hs else None),
           "worker_dropped": (hs[-1]["pipeline"].get("worker_dropped") if hs else None),
           "power_mode": Path("/var/lib/nvpmodel/status").read_text().strip(), "per_source": per}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counts", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--max-fps", type=float, default=10)
    ap.add_argument("--interval", type=int, default=0)
    ap.add_argument("--roi", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    sh(COMPOSE + ["up", "-d", "mediamtx"])
    time.sleep(5)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    for n in a.counts:
        r = run_one(n, a)
        with open(a.out, "a") as f:
            f.write(json.dumps(r) + "\n")
        print(json.dumps({k: v for k, v in r.items() if k != "per_source"}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
