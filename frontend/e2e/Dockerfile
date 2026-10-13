# E2E runner: Node 20.18.1 + Debian chromium + puppeteer-core (from package-lock.json).
FROM node:20.18.1-bookworm-slim@sha256:b2c8e0eb8a6aeeae33b2711f8f516003e27ee45804e270468d937b3214f2f0cc
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends chromium fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /e2e
COPY frontend/package.json frontend/package-lock.json ./
RUN PUPPETEER_SKIP_DOWNLOAD=1 npm ci --no-audit --no-fund --include=dev
COPY frontend/e2e/run.mjs ./e2e/run.mjs
ENV CHROME=/usr/bin/chromium
CMD ["node", "e2e/run.mjs"]
