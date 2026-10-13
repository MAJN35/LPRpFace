# Face service: Kafka face events -> SCRFD landmarks + ArcFace R50 embedding (onnxruntime CPU) -> backend.
# Base: python 3.10.22-slim-bookworm, pinned by digest. Model weights are mounted read-only (models/face/arcface_r50).
ARG BASE=python:3.10.22-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370
FROM ${BASE}
COPY face/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.lock \
 && useradd --system --uid 10001 --home /app lpr
COPY face/lpr_face.py /app/lpr_face.py
COPY schemas /app/schemas
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
USER lpr
HEALTHCHECK --interval=15s --timeout=3s --retries=5 --start-period=60s CMD python -c "import json,time,sys; d=json.load(open('/tmp/face-health.json')); sys.exit(0 if time.time()-d['updated_at']<30 else 1)"
CMD ["python", "lpr_face.py"]
