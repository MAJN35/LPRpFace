#!/usr/bin/env python3
"""Check track-level events of a synthetic test video against its clips (tools/make_test_video.py sidecar).

    python3 tools/check_video_events.py --events events.jsonl --video tests/data/private/videos/test_h264.json \
        --source video-h264 [--offline offline.json]

Each clip shows one plate; the expected result is exactly one plate.recognized event whose plate_string_latin
equals the clip's ground truth. Extra events (e.g. a track split) and misses are listed. With --offline (output of
tools/offline_video_reader.py), the per-clip voted string of the offline reader is shown next to the event.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--offline", type=Path)
    a = ap.parse_args(argv)
    side = json.loads(a.video.read_text())
    evs = [e for e in map(json.loads, a.events.read_text().splitlines())
           if e["source"]["id"] == a.source and e["event_type"] == "plate.recognized"]
    got = Counter(e["plate_string_latin"] for e in evs)
    offline = json.loads(a.offline.read_text()) if a.offline else {}
    ok = 0
    print(f"{len(evs)} events from {a.source}; {len(side['clips'])} clips")
    for c in side["clips"]:
        gt = c["gt_string_latin"]
        hit = got.get(gt, 0)
        ok += hit >= 1
        off = offline.get(c["image"], "")
        print(f"  {'OK ' if hit else 'MISS'} {gt:20s} events={hit} offline={off!r}")
    extra = {k: v for k, v in got.items() if k not in {c['gt_string_latin'] for c in side['clips']}}
    print(f"clips read correctly: {ok}/{len(side['clips'])}; other event strings: {dict(extra)}")
    return 0 if ok == len(side["clips"]) else 1


if __name__ == "__main__":
    sys.exit(main())
