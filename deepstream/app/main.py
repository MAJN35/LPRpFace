"""Entry point of the DeepStream LPR service.  python3 -m app.main

Environment (defaults in brackets):
  MODEL_VERSION [v2]  PRECISION [fp16]  BATCH_PROFILE [1,2,4]   model and engine profile (A.3, M0/M3 decisions)
  ENGINE_DIR [/engines]  ONNX_DIR [/models/<ver>/export]  META_DIR [/app/models-meta/<ver>]
  LPR_SOURCES_FILE [/config/sources.yaml]
  LPR_EVENT_SINKS [stdout,jsonl]  LPR_EVENTS_JSONL [/data/events/events.jsonl]  LPR_EVENT_HTTP_URL []
  KAFKA_BROKERS []  KAFKA_TOPIC [lpr.plate.events]
  LPR_CROPS_DIR [/data/crops]  LPR_JOBS_DIR [/data/jobs]
  LPR_CONTROL_HOST [0.0.0.0]  LPR_CONTROL_PORT [8090]  LPR_IMAGE_API [1]
  LPR_LIVE [0]  LPR_RESTREAM [1: network cameras through the gateway when LPR_LIVE=1]  LPR_MEDIA_RTSP [rtsp://media:8554]  LPR_MEDIA_API [http://media:9997]  LPR_INTERVAL [0]  LPR_EXIT_ON_EOS [auto: 1 without live sources and API]
  LPR_FACES [1]  LPR_FACE_MIN_FRAMES [2]  LPR_FACE_MIN_PX [40]  KAFKA_FACE_TOPIC [lpr.face.events]
  LPR_DEDUP_S [30]  LPR_TRACK_TIMEOUT_S [3]  LPR_MIN_TRACK_FRAMES [3]  LPR_EMIT_INVALID [0]
  LPR_MAX_CAMERAS [unset until measured, M8]
"""
from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

from lpr_reader.voting import VoteConfig  # noqa: E402

from . import nvinfer_config  # noqa: E402
from .config import Source, load_sources  # noqa: E402
from .control import JOB_SOURCE_ID, ControlServer  # noqa: E402
from .engine import ModelCheckError, ensure_engine  # noqa: E402
from .pipeline import AppConfig, LprPipeline  # noqa: E402
from .runtime_sources import RuntimeSources  # noqa: E402
from .sinks import EventEmitter, build_sinks  # noqa: E402
from .worker import ReaderWorker  # noqa: E402

log = logging.getLogger("lpr")


def env(name, default=""):
    return os.environ.get(name, default)


