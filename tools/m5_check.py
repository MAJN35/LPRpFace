#!/usr/bin/env python3
"""M5 integration helper (runs in the DeepStream image on the compose network `lpr`).

    produce --run R --n 20 --dups 5 --invalid 3    synthetic events through the app's EventEmitter + KafkaSink
    count   --run R                                 events of run R visible through the backend API
    dlq     --run R                                 messages of run R in lpr.dead-letter
    outage  --run R --n 50                          emit while the broker is down: emit() must not block,
                                                    counters rise, messages stay buffered (exit 0 if so)
Events of one run share camera_id "m5-<run>", so checks only see their own events.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "reader"), str(REPO / "deepstream")]

BROKERS = os.environ.get("KAFKA_BROKERS", "kafka:9092")
BACKEND = os.environ.get("BACKEND_URL", "http://backend:8000")


def event(run: str, i: int):
    return {"schema_version": "2.0", "event_id": str(uuid.uuid4()), "event_type": "plate.recognized",
            "source": {"id": f"m5-{run}", "type": "file", "uri_redacted": "file:///synthetic", "file_name": None},
            "camera_id": f"m5-{run}", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "track_id": i, "model": {"version": "v2", "sha256": "f" * 64, "engine_sha256": None, "precision": "fp16",
                                     "batch_profile": [1, 2, 4]},
            "plate_type": "standard", "plate_string_fa": "۱۲ ب ۳۴۵ | ۶۷", "plate_string_latin": "12 Be 345 | 67",
            "plate_key": "12Be34567", "zone": None, "expiry": None, "markers": [], "characters": [],
            "confidence": 0.9, "is_valid": True, "invalid_reason": None, "frames_voted": 3,
            "plate_bbox": [0, 0, 10, 10], "frame_size": [1920, 1080], "best_frame_crop_path": None}


def token():
    data = urllib.parse.urlencode({"username": os.environ["ADMIN_USERNAME"], "password": os.environ["ADMIN_PASSWORD"]})
    with urllib.request.urlopen(f"{BACKEND}/api/v1/auth/login", data=data.encode(), timeout=10) as r:
        return json.load(r)["access_token"]


def count(run: str) -> int:
    req = urllib.request.Request(f"{BACKEND}/api/v1/events?camera_id=m5-{run}&limit=1",
                                 headers={"Authorization": f"Bearer {token()}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["total"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["produce", "count", "dlq", "outage"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--dups", type=int, default=0)
    ap.add_argument("--invalid", type=int, default=0)
    ap.add_argument("--expect", type=int)
    ap.add_argument("--wait", type=float, default=60)
    a = ap.parse_args(argv)
    from confluent_kafka import Consumer, Producer

    from app.sinks import EventEmitter, KafkaSink

    if a.cmd == "produce":
        sink = KafkaSink(BROKERS, "lpr.plate.events")
        em = EventEmitter([sink])
        evs = [event(a.run, i) for i in range(a.n)]
        for e in evs + evs[: a.dups]:          # duplicates = same event_id sent again
            em.emit(e)
        em.close()
        p = Producer({"bootstrap.servers": BROKERS})
        for i in range(a.invalid):             # poison: broken JSON / wrong schema
            p.produce("lpr.plate.events", value=(b"{not json " + a.run.encode()) if i % 2 == 0
                      else json.dumps({"schema_version": "2.0", "run": a.run}).encode())
        p.flush(10)
        print(json.dumps({"produced": a.n, "duplicates": a.dups, "invalid": a.invalid, "emitter": em.stats,
                          "sink": sink.stats}))
        return 0
    if a.cmd == "count":
        deadline = time.time() + a.wait
        n = count(a.run)
        while a.expect is not None and n < a.expect and time.time() < deadline:
            time.sleep(2)
            n = count(a.run)
        print(json.dumps({"run": a.run, "events_in_backend": n}))
        return 0 if a.expect is None or n == a.expect else 1
    if a.cmd == "dlq":
        c = Consumer({"bootstrap.servers": BROKERS, "group.id": f"m5-dlq-{uuid.uuid4()}", "auto.offset.reset": "earliest"})
        c.subscribe(["lpr.dead-letter"])
        hits, idle = 0, time.time()
        while time.time() - idle < 10:
            m = c.poll(1.0)
            if m is None or m.error():
                continue
            idle = time.time()
            if a.run.encode() in (m.value() or b""):
                hits += 1
        c.close()
        print(json.dumps({"run": a.run, "dead_lettered": hits}))
        return 0 if a.expect is None or hits == a.expect else 1
    if a.cmd == "outage":
        sink = KafkaSink(BROKERS, "lpr.plate.events")
        em = EventEmitter([sink])
        t = time.time()
        for i in range(a.n):
            em.emit(event(a.run, i))
        emit_s = time.time() - t
        time.sleep(5)
        buffered = len(sink.p)
        res = {"emit_seconds": round(emit_s, 3), "emitter": dict(em.stats), "delivered_so_far": sink.stats,
               "buffered_in_producer": buffered}
        print(json.dumps(res))
        ok = emit_s < 1.0 and em.stats["emitted"] == a.n and buffered >= a.n  # librdkafka len() also counts internal requests
        # keep the producer alive so the buffered messages go out when the broker returns
        deadline = time.time() + a.wait
        while len(sink.p) and time.time() < deadline:
            sink.p.poll(1.0)
        print(json.dumps({"after_wait_buffered": len(sink.p), "delivered": sink.stats}))
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
