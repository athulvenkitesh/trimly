"""S3-compatible logo storage (Cloudflare R2 in production)."""

from app.integrations.storage.provider import LogoStorage, content_name

# One year: object names are content hashes, so the bytes behind a URL never change.
CACHE_CONTROL = "public, max-age=31536000, immutable"


class S3LogoStorage(LogoStorage):
    def __init__(self, *, bucket: str, endpoint_url: str | None, region: str,
                 access_key_id: str, secret_access_key: str, public_base_url: str,
                 prefix: str = "shops", client=None):
        self.bucket = bucket
        self.prefix = prefix
        self.public_base_url = public_base_url.rstrip("/")
        self._client = client or _build_client(endpoint_url, region, access_key_id, secret_access_key)

    def save(self, data: bytes, suffix: str, content_type: str) -> str:
        name = content_name(data, suffix)
        key = f"{self.prefix}/{name}"
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl=CACHE_CONTROL,
        )
        return f"{self.public_base_url}/{key}"


def _build_client(endpoint_url: str | None, region: str, access_key_id: str, secret_access_key: str):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        # R2 requires a region value but ignores it; "auto" is what Cloudflare documents.
        region_name=region or "auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )
