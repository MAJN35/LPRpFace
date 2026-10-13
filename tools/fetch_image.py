#!/usr/bin/env python3
"""Fetch a pinned image from Docker Hub without the Docker daemon and load it (workaround, see docs/decisions.md).

    python3 tools/fetch_image.py python:3.10.22-slim-bookworm@sha256:<index digest> [--arch arm64]

On this Jetson the daemon must use an HTTP proxy whose exit IP Docker's CDN refuses (403), while direct downloads
work. This script resolves the digest-pinned reference directly, verifies the SHA-256 of the manifest, config and
every layer, writes a docker-archive and runs ``docker load``. It prints the image ID (= config digest), which build
scripts compare against the expected value. Standard library only (runs on the host Python 3.8).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REGISTRY = "https://registry-1.docker.io"
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
MANIFEST_TYPES = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")
# Direct connection: ignore any proxy environment.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url: str, token: str, accept=(), stream_to: Path = None) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": ", ".join(accept)})
    with OPENER.open(req, timeout=120) as r:
        if stream_to is None:
            return r.read()
        h = hashlib.sha256()
        with open(stream_to, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
                f.write(chunk)
        return h.hexdigest().encode()


def verify(data: bytes, digest: str, what: str) -> None:
    got = "sha256:" + hashlib.sha256(data).hexdigest()
    if got != digest:
        sys.exit(f"FAIL: {what} digest {got} != {digest}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ref", help="name:tag@sha256:<digest> (Docker Hub)")
    ap.add_argument("--arch", default="arm64")
    a = ap.parse_args(argv)
    if "@sha256:" not in a.ref:
        sys.exit("FAIL: the reference must be pinned by digest")
    name_tag, digest = a.ref.split("@")
    name, tag = name_tag.rsplit(":", 1)
    repo = name if "/" in name else f"library/{name}"

    tok_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
    with OPENER.open(tok_url, timeout=60) as r:
        token = json.load(r)["token"]

    raw = get(f"{REGISTRY}/v2/{repo}/manifests/{digest}", token, INDEX_TYPES + MANIFEST_TYPES)
    verify(raw, digest, "index/manifest")
    doc = json.loads(raw)
    if doc.get("mediaType") in INDEX_TYPES or "manifests" in doc:
        plat = [m for m in doc["manifests"]
                if m["platform"].get("os") == "linux" and m["platform"].get("architecture") == a.arch]
        if not plat:
            sys.exit(f"FAIL: no linux/{a.arch} manifest in {digest}")
        mdigest = plat[0]["digest"]
        raw = get(f"{REGISTRY}/v2/{repo}/manifests/{mdigest}", token, MANIFEST_TYPES)
        verify(raw, mdigest, "platform manifest")
        doc = json.loads(raw)
        print(f"linux/{a.arch} manifest {mdigest}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg_digest = doc["config"]["digest"]
        cfg = get(f"{REGISTRY}/v2/{repo}/blobs/{cfg_digest}", token)
        verify(cfg, cfg_digest, "config")
        cfg_name = cfg_digest.split(":")[1] + ".json"
        (tmp / cfg_name).write_bytes(cfg)
        layers = []
        for i, layer in enumerate(doc["layers"]):
            fname = layer["digest"].split(":")[1] + ".tar.gz"
            got = get(f"{REGISTRY}/v2/{repo}/blobs/{layer['digest']}", token, stream_to=tmp / fname).decode()
            if "sha256:" + got != layer["digest"]:
                sys.exit(f"FAIL: layer {layer['digest']} digest mismatch")
            print(f"layer {i + 1}/{len(doc['layers'])} {layer['digest'][:19]} {layer['size']} B ok")
            layers.append(fname)
        (tmp / "manifest.json").write_text(json.dumps([{"Config": cfg_name, "RepoTags": [name_tag], "Layers": layers}]))
        archive = tmp / "image.tar"
        with tarfile.open(archive, "w") as t:
            for f in [cfg_name, "manifest.json"] + layers:
                t.add(tmp / f, arcname=f)
        subprocess.run(["docker", "load", "-i", str(archive)], check=True)
    image_id = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", name_tag],
                              check=True, capture_output=True, text=True).stdout.strip()
    if image_id != cfg_digest:
        sys.exit(f"FAIL: loaded image id {image_id} != config digest {cfg_digest}")
    print(f"loaded {name_tag} image id {image_id} (from {digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
