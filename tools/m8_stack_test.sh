#!/usr/bin/env bash
# M8 full-stack test: compose deployment with one RTSP test camera, forced admin password change, restart of every
# container in turn with a no-loss check (every event id in DeepStream's JSONL must reach the database), e2e checks.
# Runs under the memory watchdog. Prints counts and states only (no plate strings).
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . deploy/.env; set +a
export SOURCES_FILE=./test/sources.yaml
export LPR_DEDUP_S=5   # the test video loops every 24 s; production default 30 s would suppress every loop after the first
C="docker compose -f deploy/compose.yaml --env-file deploy/.env --profile test"
API=http://127.0.0.1:${FRONTEND_PORT:-8080}/api/v1
LOG=out/m8; rm -rf "$LOG"; mkdir -p "$LOG"

api() {  # method path [json] -> body (uses $TOKEN)
  python3 - "$@" <<'PY'
import json, os, sys, urllib.request
m, p = sys.argv[1], sys.argv[2]
body = sys.argv[3].encode() if len(sys.argv) > 3 else None
h = {"Content-Type": "application/json"}
if os.environ.get("TOKEN"):
    h["Authorization"] = "Bearer " + os.environ["TOKEN"]
r = urllib.request.Request(os.environ["API"] + p, data=body, method=m, headers=h)
try:
    print(urllib.request.urlopen(r, timeout=15).read().decode())
except urllib.error.HTTPError as e:
    print(json.dumps({"http_error": e.code, "body": e.read().decode()[:200]}))
PY
}
login() {
  python3 - "$1" <<'PY'
import json, os, sys, urllib.parse, urllib.request
d = urllib.parse.urlencode({"username": os.environ["ADMIN_USERNAME"], "password": sys.argv[1]}).encode()
try:
    r = json.load(urllib.request.urlopen(os.environ["API"] + "/auth/login", data=d, timeout=15))
    print(r["access_token"], r["must_change_password"])
except Exception as e:
    print("FAIL", e)
PY
}
export API
wait_healthy() {  # service
  local i s
  for i in $(seq 1 120); do
    s=$($C ps --format '{{.Service}} {{.Health}}' 2>/dev/null | awk -v s="$1" '$1==s {print $2}')
    [[ "$s" == "healthy" ]] && return 0
    sleep 5
  done
  echo "   $1 not healthy after 10 min"; return 1
}
noloss() {  # label
  local jsonl db
  jsonl=$(docker exec lpr-deepstream-1 python3 -c "
import json; print(' '.join(sorted(json.loads(l)['event_id'] for l in open('/data/events/events.jsonl'))))" 2>/dev/null)
  sleep 20   # let the consumer catch up
  db=$(python3 - <<'PY'
import json, os, urllib.request
ids, off = [], 0
while True:
    r = urllib.request.Request(os.environ["API"] + f"/events?limit=200&offset={off}", headers={"Authorization": "Bearer " + os.environ["TOKEN"]})
    page = json.load(urllib.request.urlopen(r, timeout=15))
    ids += [e["event_id"] for e in page["items"]]
    off += 200
    if off >= page["total"]:
        break
print(" ".join(sorted(ids)))
PY
)
  local nj nd missing
  nj=$(wc -w <<<"$jsonl"); nd=$(wc -w <<<"$db")
  missing=$(comm -23 <(tr ' ' '\n' <<<"$jsonl" | sort) <(tr ' ' '\n' <<<"$db" | sort) | grep -c . || true)
  echo "   [$1] events emitted (JSONL): $nj | in database: $nd | emitted but missing in DB: $missing"
}

echo "# M8 full-stack test $(date -u +%FT%TZ)"
$C down -v --remove-orphans >/dev/null 2>&1; echo "test volumes wiped (only test data of this project)"
tools/guarded_run.sh "$LOG/guard" sleep 3000 > "$LOG/guard.out" 2>&1 &
GUARD=$!
sleep 3
$C up -d >/dev/null 2>&1
for s in db kafka backend frontend deepstream; do wait_healthy $s && echo "   $s healthy"; done
read -r TOKEN FLAG <<<"$(login "$ADMIN_PASSWORD")"
echo "## forced password change: admin must_change_password=$FLAG"
export TOKEN
echo "   events before change: $(api GET '/events?limit=1' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("http_error"), d.get("body","")[:40])')"
api POST /auth/change-password "{\"current_password\": \"$ADMIN_PASSWORD\", \"new_password\": \"$E2E_NEW_PASSWORD\"}" >/dev/null
read -r TOKEN FLAG <<<"$(login "$E2E_NEW_PASSWORD")"; export TOKEN
echo "   after change: must_change_password=$FLAG"
sleep 120
echo "## steady state (one RTSP camera)"
api GET /status | python3 -c "
import json,sys; d=json.load(sys.stdin); i=d['inference']
print('   inference reachable:', i['reachable'], '| sources:', {k: (v['status'], v.get('fps_in'), v.get('fps_out')) for k,v in (i.get('sources') or {}).items()})
print('   worker:', {k: i['worker'][k] for k in ('frames','events','errors')} if i.get('worker') else None, '| db events:', d['database']['events'])"
noloss steady
for svc in deepstream kafka consumer backend db frontend; do
  echo "## restart $svc"
  $C restart $svc >/dev/null 2>&1
  wait_healthy $svc >/dev/null && echo "   $svc healthy again"
  if [[ $svc == db || $svc == backend ]]; then
    wait_healthy backend >/dev/null; sleep 5
    read -r TOKEN FLAG <<<"$(login "$E2E_NEW_PASSWORD")"; export TOKEN
  fi
  sleep 60
  noloss "after $svc restart"
done
echo "## e2e against the running stack (no screenshots: real test plates are on screen)"
docker run --rm --network lpr --memory 1g -e E2E_URL=http://frontend:8080 -e BACKEND_URL=http://backend:8000 \
  -e ADMIN_USERNAME=$ADMIN_USERNAME -e ADMIN_PASSWORD=$E2E_NEW_PASSWORD -e E2E_NEW_PASSWORD=$E2E_NEW_PASSWORD \
  -e INGEST_KEY=$INGEST_KEY lpr-e2e:1.0 2>&1 | sed 's/^/   /'
kill $GUARD 2>/dev/null; wait $GUARD 2>/dev/null
grep -h 'guarded run finished\|WATCHDOG' "$LOG/guard/mem.log" | sed 's/^/   guard: /'
awk '{for(i=1;i<=NF;i++) if($i=="RAM") {split($(i+1),a,"/"); if(a[1]>m) m=a[1]}} END {print "   peak RAM (board) during the test: " m " MB"}' "$LOG/guard/tegrastats.log"
echo "# done"
