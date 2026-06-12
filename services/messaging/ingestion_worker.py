"""
services/messaging/ingestion_worker.py

Standalone subscriber process. Runs SEPARATELY from FastAPI.

In production this runs as a separate Railway service or Cloud Run job,
NOT in the same process as the API. This decoupling is intentional:
  - The API can be scaled independently from the worker.
  - A slow ingestion (e.g., large PDF) never blocks the API.
  - Worker crashes don't take down the API.

Run locally:
    python -m services.messaging.ingestion_worker

Run via docker-compose:
    services:
      worker:
        build: .
        command: python -m services.messaging.ingestion_worker

Key concepts:
  ack()  — tells Pub/Sub "I processed this successfully, remove it from the queue."
           Without ack(), Pub/Sub redelivers after the ack_deadline (60s).
           MISSING ack = duplicate processing (the at-least-once delivery guarantee
           means Pub/Sub WILL redeliver). This is why idempotent embedding matters.

  nack() — tells Pub/Sub "I failed, please redeliver." Combined with the
           dead_letter_policy (max 5 attempts), after 5 nacks the message
           moves to the dead-letter topic so it is never silently lost.
"""

import json
import logging
import os
import sys
import threading

from google.cloud import pubsub_v1

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("worker")

# ---------------------------------------------------------------------------
# Constants (mirrors pubsub_client.py — kept here so the worker is standalone)
# ---------------------------------------------------------------------------

PROJECT_ID = settings.GCP_PROJECT_ID
SUBSCRIPTION_ID = "incident-ingested-sub"
DEAD_LETTER_SUBSCRIPTION_ID = "incident-ingested-dead-letter-sub"


