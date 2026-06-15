"""
services/messaging/pubsub_client.py

Thin wrapper around AWS SQS to act as a robust message queue.
Uses boto3 to publish ingestion tasks to the incident-ingested-queue.

SQS gives us true ack/nack semantics:
  - Producer: send_message() → fire and forget
  - Consumer: receive_message() + delete_message() on success (ACK)
  - Consumer: do nothing on failure → SQS redelivers after VisibilityTimeout (NACK)
  - After maxReceiveCount failures → message moves to Dead-Letter Queue (DLQ)
"""

import json
import logging
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
QUEUE_NAME = "incident-ingested-queue"
DLQ_NAME = "incident-ingested-dlq"


class PubSubClient:
    """
    Handles publishing to the SQS queue used for asynchronous incident ingestion.

    Usage:
        client = PubSubClient()
        client.create_topic_and_subscription_if_not_exists()  # idempotent
        msg_id = client.publish_incident_ingested(
            incident_id="...", filename="...", file_path="..."
        )
    """

    def __init__(self):
        self._sqs = None
        self._queue_url = None
        try:
            boto_kwargs = {"region_name": settings.AWS_REGION}
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                boto_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                boto_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
                
            self._sqs = boto3.client("sqs", **boto_kwargs)
            logger.info("[pubsub] SQS client initialized for region %s", settings.AWS_REGION)
        except Exception as e:
            logger.warning("[pubsub] Failed to initialize SQS client: %s. Messages will not be queued.", e)

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
        Returns the SQS MessageId on success, None on failure.
        """
        if not self._sqs or not self._queue_url:
            logger.error("[pubsub] SQS client not initialized. Cannot publish message.")
            return None

        payload = {
            "incident_id": incident_id,
            "filename": filename,
            "file_path": file_path,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "incident_ingest_api",
        }

        try:
            response = self._sqs.send_message(
                QueueUrl=self._queue_url,
                MessageBody=json.dumps(payload),
            )
            msg_id = response.get("MessageId")
            logger.info(
                "[pubsub] Published incident_ingested for '%s' to SQS queue '%s' (MessageId=%s)",
                filename,
                QUEUE_NAME,
                msg_id,
            )
            return msg_id
        except Exception as exc:
            logger.error(
                "[pubsub] Failed to publish for '%s': %s",
                filename,
                exc,
            )
            return None

    def create_topic_and_subscription_if_not_exists(self) -> None:
        """
        Idempotently ensure the SQS queues exist.
        SQS create_queue is idempotent — safe to call on every startup.
        """
        if not self._sqs:
            logger.warning("[pubsub] SQS client not available — skipping queue creation.")
            return

        try:
            # Create DLQ first (needed for the redrive policy on the main queue)
            dlq_resp = self._sqs.create_queue(QueueName=DLQ_NAME)
            dlq_url = dlq_resp["QueueUrl"]

            dlq_attrs = self._sqs.get_queue_attributes(
                QueueUrl=dlq_url,
                AttributeNames=["QueueArn"]
            )
            dlq_arn = dlq_attrs["Attributes"]["QueueArn"]

            # Create main queue with redrive policy pointing to DLQ
            main_resp = self._sqs.create_queue(
                QueueName=QUEUE_NAME,
                Attributes={
                    "VisibilityTimeout": "300",
                    "RedrivePolicy": json.dumps({
                        "deadLetterTargetArn": dlq_arn,
                        "maxReceiveCount": 5,
                    }),
                },
            )
            self._queue_url = main_resp["QueueUrl"]
            logger.info("[pubsub] SQS queues ready. Main: %s | DLQ: %s", self._queue_url, dlq_url)

        except ClientError as e:
            logger.error("[pubsub] Failed to create SQS queues: %s", e)


# Module-level singleton — created once, reused across all requests
pubsub_client = PubSubClient()
