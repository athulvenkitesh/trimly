from app.core.config import Settings, settings


def test_public_url_defaults_to_render_url(monkeypatch):
    # Render sets RENDER_EXTERNAL_URL for every web service, so a first deploy
    # needs no manually copied https://trimly-xxxx.onrender.com.
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://trimly-abc.onrender.com")
    assert Settings(_env_file=None).public_base_url == "https://trimly-abc.onrender.com"


def test_public_url_explicit_value_wins_over_render_url(monkeypatch):
    # A custom domain must beat the onrender.com URL.
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://trimly-abc.onrender.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://trimly.app")
    assert Settings(_env_file=None).public_base_url == "https://trimly.app"


def test_public_url_falls_back_to_localhost_off_host(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert Settings(_env_file=None).public_base_url == "http://localhost:8000"


def test_running_settings_are_still_usable():
    # The module-level singleton imports from .env; it must resolve to something.
    assert settings.public_base_url.startswith("http")
