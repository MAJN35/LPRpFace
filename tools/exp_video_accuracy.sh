#!/usr/bin/env bash
# Accuracy side of the M8 experiments, measured like a camera: the 6-clip test video served by mediamtx as RTSP
# (looping, cam-01), consumed live (leaky queues, frame drops) for SECONDS under one setting.
#   tools/exp_video_accuracy.sh <name> <max_fps> <interval> [roi] [sources]
# Metric: correct events / clip appearances (loops x 6 clips); wrong events listed as a count only.
set -euo pipefail
cd "$(dirname "$0")/.."
name="$1"; maxfps="$2"; interval="$3"; roi="${4:-}"; secs="${SECONDS_RUN:-150}"
out="out/exp_$name"; rm -rf "$out"; mkdir -p "$out"
roi_line=""
[[ -n "$roi" && "$roi" != "none" ]] && roi_line=", roi: [[0.2, 0.3], [0.8, 0.3], [0.8, 1], [0.2, 1]]"
echo "sources: [{id: cam-01, type: rtsp, uri: 'rtsp://mediamtx:8554/cam-01', max_fps: $maxfps, min_plate_px: 40$roi_line}]" > "$out/sources.yaml"
docker compose -f deploy/compose.yaml --env-file deploy/.env --profile test up -d mediamtx >/dev/null 2>&1
LPR_DOCKER_NETWORK=lpr LPR_DOCKER_ARGS="--name lpr-ds-exp" deepstream/run.sh env LPR_EVENT_SINKS=jsonl \
  LPR_SOURCES_FILE=/work/$out/sources.yaml ENGINE_DIR=/engines META_DIR=/work/models/v2 ONNX_DIR=/work/models/v2/export \
  LPR_EVENTS_JSONL=/work/$out/events.jsonl LPR_CROPS_DIR=/work/$out/crops LPR_JOBS_DIR=/work/$out/jobs LPR_IMAGE_API=0 \
  LPR_DEDUP_S=5 LPR_INTERVAL="$interval" python3 -m app.main > "$out/app.log" 2>&1 &
app=$!
for i in $(seq 1 60); do grep -q 'input 1920x1080' "$out/app.log" 2>/dev/null && break; sleep 3; done
start=$(date +%s); sleep "$secs"; docker stop -t 20 lpr-ds-exp >/dev/null; wait $app || true
python3 - "$out/events.jsonl" "$secs" "$name" "$maxfps" "$interval" "${roi:-none}" <<'PY'
import collections, json, sys
path, secs, name, maxfps, interval, roi = sys.argv[1], float(sys.argv[2]), *sys.argv[3:]
side = json.load(open("tests/data/private/videos/test_h264.json"))
gt = {c["gt_string_latin"] for c in side["clips"]}
ev = [json.loads(l) for l in open(path)] if open(path).read().strip() else []
appearances = secs / (side["frames"] / side["fps"]) * len(side["clips"])
ok = sum(1 for e in ev if e["plate_string_latin"] in gt)
fv = sorted(e["frames_voted"] for e in ev)
print(f"[{name} max_fps={maxfps} interval={interval} roi={roi}] correct events {ok} / ~{appearances:.0f} clip appearances "
      f"({100 * ok / appearances:.0f} %), wrong/partial events {len(ev) - ok}, frames voted median {fv[len(fv)//2] if fv else 0}")
PY
