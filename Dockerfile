FROM python:3.12-slim

WORKDIR /app

# Install system dependencies first (for chroma-hnswlib C++ compilation and ECS health checks)
RUN apt-get update && apt-get install -y build-essential gcc curl && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .

# Parallelize C++ compilation if needed
ENV MAKEFLAGS="-j4"

# Attempt to grab a pre-built wheel first to prevent 20-min compilation
RUN pip install --no-cache-dir chroma-hnswlib || true

# Install CPU version of torch first to prevent massive CUDA download and EOF timeout
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

# PRE-DOWNLOAD the embedding model so it's baked into the image
# (not downloaded at runtime — runtime downloads fail in serverless environments)
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code (data/ folder included for initial seeding)
COPY . .

# Initial data seeded at build time. Railway volume persists updates.
# Cloud Run alternative: GCS snapshot restore (see services/storage/gcs_sync.py stub).
RUN python -m services.retrieval.ingest && \
    python -m services.retrieval.tree_index

# PORT is injected by Railway (dev) and Cloud Run (prod) — same pattern.
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