def main() -> int:
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Gst.init(None)
    ver, precision = env("MODEL_VERSION", "v2"), env("PRECISION", "fp16")
    profile = tuple(int(x) for x in env("BATCH_PROFILE", "1,2,4").split(","))
    meta_dir = Path(env("META_DIR", f"/app/models-meta/{ver}"))
    try:
        engine, einfo = ensure_engine(ver, meta_dir, Path(env("ONNX_DIR", f"/models/{ver}/export")),
                                      Path(env("ENGINE_DIR", "/engines")), precision, profile)
    except ModelCheckError as e:
        log.critical("model check failed, refusing to run: %s", e)
        return 2
    model = {"version": ver, "sha256": einfo["pt_sha256"], "engine_sha256": einfo.get("engine_sha256"),
             "precision": precision, "batch_profile": list(profile)}
    log.info("model %s (pt %s…), engine %s", ver, model["sha256"][:12], engine.name)

    # uploaded videos (dashboard Settings -> Videos) land here; the backend (uid 10001) writes them, this container reads
    videos = Path(env("LPR_VIDEOS_DIR", "/data/videos"))
    try:
        videos.mkdir(parents=True, exist_ok=True)
        os.chown(videos, int(env("LPR_CROPS_UID", "10001")), int(env("LPR_CROPS_UID", "10001")))
    except OSError as e:
        log.warning("videos folder %s not prepared: %s", videos, e)
    store = RuntimeSources(env("LPR_RUNTIME_SOURCES", "/data/sources.runtime.json"))
    sources = store.apply(load_sources(), dict(os.environ))   # sources.yaml + changes made at runtime
    image_api = env("LPR_IMAGE_API", "1") == "1"
    if image_api and not any(s.id == JOB_SOURCE_ID for s in sources):
        sources.append(Source(id=JOB_SOURCE_ID, type="image_job", name="API image uploads", face_blur=True))
    has_live = any(s.is_live and s.enabled for s in sources)
    exit_on_eos = env("LPR_EXIT_ON_EOS", "1" if not (has_live or image_api) else "0") == "1"

    cfg_dir = Path(env("LPR_RUNTIME_DIR", "/tmp/lpr"))
    cfg_dir.mkdir(parents=True, exist_ok=True)
    interval = int(env("LPR_INTERVAL", "0"))
    infer_cfg = nvinfer_config.write(str(cfg_dir / "nvinfer.txt"), str(engine), str(meta_dir / "labels.txt"),
                                     "/app/parsers/libnvdsparse_yolo12_lpr.so", profile[2], precision, interval)
    sinks = build_sinks(env("LPR_EVENT_SINKS", "stdout,jsonl"), env("LPR_EVENTS_JSONL", "/data/events/events.jsonl"),
                        env("LPR_EVENT_HTTP_URL"), env("KAFKA_BROKERS"), env("KAFKA_TOPIC", "lpr.plate.events"))
    emitter = EventEmitter(sinks)
    # Face recognition (LPR_FACES=1): face snapshots + events on their own topic (lpr.face.events) and JSONL file.
    face_emitter = None
    if env("LPR_FACES", "1") == "1":
        face_spec = ",".join(x for x in env("LPR_EVENT_SINKS", "stdout,jsonl").split(",") if x.strip() in ("jsonl", "kafka"))
        face_emitter = EventEmitter(build_sinks(face_spec, env("LPR_FACE_EVENTS_JSONL", "/data/events/faces.jsonl"), "",
                                                env("KAFKA_BROKERS"), env("KAFKA_FACE_TOPIC", "lpr.face.events")))
    # Video emit policy (user request 2026-10-13): one event per tracker track seen in >= LPR_MIN_TRACK_FRAMES
    # frames, and only plausible plates unless LPR_EMIT_INVALID=1. Image jobs always return their read.
    worker = ReaderWorker(emitter, model, env("LPR_CROPS_DIR", "/data/crops"), float(env("LPR_DEDUP_S", "30")),
                          VoteConfig(track_timeout_s=float(env("LPR_TRACK_TIMEOUT_S", "3")),
                                     min_frames=int(env("LPR_MIN_TRACK_FRAMES", "3"))),
                          emit_invalid=env("LPR_EMIT_INVALID", "0") == "1", face_emitter=face_emitter,
                          face_min_frames=int(env("LPR_FACE_MIN_FRAMES", "2")),
                          face_min_px=float(env("LPR_FACE_MIN_PX", "40")))
    app_cfg = AppConfig(nvinfer_config=infer_cfg, tracker_config=env("LPR_TRACKER_CONFIG",
                                                                      "/app/configs/tracker_nvsort_lpr.yml"),
                        max_batch=profile[2], interval=interval, live=env("LPR_LIVE", "0") == "1",
                        media_rtsp=env("LPR_MEDIA_RTSP", "rtsp://media:8554"),
                        media_api=env("LPR_MEDIA_API", "http://media:9997"), exit_on_eos=exit_on_eos,
                        restream=env("LPR_RESTREAM", "1") == "1",
                        max_sources=int(env("LPR_MAX_CAMERAS", "4").strip() or "4"))
    app = LprPipeline(app_cfg, sources, worker)
    def env_int(name, default):
        v = env(name).strip()
        return int(v) if v else default
    # Measured capacity (docs/benchmark.md): exposed in /health and the dashboard's System health page.
    capacity = {"max_cameras_memory_safe": env_int("LPR_MAX_CAMERAS", 4),
                "max_cameras_at_target_fps": env_int("LPR_MAX_CAMERAS_AT_TARGET", 0),
                "target_fps_per_camera": env_int("LPR_TARGET_FPS", 8), "source": "docs/benchmark.md"}
    info = {"model": model, "max_cameras": capacity["max_cameras_memory_safe"], "capacity": capacity,
            "engine": engine.name}
    control = ControlServer(app, env("LPR_CONTROL_HOST", "0.0.0.0"), int(env("LPR_CONTROL_PORT", "8090")),
                            env("LPR_JOBS_DIR", "/data/jobs"), info, store)
    control.start()

    def stop(*_):
        log.info("stopping (signal)")
        GLib.idle_add(lambda: (app.pipeline.send_event(Gst.Event.new_eos()), app.loop.quit(), False)[2])

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        app.run()
    finally:
        control.stop()
        log.info("final stats: %s", app.health()["worker"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
