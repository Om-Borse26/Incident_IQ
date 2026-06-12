"""
services/messaging/pubsub_client.py

Thin wrapper around Redis to act as a robust message queue.
Uses Redis Lists (`lpush`) to queue ingestion tasks.
"""

import json
import logging
from datetime import datetime
import redis

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
QUEUE_NAME = "incident-ingested-queue"


class PubSubClient:
    """
    Handles publishing to the Redis queue used for asynchronous incident ingestion.

    Usage:
        client = PubSubClient()
        client.create_topic_and_subscription_if_not_exists()  # no-op for Redis
        msg_id = client.publish_incident_ingested(
            incident_id="...", filename="...", file_path="..."
        )
    """

    def __init__(self):
        self._redis_client = None
        try:
            self._redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            # Test connection
            self._redis_client.ping()
            logger.info(f"[pubsub] Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            logger.warning(f"[pubsub] Failed to connect to Redis: {e}. Messages will not be queued.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish_incident_ingested(
        self,
        incident_id: str,
        filename: str,
        file_path: str,
    ) -> str | None:
        """
        Publish a message when a new incident file has been validated and saved.
        """
        if not self._redis_client:
            logger.error("[pubsub] Redis client not initialized. Cannot publish message.")
            return None

        payload = {
            "incident_id": incident_id,
            "filename": filename,
            "file_path": file_path,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "incident_ingest_api",
        }
        data = json.dumps(payload)

        try:
            # lpush adds to the left of the list
            self._redis_client.lpush(QUEUE_NAME, data)
            logger.info(
                "[pubsub] Published incident_ingested for '%s' to Redis queue '%s'",
                filename,
                QUEUE_NAME,
            )
            return incident_id
        except Exception as exc:
            logger.error(
                "[pubsub] Failed to publish for '%s': %s. ",
                filename,
                exc,
            )
            return None

    def create_topic_and_subscription_if_not_exists(self) -> None:
        """
        Redis lists are created automatically when you push to them.
        This is a no-op to maintain API compatibility with main.py.
        """
        pass


# Module-level singleton — created once, reused across all requests
pubsub_client = PubSubClient()
