import io
from pathlib import Path

import pytest

from app.core.config import sqlalchemy_url
from app.integrations.storage.provider import (
    LocalLogoStorage,
    content_name,
    get_logo_storage,
)
from app.integrations.storage.s3 import S3LogoStorage

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-logo-bytes" * 10


def test_content_name_is_deterministic_and_keeps_extension():
    assert content_name(PNG, ".png") == content_name(PNG, ".png")
    assert content_name(PNG, ".png").endswith(".png")
    assert content_name(PNG, ".png") != content_name(PNG + b"x", ".png")
    assert len(content_name(PNG, ".png")) == 20  # 16 hex chars + ".png"


def test_local_storage_writes_under_the_static_mount(tmp_path):
    url = LocalLogoStorage(tmp_path).save(PNG, ".png", "image/png")
    assert url == f"/uploads/shops/{content_name(PNG, '.png')}"
    assert (tmp_path / content_name(PNG, ".png")).read_bytes() == PNG


class StubS3Client:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        return {"ETag": '"abc"'}


def test_s3_storage_uploads_with_cache_headers_and_returns_public_url():
    client = StubS3Client()
    storage = S3LogoStorage(
        bucket="trimly-logos",
        endpoint_url="https://account.r2.cloudflarestorage.com",
        region="auto",
        access_key_id="key",
        secret_access_key="secret",
        public_base_url="https://cdn.example.com/",
        client=client,
    )

    url = storage.save(PNG, ".png", "image/png")

    assert url == f"https://cdn.example.com/shops/{content_name(PNG, '.png')}"
    call = client.calls[0]
    assert call["Bucket"] == "trimly-logos"
    assert call["Key"] == f"shops/{content_name(PNG, '.png')}"
    assert call["Body"] == PNG and call["ContentType"] == "image/png"
    assert "immutable" in call["CacheControl"]


def test_s3_backend_refuses_to_start_without_credentials(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "trimly-logos")
    monkeypatch.setattr(settings, "s3_access_key_id", "")
    with pytest.raises(RuntimeError, match="S3_ACCESS_KEY_ID"):
        get_logo_storage()


def test_default_backend_is_local_disk(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_backend", "local")
    assert isinstance(get_logo_storage(), LocalLogoStorage)


def test_local_storage_writes_where_the_static_mount_serves(monkeypatch):
    # Regression: the directory was once resolved one level too deep (app/uploads),
    # so uploads succeeded but every logo URL 404'd.
    from app.core.config import settings
    import app.main as main

    monkeypatch.setattr(settings, "storage_backend", "local")
    assert get_logo_storage().directory == main.uploads_dir / "shops"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql+psycopg://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("sqlite:///./test_booking.db", "sqlite:///./test_booking.db"),
    ],
)
def test_hosted_postgres_urls_are_rewritten_for_psycopg(raw, expected):
    # Render hands out postgresql://..., which SQLAlchemy would route to psycopg2.
    assert sqlalchemy_url(raw) == expected


def test_logo_upload_route_stores_through_the_boundary(client, monkeypatch, tmp_path):
    import app.api.routes.barber as barber

    monkeypatch.setattr(barber, "get_logo_storage", lambda: LocalLogoStorage(tmp_path))

    tokens = client.post("/api/v1/auth/register", json={
        "email": "logo@example.com", "password": "password123", "role": "SHOP_OWNER"}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    shop = client.post("/api/v1/shops", headers=headers, json={"name": "Logo Shop"}).json()

    response = client.put(
        f"/api/v1/barber/shops/{shop['id']}/logo",
        headers=headers,
        files={"file": ("logo.png", io.BytesIO(PNG), "image/png")},
    )

    assert response.status_code == 200, response.text
    expected = f"/uploads/shops/{content_name(PNG, '.png')}"
    assert response.json()["logo_url"] == expected
    assert (tmp_path / content_name(PNG, ".png")).read_bytes() == PNG
    # The stored URL is what customers see on the shop detail.
    assert client.get(f"/api/v1/shops/{shop['id']}").json()["logo_url"] == expected


def test_logo_upload_rejects_non_images(client, monkeypatch, tmp_path):
    import app.api.routes.barber as barber

    monkeypatch.setattr(barber, "get_logo_storage", lambda: LocalLogoStorage(tmp_path))
    tokens = client.post("/api/v1/auth/register", json={
        "email": "badlogo@example.com", "password": "password123", "role": "SHOP_OWNER"}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    shop = client.post("/api/v1/shops", headers=headers, json={"name": "Bad Logo Shop"}).json()

    response = client.put(
        f"/api/v1/barber/shops/{shop['id']}/logo",
        headers=headers,
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 422
    assert not list(Path(tmp_path).glob("*"))
