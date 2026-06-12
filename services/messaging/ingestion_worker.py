"""
services/messaging/ingestion_worker.py

Standalone subscriber process. Runs SEPARATELY from FastAPI.

In production this runs as a separate Railway service or Cloud Run job.
Listens to the Redis queue for asynchronous ingestion tasks.

Run locally:
    python -m services.messaging.ingestion_worker
"""

import json
import logging
import os
import sys
import time

import redis

from app.config import settings
from services.messaging.pubsub_client import QUEUE_NAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("worker")


class IngestionWorker:
    """
    Subscribes to the incident-ingested Redis queue and performs
    full ChromaDB ingestion + tree index rebuild for each new document.
    """

    def __init__(self):
        self._redis_client = None
        try:
            self._redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self._redis_client.ping()
            logger.info(f"[worker] Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            logger.critical(f"[worker] Failed to connect to Redis: {e}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Pull messages from the Redis list and process them.
        Blocks forever (designed for long-running service deployment).
        """
        logger.info(f"[worker] Listening on Redis queue: {QUEUE_NAME}")

        while True:
            try:
                # brpop blocks until a message is available (timeout 0 means block forever)
                # It returns a tuple: (queue_name, message_data)
                result = self._redis_client.brpop(QUEUE_NAME, timeout=0)
                if result:
                    _, message_data = result
                    try:
                        data = json.loads(message_data)
                        filename = data.get("filename", "unknown")
                        logger.info("[worker] Received message for '%s'", filename)

                        self._process_ingestion(data)
                        logger.info("[worker] Ingested successfully: %s", filename)

                    except Exception as exc:
                        logger.error(
                            "[worker] Ingestion failed for data '%s': %s",
                            message_data,
                            exc,
                        )
            except KeyboardInterrupt:
                logger.info("[worker] Gracefully shutting down.")
                break
            except Exception as exc:
                logger.error("[worker] Unrecoverable worker error: %s. Retrying in 5s...", exc)
                time.sleep(5)

    # ------------------------------------------------------------------
    # Core ingestion work
    # ------------------------------------------------------------------

    def _process_ingestion(self, data: dict) -> None:
        """
        Performs the full ingestion pipeline for a new incident document.
        """
        filename = data.get("filename", "unknown")
        file_path = data.get("file_path", "")

        logger.info("[worker] Processing: %s (path=%s)", filename, file_path)

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(
                f"File not found at path '{file_path}'. "
                "The API saved it, but the worker cannot read it. "
                "Check DATA_DIR mounts."
            )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        logger.info("[worker] Running embedding for '%s'...", filename)
        from services.retrieval.ingest import ingest_single_document
        ingest_single_document(content, filename)
        logger.info("[worker] ChromaDB updated for '%s'", filename)

        logger.info("[worker] Rebuilding tree index...")
        try:
            from services.retrieval.tree_search import _rebuild_tree_index
            _rebuild_tree_index()
            logger.info("[worker] Tree index rebuilt.")
        except Exception as exc:
            logger.warning("[worker] Tree index rebuild failed (non-fatal): %s", exc)

        try:
            from app.main import QUERY_CACHE
            QUERY_CACHE.clear()
            logger.info("[worker] Query cache cleared.")
        except Exception as exc:
            logger.warning("[worker] Could not clear query cache (non-fatal): %s", exc)

        logger.info("[worker] ✅ Full ingestion complete for '%s'", filename)


if __name__ == "__main__":
    worker = IngestionWorker()
    worker.start()
