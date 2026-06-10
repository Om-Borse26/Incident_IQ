"""
GCS Snapshot Sync — STUB for future Cloud Run migration.

When deploying to Google Cloud Run (Phase 9 GCP), this module will:
  upload_snapshot(): push local chroma_db + tree_index to a GCS bucket
  restore_snapshot(): pull from GCS to /tmp on container startup

Currently IncidentIQ runs on Railway with persistent volumes, so this
module is not used. It documents the interface for when you switch.

Migration checklist (Railway → Cloud Run):
  1. Implement upload_snapshot() and restore_snapshot() using google-cloud-storage
  2. Add restore_snapshot() call to app/main.py lifespan startup
  3. Set DATA_DIR=/tmp in Cloud Run env vars
  4. Create a GCS bucket and upload current data
  5. Everything else (Dockerfile, app code) stays the same
"""

import logging

logger = logging.getLogger(__name__)


def upload_snapshot():
    """Upload chroma_db + tree_index to GCS. Used in Cloud Run deployment.

    TODO: implement when migrating to Cloud Run (Phase 9 GCP).
    Requires: pip install google-cloud-storage
    """
    raise NotImplementedError(
        "GCS sync not configured. This stub is for future Cloud Run migration. "
        "Currently using Railway persistent volumes."
    )


def restore_snapshot():
    """Restore chroma_db + tree_index from GCS to DATA_DIR. Used in Cloud Run startup.

    TODO: implement when migrating to Cloud Run (Phase 9 GCP).
    Requires: pip install google-cloud-storage
    """
    raise NotImplementedError(
        "GCS sync not configured. This stub is for future Cloud Run migration. "
        "Currently using Railway persistent volumes."
    )
