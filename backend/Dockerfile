# Backend API. Base: python 3.10.22-slim-bookworm, pinned by digest (same as the tools image).
ARG BASE=python:3.10.22-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370
FROM ${BASE}
COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.lock \
 && useradd --system --uid 10001 --home /app lpr
COPY reader/lpr_reader /app/lpr_reader
COPY backend/app /app/app
COPY backend/migrations /app/migrations
COPY backend/alembic.ini /app/alembic.ini
WORKDIR /app
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER lpr
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=2)"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
