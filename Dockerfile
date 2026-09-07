# All-in-one image: bathys MCP server + native SearXNG + headless chromium.
#
# STATUS: written for v1.0 (F-404), NOT yet tested in a real container runtime —
# the development box has no docker (distrobox). Before publishing, run:
#   docker build -t bathys .
#   docker run --rm -i -e BATHYS_START_MODE=native bathys < scripts/stdio_check-ish JSON
# and only then treat this file as verified. Native mode inside the container
# git-clones SearXNG on first call (git/curl present below) and pins the
# reviewed commit from config.SEARXNG_REF.

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
