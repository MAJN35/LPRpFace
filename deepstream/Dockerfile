# DeepStream app image. Base: NGC nvcr.io/nvidia/deepstream-l4t:6.3-samples (DeepStream 6.3, JetPack 5.1.2,
# TensorRT 8.5.2.2, CUDA 11.4, Python 3.8), pinned by the digest NGC reports for that tag (verified 2026-10-13).
ARG BASE=nvcr.io/nvidia/deepstream-l4t:6.3-samples@sha256:e01bb8f5ba10584d752b83c7b3cf66c6e01c0e1afd2cdbb1ec31082e947b75cf
FROM ${BASE} AS base

# GStreamer Python bindings + RTSP server (test sources) + codecs; the base image lacks the Gst typelibs.
# All packages come from Ubuntu. NVIDIA's Jetson apt repo (in /etc/apt/sources.list) answers 403 from this network,
# so this step uses a filtered copy of the source list; the image's own list is left unchanged.
RUN grep -v "repo.download.nvidia.com" /etc/apt/sources.list > /tmp/ubuntu.list \
 && APT="-o Dir::Etc::SourceList=/tmp/ubuntu.list -o Dir::Etc::SourceParts=/dev/null" \
 && apt-get $APT update \
 && DEBIAN_FRONTEND=noninteractive apt-get $APT install -y --no-install-recommends \
      python3-gi python3-gst-1.0 gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gir1.2-gst-rtsp-server-1.0 \
      libgstrtspserver-1.0-0 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
      gstreamer1.0-libav gstreamer1.0-tools v4l-utils python3-venv \
 && rm -rf /var/lib/apt/lists/* /tmp/ubuntu.list

# pip >= 20.3 understands manylinux_2_28 wheels (confluent-kafka); the base image ships pip 20.0.
RUN pip3 install --no-cache-dir pip==24.2

# DeepStream Python bindings v1.1.8 (DeepStream 6.3, Python 3.8), official release wheel, checksum-verified.
ARG PYDS_URL=https://github.com/NVIDIA-AI-IOT/deepstream_python_apps/releases/download/v1.1.8/pyds-1.1.8-py3-none-linux_aarch64.whl
ARG PYDS_SHA256=54f53b584fd668b62f86c6183c942e3e9ade5619465517864bb8180ae46bddae
RUN curl -fsSL -o /tmp/pyds-1.1.8-py3-none-linux_aarch64.whl "$PYDS_URL" \
 && echo "$PYDS_SHA256  /tmp/pyds-1.1.8-py3-none-linux_aarch64.whl" | sha256sum -c - \
 && pip3 install --no-cache-dir --no-deps /tmp/pyds-1.1.8-py3-none-linux_aarch64.whl \
 && rm /tmp/pyds-1.1.8-py3-none-linux_aarch64.whl

FROM base AS app
COPY requirements.lock /tmp/requirements.lock
RUN pip3 install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.lock
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
