# syntax=docker/dockerfile:1
# The backoffice (uvicorn) under Litestream, which streams the SQLite database to R2.
# Dokploy schedules run the collectors in this same container (docs/deploy.md).
FROM python:3.12-slim-bookworm

ARG LITESTREAM_VERSION=0.3.13

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl sqlite3 tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C /usr/local/bin litestream

COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:${PATH}" \
    FRAGRANCE_DB=/data/fragrance.db

COPY docker/litestream.yml /etc/litestream.yml
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chmod=0755 docker/run-supplier.sh /usr/local/bin/run-supplier

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
