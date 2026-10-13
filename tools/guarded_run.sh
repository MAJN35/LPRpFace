#!/usr/bin/env bash
# Run one experiment/benchmark/pipeline under the Jetson memory rules (docs/STATUS.md, incident 2026-10-13):
#   tools/guarded_run.sh <log dir> <command ...>
# - tegrastats every second -> <log dir>/tegrastats.log
# - watchdog every second -> <log dir>/mem.log; if MemAvailable < ${MIN_AVAIL_MB:-800} MB it kills every container
#   labelled lpr.guarded=1 (deepstream/run.sh sets it) and the command, writes WATCHDOG to the log, exits 99
# - refuses to start if another guarded container is running (one pipeline at a time)
# deepstream/run.sh adds docker --memory=${LPR_MEMORY_LIMIT:-5g}. Note: GPU (nvmap) memory is probably not charged
# to the container's cgroup on Jetson, which is why the host-level watchdog is the real guard.
set -uo pipefail
logdir="${1:?log dir}"; shift
mkdir -p "$logdir"
rm -f "$logdir/mem.log" "$logdir/tegrastats.log"   # every run starts with fresh logs
min="${MIN_AVAIL_MB:-800}"
if [[ -n "$(docker ps -q --filter label=lpr.guarded=1)" ]]; then
  echo "another guarded run is active; one pipeline at a time" >&2; exit 98
fi
avail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
tegrastats --interval 1000 --logfile "$logdir/tegrastats.log" &
teg=$!
setsid "$@" &
cmd=$!
status=0
while kill -0 "$cmd" 2>/dev/null; do
  a=$(avail)
  echo "$(date -u +%FT%TZ) avail_mb=$a" >> "$logdir/mem.log"
  if (( a < min )); then
    echo "$(date -u +%FT%TZ) WATCHDOG: MemAvailable ${a} MB < ${min} MB, killing the run" | tee -a "$logdir/mem.log" >&2
    docker ps -q --filter label=lpr.guarded=1 | xargs -r docker kill >/dev/null 2>&1
    kill -TERM -- "-$cmd" 2>/dev/null; sleep 3; kill -KILL -- "-$cmd" 2>/dev/null
    status=99
    break
  fi
  sleep 1
done
wait "$cmd" 2>/dev/null; rc=$?
[[ $status -eq 0 ]] && status=$rc
kill "$teg" 2>/dev/null; wait "$teg" 2>/dev/null
low=$(grep -o 'avail_mb=[0-9]*' "$logdir/mem.log" | cut -d= -f2 | sort -n | head -1)
echo "guarded run finished: exit $status, lowest MemAvailable ${low} MB (limit ${min} MB)" | tee -a "$logdir/mem.log"
exit $status
