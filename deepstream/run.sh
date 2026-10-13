#!/usr/bin/env bash
# Run a command in the DeepStream image with GPU access, as the calling user (video/render groups for /dev/nvmap),
# the repo at /work and the engine cache at /engines. Development/test helper; deployment uses deploy/compose.yaml.
#   deepstream/run.sh python3 -m pytest deepstream/tests
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$repo/engine_cache"
exec docker run --rm -i --runtime nvidia --network "${LPR_DOCKER_NETWORK:-host}" \
  -u "$(id -u):$(id -g)" --group-add "$(getent group video | cut -d: -f3)" --group-add "$(getent group render | cut -d: -f3)" \
  -e HOME=/tmp -e PYTHONPATH=/work/reader:/work/deepstream:/work/tools ${LPR_DOCKER_ARGS:-} \
  -v "$repo:/work" -v "$repo/engine_cache:/engines" -w /work "${LPR_DS_IMAGE:-lpr-deepstream:6.3}" "$@"
