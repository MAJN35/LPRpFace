#!/usr/bin/env bash
# Build the CPU tooling image. With --lock, (re)generate tools/docker/requirements.lock first (pip-compile with
# hashes, resolved inside the pinned base image so the lock matches its platform).
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
base="$(sed -n 's/^FROM //p' "$repo/tools/docker/Dockerfile")"
if [[ "${1:-}" == "--lock" ]]; then
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$repo/tools/docker:/d" -w /d "$base" sh -c \
    'pip install --quiet --user pip-tools==7.4.1 && python -m piptools compile --quiet --generate-hashes \
       --allow-unsafe --strip-extras -o requirements.lock requirements.in'
fi
docker build -t lpr-tools:cpu "$repo/tools/docker"
