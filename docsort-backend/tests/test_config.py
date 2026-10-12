"""Configuration and JWT-secret enforcement tests."""
import importlib
import pytest


def _fresh_settings(**env):
    import os
    from app.core import config as cfg
    for k, v in env.items():
        os.environ[k] = v
    return cfg.Settings


def test_valid_secret_boots():
    from app.core.config import Settings
    s = Settings(
        _env_file=None,
        jwt_secret="test-secret-value-at-least-32-bytes-12345",
        supabase_url="https://example.supabase.co",
        supabase_service_key="service-key",
    )
    assert s.jwt_secret == "test-secret-value-at-least-32-bytes-12345"


def test_short_secret_rejected():
    from app.core.config import Settings
    with pytest.raises(Exception):
        Settings(
            _env_file=None, jwt_secret="too-short",
            supabase_url="https://example.supabase.co", supabase_service_key="service-key"
        )


def test_placeholder_secret_rejected():
    from app.core.config import Settings
    with pytest.raises(Exception):
        Settings(
            _env_file=None, jwt_secret="change-me-in-production",
            supabase_url="https://example.supabase.co", supabase_service_key="service-key"
        )


def test_empty_secret_rejected():
    from app.core.config import Settings
    with pytest.raises(Exception):
        Settings(
            _env_file=None, jwt_secret="",
            supabase_url="https://example.supabase.co", supabase_service_key="service-key"
        )


def test_cors_origins_parse():
    from app.core.config import Settings
    s = Settings(
        _env_file=None, jwt_secret="test-secret-value-at-least-32-bytes-12345",
        supabase_url="https://example.supabase.co", supabase_service_key="service-key",
        cors_origins="http://a.com, http://b.com ,",
    )
    assert s.cors_origin_list == ["http://a.com", "http://b.com"]


def test_missing_supabase_config_rejected(monkeypatch):
    from app.core.config import Settings
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None, jwt_secret="test-secret-value-at-least-32-bytes-12345")


def test_invalid_supabase_url_rejected():
    from app.core.config import Settings
    with pytest.raises(Exception):
        Settings(
            _env_file=None, jwt_secret="test-secret-value-at-least-32-bytes-12345",
            supabase_url="not-a-url", supabase_service_key="service-key"
        )
