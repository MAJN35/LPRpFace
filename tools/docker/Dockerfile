# CPU tooling image for model checks, ONNX export and parity (M1/M2). Runs on the Jetson's CPU (arm64) or on x86.
# Base pinned by tag and multi-arch index digest (docker.io/library/python, PYTHON_VERSION=3.10.22, 2026-10-06).
# tools/build_cpu_image.sh passes the plain tag only when the image was loaded with tools/fetch_image.py and its
# image ID equals the verified arm64 config digest (docker load does not record the registry digest).
ARG BASE=python:3.10.22-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370
FROM ${BASE}

# libgl/glib: opencv-headless and ultralytics import-time deps.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.lock

ENV YOLO_AUTOINSTALL=false YOLO_OFFLINE=true YOLO_CONFIG_DIR=/tmp/ultralytics PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
