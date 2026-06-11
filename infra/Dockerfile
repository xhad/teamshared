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
COPY plugins/teamshared ./plugins/teamshared
COPY install_assets ./install_assets

RUN pip install --upgrade pip \
 && pip install '.[neo4j,local-embed,hnsw]'

# Pre-bake the default local embedding model so containers don't stall on a
# HuggingFace download at first recall (TEAMSHARED_EMBED_PROVIDER=local).
ENV TEAMSHARED_EMBED_CACHE_DIR=/app/.fastembed
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/.fastembed')"

ENV TEAMSHARED_HOST=0.0.0.0 \
    TEAMSHARED_PORT=8077

EXPOSE 8077

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8077/health || exit 1

CMD ["teamshared", "serve", "--transport", "http"]
