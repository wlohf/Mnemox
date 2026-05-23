from app.config import Settings, _DEFAULT_UPDATE_MANIFEST_URL


def test_update_manifest_url_falls_back_to_public_manifest_when_blank():
    settings = Settings(_env_file=None, APP_UPDATE_MANIFEST_URL="")

    assert settings.APP_UPDATE_MANIFEST_URL == _DEFAULT_UPDATE_MANIFEST_URL
