"""
services/messaging/gcs_sync.py

Stub for Google Cloud Storage snapshot synchronisation.

In production (Cloud Run migration), this module will:
  1. Upload chroma_db/ to gs://<bucket>/snapshots/chroma_db/
  2. Upload tree_index/ to gs://<bucket>/snapshots/tree_index/

This ensures that when a Cloud Run container cold-starts, it can restore
the full knowledge base from GCS instead of starting empty.

On Railway (persistent volume) or local dev, this is a no-op.
"""

import logging

logger = logging.getLogger(__name__)


def upload_snapshot() -> None:
    """
    Stub: Upload chroma_db/ and tree_index/ to GCS for cross-container persistence.

    TODO (Cloud Run migration):
      1. pip install google-cloud-storage
      2. from google.cloud import storage
      3. client = storage.Client()
      4. bucket = client.bucket(os.environ["GCS_BUCKET"])
      5. Upload all files under chroma_db/ and tree_index/

    For now, this is intentionally a no-op so the worker can call it
    unconditionally without failing in local/Railway environments.
    """
    logger.debug("[gcs_sync] upload_snapshot called (no-op stub — not yet implemented)")
