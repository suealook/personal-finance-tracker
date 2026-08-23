ARG BUILD_FROM
FROM $BUILD_FROM

ARG BUILD_ARCH

ENV LANG=C.UTF-8
# Flask is now internal-only, reached through Caddy (see Caddyfile) rather
# than exposed to the LAN directly.
ENV WEB_BIND_HOST=127.0.0.1
ENV WEB_PORT=5001

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip curl \
 && rm -rf /var/lib/apt/lists/*

# Caddy terminates HTTPS on the add-on's exposed port and reverse-proxies to
# Flask internally — see Caddyfile for why. Static binary from GitHub
# releases, not an apt package, so there's no extra repo/GPG-key setup.
ARG CADDY_VERSION=2.8.4
RUN set -eux; \
    case "$BUILD_ARCH" in \
      aarch64) CADDY_ARCH=arm64 ;; \
      armv7) CADDY_ARCH=armv7 ;; \
      *) echo "Unsupported BUILD_ARCH for Caddy: $BUILD_ARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${CADDY_ARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin caddy; \
    chmod +x /usr/local/bin/caddy

WORKDIR /app

# app/ is a generated mirror of the repo-root app source — see sync_app.py.
COPY app/requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY app/bot ./bot
COPY app/web ./web
COPY app/common ./common
COPY app/config ./config
COPY app/scripts ./scripts
COPY Caddyfile /etc/caddy/Caddyfile

# Starts and supervises the bot + web + caddy processes directly — no
# dependency on the base image's s6-overlay init, which failed to start
# reliably (see CHANGELOG).
COPY run_supervisor.py /run_supervisor.py

ENTRYPOINT ["python3", "/run_supervisor.py"]
