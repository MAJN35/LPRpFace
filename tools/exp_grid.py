#!/usr/bin/env python3
"""One configuration of the M8 configuration table: N camera-like sources (RTSP from mediamtx, all streaming the
6-clip H.264 1080p test video, cam-01) under one setting; speed and plate-string accuracy in the same run.
Always run it through the guarded runner (memory rules):

    tools/guarded_run.sh out/grid/n2_default python3 tools/exp_grid.py --n 2 --max-fps 10 --interval 0 \
        --log out/grid/n2_default --out docs/bench/grid.jsonl

Accuracy = events whose plate_string_latin equals the clip's ground truth / clip appearances per source
(run seconds / video length x 6 clips), dedup window 5 s so repeated loops count. Speed = per-source fps_out
(inferred frames/s) and latency (muxer arrival -> after tracker) from the control API every 10 s. Peak RAM = max
used RAM in the run's tegrastats log (whole board). Output: one JSON line. Never prints plate strings.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDE = REPO / "tests/data/private/videos/test_h264.json"


def health(name):
    r = subprocess.run(["docker", "exec", name, "python3", "-c",
                        "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8090/health',timeout=5).read().decode())"],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--max-fps", type=float, default=10)
    ap.add_argument("--model", default="v2", help="model folder under models/ (v2, v3m, ...)")
    ap.add_argument("--profile", default="1,2,4", help="engine batch profile min,opt,max (must exist in engine_cache)")
    ap.add_argument("--m8-policy", action="store_true", help="event policy of the M8 runs: track timeout 1.5 s, one frame "
                    "per track, invalid reads emitted (the default is the current production policy)")
    ap.add_argument("--interval", type=int, default=0)
    ap.add_argument("--roi", action="store_true")
    ap.add_argument("--seconds", type=int, default=150)
    ap.add_argument("--log", type=Path, required=True, help="guarded run log dir (tegrastats.log)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    side = json.loads(SIDE.read_text())
    gt = {c["gt_string_latin"] for c in side["clips"]}
    name = f"lpr-ds-grid-{a.n}"
    tag = f"{a.model}{'_m8policy' if a.m8_policy else ''}_n{a.n}_mf{a.max_fps:g}_i{a.interval}{'_roi' if a.roi else ''}"
    out = REPO / "out" / "grid" / tag
    out.mkdir(parents=True, exist_ok=True)
    srcs = []
    for k in range(a.n):
        s = {"id": f"cam-{k + 1:02d}", "type": "rtsp", "uri": "rtsp://mediamtx:8554/cam-01", "max_fps": a.max_fps,
             "min_plate_px": 40}
        if a.roi:
            s["roi"] = [[0.2, 0.3], [0.8, 0.3], [0.8, 1], [0.2, 1]]
        srcs.append(s)
    (out / "sources.yaml").write_text(json.dumps({"sources": srcs}))
    rel = out.relative_to(REPO)
    subprocess.run(["docker", "compose", "-f", "deploy/compose.yaml", "--env-file", "deploy/.env", "--profile", "test",
                    "up", "-d", "mediamtx"], cwd=REPO, capture_output=True)
    env = dict(os.environ, LPR_DOCKER_NETWORK="lpr", LPR_DOCKER_ARGS=f"--name {name}")
    log = open(out / "app.log", "w")
    app = subprocess.Popen(["deepstream/run.sh", "env", "LPR_EVENT_SINKS=jsonl", f"LPR_SOURCES_FILE=/work/{rel}/sources.yaml",
                            "ENGINE_DIR=/engines", f"META_DIR=/work/models/{a.model}", f"ONNX_DIR=/work/models/{a.model}/export",
                            f"MODEL_VERSION={a.model}", f"BATCH_PROFILE={a.profile}", "LPR_FACES=0", "LPR_VIDEOS_DIR=/tmp/videos",
                            *(["LPR_TRACK_TIMEOUT_S=1.5", "LPR_MIN_TRACK_FRAMES=1", "LPR_EMIT_INVALID=1"] if a.m8_policy else []),
                            f"LPR_EVENTS_JSONL=/work/{rel}/events.jsonl", f"LPR_CROPS_DIR=/work/{rel}/crops",
                            f"LPR_JOBS_DIR=/work/{rel}/jobs", "LPR_IMAGE_API=0", "LPR_DEDUP_S=5",
                            f"LPR_INTERVAL={a.interval}", "python3", "-m", "app.main"],
                           cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 180:  # engine load + first frames of every source
        h = health(name)
        if h and all(v.get("status") == "live" for v in h["sources"].values()):
            break
        if app.poll() is not None:
            break
        time.sleep(3)
    start = time.time()
    samples = []
    while time.time() - start < a.seconds and app.poll() is None:
        time.sleep(10)
        h = health(name)
        if h:
            samples.append(h)
    run_s = time.time() - start
    subprocess.run(["docker", "stop", "-t", "20", name], capture_output=True)
    app.wait(timeout=120)
    end = start + run_s
    evs = [json.loads(l) for l in open(out / "events.jsonl")] if (out / "events.jsonl").exists() else []
    # only events finalized inside the measurement window (warm-up events would inflate the rate)
    import datetime as _dt
    ts = lambda e: _dt.datetime.strptime(e["processed_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=_dt.timezone.utc).timestamp()  # noqa: E731
    evs = [e for e in evs if start <= ts(e) <= end]
    appearances = run_s / (side["frames"] / side["fps"]) * len(side["clips"])
    per_clip = appearances / len(side["clips"])   # appearances of each clip in the window
    per = {}
    for s in srcs:
        sid = s["id"]
        mine = [e for e in evs if e["camera_id"] == sid]
        vals = [h["sources"].get(sid, {}) for h in samples]
        per[sid] = {"fps_out": round(statistics.mean(v.get("fps_out", 0) for v in vals), 2) if vals else 0,
                    # a split track can give two correct events for one appearance: cap per clip
                    "correct": sum(min(sum(1 for e in mine if e["plate_string_latin"] == g), per_clip) for g in gt),
                    "correct_events": sum(1 for e in mine if e["plate_string_latin"] in gt), "events": len(mine),
                    "latency_ms_p50": vals[-1].get("latency_ms_p50") if vals else None,
                    "latency_ms_p95": vals[-1].get("latency_ms_p95") if vals else None}
    ram = [int(m.group(1)) for m in re.finditer(r"RAM (\d+)/", (a.log / "tegrastats.log").read_text())] \
        if (a.log / "tegrastats.log").exists() else []
    acc = [p["correct"] / appearances for p in per.values()] if appearances else [0]
    res = {"config": tag, "model": a.model, "profile": a.profile, "policy": "m8" if a.m8_policy else "production", "sources": a.n, "max_fps": a.max_fps, "interval": a.interval, "roi": a.roi,
           "run_seconds": round(run_s), "window_utc": [round(start), round(end)], "fps_out_per_source_mean": round(statistics.mean(p["fps_out"] for p in per.values()), 2),
           "fps_out_per_source_min": min(p["fps_out"] for p in per.values()),
           "accuracy_mean": round(statistics.mean(acc), 3), "accuracy_min": round(min(acc), 3),
           "wrong_events": sum(p["events"] - p["correct_events"] for p in per.values()),
           "latency_ms_p50_max": max((p["latency_ms_p50"] or 0) for p in per.values()),
           "latency_ms_p95_max": max((p["latency_ms_p95"] or 0) for p in per.values()),
           "peak_ram_mb": max(ram) if ram else None, "power_mode": Path("/var/lib/nvpmodel/status").read_text().strip(),
           "per_source": per}
    with open(a.out, "a") as f:
        f.write(json.dumps(res) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "per_source"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
