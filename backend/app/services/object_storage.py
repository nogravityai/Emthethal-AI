"""
services/object_storage.py — Emthethal AI
==========================================
MinIO/S3 object storage service for original uploaded files.

Rule: FastAPI never keeps uploaded files in /tmp or memory.
Every file uploaded via /ingest is persisted to MinIO immediately,
then the object key is passed downstream to the pipeline.

This prevents:
  - Memory exhaustion on large PDF batches
  - Loss of original files after processing
  - Inability to re-ingest without re-uploading

Swap backend: change STORAGE_BACKEND env var.
  "minio"  → MinIO (default, self-hosted)
  "s3"     → AWS S3
  "local"  → Local filesystem fallback (dev only)
"""

import hashlib
import logging
import os
import uuid
from datetime import datetime
from io import BytesIO
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "minio")
MINIO_ENDPOINT  = os.getenv("MINIO_ENDPOINT",  "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "emthethal")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "emthethal_secret_2026")
MINIO_BUCKET    = os.getenv("MINIO_BUCKET",    "emthethal-originals")
MINIO_SECURE    = os.getenv("MINIO_SECURE",    "false").lower() == "true"


def _build_object_key(filename: str) -> str:
    """
    Build a deterministic, collision-resistant object key.
    Format: uploads/YYYY/MM/DD/<uuid4>_<sanitized_filename>
    """
    today = datetime.utcnow().strftime("%Y/%m/%d")
    file_uuid = str(uuid.uuid4())
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
    return f"uploads/{today}/{file_uuid}_{safe_name}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStorageService:
    """
    Unified object storage client.
    Uses MinIO by default; swappable via STORAGE_BACKEND env var.
    """

    def __init__(self):
        self.backend = STORAGE_BACKEND
        self._client = None

    def _get_minio_client(self):
        """Lazy MinIO client initialization."""
        if self._client is None:
            try:
                from minio import Minio
                self._client = Minio(
                    MINIO_ENDPOINT,
                    access_key=MINIO_ACCESS_KEY,
                    secret_key=MINIO_SECRET_KEY,
                    secure=MINIO_SECURE,
                )
                # Ensure bucket exists
                if not self._client.bucket_exists(MINIO_BUCKET):
                    self._client.make_bucket(MINIO_BUCKET)
                    logger.info(f"Created MinIO bucket: {MINIO_BUCKET}")
            except ImportError:
                logger.warning("minio package not installed. Object storage disabled.")
                self._client = "unavailable"
        return self._client

    def store(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> Tuple[str, str, str]:
        """
        Store file bytes to object storage.

        Returns:
            (object_key, bucket_name, sha256_checksum)
        """
        object_key = _build_object_key(filename)
        checksum   = _sha256(file_bytes)

        if self.backend == "local":
            # Dev fallback: write to local disk
            local_path = f"/tmp/emthethal_objects/{object_key}"
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(file_bytes)
            logger.info(f"[local] Stored {len(file_bytes)} bytes → {local_path}")
            return object_key, "local", checksum

        # MinIO / S3
        client = self._get_minio_client()
        if client == "unavailable":
            logger.warning("Object storage unavailable. File not persisted.")
            return object_key, MINIO_BUCKET, checksum

        client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=object_key,
            data=BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type,
            metadata={"sha256": checksum, "original_filename": filename},
        )
        logger.info(
            f"[minio] Stored {len(file_bytes)} bytes → "
            f"{MINIO_BUCKET}/{object_key} (sha256={checksum[:8]}...)"
        )
        return object_key, MINIO_BUCKET, checksum

    def get_url(self, object_key: str, expiry_seconds: int = 3600) -> Optional[str]:
        """Generate a presigned URL for file download (audit/review UI)."""
        if self.backend == "local":
            return f"/api/v1/files/{object_key}"

        client = self._get_minio_client()
        if client == "unavailable":
            return None

        from datetime import timedelta
        return client.presigned_get_object(
            MINIO_BUCKET,
            object_key,
            expires=timedelta(seconds=expiry_seconds),
        )

    def health(self) -> dict:
        """Return storage backend health status."""
        if self.backend == "local":
            return {"backend": "local", "status": "ok"}
        client = self._get_minio_client()
        if client == "unavailable":
            return {"backend": "minio", "status": "unavailable"}
        try:
            client.bucket_exists(MINIO_BUCKET)
            return {"backend": "minio", "endpoint": MINIO_ENDPOINT, "status": "ok"}
        except Exception as e:
            return {"backend": "minio", "status": "error", "error": str(e)}


# Singleton
object_storage = ObjectStorageService()
