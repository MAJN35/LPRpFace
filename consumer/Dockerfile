# Kafka -> backend consumer. Base: python 3.10.22-slim-bookworm, pinned by digest.
ARG BASE=python:3.10.22-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370
FROM ${BASE}
COPY consumer/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.lock \
 && useradd --system --uid 10001 --home /app lpr
COPY consumer/lpr_consumer.py /app/lpr_consumer.py
COPY schemas /app/schemas
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER lpr
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import json,time,sys; d=json.load(open('/tmp/consumer-health.json')); sys.exit(0 if time.time()-d['updated_at']<30 else 1)"
CMD ["python", "lpr_consumer.py"]
