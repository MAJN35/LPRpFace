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
        self._pending: Dict[Tuple[int, int], FrameItem] = {}  # probe A -> probe B, by (pad index, frame number)
        self.playing_since: Optional[float] = None
        # per source: inferred frames (for fps_out) and recent latencies muxer arrival -> after tracker (ms)
        self.inferred: Dict[str, int] = collections.Counter()
        self.latency_ms: Dict[str, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=600))
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
            el.set_property(k.rstrip("_").replace("_", "-"), v)  # async_ -> async
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
        self.pgie.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._batch_probe(self._detections))
        q3.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._batch_probe(self._frame))
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
        st.update(status="connecting", started_at=time.time(), retry_at=None, frames_in=0, fps_in=0.0, _frames_prev=0)
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

    def _frame(self, buf, fm):  # probe B
        sb = self.bins.get(fm.pad_index)
        if sb is None:
            return
        st = self.state.get(sb.src.id)
        if st is not None and st.get("status") in ("connecting", "reconnecting", "starting"):
            st["status"] = "live" if sb.src.is_live else "running"
            st["failures"] = 0
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
            if om.class_id == C.FACE_ID and self.cfg.osd and sb.src.face_blur:
                om.rect_params.has_bg_color = 1       # opaque privacy mask on the output stream
                om.rect_params.bg_color.set(0.1, 0.1, 0.1, 1.0)
                om.rect_params.border_width = 0
            elif om.class_id != C.PLATE_ID:
                if self.cfg.osd:
                    om.rect_params.border_width = 0
                continue
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
                if self.cfg.osd:
                    om.text_params.display_text = self.worker.osd_text(sb.src.id, int(om.object_id))
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
        dump = os.environ.get("LPR_DEBUG_DUMP_DIR")
        if dump:
            log.info("[debug] %s frame %d pts %d file %s: %d detections, %d plates, tracks %s", sb.src.id,
                     fm.frame_num, fm.buf_pts, item.image_file, len(item.dets), len(plate_dets),
                     [d["track_id"] for d in plate_dets])
        for d in item.dets:
            d.pop("mux_box", None)
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
        """Per-source health every 2 s. A source that has produced frames is left to nvurisrcbin's own RTSP
        reconnect (replacing its bin while the camera is down defeats it: a bin attached at runtime whose first
        connection fails never retries). Only a live source that has never produced a frame is rebuilt, with
        backoff, since each new bin is a fresh connection attempt."""
        now = time.time()
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
        return {"sources": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in self.state.items()},
                "pipeline": dict(self.stats), "worker": self.worker.stats_snapshot()}

    def run(self) -> None:
        GLib.timeout_add(2000, self._health_tick)
        GLib.timeout_add(500, lambda: (self.worker.tick(), True)[1])
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("pipeline refused to start")
        self.pipeline.get_state(Gst.CLOCK_TIME_NONE)  # wait until PLAYING (engine loaded)
        self.playing_since = time.time()
        try:
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            self.worker.finish()


def _iou(a, b) -> float:
    return float(iou_matrix(a, b)[0, 0])
