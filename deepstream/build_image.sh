#!/usr/bin/env bash
# Build the DeepStream app image lpr-deepstream:6.3. With --lock, regenerate deepstream/requirements.lock first
# (inside the base stage, so the lock matches its Python 3.8 / aarch64 platform).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
# Stage the host's TensorRT and CUDA headers for the parser build (not committed).
rm -rf "$here/.build-include" && mkdir -p "$here/.build-include/trt" "$here/.build-include/cuda"
cp /usr/include/aarch64-linux-gnu/Nv*.h "$here/.build-include/trt/"
cp -rL /usr/local/cuda/include/. "$here/.build-include/cuda/"
if [[ "${1:-}" == "--lock" ]]; then
  docker build --target base -f "$here/Dockerfile" -t lpr-deepstream:base "$repo"
  cache="${XDG_CACHE_HOME:-$HOME/.cache}/lpr-deepstream-wheels"
  mkdir -p "$cache"
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$here:/d" -v "$repo/tools/docker/make_lock.py:/make_lock.py:ro" \
    -v "$cache:/tmp/wheels" -w /d lpr-deepstream:base python3 /make_lock.py
fi
docker build -f "$here/Dockerfile" -t lpr-deepstream:6.3 "$repo"
