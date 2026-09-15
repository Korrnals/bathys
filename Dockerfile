# All-in-one image: bathys MCP server + native SearXNG + headless chromium.
#
# STATUS (2026-09-15): still NOT verified in a container runtime. docker is
# absent on the dev box; podman 4.9.3 is present but cannot start — the
# distrobox /etc/subuid declares abyss:100000:65536 while the HOST range is
# abyss:524288:65536, so newuidmap fails with "write to uid_map failed:
# Operation not permitted". Fix (needs root on the host or inside the box):
#   sed -i 's/^abyss:100000:65536$/abyss:524288:65536/' /etc/subuid
# then `podman system migrate` and build:
#   podman build -t bathys . && podman run --rm -i bathys < scripts/stdio_smoke.json

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
