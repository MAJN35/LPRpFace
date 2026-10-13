#!/usr/bin/env bash
# Usage: bash tools/unzip_testset.sh [path/to/agent_testset_v2.zip]   (run from the repository root)
set -euo pipefail
ZIP="${1:-$HOME/agent_testset_v2.zip}"
DEST="tests/data/private"

[ -f "$ZIP" ] || { echo "zip not found: $ZIP"; exit 1; }
mkdir -p "$DEST"

python3 - "$ZIP" "$DEST" <<'EOF'
import sys, json, zipfile
from pathlib import Path
from collections import Counter
zp, dest = Path(sys.argv[1]), Path(sys.argv[2])
with zipfile.ZipFile(zp) as z:
    bad = z.testzip()
    if bad:
        sys.exit(f"corrupt file in zip: {bad} (download it again)")
    for m in z.namelist():                                   # refuse paths that would escape the destination
        if m.startswith("/") or ".." in Path(m).parts:
            sys.exit(f"unsafe path in zip: {m}")
    z.extractall(dest)
root = dest / "agent_testset_v2"
man = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
missing = [m["file"] for m in man if not (root / m["file"]).exists()] + \
          [m["label_file"] for m in man if not (root / m["label_file"]).exists()]
print(f"extracted to {root}")
print(f"images: {len(man)} | missing files: {len(missing)}")
print("by group:", dict(Counter(m["group"].split(":")[0] for m in man)))
print("by plate type:", dict(Counter(m["plate_type"] for m in man)))
print("plates with complete standard label:", sum(p["standard_8_chars"] for m in man for p in m["plates"]))
if missing:
    sys.exit(f"missing: {missing[:5]} ...")
EOF

# keep the private test data out of git
touch .gitignore
grep -qxF 'tests/data/private/' .gitignore || echo 'tests/data/private/' >> .gitignore
git check-ignore -q tests/data/private/agent_testset_v2/manifest.json && echo "[ok] tests/data/private/ is git-ignored"
