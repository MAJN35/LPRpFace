"""Kafka -> backend consumer (AGENTS.md A.7 Events; M5).

* Reads ``lpr.plate.events`` (group ``lpr-consumer``), auto-commit off: an offset is committed only after its
  message was delivered to the backend or dead-lettered, so a restart re-reads anything unfinished (at-least-once;
  no exactly-once claim).
* Validates each message against schemas/plate_event-2.0.json. Undecodable or invalid messages, and messages the
  backend rejects with a 4xx, go to ``lpr.dead-letter`` with the reason in headers, then are committed.
* Delivery is idempotent end to end: the backend upserts by ``event_id``; the consumer also skips event ids it
  already delivered recently (bounded memory).
* Backend unavailable (connection error, 5xx): retry with backoff, without committing and without consuming
  further, until it is back.

Environment: KAFKA_BROKERS, KAFKA_TOPIC [lpr.plate.events], KAFKA_DLQ_TOPIC [lpr.dead-letter], KAFKA_GROUP
[lpr-consumer], BACKEND_URL [http://backend:8000], INGEST_KEY, CONSUMER_HEALTH_FILE [/tmp/consumer-health.json].
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import jsonschema

log = logging.getLogger("lpr.consumer")
SCHEMA = Path(os.environ.get("EVENT_SCHEMA", Path(__file__).resolve().parent / "schemas" / "plate_event-2.0.json"))


class Delivery:
    """POST to the backend's idempotent ingest endpoint. Returns 'ok', 'reject' (4xx, do not retry) or 'retry'."""

    def __init__(self, url: str, key: str, timeout_s: float = 5.0):
        self.url, self.key, self.timeout_s = url.rstrip("/") + "/api/v1/ingest/events", key, timeout_s

    def __call__(self, event: Dict[str, Any]) -> Tuple[str, str]:
        req = urllib.request.Request(self.url, data=json.dumps(event, ensure_ascii=False).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Ingest-Key": self.key})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return ("ok", str(r.status)) if 200 <= r.status < 300 else ("retry", str(r.status))
        except urllib.error.HTTPError as e:
            try:
                body = e.read()[:200]
            except Exception:  # noqa: BLE001 - error without a body
                body = b""
            if 400 <= e.code < 500 and e.code not in (408, 429):
                return "reject", f"{e.code} {body!r}"
            return "retry", str(e.code)
        except Exception as e:  # noqa: BLE001 - connection refused, timeout, DNS ...
            return "retry", str(e)[:200]


class Processor:
    """Broker-independent core (unit-tested with fakes): validate -> deliver/dead-letter -> commit."""

    def __init__(self, deliver: Callable, dead_letter: Callable, commit: Callable, seen_max: int = 50000,
                 backoff_min_s: float = 1.0, backoff_max_s: float = 30.0, sleep=time.sleep):
        self.validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))
        self.deliver, self.dead_letter, self.commit = deliver, dead_letter, commit
        self.seen: "OrderedDict[str, None]" = OrderedDict()
        self.seen_max = seen_max
        self.backoff_min_s, self.backoff_max_s, self.sleep = backoff_min_s, backoff_max_s, sleep
        self.stats = {"received": 0, "delivered": 0, "duplicates_skipped": 0, "dead_lettered": 0,
                      "backend_retries": 0}
        self.stopping = False

    def handle(self, msg) -> None:
        """Process one message completely (blocks while the backend is down)."""
        self.stats["received"] += 1
        raw = msg.value()
        try:
            event = json.loads(raw)
            self.validator.validate(event)
        except (ValueError, jsonschema.ValidationError) as e:
            self._dlq(msg, f"invalid: {str(e).splitlines()[0][:300]}")
            return
        eid = event["event_id"]
        if eid in self.seen:
            self.stats["duplicates_skipped"] += 1
            self.commit(msg)
            return
        delay = self.backoff_min_s
        while not self.stopping:
            status, detail = self.deliver(event)
            if status == "ok":
                self.stats["delivered"] += 1
                self._remember(eid)
                self.commit(msg)
                return
            if status == "reject":
                self._dlq(msg, f"backend rejected: {detail}")
                return
            self.stats["backend_retries"] += 1
            log.warning("backend unavailable (%s); retrying in %.0f s", detail, delay)
            self.sleep(delay)
            delay = min(delay * 2, self.backoff_max_s)

    def _remember(self, eid: str) -> None:
        self.seen[eid] = None
        if len(self.seen) > self.seen_max:
            self.seen.popitem(last=False)

    def _dlq(self, msg, reason: str) -> None:
        self.dead_letter(msg, reason)
        self.stats["dead_lettered"] += 1
        self.commit(msg)


def run() -> int:  # pragma: no cover - needs a broker; covered by the integration test
    from confluent_kafka import Consumer, Producer

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    brokers = os.environ["KAFKA_BROKERS"]
    topic = os.environ.get("KAFKA_TOPIC", "lpr.plate.events")
    dlq_topic = os.environ.get("KAFKA_DLQ_TOPIC", "lpr.dead-letter")
    health = Path(os.environ.get("CONSUMER_HEALTH_FILE", "/tmp/consumer-health.json"))
    c = Consumer({"bootstrap.servers": brokers, "group.id": os.environ.get("KAFKA_GROUP", "lpr-consumer"),
                  "enable.auto.commit": False, "auto.offset.reset": "earliest", "max.poll.interval.ms": 3600000})
    p = Producer({"bootstrap.servers": brokers, "enable.idempotence": True, "acks": "all"})

    def dead_letter(msg, reason):
        p.produce(dlq_topic, key=msg.key(), value=msg.value(),
                  headers=[("reason", reason.encode()), ("source_topic", msg.topic().encode()),
                           ("source_offset", str(msg.offset()).encode())])
        p.flush(10)

    proc = Processor(Delivery(os.environ.get("BACKEND_URL", "http://backend:8000"), os.environ.get("INGEST_KEY", "")),
                     dead_letter, lambda m: c.commit(message=m, asynchronous=False))

    def stop(*_):
        proc.stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    c.subscribe([topic])
    log.info("consuming %s from %s", topic, brokers)
    last = 0.0
    while not proc.stopping:
        msg = c.poll(1.0)
        if msg is not None:
            if msg.error():
                log.warning("kafka: %s", msg.error())
            else:
                proc.handle(msg)
        if time.time() - last > 5:
            last = time.time()
            health.write_text(json.dumps(dict(proc.stats, updated_at=last)))
    c.close()
    p.flush(10)
    return 0


if __name__ == "__main__":
    sys.exit(run())
