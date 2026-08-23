ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8
ENV WEB_BIND_HOST=0.0.0.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# app/ is a generated mirror of the repo-root app source — see sync_app.py.
COPY app/requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY app/bot ./bot
COPY app/web ./web
COPY app/common ./common
COPY app/config ./config
COPY app/scripts ./scripts

# Starts and supervises the bot + web processes directly — no dependency on the
# base image's s6-overlay init, which failed to start reliably (see CHANGELOG).
COPY run_supervisor.py /run_supervisor.py

ENTRYPOINT ["python3", "/run_supervisor.py"]
