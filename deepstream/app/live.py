"""Live view: raw camera streams and per-camera detection overlay (OSD) through the mediamtx gateway.

* Raw: for network cameras (rtsp/rtmp/http/hls) a mediamtx path ``<id>`` is registered through mediamtx's internal
  API with the camera URI as its source, pulled continuously so several views open at once without a start-up wait
  (a second camera session; mediamtx only remuxes, no decoding).
* OSD (detection stream): one source at a time (memory: an encoder per camera does not fit the 8 GB board, and
  nvstreamdemux cannot add pads at runtime - both measured). The first viewer of ``<id>-osd`` selects the source
  (mediamtx runOnDemand -> control API); see ``LiveOsd``. A separate small publisher pipeline (appsrc ->
  rtspclientsink -> mediamtx) takes the encoded frames, so a gateway outage never raises an error inside the
  inference pipeline; the publisher retries every 5 s on its own.
The browser plays both through nginx (HLS, behind the dashboard login).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

from .config import Source, URI_TYPES  # noqa: E402

log = logging.getLogger("lpr.live")
RAW_TYPES = tuple(t for t in URI_TYPES if t != "file")
PUBLISH_RETRY_S = 5


class MediaGateway:
    """Registers/unregisters raw camera paths in mediamtx (HTTP API on the internal network), off the main thread."""

    def __init__(self, api_url: str):
        self.api = api_url.rstrip("/")
        self._paths: Dict[str, str] = {}  # id -> camera URI (with credentials; never logged)
        self._lock = threading.Lock()
        threading.Thread(target=self._sync_loop, name="media-gateway", daemon=True).start()

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> int:
        req = urllib.request.Request(self.api + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:  # noqa: BLE001 - gateway not up yet
            return 0

    def register_raw(self, src: Source) -> None:
        if src.type in RAW_TYPES:
            with self._lock:
                self._paths[src.id] = src.uri

    def unregister_raw(self, sid: str) -> None:
        with self._lock:
            self._paths.pop(sid, None)
        self._call("DELETE", f"/v3/config/paths/delete/{sid}")

    def _sync_loop(self) -> None:
        """Keep mediamtx in sync (it may start later or restart): add missing raw paths every 10 s."""
        while True:
            with self._lock:
                paths = dict(self._paths)
            for sid, uri in paths.items():
                conf = {"source": uri, "sourceOnDemand": False, "rtspTransport": "tcp"}
                code = self._call("POST", f"/v3/config/paths/add/{sid}", conf)
                if code == 400:  # exists: make sure it points at the current URI
                    code = self._call("PATCH", f"/v3/config/paths/patch/{sid}", conf)
                if code not in (200, 400):
                    log.debug("raw path %s: gateway answered %s", sid, code)
            time.sleep(10)


class Publisher:
    """appsrc -> h264parse -> rtspclientsink in its own pipeline; restarts itself after errors."""

    def __init__(self, url: str, name: str):
        self.url, self.name = url, name
        self.pipe: Optional[Gst.Pipeline] = None
        self.src = None
        self.ok = False
        self.pushed = 0
        self._closed = False
        self._start()

    def _start(self) -> bool:
        if self._closed:
            return False
        p = Gst.parse_launch(
            "appsrc name=src is-live=true format=time do-timestamp=true "
            "caps=video/x-h264,stream-format=byte-stream,alignment=au ! h264parse config-interval=-1 ! "
            f"rtspclientsink name=sink location={self.url} protocols=tcp latency=0")
        self.pipe, self.src = p, p.get_by_name("src")
        bus = p.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        self.ok = p.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE
        return False

    def _on_error(self, _bus, msg):
        err, _ = msg.parse_error()
        if self.ok:
            log.warning("[%s] live publisher: %s; retrying every %d s", self.name, err.message, PUBLISH_RETRY_S)
        self.ok = False
        p = self.pipe
        self.pipe, self.src = None, None
        if p is not None:
            p.get_bus().remove_signal_watch()
            p.set_state(Gst.State.NULL)
        GLib.timeout_add_seconds(PUBLISH_RETRY_S, self._start)

    def push(self, sample) -> None:
        src = self.src
        if src is None or not self.ok:
            return
        buf = sample.get_buffer()
        if src.emit("push-buffer", buf.copy()) == Gst.FlowReturn.OK:
            self.pushed += 1

    def close(self) -> None:
        self._closed = True
        if self.pipe is not None:
            self.pipe.get_bus().remove_signal_watch()
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None


def _make(factory: str, name: str, **props) -> Gst.Element:
    el = Gst.ElementFactory.make(factory, name)
    if el is None:
        raise RuntimeError(f"cannot create {factory}")
    for k, v in props.items():
        el.set_property(k.rstrip("_").replace("_", "-"), v)  # async_ -> async
    return el


class LiveOsd:
    """The detection stream: one source at a time, so one encoder (the board's memory cannot afford one per camera).

    valve (drops everything while nobody watches) -> nvmultistreamtiler (shows the selected source full size, keeps
    object metadata in tile coordinates) -> nvdsosd -> nvvideoconvert (crops the square muxer canvas back to the
    camera's aspect) -> H.264 (NVENC) -> appsink -> Publisher (separate pipeline) -> mediamtx <id>-osd.
    """

    SIZE = 1280  # tiler output (square, like the muxer canvas)

    def __init__(self, pipeline: Gst.Pipeline, rtsp_base: str, mux_size: int, bitrate: int = 2_000_000):
        self.rtsp_base = rtsp_base.rstrip("/")
        self.k = self.SIZE / mux_size
        self.index: Optional[int] = None
        self.sid: Optional[str] = None
        self.publisher: Optional[Publisher] = None
        self.geometry: Optional[Tuple[str, int, int]] = None
        self.valve = _make("valve", "live-valve", drop=True)
        self.tiler = _make("nvmultistreamtiler", "live-tiler", rows=8, columns=8, width=self.SIZE, height=self.SIZE)
        osd = _make("nvdsosd", "live-osd", process_mode=1, display_mask=0)
        self.conv = _make("nvvideoconvert", "live-conv")
        self.caps = _make("capsfilter", "live-caps", caps=Gst.Caps.from_string("video/x-raw(memory:NVMM),format=I420"))
        q = _make("queue", "live-q", leaky=2, max_size_buffers=2, max_size_bytes=0, max_size_time=0)
        enc = _make("nvv4l2h264enc", "live-enc", bitrate=bitrate, iframeinterval=10, idrinterval=10, insert_sps_pps=True)
        parse = _make("h264parse", "live-parse")
        out = _make("appsink", "live-out", emit_signals=True, sync=False, drop=True, max_buffers=4)
        out.connect("new-sample", self._on_sample)
        self.elements = [self.valve, self.tiler, osd, self.conv, self.caps, q, enc, parse, out]
        for el in self.elements:
            pipeline.add(el)

    def _on_sample(self, appsink):
        sample = appsink.emit("pull-sample")
        if sample is not None and self.publisher is not None:
            self.publisher.push(sample)
        return Gst.FlowReturn.OK

    def start(self, index: int, sid: str) -> None:
        if self.index == index:
            return
        self.stop()
        self.index, self.sid = index, sid
        self.tiler.set_property("show-source", index)
        self.publisher = Publisher(f"{self.rtsp_base}/{sid}-osd", sid)
        self.valve.set_property("drop", False)
        log.info("[%s] live detection stream started", sid)

    def stop(self) -> None:
        self.valve.set_property("drop", True)
        if self.publisher is not None:
            self.publisher.close()
            log.info("[%s] live detection stream stopped", self.sid)
        self.publisher, self.index, self.sid, self.geometry = None, None, None, None

    def set_geometry(self, mux_w: int, mux_h: int, cw: int, ch: int, scale: float) -> None:
        """Crop the centered camera image out of the tiler's square output; even sizes for the encoder."""
        if not cw or not ch:
            return
        k = self.k
        w, h = int(cw * scale * k) // 2 * 2, int(ch * scale * k) // 2 * 2
        left, top = int((mux_w - cw * scale) / 2 * k) // 2 * 2, int((mux_h - ch * scale) / 2 * k) // 2 * 2
        geo = (f"{left}:{top}:{w}:{h}", w, h)
        if geo != self.geometry:
            self.geometry = geo
            self.conv.set_property("src-crop", geo[0])
            self.caps.set_property("caps", Gst.Caps.from_string(
                f"video/x-raw(memory:NVMM),format=I420,width={w},height={h}"))
            log.info("[%s] live detection stream %dx%d", self.sid, w, h)

    def stats(self) -> Dict[str, object]:
        p = self.publisher
        return {"publishing": bool(p and p.ok), "frames_published": p.pushed if p else 0}
