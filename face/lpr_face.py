"""Face service: Kafka face events -> landmarks, alignment, ArcFace embedding -> backend (face recognition).

* Reads ``lpr.face.events`` (schemas/face_event-1.0.json; one event per face track with a snapshot on the shared
  data volume). Auto-commit off: an offset is committed only after the backend accepted the face or it was
  dead-lettered (at-least-once; the backend upserts by event_id).
* Per snapshot: SCRFD (InsightFace ``det_10g``) finds the face and its 5 landmarks on a small input (the snapshot is
  already a face crop), the face is aligned to the ArcFace 112x112 template, and ArcFace R50 (``w600k_r50``) gives a
  512-d L2-normalized embedding. A snapshot where no face is found is still delivered (no embedding), so the person
  can see it; it is never matched.
* Runs on the CPU (onnxruntime), in its own container with a memory limit, so the inference pipeline never waits.
  Measured on the Xavier NX (4 threads): SCRFD at 160 px ~0.11 s, ArcFace ~0.5 s per face.
* Model weights: InsightFace buffalo_l, licensed for non-commercial research only (AGENTS.md Privacy).

* Manual registration: ``POST /embed`` (internal network only, X-Ingest-Key) takes one photo (JPEG/PNG bytes), finds
  the largest face at a higher detector resolution (photos are not face crops), and returns its embedding and a
  face crop (JPEG) for the person's reference faces. Port FACE_HTTP_PORT [8095].

Environment: KAFKA_BROKERS, KAFKA_FACE_TOPIC [lpr.face.events], KAFKA_DLQ_TOPIC [lpr.dead-letter], KAFKA_GROUP
[lpr-face], BACKEND_URL [http://backend:8000], INGEST_KEY, CROPS_DIR [/data/crops], FACE_MODEL_DIR [/models/face],
FACE_THREADS [4], FACE_HEALTH_FILE [/tmp/face-health.json].
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger("lpr.face")
HERE = Path(__file__).resolve().parent
SCHEMA = Path(os.environ.get("FACE_EVENT_SCHEMA", HERE / "schemas" / "face_event-1.0.json"))
EMBED_MODEL = "arcface_r50_w600k"
# ArcFace 112x112 alignment template (InsightFace arcface_dst): eyes, nose tip, mouth corners.
ARC_DST = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655],
                    [70.7299, 92.2041]], dtype=np.float32)
DET_SIZE = 192          # SCRFD input (multiple of 32); the snapshot is a face crop with margin
DET_THRESH = 0.45


# --- pure functions (unit-tested without models) -------------------------------------------------------------------
def anchor_centers(h: int, w: int, stride: int, num_anchors: int = 2) -> np.ndarray:
    ys, xs = np.mgrid[:h, :w]
    c = (np.stack([xs, ys], axis=-1).astype(np.float32) * stride).reshape(-1, 2)
    return np.repeat(c, num_anchors, axis=0)


def decode_scrfd(outs: List[np.ndarray], size: int, thresh: float = DET_THRESH) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SCRFD heads (3 strides x [scores, boxes, keypoints]) -> boxes (N,4), keypoints (N,5,2), scores (N,), in
    input pixels, after NMS."""
    boxes, kpss, scores = [], [], []
    for i, stride in enumerate((8, 16, 32)):
        sc = outs[i].reshape(-1)
        bb = outs[i + 3].reshape(-1, 4) * stride
        kp = outs[i + 6].reshape(-1, 10) * stride
        ac = anchor_centers(size // stride, size // stride, stride)
        keep = np.where(sc >= thresh)[0]
        if not len(keep):
            continue
        c = ac[keep]
        b = bb[keep]
        boxes.append(np.stack([c[:, 0] - b[:, 0], c[:, 1] - b[:, 1], c[:, 0] + b[:, 2], c[:, 1] + b[:, 3]], axis=1))
        k = kp[keep].reshape(-1, 5, 2) + c[:, None, :]
        kpss.append(k)
        scores.append(sc[keep])
    if not boxes:
        return np.zeros((0, 4), np.float32), np.zeros((0, 5, 2), np.float32), np.zeros((0,), np.float32)
    boxes_a, kps_a, sc_a = np.concatenate(boxes), np.concatenate(kpss), np.concatenate(scores)
    keep = nms(boxes_a, sc_a, 0.4)
    return boxes_a[keep], kps_a[keep], sc_a[keep]


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> List[int]:
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0]); yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2]); yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area = lambda b: (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])  # noqa: E731
        ov = inter / (area(boxes[i]) + area(boxes[order[1:]]) - inter + 1e-9)
        order = order[1:][ov <= iou]
    return keep


def iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / u) if u > 0 else 0.0


def pick_face(boxes: np.ndarray, kps: np.ndarray, scores: np.ndarray, hint) -> Optional[int]:
    """The detection that is the tracked face: best overlap with the hint box, else the most confident."""
    if not len(boxes):
        return None
    if hint is not None:
        ov = [iou(b, hint) for b in boxes]
        k = int(np.argmax(ov))
        if ov[k] > 0.2:
            return k
    return int(np.argmax(scores))


