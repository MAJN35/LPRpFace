"""sources.yaml parsing, URI redaction, event schema 2.0 and the non-blocking emitter (no GStreamer needed)."""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "reader"), str(REPO / "deepstream")]

from app import events  # noqa: E402
from app.config import ConfigError, load_sources, redact_uri, split_credentials  # noqa: E402
from app.sinks import EventEmitter, HttpSink, JsonlSink, Sink  # noqa: E402
from lpr_reader.voting import TrackResult  # noqa: E402

MODEL = {"version": "v2", "sha256": "a" * 64, "engine_sha256": "b" * 64, "precision": "fp16", "batch_profile": [1, 2, 4]}


def write_yaml(tmp_path, text):
    p = tmp_path / "sources.yaml"
    p.write_text(text)
    return str(p)


def test_env_expansion_and_redaction(tmp_path):
    path = write_yaml(tmp_path, """
defaults: {max_fps: 10}
sources:
  - {id: cam-01, type: rtsp, uri: "rtsp://${U}:${P}@10.0.0.11:554/ch1", rtsp_transport: udp}
""")
    [s] = load_sources(path, env={"U": "admin", "P": "p@ss:w"})
    assert s.uri == "rtsp://admin:p@ss:w@10.0.0.11:554/ch1"
    assert s.uri_redacted == "rtsp://10.0.0.11:554/ch1"
    assert s.max_fps == 10.0 and s.rtsp_transport == "udp" and s.is_live
    assert split_credentials(s.uri) == ("rtsp://10.0.0.11:554/ch1", "admin", "p@ss:w")


def test_missing_env_for_enabled_source_fails_but_disabled_is_ok(tmp_path):
    path = write_yaml(tmp_path, """
sources:
  - {id: cam-01, type: rtsp, uri: "rtsp://${U}:${P}@host/x", enabled: false}
""")
    assert load_sources(path, env={})[0].enabled is False
    with pytest.raises(ConfigError, match="not set"):
        load_sources(path, env={"LPR_SOURCE_CAM_01_ENABLED": "1"})


def test_image_folder_and_file_resolution(tmp_path):
    (tmp_path / "imgs").mkdir()
    for n in ("b.jpg", "a.png", "c.txt"):
        (tmp_path / "imgs" / n).write_bytes(b"x")
    (tmp_path / "v.mp4").write_bytes(b"x")
    path = write_yaml(tmp_path, f"""
sources:
  - {{id: folder, type: image_folder, uri: "{tmp_path / 'imgs'}"}}
  - {{id: video, type: file, uri: "{tmp_path / 'v.mp4'}", loop: true, realtime: false}}
""")
    folder, video = load_sources(path, env={})
    assert [Path(f).name for f in folder.files] == ["a.png", "b.jpg"]
    assert video.uri.startswith("file:///") and video.loop and not video.realtime


@pytest.mark.parametrize("bad, msg", [
    ("{id: x, type: webcam, uri: a}", "type"),
    ("{id: 'bad id', type: rtsp, uri: a}", "source id"),
    ("{id: x, type: rtsp, uri: a, colour: red}", "unknown keys"),
    ("{id: x, type: rtsp, uri: a, roi: [[0, 0], [2, 0], [1, 1]]}", "roi"),
    ("{id: x, type: file, uri: /nonexistent.mp4}", "not found"),
])
def test_invalid_sources_rejected(tmp_path, bad, msg):
    with pytest.raises(ConfigError, match=msg):
        load_sources(write_yaml(tmp_path, f"sources:\n  - {bad}\n"), env={})


def test_duplicate_ids_rejected(tmp_path):
    path = write_yaml(tmp_path, "sources:\n  - {id: a, type: rtsp, uri: x}\n  - {id: a, type: rtsp, uri: y}\n")
    with pytest.raises(ConfigError, match="duplicate"):
        load_sources(path, env={})


def test_redact_variants():
    assert redact_uri("rtsp://u:p@h:554/a?b=c") == "rtsp://h:554/a?b=c"
    assert redact_uri("file:///x/y.mp4") == "file:///x/y.mp4"
    assert redact_uri("/dev/video0") == "/dev/video0"


def _track_event(src):
    res = TrackResult(7, "standard", "۱۲ ب ۳۴۵ | ۶۷", "12 Be 345 | 67",
                      [{"class_id": 1, "name": "1", "confidence": 0.9, "box": [1, 2, 3, 4]}], None, None, [], 0.9,
                      True, None, 5, 1.0, 2.0, {"plate_bbox": [10, 20, 110, 50]})
    return events.from_track(res, src, MODEL, (1920, 1080), "/crops/x.jpg", 1760000000.25)


def test_track_event_matches_schema(tmp_path):
    [src] = load_sources(write_yaml(tmp_path, "sources:\n  - {id: cam-01, type: rtsp, uri: 'rtsp://u:p@h/x'}\n"), env={})
    ev = _track_event(src)
    events.validate(ev)
    assert ev["source"]["uri_redacted"] == "rtsp://h/x" and ev["plate_key"] == "12Be34567"
    assert ev["timestamp"].endswith("Z") and ev["track_id"] == 7


def test_schema_rejects_credentials_and_bad_fields(tmp_path):
    [src] = load_sources(write_yaml(tmp_path, "sources:\n  - {id: cam-01, type: rtsp, uri: 'rtsp://h/x'}\n"), env={})
    ev = _track_event(src)
    for mutate in (lambda e: e["source"].update(uri_redacted="rtsp://u:p@h/x"), lambda e: e.update(extra=1),
                   lambda e: e.update(event_type="plate.seen"), lambda e: e["model"].update(version="v3")):
        bad = json.loads(json.dumps(ev))
        mutate(bad)
        with pytest.raises(jsonschema.ValidationError):
            events.validate(bad)


class _Slow(Sink):
    name = "slow"

    def write(self, event):
        time.sleep(0.5)
        return True


def test_emitter_never_blocks_and_counts_drops():
    em = EventEmitter([_Slow()], max_queue=2)
    t = time.time()
    results = [em.emit({"n": i}) for i in range(10)]
    assert time.time() - t < 0.2                      # emit() only enqueues
    assert results.count(False) >= 7 and em.stats["dropped_queue_full"] >= 7


def test_jsonl_and_http_sinks(tmp_path):
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    em = EventEmitter([JsonlSink(str(tmp_path / "ev.jsonl")), HttpSink(f"http://127.0.0.1:{srv.server_port}/events")])
    em.emit({"event_id": "1"})
    em.close()
    srv.shutdown()
    assert (tmp_path / "ev.jsonl").read_text().strip() == '{"event_id": "1"}'
    assert got == [{"event_id": "1"}] and em.stats["http_ok"] == 1


def test_http_sink_failure_is_counted_not_raised():
    em = EventEmitter([HttpSink("http://127.0.0.1:9/none", timeout_s=0.2, retries=1, backoff_s=0.01)])
    em.emit({"event_id": "1"})
    em.close()
    assert em.stats["http_failed"] == 1
