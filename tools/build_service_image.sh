#!/usr/bin/env bash
# Build a Python service image (backend | consumer | face) from the repo root.
#   tools/build_service_image.sh backend [--lock]
# --lock regenerates <service>/requirements.lock inside the pinned base image (tools/docker/make_lock.py).
set -euo pipefail
svc="${1:?backend|consumer|face}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
base="python:3.10.22-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370"
if [[ "${2:-}" == "--lock" ]]; then
  cache="${XDG_CACHE_HOME:-$HOME/.cache}/lpr-$svc-wheels"
  mkdir -p "$cache"
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$repo/$svc:/d" -v "$repo/tools/docker/make_lock.py:/make_lock.py:ro" \
    -v "$cache:/tmp/wheels" -w /d "$base" python /make_lock.py
fi
docker build -f "$repo/$svc/Dockerfile" -t "lpr-$svc:1.0" "$repo"
