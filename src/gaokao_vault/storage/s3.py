"""S3-compatible (MinIO) image storage for VisionAnalyzer."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import boto3

from gaokao_vault.config import S3Config

logger = logging.getLogger(__name__)

__all__ = ["S3Storage"]


class S3Storage:
    """Upload images to MinIO/S3 and generate presigned GET URLs."""

    def __init__(self, config: S3Config) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name="us-east-1",
        )
        self._bucket = config.bucket_name
        self._public_url = config.public_url.rstrip("/")
        self._endpoint_url = config.endpoint_url.rstrip("/")
        self._presign_expires = config.presign_expires

    def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            logger.info("Creating bucket %s", self._bucket)
            self._client.create_bucket(Bucket=self._bucket)

    def upload_image(self, image_path: Path, key: str) -> str:
        """Upload a local image file and return the object key."""
        guessed_type, _ = mimetypes.guess_type(image_path.name)
        content_type = guessed_type or "application/octet-stream"
        self._client.upload_file(
            str(image_path),
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.debug("Uploaded %s -> s3://%s/%s", image_path.name, self._bucket, key)
        return key

    def presigned_url(self, key: str) -> str:
        """Generate a presigned GET URL, rewritten to use the public endpoint.

        Supports public URLs with path prefixes (e.g. ``http://host/minio-s3``)
        for reverse-proxy setups where the external API (OpenAI) cannot reach
        non-standard ports like 9000.
        """
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._presign_expires,
        )
        # Replace internal Docker endpoint with public URL so the
        # external API proxy can reach the image.
        if self._public_url != self._endpoint_url:
            parsed_public = urlparse(self._public_url)
            public_prefix = f"{parsed_public.scheme}://{parsed_public.netloc}{parsed_public.path.rstrip('/')}"
            url = url.replace(self._endpoint_url, public_prefix, 1)
        return url

    def delete_image(self, key: str) -> None:
        """Delete an object from the bucket."""
        self._client.delete_object(Bucket=self._bucket, Key=key)
        logger.debug("Deleted s3://%s/%s", self._bucket, key)
