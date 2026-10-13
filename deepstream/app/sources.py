"""GStreamer source bins, one per source type. Every bin ends in a ghost pad "src" carrying video/x-raw(memory:NVMM)
RGBA, so all types converge on nvstreammux the same way.

  rtsp/rtmp/http/hls/file  nvurisrcbin (hardware decode, RTSP reconnect, TCP/UDP, file loop)
  usb                      v4l2src -> (MJPEG: jpegparse ! nvv4l2decoder mjpeg=1 | raw) -> nvvideoconvert
  csi                      nvarguscamerasrc
  image / image_folder / image_job
                           appsrc fed by a thread: one buffer per image (CPU decode with OpenCV, JPEG and PNG;
                           sizes vary per image, so caps are renegotiated per buffer), PTS = image index

Per source, after the decoder: optional ROI crop (nvvideoconvert src-crop = bounding box of the ROI polygon),
optional max_fps (videorate drop-only), and a leaky queue so a slow pipeline drops old frames instead of
back-pressuring the camera (from the earlier project's sources.py).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, List, Optional, Tuple
from urllib.parse import quote

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from .config import Source, split_credentials  # noqa: E402

log = logging.getLogger("lpr.sources")
RTSP_RECONNECT_S = 5


def _make(factory: str, name: str) -> Gst.Element:
    el = Gst.ElementFactory.make(factory, name)
    if el is None:
        raise RuntimeError(f"cannot create {factory}")
    return el


def _encoded_uri(uri: str) -> str:
    """Percent-encode the RTSP userinfo, so a password containing '@' or ':' survives GStreamer's URI parser
    (which splits at the first '@')."""
    clean, user, pw = split_credentials(uri)
    if user is None:
        return uri
    scheme, rest = clean.split("://", 1)
    return f"{scheme}://{quote(user, safe='')}:{quote(pw or '', safe='')}@{rest}"


def roi_crop(src: Source, width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
    """Bounding box (left, top, w, h) of the ROI polygon in pixels, even-aligned, or None."""
    if not src.roi or not width or not height:
        return None
    xs = [p[0] * width for p in src.roi]
    ys = [p[1] * height for p in src.roi]
    left, top = int(min(xs)) // 2 * 2, int(min(ys)) // 2 * 2
    right, bottom = min(width, int(max(xs) + 1)), min(height, int(max(ys) + 1))
    return left, top, (right - left) // 2 * 2, (bottom - top) // 2 * 2


class SourceBin:
    """Builds the bin for one source and keeps per-source state (health, image queue, ROI offset)."""

    def __init__(self, src: Source, index: int, on_image_done: Optional[Callable] = None,
                 input_uri: Optional[str] = None):
        self.src = src
        # restream (live view on): network cameras are read through the gateway (one camera connection shared with
        # the browsers; late joiners get the cached stream parameters); events keep the camera's own URI.
        self.input_uri = input_uri
        self.index = index                      # nvstreammux pad index = frame_meta.pad_index
        self.bin = Gst.Bin.new(f"source-bin-{index}")
        self.images: List[Tuple[str, Tuple[int, int]]] = []   # image sources: (file, (w, h)) by PTS index
        self.image_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self.on_image_done = on_image_done
        self.crop: Optional[Tuple[int, int, int, int]] = None  # ROI crop in source pixels
        self.frame_size: Tuple[int, int] = (src.width, src.height)
        self.last_buffer_t: Optional[float] = None
        self.frames_in = 0
        self._feeder: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._build()

    # --- construction -------------------------------------------------------------------------------------------
    def _build(self):
        s, i = self.src, self.index
        tail = self._tail()
        if s.type in ("rtsp", "rtmp", "http", "hls", "file"):
            uri = _make("nvurisrcbin", f"uri-{i}")
            uri.set_property("uri", self.input_uri or _encoded_uri(s.uri))
            uri.set_property("num-extra-surfaces", 4)  # decoder headroom while frames wait downstream
            if s.type == "rtsp" or self.input_uri:
                uri.set_property("rtsp-reconnect-interval", RTSP_RECONNECT_S)
                uri.set_property("select-rtp-protocol", 4 if s.rtsp_transport == "tcp" or self.input_uri else 1)
                uri.set_property("latency", 200)
            if s.type == "file":
                uri.set_property("file-loop", s.loop)
            self.bin.add(uri)
            uri.connect("pad-added", self._on_pad_added, tail)
        elif s.type == "usb":
            v4l2 = _make("v4l2src", f"v4l2-{i}")
            v4l2.set_property("device", s.device)
            caps = _make("capsfilter", f"v4l2caps-{i}")
            parts = ["image/jpeg"]
            if s.width and s.height:
                parts.append(f"width={s.width},height={s.height}")
            if s.fps:
                parts.append(f"framerate={s.fps}/1")
            caps.set_property("caps", Gst.Caps.from_string(",".join(parts)))
            parse = _make("jpegparse", f"jpegparse-{i}")
            dec = _make("nvv4l2decoder", f"mjpegdec-{i}")
            dec.set_property("mjpeg", 1)
            for el in (v4l2, caps, parse, dec):
                self.bin.add(el)
            v4l2.link(caps)
            caps.link(parse)
            parse.link(dec)
            dec.link(tail)
        elif s.type == "csi":
            cam = _make("nvarguscamerasrc", f"argus-{i}")
            cam.set_property("sensor-id", s.sensor_id)
            caps = _make("capsfilter", f"arguscaps-{i}")
            w, h, f = s.width or 1920, s.height or 1080, s.fps or 30
            caps.set_property("caps", Gst.Caps.from_string(
                f"video/x-raw(memory:NVMM),width={w},height={h},framerate={f}/1,format=NV12"))
            self.bin.add(cam)
            self.bin.add(caps)
            cam.link(caps)
            caps.link(tail)
            self.frame_size = (w, h)
        else:  # image sources
            app = _make("appsrc", f"images-{i}")
            app.set_property("format", Gst.Format.TIME)
            app.set_property("is-live", False)
            app.set_property("block", True)
            app.set_property("max-bytes", 64 << 20)
            self.appsrc = app
            conv = _make("videoconvert", f"imgconv-{i}")
            self.bin.add(app)
            self.bin.add(conv)
            app.link(conv)
            conv.link(tail)
            for f in s.files:
                self.image_queue.put(f)
            if s.type != "image_job":
                self.image_queue.put(None)  # folder/single image: EOS after the last file

    def _tail(self) -> Gst.Element:
        """nvvideoconvert (ROI crop, RGBA NVMM) -> [videorate max_fps] -> leaky queue -> ghost src."""
        s, i = self.src, self.index
        conv = _make("nvvideoconvert", f"conv-{i}")
        # More output buffers than the leaky queue can hold: with the default 4 and a 4-deep queue the converter's
        # pool ran dry, blocking the decoder and rtspsrc ("connection is too slow" on the RTSP server).
        conv.set_property("output-buffers", 8)
        self.conv = conv
        caps = _make("capsfilter", f"rgba-{i}")
        caps.set_property("caps", Gst.Caps.from_string("video/x-raw(memory:NVMM),format=RGBA"))
        chain = [conv, caps]
        if s.max_fps and not s.is_image:
            rate = _make("videorate", f"rate-{i}")
            rate.set_property("drop-only", True)
            rate.set_property("max-rate", max(1, int(round(s.max_fps))))
            chain.append(rate)
        q = _make("queue", f"srcq-{i}")
        if s.is_live:
            q.set_property("leaky", 2)
            q.set_property("max-size-buffers", 2)
            q.set_property("max-size-bytes", 0)
            q.set_property("max-size-time", 0)
        chain.append(q)
        for el in chain:
            self.bin.add(el)
        for a, b in zip(chain, chain[1:]):
            a.link(b)
        self.bin.add_pad(Gst.GhostPad.new("src", q.get_static_pad("src")))
        conv.get_static_pad("sink").add_probe(Gst.PadProbeType.BUFFER, self._on_buffer)
        conv.get_static_pad("sink").add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, self._on_caps)
        return conv

    def _on_pad_added(self, _uribin, pad, conv):
        caps = pad.get_current_caps() or pad.query_caps(None)
        if caps and caps.get_structure(0).get_name().startswith("video/"):
            sink = conv.get_static_pad("sink")
            if not sink.is_linked():
                pad.link(sink)

    def _on_caps(self, _pad, info):
        ev = info.get_event()
        if ev is not None and ev.type == Gst.EventType.CAPS:
            st = ev.parse_caps().get_structure(0)
            ok_w, w = st.get_int("width")
            ok_h, h = st.get_int("height")
            if ok_w and ok_h and (w, h) != tuple(self.frame_size) and not self.src.is_image:
                self.frame_size = (w, h)
                self.crop = roi_crop(self.src, w, h)
                if self.crop:
                    left, top, cw, ch = self.crop
                    self.conv.set_property("src-crop", f"{left}:{top}:{cw}:{ch}")
                log.info("[%s] input %dx%d%s", self.src.id, w, h, f", ROI crop {self.crop}" if self.crop else "")
        return Gst.PadProbeReturn.OK

    def _on_buffer(self, _pad, _info):
        self.last_buffer_t = time.time()
        self.frames_in += 1
        return Gst.PadProbeReturn.OK

    # --- image feeding ------------------------------------------------------------------------------------------
    def start_feeder(self):
        if self.src.is_image and self._feeder is None:
            self._feeder = threading.Thread(target=self._feed, name=f"images-{self.src.id}", daemon=True)
            self._feeder.start()

    def add_image(self, path: str) -> None:
        self.image_queue.put(path)

    def _feed(self):
        import cv2

        idx = 0
        while not self._stop.is_set():
            path = self.image_queue.get()
            if path is None:
                self.appsrc.emit("end-of-stream")
                return
            img = cv2.imread(path, cv2.IMREAD_COLOR)
            if img is None:
                log.warning("[%s] cannot decode %s", self.src.id, path)
                if self.on_image_done:
                    self.on_image_done(self, path, error="cannot decode image")
                continue
            h, w = img.shape[:2]
            rgba = cv2.cvtColor(img, cv2.COLOR_BGR2RGBA)
            self.images.append((path, (w, h)))
            caps = Gst.Caps.from_string(f"video/x-raw,format=RGBA,width={w},height={h},framerate=0/1")
            self.appsrc.set_property("caps", caps)
            buf = Gst.Buffer.new_wrapped(rgba.tobytes())
            buf.pts = idx * Gst.SECOND
            buf.duration = Gst.SECOND
            idx += 1
            if self.appsrc.emit("push-buffer", buf) != Gst.FlowReturn.OK:
                log.warning("[%s] push-buffer refused, stopping feeder", self.src.id)
                return

    def image_for_pts(self, pts: int) -> Optional[Tuple[str, Tuple[int, int]]]:
        k = int(round(pts / Gst.SECOND))
        return self.images[k] if 0 <= k < len(self.images) else None

    def stop(self):
        self._stop.set()
        self.image_queue.put(None)
