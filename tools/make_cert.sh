#!/usr/bin/env bash
# Self-signed TLS certificate for the dashboard on the LAN (HTTPS on 8443 = secure context = OS notifications).
#   tools/make_cert.sh [extra IP or hostname ...]     -> deploy/certs/tls.crt, tls.key (git-ignored)
# Covers this machine's LAN addresses, its hostname and localhost. Browsers warn once per device; accept the
# certificate (or install deploy/certs/tls.crt as trusted) to get notifications without the warning.
set -euo pipefail
out="$(cd "$(dirname "$0")/.." && pwd)/deploy/certs"
mkdir -p "$out"
san="DNS:localhost,DNS:$(hostname),IP:127.0.0.1"
for ip in $(hostname -I); do [[ $ip == *:* ]] || san+=",IP:$ip"; done
for x in "$@"; do [[ $x =~ ^[0-9.]+$ ]] && san+=",IP:$x" || san+=",DNS:$x"; done
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 825 \
  -subj "/CN=EdgeTech LPR dashboard" -addext "subjectAltName=$san" \
  -addext "extendedKeyUsage=serverAuth" -keyout "$out/tls.key" -out "$out/tls.crt" 2>/dev/null
chmod 600 "$out/tls.key"; chmod 644 "$out/tls.crt"
echo "certificate for: $san"
openssl x509 -in "$out/tls.crt" -noout -fingerprint -sha256
