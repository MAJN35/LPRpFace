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

import collections
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
from lpr_reader.decode import iou_matrix  # noqa: E402

from .config import Source  # noqa: E402
from .live import LiveOsd, MediaGateway  # noqa: E402
from .sources import SourceBin  # noqa: E402

log = logging.getLogger("lpr.pipeline")
NET = 960
RECONNECT_MIN_S, RECONNECT_MAX_S = 2.0, 60.0
AUTH_RETRY_MIN_S, AUTH_RETRY_MAX_S = 300.0, 3600.0
STALL_S = 20.0             # no frame for this long -> "reconnecting" (nvurisrcbin retries every RTSP_RECONNECT_S)
NEVER_CONNECTED_S = 30.0   # a live source without any frame after this long is rebuilt (backoff)


def is_auth_error(text: str) -> bool:
    t = (text or "").lower()
    return "unauthorized" in t or "401" in t or "forbidden" in t or "403" in t


@dataclass
class AppConfig:
    nvinfer_config: str
    tracker_config: str
    max_batch: int = 4
    mux_width: int = 1920     # square like the 960x960 network input: every aspect ratio keeps its full scale
    mux_height: int = 1920    # (a 16:9 canvas shrank portrait/4:3 images to ~56 % before the letterbox)
    batched_push_timeout_us: int = 40000
    interval: int = 0
    live: bool = False                     # live view: one detection stream at a time + raw camera paths
    media_rtsp: str = "rtsp://media:8554"  # mediamtx RTSP (the detection stream is published as <id>-osd)
    media_api: str = "http://media:9997"   # mediamtx API (raw camera paths are registered here)
    restream: bool = True                  # read network cameras through the gateway (one camera connection)
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
    # faces (face recognition, LPR_FACES=1): tracked faces in this frame and RGBA crops (with margin) of those larger
    # than any earlier frame of their track: {track_id, box (source px), score, crop_box (face inside the crop)}
    faces: List[Dict[str, Any]] = field(default_factory=list)
    face_crops: Dict[int, np.ndarray] = field(default_factory=dict)


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
        self.best_face: Dict[Tuple[int, int], float] = {}    # (source index, track id) -> best face width seen
        self.faces_on = os.environ.get("LPR_FACES", "1") == "1"
        self.gateway = MediaGateway(cfg.media_api) if cfg.live else None
        self.live_osd: Optional[LiveOsd] = None
        self._pending: Dict[Tuple[int, int], FrameItem] = {}  # probe A -> probe B, by (pad index, frame number)
        self.playing_since: Optional[float] = None
        # per source: inferred frames (for fps_out) and recent latencies muxer arrival -> after tracker (ms)
        self.inferred: Dict[str, int] = collections.Counter()
        self.latency_ms: Dict[str, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=600))
        self.stats = {"frames_inferred": 0, "worker_dropped": 0, "inference_fps": 0.0}
        self._fps_hist: collections.deque = collections.deque(maxlen=6)   # (time, frames_inferred) every 2 s
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
            el.set_property(k.rstrip("_").replace("_", "-"), v)  # async_ -> async
        self.pipeline.add(el)
        return el

    def _build(self):
        cfg = self.cfg
        self.pipeline = Gst.Pipeline.new("lpr")
        # A file played in real time is paced like a camera: with a non-live muxer and a synced sink the pipeline
        # stalled after a few frames (measured), with a live muxer it runs.
        live = any(s.is_live or (s.type == "file" and s.realtime) for s in self.configs.values())
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
        if cfg.live:
            # One detection stream at a time (memory): valve (closed without a viewer) -> tiler showing the selected
            # source full size -> nvdsosd -> crop/scale -> H.264 -> appsink -> separate publisher (live.LiveOsd).
            self.live_osd = LiveOsd(self.pipeline, cfg.media_rtsp, cfg.mux_width)
            chain += self.live_osd.elements
        else:
            sync = any(s.type == "file" and s.realtime for s in self.configs.values())
            # async=false when not synced: the pipeline must reach PLAYING without a first frame (e.g. only the
            # API image source, idle until an upload); a synced real-time file keeps async prerolling.
            sink = self._make("fakesink", "sink", sync=sync, qos=False)
            if not sync:
                sink.set_property("async", False)
            chain.append(sink)
        for a, b in zip(chain, chain[1:]):
            if not a.link(b):
                raise RuntimeError(f"cannot link {a.get_name()} -> {b.get_name()}")
        self.pgie.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._batch_probe(self._detections))
        q3.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._batch_probe(self._frame))
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    # --- sources ------------------------------------------------------------------------------------------------
    def _attach(self, src: Source, relay_checked: Optional[bool] = None) -> None:
        """Restream: a network camera is read through the gateway, but only once the gateway has its stream (connecting
        earlier fails, and DeepStream 6.3's reconnect then leaves the decoder broken - measured). The wait runs off
        the main loop; if the gateway is not ready within 30 s the camera is read directly, so inference never
        depends on the gateway."""
        relay_wanted = self.cfg.live and self.cfg.restream and self.gateway is not None and \
            src.type in ("rtsp", "rtmp", "http", "hls")
        if relay_wanted and relay_checked is None:
            self.gateway.register_raw(src)
            self.state.setdefault(src.id, {"failures": 0, "reconnects": 0}).update(status="connecting", started_at=time.time())

            def wait():
                ok = self.gateway.wait_ready(src.id, 30.0)
                if not ok:
                    log.warning("[%s] gateway has no stream after 30 s: reading the camera directly", src.id)
                # removed or replaced while waiting: nothing to attach
                GLib.idle_add(lambda: (self.configs.get(src.id) is src and src.id not in self.by_id
                                       and self._attach(src, ok), False)[-1])
            threading.Thread(target=wait, name=f"relay-{src.id}", daemon=True).start()
            return
        idx = self._next_index
        self._next_index += 1
        relay = f"{self.cfg.media_rtsp.rstrip('/')}/{src.id}" if relay_wanted and relay_checked else None
        sb = SourceBin(src, idx, on_image_done=self.worker.image_failed, input_uri=relay)
        self.pipeline.add(sb.bin)
        sink = self.mux.get_request_pad(f"sink_{idx}")
        if sb.bin.get_static_pad("src").link(sink) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"cannot link source {src.id} to the muxer")
        sb.bin.get_static_pad("src").add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, self._source_event, idx)
        with self._lock:
            self.bins[idx] = sb
            self.by_id[src.id] = idx
        st = self.state.setdefault(src.id, {"failures": 0, "reconnects": 0})
        st.update(status="connecting", started_at=time.time(), retry_at=None, frames_in=0, fps_in=0.0, _frames_prev=0)
        self.worker.register(sb)
        if self.gateway is not None:
            self.gateway.register_raw(src)
        # also while the pipeline is still on its way to PLAYING (a deferred relay attach lands then)
        _, cur, pending = self.pipeline.get_state(0)
        if cur in (Gst.State.PLAYING, Gst.State.PAUSED) or pending in (Gst.State.PLAYING, Gst.State.PAUSED):
            sb.bin.sync_state_with_parent()
        sb.start_feeder()
        where = src.uri_redacted or (src.device if src.type == "usb" else f"sensor {src.sensor_id}" if src.type == "csi" else "")
        log.info("[%s] attached as mux pad %d (%s %s)", src.id, idx, src.type, where)

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
        if self.live_osd is not None and self.live_osd.index == idx:
            self.live_osd.stop()
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
        if self.gateway is not None:
            self.gateway.unregister_raw(sid)
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

    def live_start(self, sid: str) -> str:
        """A viewer opened <sid>-osd (called by the media gateway). One detection stream at a time."""
        idx = self.by_id.get(sid)
        if self.live_osd is None or idx is None:
            return "unknown"
        if self.bins[idx].src.is_image:
            return "not_video"
        if self.live_osd.index not in (None, idx):
            return "busy"
        GLib.idle_add(self._idle(self.live_osd.start, idx, sid))
        return "starting"

    def live_stop(self, sid: str) -> str:
        idx = self.by_id.get(sid)
        if self.live_osd is None or idx is None or self.live_osd.index != idx:
            return "not_running"
        GLib.idle_add(self._idle(self.live_osd.stop))
        return "stopping"

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

    # --- probes (streaming threads: metadata only, never block) -------------------------------------------------
    # A (nvinfer src): every detection with its 48 class scores. The tracker drops targets in their first
    # (tentative) frame, so detections must be read before it - image frames are always first frames.
    # B (tracker src): track ids are joined to A's detections by box; crops; hand-off to the worker.
    def _batch_probe(self, handler):
        def probe(_pad, info):
            buf = info.get_buffer()
            if buf is None:
                return Gst.PadProbeReturn.OK
            batch = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
            l_frame = batch.frame_meta_list
            while l_frame is not None:
                fm = pyds.NvDsFrameMeta.cast(l_frame.data)
                try:
                    handler(buf, fm)
                except Exception:
                    log.exception("probe failed on a frame")
                l_frame = l_frame.next
            return Gst.PadProbeReturn.OK
        return probe

    def _geometry(self, sb, fm):
        """-> (image_file, (w, h), (crop_left, crop_top, crop_w, crop_h), mux scale) for mapping mux -> source px.
        nvstreammux (enable-padding=1) scaled the (ROI-cropped) source into mux_width x mux_height keeping the aspect
        ratio and CENTERED it (measured: offsets equal (mux - size*scale)/2); see _to_source."""
        if sb.src.is_image:
            hit = sb.image_for_pts(fm.buf_pts)
            image_file, (w, h) = (hit[0], hit[1]) if hit else (None, sb.frame_size)
            cl, ct, cw, ch = 0, 0, w, h
        else:
            image_file = None
            w, h = sb.frame_size
            cl, ct, cw, ch = sb.crop if sb.crop else (0, 0, w, h)
        scale = min(self.cfg.mux_width / cw, self.cfg.mux_height / ch) if cw and ch else 0.0
        return image_file, (w, h), (cl, ct, cw, ch), scale

    def _detections(self, buf, fm):  # probe A
        sb = self.bins.get(fm.pad_index)
        if sb is None or not fm.bInferDone:
            return
        image_file, (w, h), (cl, ct, cw, ch), scale = self._geometry(sb, fm)
        if not scale:
            return
        dets = []
        l_obj = fm.obj_meta_list
        while l_obj is not None:
            om = pyds.NvDsObjectMeta.cast(l_obj.data)
            l_obj = l_obj.next
            r = om.rect_params
            mux = [r.left, r.top, r.left + r.width, r.top + r.height]
            px = (self.cfg.mux_width - cw * scale) / 2   # centered padding
            py = (self.cfg.mux_height - ch * scale) / 2
            box = [(mux[0] - px) / scale + cl, (mux[1] - py) / scale + ct,
                   (mux[2] - px) / scale + cl, (mux[3] - py) / scale + ct]
            mp = om.mask_params
            scores = np.array(mp.get_mask_array(), dtype=np.float32)[:C.NUM_CLASSES].copy() if mp.size >= 192 else None
            dets.append({"box": box, "mux_box": mux, "cls": int(om.class_id), "score": float(om.confidence),
                         "scores": scores, "track_id": -1})
        item = FrameItem(fm.pad_index, frame_num=fm.frame_num,
                         t=fm.ntp_timestamp / 1e9 if fm.ntp_timestamp else time.time(), pts=fm.buf_pts, dets=dets,
                         frame_size=(w, h), image_file=image_file)
        with self._lock:
            self._pending[(fm.pad_index, fm.frame_num)] = item
            if len(self._pending) > 256:  # frames dropped between the probes must not leak
                for k in list(self._pending)[:128]:
                    self._pending.pop(k, None)

    # Detection-stream look (live view): brand colours, plate label above the box, faces masked or outlined, and a
    # header bar with camera, model rate and local time. The OSD cannot shape Persian, so plate text is Latin (A.7).
    PLATE_RGBA = (0.18, 0.53, 1.0, 1.0)         # EdgeTech blue
    LABEL_BG = (0.06, 0.32, 0.80, 0.88)
    FACE_RGBA = (1.0, 0.71, 0.28, 1.0)          # amber
    HEADER_BG = (0.05, 0.09, 0.15, 0.62)

    def _style(self, sb, fm) -> None:
        _, _, (cl, ct, cw, ch), scale = self._geometry(sb, fm)
        x0 = (self.cfg.mux_width - cw * scale) / 2       # the camera image inside the square mux canvas
        y0 = (self.cfg.mux_height - ch * scale) / 2
        unit = max(12, int(cw * scale / 64))             # text size follows the shown image width
        l_obj = fm.obj_meta_list
        while l_obj is not None:
            om = pyds.NvDsObjectMeta.cast(l_obj.data)
            l_obj = l_obj.next
            r = om.rect_params
            tp = om.text_params
            if om.class_id == C.PLATE_ID:
                tid = int(om.object_id) if om.object_id != 0xFFFFFFFFFFFFFFFF else -1
                text = self.worker.osd_text(sb.src.id, tid)
                r.border_width = max(2, unit // 6)
                r.border_color.set(*self.PLATE_RGBA)
                r.has_bg_color = 1
                r.bg_color.set(0.18, 0.53, 1.0, 0.10)
                tp.display_text = f" {text} " if text else ""
                if text:
                    tp.font_params.font_name = "Sans Bold"
                    tp.font_params.font_size = unit
                    tp.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
                    tp.set_bg_clr = 1
                    tp.text_bg_clr.set(*self.LABEL_BG)
                    tp.x_offset = int(max(x0, r.left))
                    tp.y_offset = int(max(y0, r.top - unit * 2.1))
            elif om.class_id == C.FACE_ID:
                tp.display_text = ""
                if sb.src.face_blur:
                    self.stats["faces_masked"] = self.stats.get("faces_masked", 0) + 1
                    r.has_bg_color = 1
                    r.bg_color.set(0.1, 0.1, 0.1, 1.0)
                    r.border_width = 0
                else:
                    r.border_width = max(2, unit // 8)
                    r.border_color.set(*self.FACE_RGBA)
                    r.has_bg_color = 0
            else:
                r.border_width = 0
                tp.display_text = ""
        self._header(sb, fm, x0, y0, cw * scale, unit)
        self.live_osd.set_geometry(self.cfg.mux_width, self.cfg.mux_height, cw, ch, scale)

    def _header(self, sb, fm, x0: float, y0: float, width: float, unit: int) -> None:
        dm = pyds.nvds_acquire_display_meta_from_pool(fm.base_meta.batch_meta)
        dm.num_rects = 1
        bar = dm.rect_params[0]
        bar.left, bar.top, bar.width, bar.height = x0, y0, width, unit * 2.4
        bar.border_width = 0
        bar.has_bg_color = 1
        bar.bg_color.set(*self.HEADER_BG)
        dm.num_labels = 1
        lab = dm.text_params[0]
        fps = self.state.get(sb.src.id, {}).get("fps_out", 0.0)
        lab.display_text = f"  EdgeTech LPR  |  {sb.src.name if sb.src.name and sb.src.name.isascii() else sb.src.id}  |  model {fps:.1f} fps  |  " \
                           f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
        lab.x_offset, lab.y_offset = int(x0 + unit * 0.4), int(y0 + unit * 0.45)
        lab.font_params.font_name = "Sans Bold"
        lab.font_params.font_size = max(10, int(unit * 0.85))
        lab.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
        lab.set_bg_clr = 0
        pyds.nvds_add_display_meta_to_frame(fm, dm)

    def _frame(self, buf, fm):  # probe B
        sb = self.bins.get(fm.pad_index)
        if sb is None:
            return
        st = self.state.get(sb.src.id)
        if st is not None and st.get("status") in ("connecting", "reconnecting", "starting"):
            st["status"] = "live" if sb.src.is_live else "running"
            st["failures"] = 0
        if self.live_osd is not None and self.live_osd.index == fm.pad_index:
            self._style(sb, fm)
        with self._lock:
            item = self._pending.pop((fm.pad_index, fm.frame_num), None)
        if item is None:  # not an inferred frame (interval) or not seen by probe A
            return
        self.stats["frames_inferred"] += 1
        self.inferred[sb.src.id] += 1
        if fm.ntp_timestamp:
            self.latency_ms[sb.src.id].append((time.time() - fm.ntp_timestamp / 1e9) * 1000.0)
        # Track ids: tracker plate objects (detector box kept in detector_bbox_info) -> nearest plate detection.
        plate_dets = [d for d in item.dets if d["cls"] == C.PLATE_ID]
        l_obj = fm.obj_meta_list
        while l_obj is not None:
            om = pyds.NvDsObjectMeta.cast(l_obj.data)
            l_obj = l_obj.next
            if om.class_id != C.PLATE_ID or om.object_id == 0xFFFFFFFFFFFFFFFF:
                continue
            r = om.detector_bbox_info.org_bbox_coords
            if r.width <= 0:
                r = om.rect_params
            tb = [r.left, r.top, r.left + r.width, r.top + r.height]
            best, best_iou = None, 0.5
            for d in plate_dets:
                iou = float(_iou(tb, d["mux_box"]))
                if iou >= best_iou:
                    best, best_iou = d, iou
            if best is not None:
                best["track_id"] = int(om.object_id)
        # Evidence crop: only when a plate is larger than any earlier frame of its track (every plate in image mode).
        need = []
        for k, d in enumerate(plate_dets):
            mb = d["mux_box"]
            width = mb[2] - mb[0]
            key = k if sb.src.is_image else d["track_id"]
            if sb.src.is_image or (d["track_id"] >= 0 and width > self.best_width.get((fm.pad_index, key), 0.0)):
                need.append((key, mb, width))
        if need:
            try:
                surface = pyds.get_nvds_buf_surface(hash(buf), fm.batch_id)
                for key, mb, width in need:
                    x1, y1, x2, y2 = (max(0, int(v)) for v in mb)
                    item.crops[key] = np.array(surface[y1:y2, x1:x2], copy=True)
                    if not sb.src.is_image:
                        self.best_width[(fm.pad_index, key)] = width
                pyds.unmap_nvds_buf_surface(hash(buf), fm.batch_id)
            except Exception:
                log.debug("crop copy failed", exc_info=True)
        if self.faces_on:
            self._faces(buf, fm, sb, item)
        dump = os.environ.get("LPR_DEBUG_DUMP_DIR")
        if dump:
            log.info("[debug] %s frame %d pts %d file %s: %d detections, %d plates, tracks %s", sb.src.id,
                     fm.frame_num, fm.buf_pts, item.image_file, len(item.dets), len(plate_dets),
                     [d["track_id"] for d in plate_dets])
        for d in item.dets:
            d.pop("mux_box", None)
        if not self.worker.offer(item):
            self.stats["worker_dropped"] += 1

    FACE_MARGIN = 0.35   # context around the face in its snapshot (the embedder finds landmarks in it)

    def _faces(self, buf, fm, sb, item: FrameItem) -> None:
        """Tracked faces of this frame; a snapshot when the face is larger than any earlier frame of its track."""
        _, _, (cl, ct, cw, ch), scale = self._geometry(sb, fm)
        if not scale:
            return
        px, py = (self.cfg.mux_width - cw * scale) / 2, (self.cfg.mux_height - ch * scale) / 2
        need = []
        l_obj = fm.obj_meta_list
        while l_obj is not None:
            om = pyds.NvDsObjectMeta.cast(l_obj.data)
            l_obj = l_obj.next
            if om.class_id != C.FACE_ID or om.object_id == 0xFFFFFFFFFFFFFFFF:
                continue
            r = om.rect_params
            tid = int(om.object_id)
            box = [(r.left - px) / scale + cl, (r.top - py) / scale + ct,
                   (r.left + r.width - px) / scale + cl, (r.top + r.height - py) / scale + ct]
            item.faces.append({"track_id": tid, "box": box, "score": float(om.confidence), "crop_box": None})
            key = (fm.pad_index, tid)
            if r.width > self.best_face.get(key, 0.0):
                need.append((tid, (r.left, r.top, r.width, r.height), item.faces[-1]))
                self.best_face[key] = r.width
        if len(self.best_face) > 4000:     # old tracks: forget the oldest half
            for k in list(self.best_face)[:2000]:
                self.best_face.pop(k, None)
        if not need:
            return
        try:
            surface = pyds.get_nvds_buf_surface(hash(buf), fm.batch_id)
            H, W = surface.shape[:2]
            for tid, (x, y, w, h), face in need:
                m = self.FACE_MARGIN
                x1, y1 = max(0, int(x - m * w)), max(0, int(y - m * h))
                x2, y2 = min(W, int(x + w + m * w)), min(H, int(y + h + m * h))
                item.face_crops[tid] = np.array(surface[y1:y2, x1:x2], copy=True)
                face["crop_box"] = [int(x - x1), int(y - y1), int(x - x1 + w), int(y - y1 + h)]
            pyds.unmap_nvds_buf_surface(hash(buf), fm.batch_id)
        except Exception:
            log.debug("face crop copy failed", exc_info=True)

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
        elif t == Gst.MessageType.ERROR and (msg.src.get_name() if msg.src else "").startswith("live-"):
            err, _ = msg.parse_error()
            log.warning("live view element %s: %s (inference continues)", msg.src.get_name(), err.message)
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
        elif t == Gst.MessageType.STATE_CHANGED and msg.src == self.pipeline:
            if msg.parse_state_changed()[1] == Gst.State.PLAYING and self.playing_since is None:
                self.playing_since = time.time()
                log.info("pipeline PLAYING")
        elif t == Gst.MessageType.WARNING:
            w, dbg = msg.parse_warning()
            log.warning("%s: %s", msg.src.get_name() if msg.src else "?", w.message)
        return True

    def _health_tick(self):
        """Per-source health every 2 s. A source that has produced frames is left to nvurisrcbin's own RTSP
        reconnect (replacing its bin while the camera is down defeats it: a bin attached at runtime whose first
        connection fails never retries). Only a live source that has never produced a frame is rebuilt, with
        backoff, since each new bin is a fresh connection attempt."""
        now = time.time()
        # model rate: frames inferred per second over the last ~10 s, all sources together
        self._fps_hist.append((now, self.stats["frames_inferred"]))
        (t0, n0), (t1, n1) = self._fps_hist[0], self._fps_hist[-1]
        self.stats["inference_fps"] = round((n1 - n0) / (t1 - t0), 2) if t1 > t0 else 0.0
        for idx, sb in list(self.bins.items()):
            st = self.state.get(sb.src.id)
            if st is None:
                continue
            prev = st.get("_frames_prev", 0)
            st["fps_in"] = round(max(0, sb.frames_in - prev) / 2.0, 2)
            st["_frames_prev"] = sb.frames_in
            done = self.inferred.get(sb.src.id, 0)
            st["fps_out"] = round(max(0, done - st.get("_inferred_prev", 0)) / 2.0, 2)   # frames inferred per s
            st["_inferred_prev"] = done
            st["frames_inferred"] = done
            lat = sorted(self.latency_ms.get(sb.src.id, ()))
            if lat:
                st["latency_ms_p50"] = round(lat[len(lat) // 2], 1)
                st["latency_ms_p95"] = round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1)
            st["frames_in"] = sb.frames_in
            st["last_frame_age_s"] = round(now - sb.last_buffer_t, 1) if sb.last_buffer_t else None
            if sb.src.type == "image_job":
                if st.get("status") in ("connecting", "starting"):
                    st["status"] = "idle"
                continue
            if not sb.src.is_live:
                continue
            if sb.last_buffer_t is None:
                # count from when the pipeline started playing (the engine load takes ~35 s before that)
                waited = now - max(st.get("started_at") or now, self.playing_since or now)
                if waited > NEVER_CONNECTED_S and not st.get("retry_at"):
                    st["status"] = "no_signal"
                    self._schedule_reconnect(idx, f"no frames since start ({waited:.0f} s)")
            elif now - sb.last_buffer_t > STALL_S:
                if st.get("status") == "live":
                    log.warning("[%s] no frames for %.0f s; waiting for the source's own reconnect", sb.src.id,
                                now - sb.last_buffer_t)
                st["status"] = "reconnecting"
            elif st.get("status") == "reconnecting":
                st["status"] = "live"
                st["reconnects"] = st.get("reconnects", 0) + 1
        return True

    def health(self) -> Dict[str, Any]:
        if self.live_osd is not None:
            for idx, sb in list(self.bins.items()):
                if sb.src.id in self.state and not sb.src.is_image:
                    shown = self.live_osd.index == idx
                    self.state[sb.src.id]["live"] = dict(self.live_osd.stats() if shown else {"publishing": False},
                                                         osd_active=shown, osd_path=f"{sb.src.id}-osd",
                                                         raw_path=sb.src.id if sb.src.type in ("rtsp", "rtmp", "http", "hls") else None)
        return {"sources": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in self.state.items()},
                "pipeline": dict(self.stats), "worker": self.worker.stats_snapshot()}

    def run(self) -> None:
        GLib.timeout_add(2000, self._health_tick)
        GLib.timeout_add(500, lambda: (self.worker.tick(), True)[1])
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("pipeline refused to start")
        # Never block here: without data the pipeline cannot preroll, and the main loop must run anyway (runtime
        # add/enable and health live on it). PLAYING is also recorded from the bus.
        if self.pipeline.get_state(10 * Gst.SECOND)[1] == Gst.State.PLAYING:
            self.playing_since = time.time()
        try:
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            self.worker.finish()


def _iou(a, b) -> float:
    return float(iou_matrix(a, b)[0, 0])
