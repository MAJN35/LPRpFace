#!/usr/bin/env bash
# Build (or reuse) the TensorRT engine for a model version, inside the DeepStream container.
#
#   deepstream/scripts/build_engine.sh v2                 # FP16, profile 1/2/4 (defaults)
#   PRECISION=fp32 MAX_BATCH=8 OPT_BATCH=4 deepstream/scripts/build_engine.sh v1
#
# Input: models/<ver>/export/*_dynbatch.onnx (M1). The engine is cached in $ENGINE_DIR under a name made of the
# ONNX SHA-256, the TensorRT version, the precision and the batch profile, so a changed model, TensorRT or
# profile can never reuse a stale engine. A <engine>.json sidecar records the command, build time and peak memory.
set -euo pipefail
ver="${1:?model version (v1|v2)}"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
PRECISION="${PRECISION:-fp16}"
MIN_BATCH="${MIN_BATCH:-1}" OPT_BATCH="${OPT_BATCH:-2}" MAX_BATCH="${MAX_BATCH:-4}"
WORKSPACE_MIB="${WORKSPACE_MIB:-2048}"
ENGINE_DIR="${ENGINE_DIR:-$repo/engine_cache}"
IMAGE="${DS_IMAGE:-nvcr.io/nvidia/deepstream-l4t:6.3-samples@sha256:e01bb8f5ba10584d752b83c7b3cf66c6e01c0e1afd2cdbb1ec31082e947b75cf}"

onnx="$(ls "$repo"/models/"$ver"/export/*_dynbatch.onnx)"
sha="$(sha256sum "$onnx" | cut -d' ' -f1)"
trt_ver="$(docker run --rm --runtime nvidia "$IMAGE" python3 -c 'import tensorrt; print(tensorrt.__version__)' 2>/dev/null | tail -1)"
name="${ver}_${sha:0:16}_trt${trt_ver}_${PRECISION}_b${MIN_BATCH}-${OPT_BATCH}-${MAX_BATCH}.engine"
mkdir -p "$ENGINE_DIR"
if [[ -s "$ENGINE_DIR/$name" && -s "$ENGINE_DIR/$name.json" ]]; then
  echo "cached: $ENGINE_DIR/$name"
  exit 0
fi

shape() { echo "images:${1}x3x960x960"; }
flags=()
[[ "$PRECISION" == "fp16" ]] && flags+=(--fp16)
log="$ENGINE_DIR/$name.log"
mem_log="$ENGINE_DIR/$name.mem"
( while sleep 1; do free -m | awk '/Mem/{print $3, $7}'; done ) > "$mem_log" &
mon=$!
start=$(date +%s)
set +e
docker run --rm --runtime nvidia -v "$repo:/work" -v "$ENGINE_DIR:/engines" -w /work "$IMAGE" \
  /usr/src/tensorrt/bin/trtexec --onnx="/work/${onnx#$repo/}" --saveEngine="/engines/$name.tmp" \
  --minShapes="$(shape "$MIN_BATCH")" --optShapes="$(shape "$OPT_BATCH")" --maxShapes="$(shape "$MAX_BATCH")" \
  --memPoolSize=workspace:"$WORKSPACE_MIB" "${flags[@]}" --skipInference --verbose > "$log" 2>&1
rc=$?
set -e
secs=$(( $(date +%s) - start ))
kill "$mon" 2>/dev/null || true
peak_used=$(sort -n "$mem_log" | tail -1 | cut -d' ' -f1)
min_avail=$(awk '{print $2}' "$mem_log" | sort -n | head -1)
if [[ $rc -ne 0 ]]; then
  echo "BUILD FAILED (rc=$rc, ${secs}s, peak used ${peak_used} MiB, min available ${min_avail} MiB); log: $log" >&2
  grep -E "ERROR|Error|error" "$log" | tail -5 >&2
  exit $rc
fi
mv "$ENGINE_DIR/$name.tmp" "$ENGINE_DIR/$name"
cat > "$ENGINE_DIR/$name.json" <<JSON
{
  "engine": "$name",
  "engine_sha256": "$(sha256sum "$ENGINE_DIR/$name" | cut -d' ' -f1)",
  "onnx": "${onnx#$repo/}",
  "onnx_sha256": "$sha",
  "tensorrt": "$trt_ver",
  "precision": "$PRECISION",
  "batch_profile": [$MIN_BATCH, $OPT_BATCH, $MAX_BATCH],
  "workspace_mib": $WORKSPACE_MIB,
  "image": "$IMAGE",
  "build_seconds": $secs,
  "host_mem_peak_used_mib": $peak_used,
  "host_mem_min_available_mib": $min_avail,
  "date_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON
cat "$ENGINE_DIR/$name.json"
