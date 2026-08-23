#!/bin/bash
# Generates a self-signed certificate for Caddy directly with openssl,
# bypassing Caddy's own `tls internal` local-CA management entirely.
#
# Why: `tls internal` tries to install its generated root CA into the VM's
# system-wide trust store as a convenience, which requires privileges the
# caddy service account doesn't have (by design — it runs unprivileged).
# Per Caddy's own docs, that failure has no supported workaround ("no
# configuration option to suppress the installation attempt"), and in
# testing it left the internal CA issuing pipeline unable to produce a
# working leaf certificate at all -- every TLS handshake failed with a
# generic "internal error" alert, on both Windows and Linux hosts. A
# directly-generated cert sidesteps that subsystem entirely: no local CA
# state machine, nothing to fail install into a trust store, just a cert
# file and a key file Caddy serves as-is.
#
# Usage: ./generate-cert.sh [ip-or-hostname]
# With no argument, auto-detects the VM's external IP via the GCP metadata
# server. Re-run this (then `sudo systemctl restart caddy`) to rotate the
# certificate — e.g. before its ~825-day validity runs out (see
# common note about Apple's certificate validity cap in the main app).

set -euo pipefail

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  TARGET=$(curl -s -H "Metadata-Flavor: Google" \
    "http://169.254.169.254/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip")
  echo "No IP/hostname given — auto-detected from GCP metadata: $TARGET"
fi

sudo mkdir -p /etc/caddy/tls
sudo openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /etc/caddy/tls/key.pem \
  -out /etc/caddy/tls/cert.pem \
  -days 825 \
  -subj "/CN=$TARGET" \
  -addext "subjectAltName=IP:$TARGET,IP:127.0.0.1"

sudo chown -R caddy:caddy /etc/caddy/tls
echo "Certificate written to /etc/caddy/tls/cert.pem (valid for $TARGET, 127.0.0.1)."
echo "Run: sudo systemctl restart caddy"