class IngestionWorker:
    """
    Subscribes to the incident-ingested Pub/Sub topic and performs
    full ChromaDB ingestion + tree index rebuild for each new document.
    """

    def __init__(self):
        # Point at emulator if configured
        emulator_host = settings.PUBSUB_EMULATOR_HOST
        if emulator_host:
            os.environ["PUBSUB_EMULATOR_HOST"] = emulator_host
            logger.info("[worker] Using local Pub/Sub emulator at %s", emulator_host)
        else:
            logger.info("[worker] Using real Google Cloud Pub/Sub")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Pull messages from the main subscription and process them.
        Also starts a background thread watching the dead-letter subscription.
        Blocks forever (designed for long-running service deployment).
        """
        subscriber = pubsub_v1.SubscriberClient()
        subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

        logger.info("[worker] Connected to Pub/Sub subscription: %s", subscription_path)

        # Start dead-letter watcher in background thread
        dl_thread = threading.Thread(
            target=self._watch_dead_letter, daemon=True, name="dead-letter-watcher"
        )
        dl_thread.start()

        def callback(message: pubsub_v1.subscriber.message.Message) -> None:
            """
            Pub/Sub streaming pull callback. Called once per message.

            IMPORTANT: This function MUST call either message.ack() or
            message.nack() before returning. If it does neither, Pub/Sub
            waits until the ack_deadline expires and then redelivers.
            """
            try:
                data = json.loads(message.data.decode("utf-8"))
                filename = data.get("filename", "unknown")
                logger.info("[worker] Received message for '%s'", filename)

                self._process_ingestion(data)

                # ✅ ACK — tells Pub/Sub this message is done, remove from queue.
                # Without this line, Pub/Sub would redeliver every 60s indefinitely.
                message.ack()
                logger.info("[worker] Ingested + acked: %s", filename)

            except Exception as exc:
                filename = "unknown"
                try:
                    data = json.loads(message.data.decode("utf-8"))
                    filename = data.get("filename", "unknown")
                except Exception:
                    pass

                logger.error(
                    "[worker] Ingestion failed for '%s': %s. "
                    "Sending nack — Pub/Sub will redeliver (up to 5 attempts).",
                    filename,
                    exc,
                )
                # ❌ NACK — tells Pub/Sub "I failed, please redeliver."
                # After max_delivery_attempts (5), Pub/Sub moves the message
                # to the dead-letter topic automatically.
                message.nack()

        # streaming_pull_future blocks until cancelled or an unrecoverable error.
        streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
        logger.info("[worker] Streaming pull active. Waiting for messages...")

        try:
            streaming_pull_future.result()  # blocks forever
        except KeyboardInterrupt:
            streaming_pull_future.cancel()
            logger.info("[worker] Gracefully shutting down.")
        except Exception as exc:
            streaming_pull_future.cancel()
            logger.critical("[worker] Unrecoverable subscriber error: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Core ingestion work
    # ------------------------------------------------------------------

    def _process_ingestion(self, data: dict) -> None:
        """
        Performs the full ingestion pipeline for a new incident document.

        Steps:
          1. Read the raw file from disk (already saved by the API)
          2. Run embedding and update ChromaDB
          3. Rebuild the tree index
          4. Clear the FastAPI QUERY_CACHE so stale results don't persist
          5. Upload GCS snapshot (no-op stub; activates on Cloud Run migration)

        This is the expensive work that previously blocked the API for 2-5s.
        Now it runs asynchronously in this separate process.
        """
        filename = data.get("filename", "unknown")
        file_path = data.get("file_path", "")

        logger.info("[worker] Processing: %s (path=%s)", filename, file_path)

        # Step 1 — Read the file
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(
                f"File not found at path '{file_path}'. "
                "The API saved it, but the worker cannot read it. "
                "Check DATA_DIR mounts in docker-compose."
            )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Step 2 — Embed + update ChromaDB
        logger.info("[worker] Running embedding for '%s'...", filename)
        from services.retrieval.ingest import ingest_single_document
        ingest_single_document(content, filename)
        logger.info("[worker] ChromaDB updated for '%s'", filename)

        # Step 3 — Rebuild tree index
        logger.info("[worker] Rebuilding tree index...")
        try:
            from services.retrieval.tree_search import _rebuild_tree_index
            _rebuild_tree_index()
            logger.info("[worker] Tree index rebuilt.")
        except Exception as exc:
            # Tree index rebuild failure is non-fatal: vector search still works.
            logger.warning("[worker] Tree index rebuild failed (non-fatal): %s", exc)

        # Step 4 — Clear the FastAPI query cache
        # Import the cache object from main.py and clear it so fresh queries
        # don't get stale pre-ingestion results.
        try:
            from app.main import QUERY_CACHE
            QUERY_CACHE.clear()
            logger.info("[worker] Query cache cleared.")
        except Exception as exc:
            logger.warning("[worker] Could not clear query cache (non-fatal): %s", exc)

        # Step 5 — Upload GCS snapshot (stub — activates on Cloud Run migration)
        from services.messaging.gcs_sync import upload_snapshot
        upload_snapshot()

        logger.info("[worker] ✅ Full ingestion complete for '%s'", filename)

    # ------------------------------------------------------------------
    # Dead-letter watcher
    # ------------------------------------------------------------------

    def _watch_dead_letter(self) -> None:
        """
        Runs in a background thread. Pulls from the dead-letter subscription
        and logs each failed message at CRITICAL level.

        In production, dead-letter messages trigger a PagerDuty/Slack alert.
        They represent incidents that failed ALL 5 delivery attempts —
        meaning there is likely a bug in _process_ingestion that needs fixing.

        Messages are acked here to prevent them from accumulating indefinitely.
        """
        subscriber = pubsub_v1.SubscriberClient()
        dl_sub_path = subscriber.subscription_path(PROJECT_ID, DEAD_LETTER_SUBSCRIPTION_ID)

        logger.info("[worker] Dead-letter watcher listening on: %s", dl_sub_path)

        def dl_callback(message: pubsub_v1.subscriber.message.Message) -> None:
            try:
                data = json.loads(message.data.decode("utf-8"))
                filename = data.get("filename", "unknown")
            except Exception:
                filename = "unknown"
                data = {}

            # Log at CRITICAL — this message failed 5 times.
            # In production: send a PagerDuty/Slack alert here.
            logger.critical(
                "[worker] DEAD LETTER: Ingestion failed permanently for '%s'. "
                "Message data: %s. "
                "ACTION REQUIRED: Investigate _process_ingestion and manually re-ingest.",
                filename,
                data,
            )
            message.ack()  # ack to stop Pub/Sub from redelivering dead-letter messages

        dl_future = subscriber.subscribe(dl_sub_path, callback=dl_callback)
        try:
            dl_future.result()
        except Exception as exc:
            logger.error("[worker] Dead-letter watcher error: %s", exc)


# ---------------------------------------------------------------------------
# Entry point — make runnable as: python -m services.messaging.ingestion_worker
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Ensure topic + subscription exist before starting the pull loop.
    # This is idempotent — safe to call even if they already exist.
    from services.messaging.pubsub_client import pubsub_client
    pubsub_client.create_topic_and_subscription_if_not_exists()

    worker = IngestionWorker()
    worker.start()
