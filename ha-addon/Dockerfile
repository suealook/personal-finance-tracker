ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8

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

COPY rootfs /
RUN chmod a+x /etc/services.d/bot/run /etc/services.d/web/run
