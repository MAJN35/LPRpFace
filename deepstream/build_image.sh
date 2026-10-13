#!/usr/bin/env bash
# Build the DeepStream app image lpr-deepstream:6.3. With --lock, regenerate deepstream/requirements.lock first
# (inside the base stage, so the lock matches its Python 3.8 / aarch64 platform).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
if [[ "${1:-}" == "--lock" ]]; then
  docker build --target base -t lpr-deepstream:base "$here"
  cache="${XDG_CACHE_HOME:-$HOME/.cache}/lpr-deepstream-wheels"
  mkdir -p "$cache"
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$here:/d" -v "$repo/tools/docker/make_lock.py:/make_lock.py:ro" \
    -v "$cache:/tmp/wheels" -w /d lpr-deepstream:base python3 /make_lock.py
fi
docker build -t lpr-deepstream:6.3 "$here"