def l2(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


# --- models -------------------------------------------------------------------------------------------------------
class FaceEmbedder:
    def __init__(self, model_dir: str, threads: int = 4):
        import onnxruntime as ort

        self.model_dir = Path(model_dir)
        self._verify()
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        prov = ["CPUExecutionProvider"]
        self.det = ort.InferenceSession(str(self.model_dir / "det_10g.onnx"), so, providers=prov)
        self.rec = ort.InferenceSession(str(self.model_dir / "w600k_r50.onnx"), so, providers=prov)

    def _verify(self) -> None:
        """Model identity = SHA256SUMS (computed on first use, like the LPR models); refuse on mismatch."""
        for line in (self.model_dir / "SHA256SUMS").read_text().split("\n"):
            if not line.strip():
                continue
            want, name = line.split()
            h = hashlib.sha256((self.model_dir / name).read_bytes()).hexdigest()
            if h != want:
                raise SystemExit(f"face model {name}: sha256 {h} != {want}")

    def __call__(self, bgr: np.ndarray, hint, det_size: int = DET_SIZE, largest: bool = False) -> Dict[str, Any]:
        import cv2

        h, w = bgr.shape[:2]
        s = det_size / max(h, w)
        img = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))))
        canvas = np.zeros((det_size, det_size, 3), np.uint8)
        canvas[:img.shape[0], :img.shape[1]] = img
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128.0, (det_size, det_size), (127.5, 127.5, 127.5), swapRB=True)
        outs = self.det.run(None, {self.det.get_inputs()[0].name: blob})
        boxes, kps, scores = decode_scrfd(outs, det_size)
        if largest and len(boxes):
            k = int(np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])))
        else:
            k = pick_face(boxes, kps, scores, None if hint is None else [v * s for v in hint])
        if k is None:
            return {"embedding": None, "det_score": None, "landmarks": None, "sharpness": None, "faces": 0}
        lmk = kps[k] / s
        m, _ = cv2.estimateAffinePartial2D(lmk.astype(np.float32), ARC_DST, method=cv2.LMEDS)
        aligned = cv2.warpAffine(bgr, m, (112, 112), borderValue=0.0)
        rb = cv2.dnn.blobFromImage(aligned, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        emb = l2(self.rec.run(None, {self.rec.get_inputs()[0].name: rb})[0][0].astype(np.float32))
        sharp = float(cv2.Laplacian(cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        return {"embedding": emb, "det_score": float(scores[k]), "landmarks": lmk.round(1).tolist(), "sharpness": sharp,
                "box": (boxes[k] / s).round(1).tolist(), "faces": int(len(boxes))}


def face_crop_jpeg(bgr: np.ndarray, box, margin: float = 0.35, max_side: int = 320) -> bytes:
    """The face with some context, at most max_side px, as JPEG (the person's reference picture)."""
    import cv2

    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    H, W = bgr.shape[:2]
    a, b = max(0, int(x1 - margin * w)), max(0, int(y1 - margin * h))
    c, d = min(W, int(x2 + margin * w)), min(H, int(y2 + margin * h))
    crop = bgr[b:d, a:c]
    s = max_side / max(crop.shape[:2])
    if s < 1:
        crop = cv2.resize(crop, (int(crop.shape[1] * s), int(crop.shape[0] * s)))
    return cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def embed_photo(embedder, data: bytes) -> Tuple[int, Dict[str, Any]]:
    """Registration photo -> (HTTP status, body). The largest face is the person; photos with no face are refused."""
    import cv2

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
    if img is None:
        return 415, {"detail": "not a JPEG/PNG image"}
    r = embedder(img, None, det_size=640, largest=True)
    if r.get("embedding") is None:
        return 422, {"detail": "no face found in the photo"}
    return 200, {"embed_model": EMBED_MODEL, "embedding_b64": base64.b64encode(np.asarray(r["embedding"], np.float32).tobytes()).decode(),
                 "det_score": r["det_score"], "sharpness": r["sharpness"], "faces": r["faces"], "box": r["box"],
                 "size": [int(img.shape[1]), int(img.shape[0])],
                 "crop_jpeg_b64": base64.b64encode(face_crop_jpeg(img, r["box"])).decode()}


def serve_http(embedder, key: str, port: int, lock) -> None:  # pragma: no cover - exercised by the deployment test
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/embed" or self.headers.get("X-Ingest-Key") != key:
                return self._send(404 if self.path != "/embed" else 401, {"detail": "no"})
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > 15 * 1024 * 1024:
                return self._send(413, {"detail": "photo too large"})
            with lock:                       # one model run at a time (shared with the Kafka loop)
                status, body = embed_photo(embedder, self.rfile.read(n))
            self._send(status, body)

        def _send(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    import threading
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever, name="embed-http", daemon=True).start()


# --- delivery -----------------------------------------------------------------------------------------------------
def post(url: str, key: str, body: Dict[str, Any], timeout_s: float = 10.0) -> Tuple[str, str]:
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Ingest-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return ("ok", str(r.status)) if 200 <= r.status < 300 else ("retry", str(r.status))
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500 and e.code not in (408, 429):
            return "reject", str(e.code)
        return "retry", str(e.code)
    except Exception as e:  # noqa: BLE001
        return "retry", str(e)[:200]


def build_body(event: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    emb = result.get("embedding")
    return {"event": event, "embed_model": EMBED_MODEL,
            "embedding_b64": base64.b64encode(np.asarray(emb, np.float32).tobytes()).decode() if emb is not None else None,
            "embed_det_score": result.get("det_score"), "landmarks": result.get("landmarks"),
            "sharpness": result.get("sharpness")}


class Processor:
    """Broker-independent core: validate -> embed -> deliver (retry while the backend is down) / dead-letter."""

    def __init__(self, embed: Callable, read_image: Callable, deliver: Callable, dead_letter: Callable,
                 commit: Callable, sleep=time.sleep):
        import jsonschema

        self.validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))
        self.embed, self.read_image, self.deliver = embed, read_image, deliver
        self.dead_letter, self.commit, self.sleep = dead_letter, commit, sleep
        self.stats = {"received": 0, "embedded": 0, "no_face": 0, "delivered": 0, "dead_lettered": 0, "retries": 0}
        self.stopping = False

    def handle(self, msg) -> None:
        import jsonschema

        self.stats["received"] += 1
        try:
            event = json.loads(msg.value())
            self.validator.validate(event)
        except (ValueError, jsonschema.ValidationError) as e:
            self._dlq(msg, f"invalid: {str(e).splitlines()[0][:300]}")
            return
        img = self.read_image(event["snapshot_path"])
        result: Dict[str, Any] = {"embedding": None}
        if img is not None:
            result = self.embed(img, event["snapshot_face_box"])
        self.stats["embedded" if result.get("embedding") is not None else "no_face"] += 1
        body = build_body(event, result)
        delay = 1.0
        while not self.stopping:
            status, detail = self.deliver(body)
            if status == "ok":
                self.stats["delivered"] += 1
                self.commit(msg)
                return
            if status == "reject":
                self._dlq(msg, f"backend rejected: {detail}")
                return
            self.stats["retries"] += 1
            log.warning("backend unavailable (%s); retrying in %.0f s", detail, delay)
            self.sleep(delay)
            delay = min(delay * 2, 30.0)

    def _dlq(self, msg, reason: str) -> None:
        self.dead_letter(msg, reason)
        self.stats["dead_lettered"] += 1
        self.commit(msg)


def run() -> int:  # pragma: no cover - needs a broker and the models; covered by the deployment test
    import cv2
    from confluent_kafka import Consumer, Producer

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    brokers = os.environ["KAFKA_BROKERS"]
    topic = os.environ.get("KAFKA_FACE_TOPIC", "lpr.face.events")
    crops = Path(os.environ.get("CROPS_DIR", "/data/crops")).resolve()
    health = Path(os.environ.get("FACE_HEALTH_FILE", "/tmp/face-health.json"))
    url = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/") + "/api/v1/ingest/faces"
    key = os.environ.get("INGEST_KEY", "")
    embedder = FaceEmbedder(os.environ.get("FACE_MODEL_DIR", "/models/face"), int(os.environ.get("FACE_THREADS", "4")))
    import threading
    lock = threading.Lock()
    serve_http(embedder, key, int(os.environ.get("FACE_HTTP_PORT", "8095")), lock)

    def embed_locked(img, hint):          # the Kafka path shares the model with registrations
        with lock:
            return embedder(img, hint)

    def read_image(rel: str):
        p = (crops / rel).resolve()
        if crops not in p.parents:
            return None
        return cv2.imread(str(p), cv2.IMREAD_COLOR) if p.is_file() else None

    c = Consumer({"bootstrap.servers": brokers, "group.id": os.environ.get("KAFKA_GROUP", "lpr-face"),
                  "enable.auto.commit": False, "auto.offset.reset": "earliest", "max.poll.interval.ms": 3600000})
    p = Producer({"bootstrap.servers": brokers, "enable.idempotence": True, "acks": "all"})

    def dead_letter(msg, reason):
        p.produce(os.environ.get("KAFKA_DLQ_TOPIC", "lpr.dead-letter"), key=msg.key(), value=msg.value(),
                  headers=[("reason", reason.encode()), ("source_topic", msg.topic().encode())])
        p.flush(10)

    proc = Processor(embed_locked, read_image, lambda b: post(url, key, b), dead_letter,
                     lambda m: c.commit(message=m, asynchronous=False))
    signal.signal(signal.SIGTERM, lambda *_: setattr(proc, "stopping", True))
    signal.signal(signal.SIGINT, lambda *_: setattr(proc, "stopping", True))
    c.subscribe([topic])
    log.info("face service: %s from %s, model %s", topic, brokers, EMBED_MODEL)
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
