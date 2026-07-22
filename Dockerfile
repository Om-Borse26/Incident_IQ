# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies first (for chroma-hnswlib C++ compilation and ECS health checks)
RUN apt-get update && apt-get install -y build-essential gcc curl && rm -rf /var/lib/apt/lists/*

# Copy requirements BEFORE app code — this is the key Docker layer-caching pattern.
# If requirements.txt hasn't changed, all pip install layers are reused from cache,
# skipping the 15-minute download entirely.
COPY requirements.txt .

# Parallelize C++ compilation
ENV MAKEFLAGS="-j4"

# BuildKit cache mount: pip download cache is preserved between builds on the same host.
# --mount=type=cache,target=/root/.cache/pip keeps downloaded wheels across builds.
# Inline cache metadata is embedded in the image so Jenkins can use --cache-from.
ARG BUILDKIT_INLINE_CACHE=1

# Attempt to grab a pre-built wheel first to prevent 20-min compilation
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install chroma-hnswlib || true

# Install CPU version of torch first to prevent massive CUDA download and EOF timeout
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --index-url https://download.pytorch.org/whl/cpu

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# PRE-DOWNLOAD the embedding model so it's baked into the image
# (not downloaded at runtime — runtime downloads fail in serverless environments)
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code (data/ folder included for initial seeding)
COPY . .

# Seed the initial knowledge base at build time
RUN python -m services.retrieval.ingest && \
    python -m services.retrieval.tree_index

# PORT is injected by Railway (dev) and ECS (prod)
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
