from app import __version__
from app.config import Settings, _DEFAULT_UPDATE_MANIFEST_URL


def test_update_manifest_url_falls_back_to_public_manifest_when_blank():
    settings = Settings(_env_file=None, APP_UPDATE_MANIFEST_URL="")

    assert settings.APP_UPDATE_MANIFEST_URL == _DEFAULT_UPDATE_MANIFEST_URL


def test_default_app_version_matches_package_version(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)

    settings = Settings(_env_file=None)

    assert settings.APP_VERSION == __version__
