"""
services/messaging/ingestion_worker.py

Background subscriber — spawned as a daemon thread inside FastAPI's lifespan
so it shares the same persistent volume as the web server.

Listens to the AWS SQS queue for asynchronous ingestion tasks.

SQS ack/nack semantics:
  - ACK: delete_message() called after successful processing.
  - NACK: do NOT delete — SQS automatically redelivers after VisibilityTimeout (300s).
  - After 5 failures: message moves to Dead-Letter Queue (DLQ).

Run standalone (for local dev):
    python -m services.messaging.ingestion_worker
"""

import json
import logging
import os
import sys
import threading
import time

import boto3
from botocore.exceptions import ClientError

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("worker")

QUEUE_NAME = "incident-ingested-queue"
DLQ_NAME = "incident-ingested-dlq"


class IngestionWorker:
    """
    Subscribes to the incident-ingested SQS queue and performs
    full ChromaDB ingestion + tree index rebuild for each new document.

    Uses SQS long-polling (WaitTimeSeconds=20) for efficient, low-latency
    message consumption without constant polling overhead.
    
    Designed to run as a daemon thread inside FastAPI — it will exit cleanly
    when the stop_event is set during application shutdown.
    """

    def __init__(self):
        self._sqs = None
        self._queue_url = None
        self._dlq_url = None
        self._ready = False
        try:
            boto_kwargs = {"region_name": settings.AWS_REGION}
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                boto_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                boto_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

            self._sqs = boto3.client("sqs", **boto_kwargs)
            # Resolve queue URLs
            self._queue_url = self._sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
            self._dlq_url = self._sqs.get_queue_url(QueueName=DLQ_NAME)["QueueUrl"]
            self._ready = True
            logger.info("[worker] Connected to SQS queue: %s", self._queue_url)
        except Exception as e:
            # Graceful degradation: log a warning but do NOT crash the app.
            # The FastAPI BackgroundTasks fallback will handle ingestion instead.
            logger.warning(
                "[worker] Could not connect to SQS: %s. "
                "Worker disabled — FastAPI BackgroundTasks will handle ingestion.",
                e,
            )

    @property
    def is_ready(self) -> bool:
        """True if the worker successfully connected to SQS and is ready to process."""
        return self._ready

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def start(self, stop_event: threading.Event | None = None) -> None:
        """
        Poll messages from the SQS queue and process them.
        Blocks until stop_event is set (or forever if stop_event is None).

        Args:
            stop_event: A threading.Event that, when set, causes the worker
                        to exit gracefully. Pass None to run forever (standalone mode).
        """
        if not self._ready:
            logger.warning("[worker] SQS not available — worker loop will not start.")
            return

        logger.info("[worker] Starting. Listening on SQS queue: %s", QUEUE_NAME)

        # Start DLQ watcher in a background daemon thread
        dlq_thread = threading.Thread(
            target=self._watch_dlq, args=(stop_event,), daemon=True, name="dlq-watcher"
        )
        dlq_thread.start()

        while stop_event is None or not stop_event.is_set():
            try:
                # Long-polling: blocks for up to 20s waiting for a message.
                response = self._sqs.receive_message(
                    QueueUrl=self._queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20,  # Long-polling reduces API calls dramatically
                    VisibilityTimeout=300,  # Hide message for 5 min while processing
                )
                messages = response.get("Messages", [])

                if not messages:
                    continue  # No message — long-poll again

                message = messages[0]
                receipt_handle = message["ReceiptHandle"]
                message_body = message["Body"]

                try:
                    data = json.loads(message_body)
                    filename = data.get("filename", "unknown")
                    logger.info("[worker] Received SQS message for '%s'", filename)

                    self._process_ingestion(data)
                    logger.info("[worker] Ingested successfully: %s", filename)

                    # --- ACK: Delete the message from SQS ---
                    self._sqs.delete_message(
                        QueueUrl=self._queue_url,
                        ReceiptHandle=receipt_handle,
                    )
                    logger.info("[worker] ACK: Deleted message from SQS for '%s'", filename)

                except Exception as exc:
                    # --- NACK: Do NOT delete the message ---
                    # SQS redelivers after VisibilityTimeout. After 5 failures → DLQ.
                    logger.error(
                        "[worker] NACK: Ingestion failed for '%s': %s. "
                        "SQS will redeliver after 300s.",
                        message_body[:200],
                        exc,
                    )

            except KeyboardInterrupt:
                logger.info("[worker] KeyboardInterrupt — shutting down.")
                break
            except Exception as exc:
                logger.error("[worker] Unrecoverable error: %s. Retrying in 5s...", exc)
                time.sleep(5)

        logger.info("[worker] Stop event received — exiting cleanly.")

    # ------------------------------------------------------------------
    # DLQ Watcher
    # ------------------------------------------------------------------

    def _watch_dlq(self, stop_event: threading.Event | None = None) -> None:
        """
        Background thread: polls the Dead-Letter Queue every 60s.
        Logs at CRITICAL level if any messages are found — these are
        messages that have failed 5 times and need manual investigation.
        """
        logger.info("[worker] DLQ watcher started for: %s", DLQ_NAME)
        while stop_event is None or not stop_event.is_set():
            try:
                # Use a short sleep loop so we can respond to stop_event quickly
                for _ in range(60):
                    if stop_event and stop_event.is_set():
                        return
                    time.sleep(1)

                response = self._sqs.receive_message(
                    QueueUrl=self._dlq_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=1,
                )
                messages = response.get("Messages", [])
                if messages:
                    logger.critical(
                        "[worker] DEAD-LETTER QUEUE ALERT: %d messages in DLQ '%s'. "
                        "These messages failed 5+ times and require manual investigation!",
                        len(messages),
                        DLQ_NAME,
                    )
                    for msg in messages:
                        logger.critical("[worker] DLQ message body: %s", msg.get("Body", "")[:500])
            except Exception as e:
                logger.error("[worker] DLQ watcher error: %s", e)

    # ------------------------------------------------------------------
    # Core ingestion work
    # ------------------------------------------------------------------

    def _process_ingestion(self, data: dict) -> None:
        """
        Performs the full ingestion pipeline for a new incident document.
        Raises on failure so the caller can NACK the message.
        """
        filename = data.get("filename", "unknown")
        file_path = data.get("file_path", "")

        logger.info("[worker] Processing: %s (path=%s)", filename, file_path)

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(
                f"File not found at path '{file_path}'. "
                "The API saved it, but the worker cannot read it. "
                "Check DATA_DIR mounts are consistent between the API and worker."
            )

        # MOVE the file to the incidents directory so the tree builder can find it
        import shutil
        from pathlib import Path
        incidents_dir = Path(os.environ.get("DATA_DIR", ".")) / "incidents"
        incidents_dir.mkdir(parents=True, exist_ok=True)
        final_path = incidents_dir / filename
        
        # Only move if the file is not already in the incidents directory
        if Path(file_path).resolve() != final_path.resolve():
            shutil.move(file_path, str(final_path))
            logger.info("[worker] Moved file from raw_documents to %s", final_path)

        with open(final_path, "r", encoding="utf-8") as f:
            content = f.read()

        logger.info("[worker] Running embedding for '%s'...", filename)
        from services.retrieval.ingest import ingest_single_document
        ingest_single_document(content, filename)
        logger.info("[worker] ChromaDB updated for '%s'", filename)

        logger.info("[worker] Rebuilding tree index...")
        try:
            from services.retrieval.tree_index import build_tree_index
            build_tree_index()
            logger.info("[worker] Tree index rebuilt.")
        except Exception as exc:
            logger.warning("[worker] Tree index rebuild failed (non-fatal): %s", exc)

        try:
            from app.main import QUERY_CACHE
            QUERY_CACHE.clear()
            logger.info("[worker] Query cache cleared.")
        except Exception as exc:
            logger.warning("[worker] Could not clear query cache (non-fatal): %s", exc)

        logger.info("[worker] Full ingestion complete for '%s'", filename)


if __name__ == "__main__":
    worker = IngestionWorker()
    worker.start()
