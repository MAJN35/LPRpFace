#!/usr/bin/env bash
# Run a command in the CPU tooling container with the repo mounted at /work (as the calling user).
#   tools/run_cpu.sh python tools/check_model.py models/v2
#   tools/run_cpu.sh pytest
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
image="${LPR_TOOLS_IMAGE:-lpr-tools:cpu}"
exec docker run --rm -i --network none --user "$(id -u):$(id -g)" -e HOME=/tmp -e USER=lpr -e LOGNAME=lpr \
  -v "$repo:/work" -w /work "$image" "$@"
