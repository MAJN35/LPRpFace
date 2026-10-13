#!/usr/bin/env bash
# M4 runtime test on the Jetson: mixed sources, broken source, runtime add/remove, RTSP disconnect/reconnect,
# API image job, clean shutdown. Prints counts/statuses only (no plate strings).
#   tools/m4_runtime_test.sh > docs/m4_runtime.txt
set -uo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
C="docker compose -f deploy/compose.yaml --env-file deploy/.env --profile test"
OUT=out/m4rt; rm -rf "$OUT"; mkdir -p "$OUT"
cat > out/m4rt_sources.yaml <<'EOF'
defaults: {max_fps: 10, min_plate_px: 40, face_blur: true, rtsp_transport: tcp}
sources:
  - {id: video-loop, type: file, uri: /work/tests/data/private/videos/test_h264.mp4, loop: true, realtime: true}
  - {id: cam-01, type: rtsp, uri: "rtsp://mediamtx:8554/cam-01"}
  - {id: broken, type: rtsp, uri: "rtsp://mediamtx:8554/does-not-exist"}
EOF
ctl() {  # control API call from inside the DeepStream container
  docker exec lpr-ds-test python3 -c "
import json,sys,urllib.request
m,p=sys.argv[1],sys.argv[2]; body=sys.argv[3].encode() if len(sys.argv)>3 else None
r=urllib.request.Request('http://127.0.0.1:8090'+p,data=body,method=m,headers={'Content-Type':'application/json'})
print(urllib.request.urlopen(r,timeout=10).read().decode())" "$@"
}
status() {
  ctl GET /health | python3 -c "
import json,sys; h=json.load(sys.stdin)
print('  ', '; '.join(f\"{k}: {v['status']} fps_in={v.get('fps_in')} frames={v.get('frames_in')} reconnects={v.get('reconnects',0)}\" for k,v in sorted(h['sources'].items())))
print('   worker:', {k: h['worker'][k] for k in ('frames','reads','events','dedup_suppressed','errors','queue')}, 'pipeline:', h['pipeline'])"
}
echo "# M4 runtime test $(date -u +%FT%TZ)"
$C up -d mediamtx >/dev/null 2>&1 && echo "mediamtx (test RTSP server) up"
sleep 5
LPR_DOCKER_NETWORK=lpr LPR_DOCKER_ARGS="--name lpr-ds-test --network-alias deepstream" deepstream/run.sh env LPR_EVENT_SINKS=jsonl \
  LPR_SOURCES_FILE=/work/out/m4rt_sources.yaml ENGINE_DIR=/engines META_DIR=/work/models/v2 ONNX_DIR=/work/models/v2/export \
  LPR_EVENTS_JSONL=/work/$OUT/events.jsonl LPR_CROPS_DIR=/work/$OUT/crops LPR_JOBS_DIR=/work/$OUT/jobs \
  LPR_CONTROL_HOST=0.0.0.0 LPR_IMAGE_API=1 LPR_RUNTIME_SOURCES=/work/$OUT/sources.runtime.json LPR_LIVE=${LPR_LIVE:-0} LPR_MEDIA_RTSP=rtsp://media:8554 LPR_MEDIA_API=http://media:9997 \
  python3 -m app.main > "$OUT/app.log" 2>&1 &
APP=$!
for i in $(seq 1 60); do ctl GET /health >/dev/null 2>&1 && break; sleep 2; done
sleep 60
echo "## 1. three sources at start (file loop + RTSP H.264 + broken RTSP), after 60 s"; status
if [[ "${LPR_LIVE:-0}" == "1" ]]; then
  echo "## 1b. live view (a viewer opens cam-01 raw and cam-01 with detections)"
  docker compose -f deploy/compose.yaml --env-file deploy/.env up -d media >/dev/null 2>&1
  for path in cam-01-osd cam-01; do
    code=000
    for i in $(seq 1 12); do
      code=$(docker exec lpr-ds-test curl -s -o /dev/null -w '%{http_code}' "http://media:8888/$path/index.m3u8")
      [[ $code == 200 ]] && break; sleep 3
    done
    info=$(docker run --rm --network lpr --entrypoint ffprobe bluenviron/mediamtx:1.12.3-ffmpeg@sha256:f4bbb3af99b7d9a812499f69f6dd3de5ac54339a788c1c5e45dc36f9c1dffbd3 \
      -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=codec_name,width,height,avg_frame_rate -of csv=p=0 "rtsp://media:8554/$path" 2>&1 | head -1)
    echo "   $path: HLS playlist HTTP $code | stream: $info"
  done
  echo "   without login through nginx: HTTP $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/hls/cam-01/index.m3u8)"
  ctl GET /health | python3 -c "import json,sys; h=json.load(sys.stdin); print('   cam-01 live:', h['sources']['cam-01'].get('live'))"
fi
echo "## 2. runtime add cam-02 (RTSP H.265 2560x1440)"
ctl POST /sources '{"id": "cam-02", "type": "rtsp", "uri": "rtsp://mediamtx:8554/cam-02", "max_fps": 10}' >/dev/null && echo "   added"
sleep 60; status
echo "## 3. runtime remove cam-02"
ctl DELETE /sources/cam-02 >/dev/null && echo "   removed"
sleep 30; status
echo "## 4. RTSP disconnect: stop the RTSP server for 40 s"
$C stop mediamtx >/dev/null 2>&1; sleep 40; status
$C start mediamtx >/dev/null 2>&1; echo "   RTSP server back"; sleep 90; status
echo "## 5. image job through the control API"
JOB=$(docker exec -i lpr-ds-test python3 -c "
import json,sys,urllib.request
data=open('/work/tests/data/private/images_folder/'+sorted(__import__('os').listdir('/work/tests/data/private/images_folder'))[0],'rb').read()
r=urllib.request.Request('http://127.0.0.1:8090/images?name=job.jpg',data=data,method='POST')
print(json.load(urllib.request.urlopen(r,timeout=10))['job_id'])")
sleep 15
ctl GET "/images/$JOB" | python3 -c "import json,sys; r=json.load(sys.stdin); print('   job', r['status'], 'events', len(r['events']), 'plate read' if r['events'] and r['events'][0]['plate_string_latin'] else 'no plate')"
echo "## 6. stop (SIGTERM)"
docker stop -t 20 lpr-ds-test >/dev/null; wait $APP
grep -E "final stats" "$OUT/app.log" | sed 's/^/   /'
python3 - "$OUT/events.jsonl" <<'PY'
import collections, json, sys
evs = [json.loads(l) for l in open(sys.argv[1])]
c = collections.Counter((e["source"]["id"], e["event_type"]) for e in evs)
print("## events per source:", dict(c))
print("   with crop:", sum(1 for e in evs if e["best_frame_crop_path"]), "of", len(evs),
      "| valid:", sum(1 for e in evs if e["is_valid"]), "| source URIs redacted:", all("@" not in e["source"]["uri_redacted"] for e in evs))
PY
$C stop mediamtx >/dev/null 2>&1
echo "# done"
