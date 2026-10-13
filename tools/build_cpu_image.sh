#!/usr/bin/env bash
# Build the CPU tooling image lpr-tools:cpu. With --lock, (re)generate tools/docker/requirements.lock first
# (exact versions + SHA-256 of the wheels for this platform, resolved inside the pinned base image).
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
base_ref="python:3.10.22-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370"
# Image ID (= config digest) of the linux/arm64 image behind base_ref.
base_id_arm64="sha256:23b459407c3482801a9ca6adb18ca6123559a0b518efd34f67fc946064e99f91"

if docker image inspect "$base_ref" >/dev/null 2>&1 || docker pull "$base_ref" >/dev/null 2>&1; then
  base="$base_ref"
else
  base="${base_ref%@*}"
  id="$(docker image inspect -f '{{.Id}}' "$base" 2>/dev/null || true)"
  if [[ "$id" != "$base_id_arm64" ]]; then
    echo "base image unavailable: pull failed and local $base has id '$id' (want $base_id_arm64)." >&2
    echo "fetch it with: python3 tools/fetch_image.py $base_ref" >&2
    exit 1
  fi
fi
echo "base: $base"

if [[ "${1:-}" == "--lock" ]]; then
  cache="${XDG_CACHE_HOME:-$HOME/.cache}/lpr-tools-wheels"  # survives interruptions; pip reuses files there
  mkdir -p "$cache"
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$repo/tools/docker:/d" -v "$cache:/tmp/wheels" \
    -w /d "$base" python make_lock.py
fi
docker build --build-arg "BASE=$base" -t lpr-tools:cpu "$repo/tools/docker"
