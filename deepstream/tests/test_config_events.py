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


def test_runtime_sources_overlay_survives_restart(tmp_path):
    from app.runtime_sources import RuntimeSources
    path = write_yaml(tmp_path, "sources:\n  - {id: cam-01, type: rtsp, uri: 'rtsp://h/1'}\n  - {id: cam-02, type: rtsp, uri: 'rtsp://h/2'}\n")
    store = RuntimeSources(str(tmp_path / "rt.json"))
    store.added({"id": "phone", "type": "rtsp", "uri": "rtsp://192.168.1.114:8554", "max_fps": 10})
    store.removed("cam-02")
    store.enabled("cam-01", False)
    again = RuntimeSources(str(tmp_path / "rt.json"))                  # "restart"
    srcs = {s.id: s for s in again.apply(load_sources(path, env={}), env={})}
    assert set(srcs) == {"cam-01", "phone"} and srcs["cam-01"].enabled is False and srcs["phone"].max_fps == 10
    assert oct((tmp_path / "rt.json").stat().st_mode)[-3:] == "600"


def test_emit_policy_accepts_only_plausible_plates():
    from types import SimpleNamespace as N
    from app.worker import plausible
    digit = lambda d: {"class_id": d}  # noqa: E731
    assert plausible(N(is_valid=True, characters=[]))
    assert not plausible(N(is_valid=False, characters=[digit(1)] * 6))           # wrong character count
    assert not plausible(N(is_valid=False, characters=[]))                       # plate box without characters
    assert plausible(N(is_valid=None, characters=[digit(1), digit(2), digit(3), digit(4)]))   # protocol, 4 digits
    assert not plausible(N(is_valid=None, characters=[digit(1), {"class_id": 11}]))



class _Collect:
    def __init__(self):
        self.events, self.stats = [], {}

    def emit(self, ev):
        self.events.append(ev)
        return True

    def close(self):
        pass


def test_one_face_event_per_track_with_its_largest_snapshot(tmp_path):
    import numpy as np
    from types import SimpleNamespace as N
    from app.worker import ReaderWorker
    [src] = load_sources(write_yaml(tmp_path, "sources:\n  - {id: door, type: rtsp, uri: 'rtsp://h/1'}\n"), env={})
    faces = _Collect()
    w = ReaderWorker(_Collect(), MODEL, str(tmp_path / "crops"), face_emitter=faces, face_min_frames=2, face_min_px=40)
    try:
        sb = N(index=0, src=src, frame_size=(1920, 1080))
        w.register(sb)
        def frame(t, track, width, crop=True):
            f = {"track_id": track, "box": [100, 100, 100 + width, 100 + width], "score": 0.8, "crop_box": [5, 5, 5 + width, 5 + width]}
            return N(source_index=0, t=t, faces=[f], frame_size=(1920, 1080), image_file=None,
                     face_crops={track: np.full((width + 10, width + 10, 4), 120, np.uint8)} if crop else {})
        w._faces(sb, frame(1.0, 7, 50))
        w._faces(sb, frame(1.1, 7, 90))          # larger: becomes the snapshot
        w._faces(sb, frame(1.2, 7, 60, crop=False))
        w._faces(sb, frame(1.0, 8, 80))          # one frame only: skipped
        w._faces(sb, frame(1.0, 9, 20))
        w._faces(sb, frame(1.1, 9, 22))          # too small: skipped
        w._finalize_faces(list(w.face_tracks))
        assert len(faces.events) == 1 and w.stats["faces_skipped"] == 2
        ev = faces.events[0]
        assert ev["event_type"] == "face.detected" and ev["track_id"] == 7 and ev["frames_seen"] == 3
        assert ev["face_bbox"] == [100, 100, 190, 190] and (tmp_path / "crops" / ev["snapshot_path"]).is_file()
        assert ev["snapshot_path"].startswith("faces/door/")
    finally:
        w.finish(5)
