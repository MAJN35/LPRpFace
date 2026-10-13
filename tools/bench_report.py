#!/usr/bin/env python3
"""Markdown tables for docs/benchmark.md from the recorded measurements (no estimates).

    python3 tools/bench_report.py > docs/bench/tables.md
"""
import json
from pathlib import Path

B = Path(__file__).resolve().parents[1] / "docs" / "bench"


def rows(name):
    p = B / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def fmt(v, suffix=""):
    return "–" if v is None else f"{v}{suffix}"


print("### Configuration table (camera-like RTSP sources, each streaming the 6-clip test video; v2 FP16, mode 8)\n")
print("| Sources | max_fps | interval | ROI | Output fps per source (mean / min) | Plate-string accuracy per source "
      "(mean / min) | Wrong events | Latency p50 / p95 (ms, worst source) | Peak RAM (board) | Result |")
print("|---|---|---|---|---|---|---|---|---|---|")
latest = {}
for r in rows("grid.jsonl"):
    latest[r["config"]] = r          # a repeated configuration replaces its earlier run
for r in sorted(latest.values(), key=lambda r: (r.get("max_fps", 0) != 10 or r.get("interval", 0) != 0 or r.get("roi", False),
                                               r.get("interval", 0), r.get("roi", False), -r.get("max_fps", 10) if "max_fps" in r else 0,
                                               r["sources"])):
    if r.get("crossed_limit"):
        print(f"| {r['sources']} | | | | – | – | – | – | – | **stopped: {r['note']}** ({r['config']}) |")
        continue
    print(f"| {r['sources']} | {r['max_fps']:g} | {r['interval']} | {'central 60 %' if r['roi'] else 'no'} | "
          f"{r['fps_out_per_source_mean']} / {r['fps_out_per_source_min']} | "
          f"{100 * r['accuracy_mean']:.0f} % / {100 * r['accuracy_min']:.0f} % | {r['wrong_events']} | "
          f"{fmt(r['latency_ms_p50_max'])} / {fmt(r['latency_ms_p95_max'])} | {fmt(r['peak_ram_mb'], ' MB')} | ok |")

print("\n### Scaling curve, default settings (RTSP cam-01/cam-02 mix, max_fps 10, interval 0; earlier run without "
      "the guarded runner)\n")
print("| Sources | fps per camera (mean / min) | Total inferred fps | Latency p50 / p95 (ms) | GPU % | CPU % | RAM max | GPU / CPU °C max |")
print("|---|---|---|---|---|---|---|---|")
for r in rows("scaling_default.jsonl"):
    print(f"| {r['sources']} | {r['per_camera_fps_out_mean']} / {r['per_camera_fps_out_min']} | {r['total_fps_out']} | "
          f"{r['latency_ms_p50_max']} / {r['latency_ms_p95_max']} | {r['gpu_pct_mean']} | {r['cpu_pct_mean']} | "
          f"{r['ram_mb_max']} MB | {r['gpu_c_max']} / {r['cpu_c_max']} |")
