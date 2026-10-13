"""DeepStream pipeline: sources -> nvstreammux -> nvinfer (YOLO12x) -> nvtracker -> probe -> [OSD out] -> sink.

The probe on the tracker's src pad only reads metadata (boxes, track ids, the 48 class scores the custom parser
attached as each object's mask) and, when a plate track gets a new best frame, copies that plate's pixels. It
hands everything to ``ReaderWorker`` through a bounded queue and never blocks; reading, voting, deduplication,
crop encoding and event emission run in the worker thread.

Sources are added/removed at runtime by requesting/releasing nvstreammux pads (pad indices are never reused: a
released and re-requested pad on a running mux does not pass buffers - from the earlier project). A source error
rebuilds only that source, with backoff (network 2 s doubling to 60 s; authentication 5 min doubling to 1 h, so a
wrong password cannot lock the camera account). A file/image source's EOS removes that source; the pipeline ends
only when the last source ends and ``exit_on_eos`` is set.
"""
from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

import pyds  # noqa: E402

from lpr_reader import classes as C  # noqa: E402

from .config import Source  # noqa: E402
from .sources import SourceBin  # noqa: E402

log = logging.getLogger("lpr.pipeline")
NET = 960
RECONNECT_MIN_S, RECONNECT_MAX_S = 2.0, 60.0
AUTH_RETRY_MIN_S, AUTH_RETRY_MAX_S = 300.0, 3600.0


def is_auth_error(text: str) -> bool:
    t = (text or "").lower()
    return "unauthorized" in t or "401" in t or "forbidden" in t or "403" in t


@dataclass
class AppConfig:
    nvinfer_config: str
    tracker_config: str
    max_batch: int = 4
    mux_width: int = 1920
    mux_height: int = 1080
    batched_push_timeout_us: int = 40000
    interval: int = 0
    osd: bool = False                      # draw boxes + Latin plate text, blur faces (output stream)
    output_rtsp: str = ""                  # e.g. rtsp://127.0.0.1:8554/lpr-out (needs a local RTSP server)
    exit_on_eos: bool = True
    worker_queue: int = 64


@dataclass
class FrameItem:
    """Everything the worker needs about one inferred frame (plain Python data, copied in the probe)."""
    source_index: int
    frame_num: int
    t: float                               # capture/arrival time (UTC epoch seconds)
    pts: int
    dets: List[Dict[str, Any]]             # {box (source px), cls, score, scores(48), track_id}
    frame_size: Tuple[int, int]
    crops: Dict[int, np.ndarray] = field(default_factory=dict)   # track_id -> RGBA plate crop
    image_file: Optional[str] = None


