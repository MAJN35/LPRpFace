#!/usr/bin/env bash
# Quick engine throughput (M3): trtexec on a cached engine at several batch sizes, inside the DeepStream image.
#   deepstream/scripts/bench_engine.sh engine_cache/<name>.engine 1 2 4
# Prints one JSON line per batch size: images/s (= trtexec qps x batch), GPU compute latency mean/p50/p95/p99.
set -euo pipefail
engine="${1:?engine path}"; shift
repo="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${DS_IMAGE:-nvcr.io/nvidia/deepstream-l4t:6.3-samples@sha256:e01bb8f5ba10584d752b83c7b3cf66c6e01c0e1afd2cdbb1ec31082e947b75cf}"
rel="$(realpath --relative-to="$repo" "$engine")"
for b in "${@:-1}"; do
  out="$(docker run --rm --runtime nvidia -v "$repo:/work" -w /work "$IMAGE" /usr/src/tensorrt/bin/trtexec \
    --loadEngine="/work/$rel" --shapes="images:${b}x3x960x960" --warmUp=3000 --duration=20 --percentile=50,95,99 2>&1)"
  qps="$(sed -n 's/.*Throughput: \([0-9.]*\) qps.*/\1/p' <<<"$out" | tail -1)"
  lat="$(grep 'GPU Compute Time: min' <<<"$out" | tail -1)"
  mean="$(sed -n 's/.*mean = \([0-9.]*\) ms.*/\1/p' <<<"$lat")"
  p50="$(sed -n 's/.*percentile(50%) = \([0-9.]*\) ms.*/\1/p' <<<"$lat")"
  p95="$(sed -n 's/.*percentile(95%) = \([0-9.]*\) ms.*/\1/p' <<<"$lat")"
  p99="$(sed -n 's/.*percentile(99%) = \([0-9.]*\) ms.*/\1/p' <<<"$lat")"
  if [[ -z "$qps" ]]; then echo "{\"batch\": $b, \"error\": \"trtexec failed\"}"; grep -iE 'error' <<<"$out" | tail -3 >&2; continue; fi
  ips="$(python3 -c "print(round($qps * $b, 2))")"
  echo "{\"batch\": $b, \"images_per_s\": $ips, \"batches_per_s\": $qps, \"gpu_ms_mean\": $mean, \"gpu_ms_p50\": $p50, \"gpu_ms_p95\": $p95, \"gpu_ms_p99\": $p99}"
done
