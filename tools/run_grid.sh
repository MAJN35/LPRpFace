#!/usr/bin/env bash
# M8 configuration table: every setting, sources increased one step at a time, each step a guarded run
# (tools/guarded_run.sh). A step that ends with the watchdog (exit 99) stops that setting: no larger N is tried.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT="${OUT:-docs/bench/grid.jsonl}"
max8=0
run_setting() {  # name max_fps interval roi_flag counts...
  local name=$1 mf=$2 iv=$3 roi=$4; shift 4
  for n in "$@"; do
    if [[ $n -eq 8 && $name != default && $max8 -eq 0 ]]; then echo "skip $name n=8 (default did not pass n=8)"; continue; fi
    local log="out/grid_logs/${name}_n${n}"; rm -rf "$log"
    tools/guarded_run.sh "$log" python3 tools/exp_grid.py --n "$n" --max-fps "$mf" --interval "$iv" $roi --log "$log" --out "$OUT"
    rc=$?
    if [[ $rc -eq 99 ]]; then
      echo "{\"config\": \"${name}_n${n}\", \"sources\": $n, \"crossed_limit\": true, \"note\": \"watchdog: MemAvailable < 800 MB\"}" >> "$OUT"
      echo "STOP $name at n=$n (memory limit)"; return
    fi
    [[ $name == default && $n -eq 8 && $rc -eq 0 ]] && max8=1
    sleep 10
  done
}
run_setting default 10 0 "" 1 2 4 8
run_setting interval2 10 2 "" 1 2 4 8
run_setting roi 10 0 --roi 1 2 4 8
run_setting maxfps3 3 0 "" 1 2 4 8
echo "grid done"
