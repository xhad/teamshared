FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY infra/migrations ./infra/migrations

RUN pip install --upgrade pip \
 && pip install .

ENV ACTX_HOST=0.0.0.0 \
    ACTX_PORT=8077

EXPOSE 8077

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8077/health || exit 1

CMD ["actx", "serve", "--transport", "http"]
