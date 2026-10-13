"""Event sinks behind a bounded queue (inference never blocks on I/O, Kafka or the backend).

``EventEmitter.emit(event)`` only enqueues (drops and counts when the queue is full); one worker thread writes to
every configured sink. Sinks: ``stdout`` (JSON lines), ``jsonl`` (local file), ``http`` (POST, retries with backoff;
the real endpoint is a configuration placeholder), ``kafka`` (confluent-kafka producer with its own bounded buffer).
"""
from __future__ import annotations

import json
import logging
import queue
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("lpr.sinks")


class Sink:
    name = "sink"

    def write(self, event: Dict[str, Any]) -> bool:  # True = delivered (or handed to a reliable buffer)
        raise NotImplementedError

    def close(self) -> None:
        pass


class StdoutSink(Sink):
    name = "stdout"

    def write(self, event):
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return True


class JsonlSink(Sink):
    name = "jsonl"

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a", encoding="utf-8")

    def write(self, event):
        self.f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.f.flush()
        return True

    def close(self):
        self.f.close()


class HttpSink(Sink):
    name = "http"

    def __init__(self, url: str, timeout_s: float = 3.0, retries: int = 3, backoff_s: float = 0.5,
                 headers: Optional[Dict[str, str]] = None):
        self.url, self.timeout_s, self.retries, self.backoff_s = url, timeout_s, retries, backoff_s
        self.headers = {"Content-Type": "application/json", **(headers or {})}

    def write(self, event):
        body = json.dumps(event, ensure_ascii=False).encode()
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(self.url, data=body, headers=self.headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                    if 200 <= r.status < 300:
                        return True
            except Exception as e:  # noqa: BLE001 - any transport error is retried, then counted
                log.debug("http sink attempt %d failed: %s", attempt + 1, e)
            time.sleep(self.backoff_s * (2 ** attempt))
        return False


class KafkaSink(Sink):
    """Async producer: ``produce`` only appends to librdkafka's bounded buffer; delivery reports update counters."""
    name = "kafka"

    def __init__(self, brokers: str, topic: str, buffer_messages: int = 10000, stats: Optional[Dict] = None):
        from confluent_kafka import Producer

        self.topic = topic
        self.stats = stats if stats is not None else {}
        self.p = Producer({"bootstrap.servers": brokers, "enable.idempotence": True, "acks": "all",
                           "queue.buffering.max.messages": buffer_messages, "message.timeout.ms": 300000,
                           "retries": 2147483647, "linger.ms": 20, "compression.type": "lz4"})

    def _report(self, err, _msg):
        key = "kafka_failed" if err is not None else "kafka_delivered"
        self.stats[key] = self.stats.get(key, 0) + 1
        if err is not None:
            log.warning("kafka delivery failed: %s", err)

    def write(self, event):
        try:
            self.p.produce(self.topic, key=event.get("camera_id", "").encode(),
                           value=json.dumps(event, ensure_ascii=False).encode(), callback=self._report)
            self.p.poll(0)
            return True
        except BufferError:
            return False

    def close(self):
        self.p.flush(10)


class EventEmitter:
    def __init__(self, sinks: List[Sink], max_queue: int = 1000):
        self.sinks = sinks
        self.q: "queue.Queue[Optional[Dict]]" = queue.Queue(maxsize=max_queue)
        self.stats: Dict[str, int] = {"emitted": 0, "dropped_queue_full": 0}
        for s in sinks:
            self.stats[f"{s.name}_ok"] = 0
            self.stats[f"{s.name}_failed"] = 0
        self._t = threading.Thread(target=self._run, name="event-emitter", daemon=True)
        self._t.start()

    def emit(self, event: Dict[str, Any]) -> bool:
        try:
            self.q.put_nowait(event)
            self.stats["emitted"] += 1
            return True
        except queue.Full:
            self.stats["dropped_queue_full"] += 1
            return False

    def _run(self):
        while True:
            ev = self.q.get()
            if ev is None:
                break
            for s in self.sinks:
                try:
                    ok = s.write(ev)
                except Exception:  # noqa: BLE001
                    log.exception("sink %s failed", s.name)
                    ok = False
                self.stats[f"{s.name}_{'ok' if ok else 'failed'}"] += 1

    def close(self, timeout: float = 10.0):
        self.q.put(None)
        self._t.join(timeout)
        for s in self.sinks:
            s.close()


def build_sinks(spec: str, jsonl_path: str = "", http_url: str = "", kafka_brokers: str = "",
                kafka_topic: str = "lpr.plate.events") -> List[Sink]:
    """``spec`` = comma list of stdout,jsonl,http,kafka (LPR_EVENT_SINKS)."""
    out: List[Sink] = []
    for name in [s.strip() for s in spec.split(",") if s.strip()]:
        if name == "stdout":
            out.append(StdoutSink())
        elif name == "jsonl":
            out.append(JsonlSink(jsonl_path))
        elif name == "http":
            if not http_url:
                raise ValueError("http sink needs LPR_EVENT_HTTP_URL")
            out.append(HttpSink(http_url))
        elif name == "kafka":
            out.append(KafkaSink(kafka_brokers, kafka_topic))
        else:
            raise ValueError(f"unknown sink {name!r}")
    return out
