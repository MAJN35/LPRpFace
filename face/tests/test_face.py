"""Face service logic without models or a broker: SCRFD decoding, face choice, payload, delivery/DLQ flow."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lpr_face as F  # noqa: E402

F.SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "face_event-1.0.json"
EVENT = {"schema_version": "1.0", "event_id": "5f0c2b1e-8d3a-4c55-9a77-0d6c0e5b1a01", "event_type": "face.detected",
         "source": {"id": "gate", "type": "rtsp", "uri_redacted": "rtsp://cam/1", "file_name": None},
         "camera_id": "gate", "timestamp": "2026-10-13T10:00:00.000Z", "track_id": 7, "face_bbox": [10, 10, 60, 70],
         "frame_size": [1920, 1080], "det_score": 0.8, "frames_seen": 4, "snapshot_path": "faces/gate/2026-10-13/x.jpg",
         "snapshot_face_box": [12, 14, 62, 74], "model": {"version": "v2", "sha256": "a" * 64}}


def heads(size, hits):
    """Fake SCRFD outputs with one confident anchor per (stride, cell index, box distances, keypoint offsets)."""
    outs = [None] * 9
    for i, s in enumerate((8, 16, 32)):
        n = (size // s) ** 2 * 2
        outs[i], outs[i + 3], outs[i + 6] = np.zeros((n, 1), np.float32), np.zeros((n, 4), np.float32), np.zeros((n, 10), np.float32)
    for stride, idx, dist, kps in hits:
        i = (8, 16, 32).index(stride)
        outs[i][idx, 0] = 0.9
        outs[i + 3][idx] = np.array(dist, np.float32) / stride
        outs[i + 6][idx] = np.array(kps, np.float32) / stride
    return outs


def test_decode_scrfd_box_and_keypoints():
    size = 64
    # stride 16, cell (x=2, y=1) -> anchor index (1*4+2)*2 = 12, centre (32, 16)
    outs = heads(size, [(16, 12, [10, 6, 12, 20], [-5, -3, 5, -3, 0, 2, -4, 8, 4, 8])])
    boxes, kps, scores = F.decode_scrfd(outs, size)
    assert boxes.shape == (1, 4) and np.allclose(boxes[0], [22, 10, 44, 36])
    assert np.allclose(kps[0][0], [27, 13]) and np.allclose(kps[0][4], [36, 24]) and scores[0] > 0.8


def test_nms_and_pick_face_prefers_the_tracked_face():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 10, 10], [50, 50, 70, 70]], np.float32)
    scores = np.array([0.9, 0.8, 0.95], np.float32)
    assert sorted(F.nms(boxes, scores, 0.4)) == [0, 2]
    assert F.pick_face(boxes, None, scores, [0, 0, 11, 11]) == 0       # overlap with the tracker's box wins
    assert F.pick_face(boxes, None, scores, None) == 2                 # else the most confident
    assert F.pick_face(np.zeros((0, 4)), None, np.zeros(0), None) is None


def test_body_carries_a_float32_embedding():
    emb = F.l2(np.arange(512, dtype=np.float32))
    body = F.build_body(EVENT, {"embedding": emb, "det_score": 0.7, "landmarks": [[1, 2]] * 5, "sharpness": 50.0})
    back = np.frombuffer(base64.b64decode(body["embedding_b64"]), np.float32)
    assert back.shape == (512,) and abs(np.linalg.norm(back) - 1) < 1e-5 and body["embed_model"] == F.EMBED_MODEL
    assert F.build_body(EVENT, {"embedding": None})["embedding_b64"] is None


def test_processor_delivers_retries_and_dead_letters():
    sent, dlq, commits, statuses = [], [], [], ["retry", "ok"]
    proc = F.Processor(embed=lambda img, hint: {"embedding": F.l2(np.ones(512, np.float32)), "det_score": 0.9},
                       read_image=lambda rel: np.zeros((80, 80, 3), np.uint8),
                       deliver=lambda b: (sent.append(b), (statuses.pop(0), ""))[1],
                       dead_letter=lambda m, r: dlq.append(r), commit=commits.append, sleep=lambda s: None)
    msg = SimpleNamespace(value=lambda: json.dumps(EVENT).encode())
    proc.handle(msg)
    assert len(sent) == 2 and commits == [msg] and proc.stats["embedded"] == 1 and proc.stats["retries"] == 1
    bad = SimpleNamespace(value=lambda: b'{"schema_version": "1.0"}')
    proc.handle(bad)
    assert dlq and dlq[0].startswith("invalid") and commits[-1] is bad


def test_missing_snapshot_is_delivered_without_embedding():
    sent = []
    proc = F.Processor(embed=lambda *a: 1 / 0, read_image=lambda rel: None, deliver=lambda b: (sent.append(b), ("ok", ""))[1],
                       dead_letter=lambda m, r: None, commit=lambda m: None)
    proc.handle(SimpleNamespace(value=lambda: json.dumps(EVENT).encode()))
    assert sent[0]["embedding_b64"] is None and proc.stats["no_face"] == 1


def test_embed_photo_refuses_non_images_and_photos_without_faces():
    import cv2
    class NoFace:
        def __call__(self, img, hint, det_size=192, largest=False):
            return {"embedding": None, "faces": 0}
    assert F.embed_photo(NoFace(), b"not an image")[0] == 415
    ok, png = cv2.imencode(".png", np.zeros((60, 60, 3), np.uint8))
    assert F.embed_photo(NoFace(), png.tobytes())[0] == 422


def test_embed_photo_returns_embedding_and_face_crop():
    import cv2
    class One:
        def __call__(self, img, hint, det_size=192, largest=False):
            assert det_size == 640 and largest
            return {"embedding": F.l2(np.ones(512, np.float32)), "det_score": 0.9, "sharpness": 10.0, "faces": 2, "box": [20, 20, 60, 70]}
    ok, jpg = cv2.imencode(".jpg", np.full((200, 160, 3), 128, np.uint8))
    status, body = F.embed_photo(One(), jpg.tobytes())
    assert status == 200 and body["faces"] == 2 and body["size"] == [160, 200]
    crop = cv2.imdecode(np.frombuffer(base64.b64decode(body["crop_jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR)
    assert crop.shape[0] > 50 and len(np.frombuffer(base64.b64decode(body["embedding_b64"]), np.float32)) == 512
