"""
services/messaging/pubsub_client.py

Thin wrapper around the Google Cloud Pub/Sub SDK.

Design principles:
  - All setup is idempotent: safe to call on every startup.
  - Publisher never raises: if Pub/Sub is unreachable, we log + return None
    so the API request still succeeds (file is already saved).
  - Topic/subscription creation uses AlreadyExists suppression so restarts
    don't crash if infrastructure already exists.
  - PUBSUB_EMULATOR_HOST env var transparently redirects to the local emulator
    when set; remove it (or leave blank) to connect to real GCP.
"""

import json
import logging
import os
from datetime import datetime

from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ID = settings.GCP_PROJECT_ID
TOPIC_ID = "incident-ingested"
SUBSCRIPTION_ID = "incident-ingested-sub"
DEAD_LETTER_TOPIC_ID = "incident-ingested-dead-letter"
DEAD_LETTER_SUBSCRIPTION_ID = "incident-ingested-dead-letter-sub"


class PubSubClient:
    """
    Handles publishing to and subscribing from the Pub/Sub topic used
    for asynchronous incident ingestion.

    Usage:
        client = PubSubClient()
        client.create_topic_and_subscription_if_not_exists()  # call once at startup
        msg_id = client.publish_incident_ingested(
            incident_id="...", filename="...", file_path="..."
        )
    """

    def __init__(self):
        # If the emulator host is configured, point the SDK at it.
        # This is a standard GCP SDK convention — set before client creation.
        emulator_host = settings.PUBSUB_EMULATOR_HOST
        if emulator_host:
            os.environ["PUBSUB_EMULATOR_HOST"] = emulator_host
            logger.info("[pubsub] Using local Pub/Sub emulator at %s", emulator_host)
        else:
            logger.info("[pubsub] Using real Google Cloud Pub/Sub (project: %s)", PROJECT_ID)

        self._publisher = pubsub_v1.PublisherClient()

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

        Returns the Pub/Sub message_id on success, or None if the publish failed.
        The caller MUST NOT raise on None — graceful degradation is intentional.

        WHY we never raise here:
          The file is already persisted to disk. Even if Pub/Sub is temporarily
          unreachable, the user's upload was successful. The worst case is that
          the incident won't be searchable until someone manually re-triggers
          ingestion. This is acceptable; a 5xx to the user is not.
        """
        topic_path = self._publisher.topic_path(PROJECT_ID, TOPIC_ID)

        payload = {
            "incident_id": incident_id,
            "filename": filename,
            "file_path": file_path,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "incident_ingest_api",
        }
        data = json.dumps(payload).encode("utf-8")

        try:
            future = self._publisher.publish(topic_path, data=data)
            message_id = future.result(timeout=10)
            logger.info(
                "[pubsub] Published incident_ingested for '%s' — message_id=%s",
                filename,
                message_id,
            )
            return message_id
        except Exception as exc:
            # Log at ERROR so it is visible, but do NOT re-raise.
            # The API endpoint will log this and return success anyway.
            logger.error(
                "[pubsub] Failed to publish for '%s': %s. "
                "File is saved; ingestion will NOT be triggered automatically. "
                "Manual re-ingest may be needed.",
                filename,
                exc,
            )
            return None

    def create_topic_and_subscription_if_not_exists(self) -> None:
        """
        Idempotent infrastructure setup. Safe to call on every application
        startup — AlreadyExists errors are swallowed.

        Creates:
          1. Main topic              — incident-ingested
          2. Main subscription       — incident-ingested-sub  (linked to topic)
          3. Dead-letter topic       — incident-ingested-dead-letter
          4. Dead-letter subscription— incident-ingested-dead-letter-sub

        Dead-letter policy:
          After 5 failed delivery attempts (nack or ack deadline exceeded),
          Pub/Sub moves the message to the dead-letter topic automatically.
          The worker has a separate pull loop for the dead-letter subscription
          that logs at CRITICAL so the team can investigate.
        """
        publisher = self._publisher
        subscriber = pubsub_v1.SubscriberClient()

        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        dead_letter_topic_path = publisher.topic_path(PROJECT_ID, DEAD_LETTER_TOPIC_ID)
        subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
        dead_letter_sub_path = subscriber.subscription_path(PROJECT_ID, DEAD_LETTER_SUBSCRIPTION_ID)

        # 1. Create main topic
        self._create_topic(publisher, topic_path)

        # 2. Create dead-letter topic (must exist before the subscription references it)
        self._create_topic(publisher, dead_letter_topic_path)

        # 3. Create main subscription with dead-letter policy
        try:
            dead_letter_policy = pubsub_v1.types.DeadLetterPolicy(
                dead_letter_topic=dead_letter_topic_path,
                max_delivery_attempts=5,  # After 5 nacks → dead-letter topic
            )
            subscriber.create_subscription(
                request={
                    "name": subscription_path,
                    "topic": topic_path,
                    "dead_letter_policy": dead_letter_policy,
                    "ack_deadline_seconds": 60,  # Worker has 60s to ack before redelivery
                }
            )
            logger.info("[pubsub] Created subscription: %s", subscription_path)
        except AlreadyExists:
            logger.debug("[pubsub] Subscription already exists: %s", subscription_path)

        # 4. Create dead-letter subscription
        try:
            subscriber.create_subscription(
                request={
                    "name": dead_letter_sub_path,
                    "topic": dead_letter_topic_path,
                }
            )
            logger.info("[pubsub] Created dead-letter subscription: %s", dead_letter_sub_path)
        except AlreadyExists:
            logger.debug("[pubsub] Dead-letter subscription already exists: %s", dead_letter_sub_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_topic(publisher: pubsub_v1.PublisherClient, topic_path: str) -> None:
        try:
            publisher.create_topic(request={"name": topic_path})
            logger.info("[pubsub] Created topic: %s", topic_path)
        except AlreadyExists:
            logger.debug("[pubsub] Topic already exists: %s", topic_path)


# Module-level singleton — created once, reused across all requests
pubsub_client = PubSubClient()
