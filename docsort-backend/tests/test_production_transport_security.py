"""Production transport configuration security tests."""
import pytest


def _settings(**overrides):
    from app.core.config import Settings

    values = {
        "_env_file": None,
        "jwt_secret": "test-secret-value-at-least-32-bytes-12345",
        "supabase_service_key": "service-key",
    }
    values.update(overrides)
    return Settings(**values)


def test_development_mode_allows_local_http_supabase():
    settings = _settings(
        app_environment="development",
        supabase_url="http://127.0.0.1:54321/",
    )

    assert settings.app_environment == "development"
    assert settings.supabase_url == "http://127.0.0.1:54321"


def test_production_mode_rejects_plain_http_supabase():
    with pytest.raises(Exception, match="HTTPS"):
        _settings(
            app_environment="production",
            supabase_url="http://example.supabase.co",
        )


def test_production_mode_accepts_https_supabase():
    settings = _settings(
        app_environment="production",
        supabase_url="https://example.supabase.co/",
    )

    assert settings.app_environment == "production"
    assert settings.supabase_url == "https://example.supabase.co"


def test_unknown_application_environment_is_rejected():
    with pytest.raises(Exception):
        _settings(
            app_environment="staging-ish",
            supabase_url="https://example.supabase.co",
        )
