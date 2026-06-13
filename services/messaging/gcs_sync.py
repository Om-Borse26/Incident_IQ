"""
services/messaging/gcs_sync.py

Stub for S3 snapshot synchronisation (formerly GCS).

On EC2 with a host-mounted EBS directory (/home/ec2-user/data:/data),
this module is a no-op — the EBS volume is the persistent storage.

If you later migrate to a stateless compute platform (e.g., ECS Fargate,
Lambda), this stub would be replaced with S3 sync logic:

TODO (ECS/Fargate migration):
  1. pip install boto3 (already in requirements.txt)
  2. import boto3
  3. s3 = boto3.client("s3")
  4. s3.upload_file(local_path, os.environ["S3_BUCKET"], s3_key)
  5. Upload all files under chroma_db/, tree_index/, and raw_documents/
     on a schedule or after each ingestion.
"""

import logging

logger = logging.getLogger(__name__)


def upload_snapshot() -> None:
    """
    Stub: Upload chroma_db/ and tree_index/ to S3 for cross-container persistence.
    No-op on EC2 with mounted EBS volume — data is already persistent on disk.
    """
    logger.debug("[s3_sync] upload_snapshot called (no-op — data persisted on EBS volume)")
