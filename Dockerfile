FROM frappe/bench:latest

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

USER frappe

ARG FRAPPE_REPO=https://github.com/cakra-erpnext-apps/frappe
ARG FRAPPE_BRANCH=version-16

WORKDIR /home/frappe

COPY --chown=frappe:frappe apps.json /tmp/apps.json

RUN bench init frappe-bench \
    --frappe-path ${FRAPPE_REPO} \
    --frappe-branch ${FRAPPE_BRANCH} \
    --skip-redis-config-generation \
    --skip-assets

WORKDIR /home/frappe/frappe-bench

COPY --chown=frappe:frappe scripts/install-apps.py /tmp/install-apps.py
COPY --chown=frappe:frappe scripts/patch-crm-assign-to.py /tmp/patch-crm-assign-to.py

ENV CYPRESS_INSTALL_BINARY=0 \
    PUPPETEER_SKIP_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

RUN python3 /tmp/install-apps.py \
    && python3 /tmp/patch-crm-assign-to.py

USER root
RUN mkdir -p /scripts && chown frappe:frappe /scripts
USER frappe

WORKDIR /home/frappe/frappe-bench
