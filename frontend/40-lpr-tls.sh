#!/bin/sh
# Enable the HTTPS server when a certificate is mounted (deploy/certs, made by tools/make_cert.sh).
if [ -s /etc/nginx/certs/tls.crt ] && [ -s /etc/nginx/certs/tls.key ]; then
  cp /etc/nginx/lpr-tls.conf /etc/nginx/conf.d/lpr-tls.conf
  echo "lpr: HTTPS enabled on 8443"
else
  rm -f /etc/nginx/conf.d/lpr-tls.conf
  echo "lpr: no certificate in /etc/nginx/certs, HTTPS off"
fi