class LprPipeline:
    def __init__(self, cfg: AppConfig, sources: List[Source], worker):
        self.cfg = cfg
        self.worker = worker
        self.loop = GLib.MainLoop()
        self.bins: Dict[int, SourceBin] = {}          # mux pad index -> bin
        self.by_id: Dict[str, int] = {}               # source id -> mux pad index
        self.configs: Dict[str, Source] = {s.id: s for s in sources}
        self.state: Dict[str, Dict[str, Any]] = {}
        self._next_index = 0
        self._lock = threading.Lock()
        self.best_width: Dict[Tuple[int, int], float] = {}   # (source index, track id) -> best plate width seen
        self.stats = {"frames_inferred": 0, "worker_dropped": 0}
        self._build()
        for s in sources:
            self.state[s.id] = {"status": "disabled" if not s.enabled else "starting", "failures": 0,
                                "last_error": None, "retry_at": None, "reconnects": 0, "fps_in": 0.0,
                                "frames_in": 0, "last_frame_age_s": None, "started_at": None}
            if s.enabled:
                self._attach(s)

    # --- graph ----------------------------------------------------------------------------------------------------
    def _make(self, factory, name, **props):
        el = Gst.ElementFactory.make(factory, name)
        if el is None:
            raise RuntimeError(f"cannot create {factory}")
        for k, v in props.items():
            el.set_property(k.replace("_", "-"), v)
        self.pipeline.add(el)
        return el

    def _build(self):
        cfg = self.cfg
        self.pipeline = Gst.Pipeline.new("lpr")
        live = any(s.is_live for s in self.configs.values())
        self.mux = self._make("nvstreammux", "mux", batch_size=cfg.max_batch, width=cfg.mux_width,
                              height=cfg.mux_height, enable_padding=1, live_source=1 if live else 0,
                              batched_push_timeout=cfg.batched_push_timeout_us, attach_sys_ts=1)
        q1 = self._make("queue", "q-infer")
        self.pgie = self._make("nvinfer", "pgie", config_file_path=cfg.nvinfer_config, batch_size=cfg.max_batch,
                               interval=cfg.interval)
        q2 = self._make("queue", "q-track")
        self.tracker = self._make("nvtracker", "tracker",
                                  ll_lib_file="/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so",
                                  ll_config_file=cfg.tracker_config, tracker_width=640, tracker_height=384,
                                  display_tracking_id=0)
        q3 = self._make("queue", "q-probe")
        chain = [self.mux, q1, self.pgie, q2, self.tracker, q3]
        if cfg.osd or cfg.output_rtsp:
            tiler_rows = 2
            chain += [self._make("nvmultistreamtiler", "tiler", rows=tiler_rows, columns=2, width=1280, height=720),
                      self._make("nvdsosd", "osd", display_mask=0, process_mode=1)]
        if cfg.output_rtsp:
            chain += [self._make("nvvideoconvert", "outconv"),
                      self._make("capsfilter", "outcaps", caps=Gst.Caps.from_string("video/x-raw(memory:NVMM),format=I420")),
                      self._make("nvv4l2h264enc", "enc", bitrate=2000000, insert_sps_pps=1, iframeinterval=30),
                      self._make("h264parse", "outparse"),
                      self._make("rtspclientsink", "outrtsp", location=cfg.output_rtsp, protocols=4)]
        else:
            sync = any(s.type == "file" and s.realtime for s in self.configs.values())
            chain.append(self._make("fakesink", "sink", sync=sync, async_=False, qos=False))
        for a, b in zip(chain, chain[1:]):
            if not a.link(b):
                raise RuntimeError(f"cannot link {a.get_name()} -> {b.get_name()}")
        q3.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._probe)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    # --- sources ------------------------------------------------------------------------------------------------
    def _attach(self, src: Source) -> None:
        idx = self._next_index
        self._next_index += 1
        sb = SourceBin(src, idx, on_image_done=self.worker.image_failed)
        self.pipeline.add(sb.bin)
        sink = self.mux.get_request_pad(f"sink_{idx}")
        if sb.bin.get_static_pad("src").link(sink) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"cannot link source {src.id} to the muxer")
        sb.bin.get_static_pad("src").add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, self._source_event, idx)
        with self._lock:
            self.bins[idx] = sb
            self.by_id[src.id] = idx
        st = self.state.setdefault(src.id, {"failures": 0, "reconnects": 0})
        st.update(status="connecting", started_at=time.time(), retry_at=None, frames_in=0, fps_in=0.0)
        self.worker.register(sb)
        if self.pipeline.get_state(0)[1] in (Gst.State.PLAYING, Gst.State.PAUSED):
            sb.bin.sync_state_with_parent()
        sb.start_feeder()
        log.info("[%s] attached as mux pad %d (%s %s)", src.id, idx, src.type, src.uri_redacted or src.device)

    def _detach(self, idx: int) -> Optional[SourceBin]:
        with self._lock:
            sb = self.bins.pop(idx, None)
            if sb is None:
                return None
            self.by_id.pop(sb.src.id, None)
        sb.stop()
        sb.bin.set_state(Gst.State.NULL)
        sink = self.mux.get_static_pad(f"sink_{idx}")
        if sink is not None:
            sink.send_event(Gst.Event.new_flush_stop(False))
            self.mux.release_request_pad(sink)
        self.pipeline.remove(sb.bin)
        self.worker.source_ended(sb)
        log.info("[%s] detached (mux pad %d)", sb.src.id, idx)
        return sb

    def add_source(self, src: Source) -> None:
        """Runtime add (called from the control API thread; runs on the main loop)."""
        if src.id in self.by_id:
            raise ValueError(f"source {src.id} already running")
        self.configs[src.id] = src
        self.state.setdefault(src.id, {"failures": 0, "reconnects": 0})
        GLib.idle_add(self._idle(self._attach, src))

    def remove_source(self, sid: str, forget: bool = True) -> None:
        idx = self.by_id.get(sid)
        if idx is not None:
            GLib.idle_add(self._idle(self._detach, idx))
        if forget:
            self.configs.pop(sid, None)
            self.state.pop(sid, None)
        elif sid in self.state:
            self.state[sid]["status"] = "disabled"

    def set_enabled(self, sid: str, enabled: bool) -> None:
        src = self.configs[sid]
        src.enabled = enabled
        if enabled and sid not in self.by_id:
            GLib.idle_add(self._idle(self._attach, src))
        elif not enabled:
            self.remove_source(sid, forget=False)

    def add_image(self, sid: str, path: str) -> None:
        idx = self.by_id.get(sid)
        if idx is None:
            raise KeyError(sid)
        self.bins[idx].add_image(path)

    @staticmethod
    def _idle(fn, *args):
        def run():
            try:
                fn(*args)
            except Exception:
                log.exception("main-loop task %s failed", getattr(fn, "__name__", fn))
            return False
        return run

    def _source_event(self, _pad, info, idx):
        ev = info.get_event()
        if ev is None or ev.type != Gst.EventType.EOS:
            return Gst.PadProbeReturn.OK
        sb = self.bins.get(idx)
        if sb is None:
            return Gst.PadProbeReturn.OK
        if sb.src.is_live:
            # A camera closing its session must not end the batch for everyone: rebuild only this source.
            GLib.idle_add(self._idle(self._schedule_reconnect, idx, "stream ended (EOS)"))
            return Gst.PadProbeReturn.DROP
        self.state[sb.src.id]["status"] = "finished"
        others = [i for i in self.bins if i != idx]
        if not others and self.cfg.exit_on_eos:
            log.info("[%s] EOS, last source: ending the pipeline", sb.src.id)
            return Gst.PadProbeReturn.OK  # mux forwards EOS -> bus EOS -> shutdown
        GLib.timeout_add(2000, self._idle(self._detach, idx))  # let in-flight frames pass first
        return Gst.PadProbeReturn.DROP

    def _schedule_reconnect(self, idx: int, reason: str) -> None:
        sb = self.bins.get(idx)
        if sb is None:
            return
        sid = sb.src.id
        st = self.state[sid]
        if st.get("retry_at"):
            return
        auth = is_auth_error(reason)
        if st.get("status") == "live" and not auth:
            st["failures"] = 0
        st["failures"] = st.get("failures", 0) + 1
        lo, hi = (AUTH_RETRY_MIN_S, AUTH_RETRY_MAX_S) if auth else (RECONNECT_MIN_S, RECONNECT_MAX_S)
        delay = min(lo * 2 ** (st["failures"] - 1), hi)
        st.update(status="auth_failed" if auth else "reconnecting", last_error=reason[:300],
                  retry_at=time.time() + delay)
        log.warning("[%s] %s; rebuilding in %.0f s (attempt %d)", sid, reason.splitlines()[0][:200], delay,
                    st["failures"])
        self._detach(idx)
        src = self.configs.get(sid)

        def retry():
            if src is not None and src.enabled and sid in self.configs and sid not in self.by_id:
                st["retry_at"] = None
                st["reconnects"] = st.get("reconnects", 0) + 1
                try:
                    self._attach(src)
                except Exception as e:  # noqa: BLE001
                    self._fail_without_bin(sid, f"attach failed: {e}")
            return False

        GLib.timeout_add(int(delay * 1000), retry)

    def _fail_without_bin(self, sid, reason):
        st = self.state[sid]
        st["failures"] = st.get("failures", 0) + 1
        delay = min(RECONNECT_MIN_S * 2 ** (st["failures"] - 1), RECONNECT_MAX_S)
        st.update(status="reconnecting", last_error=reason, retry_at=time.time() + delay)
        GLib.timeout_add(int(delay * 1000), self._idle(self._attach, self.configs[sid]))

    # --- probe (streaming thread: metadata only, never blocks) --------------------------------------------------------
    def _probe(self, _pad, info):
        buf = info.get_buffer()
        if buf is None:
            return Gst.PadProbeReturn.OK
        batch = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
        l_frame = batch.frame_meta_list
        while l_frame is not None:
            fm = pyds.NvDsFrameMeta.cast(l_frame.data)
            try:
                self._frame(buf, fm)
            except Exception:
                log.exception("probe failed on a frame")
            l_frame = l_frame.next
        return Gst.PadProbeReturn.OK

    def _frame(self, buf, fm):
        sb = self.bins.get(fm.pad_index)
        if sb is None:
            return
        st = self.state.get(sb.src.id)
        if st is not None and st.get("status") in ("connecting", "reconnecting", "starting"):
            st["status"] = "live" if sb.src.is_live else "running"
            st["failures"] = 0
        if not fm.bInferDone:
            return
        self.stats["frames_inferred"] += 1
        # nvstreammux scaled the (ROI-cropped) source into mux_width x mux_height, padding right/bottom.
        if sb.src.is_image:
            hit = sb.image_for_pts(fm.buf_pts)
            image_file, (w, h) = (hit[0], hit[1]) if hit else (None, sb.frame_size)
            cl, ct, cw, ch = 0, 0, w, h
        else:
            image_file = None
            w, h = sb.frame_size
            cl, ct, cw, ch = sb.crop if sb.crop else (0, 0, w, h)
        if not cw or not ch:
            return
        scale = min(self.cfg.mux_width / cw, self.cfg.mux_height / ch)
        dets, plates = [], []
        l_obj = fm.obj_meta_list
        while l_obj is not None:
            om = pyds.NvDsObjectMeta.cast(l_obj.data)
            l_obj = l_obj.next
            r = om.detector_bbox_info.org_bbox_coords
            if r.width <= 0:  # tracker-only object (no detection in this frame)
                continue
            box = [r.left / scale + cl, r.top / scale + ct, (r.left + r.width) / scale + cl,
                   (r.top + r.height) / scale + ct]
            mp = om.mask_params
            scores = np.array(mp.get_mask_array(), dtype=np.float32)[:C.NUM_CLASSES].copy() if mp.size >= 192 else None
            tid = int(om.object_id) if om.object_id != 0xFFFFFFFFFFFFFFFF else -1
            dets.append({"box": box, "cls": int(om.class_id), "score": float(om.confidence), "scores": scores,
                         "track_id": tid})
            if om.class_id == C.FACE_ID and self.cfg.osd and sb.src.face_blur:
                om.rect_params.has_bg_color = 1       # opaque privacy mask on the output stream
                om.rect_params.bg_color.set(0.1, 0.1, 0.1, 1.0)
                om.rect_params.border_width = 0
            elif om.class_id != C.PLATE_ID:
                om.rect_params.border_width = 0 if self.cfg.osd else om.rect_params.border_width
            if om.class_id == C.PLATE_ID:
                plates.append((om, r, tid))
                if self.cfg.osd:
                    om.text_params.display_text = self.worker.osd_text(sb.src.id, tid)
        item = FrameItem(fm.pad_index, frame_num=fm.frame_num, t=fm.ntp_timestamp / 1e9 if fm.ntp_timestamp else time.time(),
                         pts=fm.buf_pts, dets=dets, frame_size=(w, h), image_file=image_file)
        # Evidence crop: only when a plate is larger than any earlier frame of its track (or in image mode).
        need = [(om, r, tid) for om, r, tid in plates
                if sb.src.is_image or r.width > self.best_width.get((fm.pad_index, tid), 0.0)]
        if need:
            try:
                surface = pyds.get_nvds_buf_surface(hash(buf), fm.batch_id)
                for om, r, tid in need:
                    x1, y1 = max(0, int(r.left)), max(0, int(r.top))
                    x2, y2 = int(r.left + r.width), int(r.top + r.height)
                    key = tid if not sb.src.is_image else len(item.crops)
                    item.crops[key] = np.array(surface[y1:y2, x1:x2], copy=True)
                    self.best_width[(fm.pad_index, tid)] = r.width
                pyds.unmap_nvds_buf_surface(hash(buf), fm.batch_id)
            except Exception:
                log.debug("crop copy failed", exc_info=True)
        if not self.worker.offer(item):
            self.stats["worker_dropped"] += 1

    # --- bus / lifecycle ----------------------------------------------------------------------------------------
    def _source_index_of(self, msg) -> Optional[int]:
        path = msg.src.get_path_string() if msg.src is not None else ""
        m = re.search(r"source-bin-(\d+)", path or "")
        if m:
            return int(m.group(1))
        dbg = msg.parse_error()[1] if msg.type == Gst.MessageType.ERROR else ""
        m = re.search(r"source-bin-(\d+)", dbg or "")
        return int(m.group(1)) if m else None

    def _on_message(self, _bus, msg):
        t = msg.type
        if t == Gst.MessageType.EOS:
            log.info("pipeline EOS")
            self.loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            idx = self._source_index_of(msg)
            if idx is not None and idx in self.bins:
                sb = self.bins[idx]
                if sb.src.is_live:
                    self._schedule_reconnect(idx, f"{err.message} {dbg or ''}")
                else:
                    log.error("[%s] source error, removing it: %s", sb.src.id, err.message)
                    self.state[sb.src.id].update(status="error", last_error=err.message)
                    if len(self.bins) == 1 and self.cfg.exit_on_eos:
                        self.loop.quit()
                    else:
                        self._detach(idx)
            else:
                log.error("pipeline error from %s: %s (%s)", msg.src.get_name() if msg.src else "?", err.message, dbg)
                self.loop.quit()
        elif t == Gst.MessageType.WARNING:
            w, dbg = msg.parse_warning()
            log.warning("%s: %s", msg.src.get_name() if msg.src else "?", w.message)
        return True

    def _health_tick(self):
        now = time.time()
        for idx, sb in list(self.bins.items()):
            st = self.state.get(sb.src.id)
            if st is None:
                continue
            prev = st.get("_frames_prev", 0)
            st["fps_in"] = round((sb.frames_in - prev) / 2.0, 2)
            st["_frames_prev"] = sb.frames_in
            st["frames_in"] = sb.frames_in
            st["last_frame_age_s"] = round(now - sb.last_buffer_t, 1) if sb.last_buffer_t else None
            if sb.src.is_live and st.get("status") == "live" and sb.last_buffer_t and now - sb.last_buffer_t > 20:
                self._schedule_reconnect(idx, "no frames for 20 s")
        return True

    def health(self) -> Dict[str, Any]:
        return {"sources": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in self.state.items()},
                "pipeline": dict(self.stats), "worker": self.worker.stats_snapshot()}

    def run(self) -> None:
        GLib.timeout_add(2000, self._health_tick)
        GLib.timeout_add(500, lambda: (self.worker.tick(), True)[1])
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("pipeline refused to start")
        try:
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            self.worker.finish()
