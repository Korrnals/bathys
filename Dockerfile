# All-in-one image: bathys MCP server + native SearXNG + headless chromium.
#
# STATUS (2026-09-16): not yet built in a container runtime. Local box: no
# docker; podman cannot run in distrobox (no real subuid delegation, cgroup
# scope hidden). Cluster release conveyor (release-pipeline) is the canonical
# build path: its docker build phase (step 6.5) requires a docker CLI inside
# the runner image (Dockerfile.pipeline) — the runner does not ship one yet
# (bathys was the first project to exercise that phase; SKIP_DOCKER=1 is set
# in the pipeline values until the runner image gains docker/buildx).
# The image will be built and pushed to ghcr.io/korrnals/bathys once the
# runner is updated — no Dockerfile changes expected. Native mode inside the
# container git-clones SearXNG on first call (git/curl present below) and
# pins the reviewed commit from config.SEARXNG_REF.

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git curl ca-certificates \
       libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
       libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
       libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && python -m playwright install chromium

# Child processes (SearXNG native, chromium) need a home.
ENV BATHYS_START_MODE=native \
    BATHYS_DATA_DIR=/srv/data \
    BATHYS_CACHE_DIR=/srv/cache \
    BATHYS_SEARXNG_HOME=/srv/searxng-home
VOLUME ["/srv/data", "/srv/cache", "/srv/searxng-home"]

# stdio MCP: clients pipe JSON-RPC through stdin/stdout.
ENTRYPOINT ["bathys"]
