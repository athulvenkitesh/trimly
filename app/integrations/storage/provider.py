"""Where shop logos live.

Uploads used to be written straight to ``uploads/shops`` on disk. That is fine
on a laptop and wrong on a container host: the filesystem is replaced on every
deploy, so a logo uploaded yesterday 404s tomorrow. This module keeps the disk
path for local development and puts the same bytes in an S3-compatible bucket
(Cloudflare R2) everywhere else.

Names stay content-addressed (sha256 prefix + extension), which is what lets a
re-upload replace the old object and lets the browser cache the URL forever.
"""

from abc import ABC, abstractmethod
from hashlib import sha256
from pathlib import Path


def content_name(data: bytes, suffix: str) -> str:
    """Deterministic object name: same bytes -> same name -> immutable caching."""
    return sha256(data).hexdigest()[:16] + suffix


class LogoStorage(ABC):
    """Provider boundary; callers get back the URL to store on the shop."""

    @abstractmethod
    def save(self, data: bytes, suffix: str, content_type: str) -> str: ...


class LocalLogoStorage(LogoStorage):
    """Development/single-box storage served by the ``/uploads`` static mount."""

    def __init__(self, directory: Path):
        self.directory = directory

    def save(self, data: bytes, suffix: str, content_type: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        name = content_name(data, suffix)
        (self.directory / name).write_bytes(data)
        return f"/uploads/shops/{name}"


def get_logo_storage() -> LogoStorage:
    """Pick the backend from settings.

    ``STORAGE_BACKEND=local`` (the default) keeps everything on disk. ``s3``
    requires the bucket and credentials to be present, and failing loudly here
    beats silently writing to a container that is about to disappear.
    """
    from app.core.config import settings

    if settings.storage_backend.lower() != "s3":
        # parents[3] is the project root: this module sits at app/integrations/storage/.
        # It must match the /uploads mount in app/main.py, not a directory under app/.
        return LocalLogoStorage(Path(__file__).resolve().parents[3] / "uploads" / "shops")

    missing = [
        name
        for name, value in (
            ("S3_BUCKET", settings.s3_bucket),
            ("S3_ACCESS_KEY_ID", settings.s3_access_key_id),
            ("S3_SECRET_ACCESS_KEY", settings.s3_secret_access_key),
            ("S3_PUBLIC_BASE_URL", settings.s3_public_base_url),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "STORAGE_BACKEND=s3 but " + ", ".join(missing) + " is not set. "
            "Set the bucket credentials or switch STORAGE_BACKEND=local."
        )

    from app.integrations.storage.s3 import S3LogoStorage

    return S3LogoStorage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url or None,
        region=settings.s3_region,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
        public_base_url=settings.s3_public_base_url,
    )
