"""Deployment and setup regression checks."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "docsort-backend"
FLUTTER = ROOT / "docsort"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runtime_config_fails_fast_without_supabase(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None, jwt_secret="test-secret-value-at-least-32-bytes-12345")

    settings = Settings(
        _env_file=None,
        jwt_secret="test-secret-value-at-least-32-bytes-12345",
        supabase_url="https://example.supabase.co/",
        supabase_service_key="service-role-key",
    )
    assert settings.supabase_url == "https://example.supabase.co"


def test_env_example_matches_active_runtime_settings():
    env_example = read(BACKEND / ".env.example")
    config = read(BACKEND / "app/core/config.py")

    assert "APP_ENVIRONMENT=development" in env_example
    assert "SUPABASE_URL=" in env_example
    assert "SUPABASE_SERVICE_KEY=" in env_example
    assert "JWT_SECRET=" in env_example
    assert "GEMINI_API_KEY=" in env_example
    assert "GEMINI_MODEL=gemini-3.8-flash" in env_example
    assert "gemini_api_key" in config
    assert "AUTOSORT_CONFIDENCE_THRESHOLD=0.75" in env_example
    assert "OCR_LANGUAGES=mar+hin+eng" in env_example


def test_local_utility_scripts_are_portable_and_source_controlled():
    for name in ("get_depts.py", "check_supabase.py"):
        script = read(ROOT / "scripts" / name)
        assert 'parents[1] / "docsort-backend"' in script
        assert "get_supabase_sync" in script

    python_scripts = sorted(path.name for path in (ROOT / "scripts").glob("*.py"))
    assert python_scripts == ["check_supabase.py", "get_depts.py"]
    all_scripts = "\n".join(read(ROOT / "scripts" / name) for name in python_scripts)
    assert "c:\\Users\\" not in all_scripts


def test_android_cleartext_is_debug_only():
    main_manifest = read(FLUTTER / "android/app/src/main/AndroidManifest.xml")
    debug_manifest = read(FLUTTER / "android/app/src/debug/AndroidManifest.xml")

    assert 'android:usesCleartextTraffic="true"' not in main_manifest
    assert 'android:usesCleartextTraffic="true"' in debug_manifest
    assert "Release builds" in debug_manifest


def test_setup_documents_bootstrap_docker_https_and_web_cors():
    setup = read(ROOT / "SETUP.md")
    readme = read(ROOT / "README.md")

    assert "SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, or `JWT_SECRET`" in setup
    assert "APP_ENVIRONMENT=production" in setup
    assert "refuses any non-HTTPS `SUPABASE_URL`" in readme
    assert "docker build -t docsort-backend ." in setup
    assert "WHERE email = 'your-admin@example.com'" in setup
    assert "department_id = COALESCE" in setup
    assert "WHERE code = 'RECORDS'" in setup
    assert "flutter run -d chrome --web-port 3000" in setup
    assert "Release builds" in setup and "HTTPS" in setup
    assert "python scripts/get_depts.py" in setup
    assert "docker build -t docsort-backend ." in readme
    assert "http://127.0.0.1:8000/ready" in setup
    assert "load-balancer/orchestrator readiness checks" in setup


def test_ci_supplies_safe_nonproduction_required_config():
    workflow = read(ROOT / ".github/workflows/backend-tests.yml")

    assert "SUPABASE_URL: https://example.supabase.co" in workflow
    assert "SUPABASE_SERVICE_KEY: test-service-role-key" in workflow
    assert "test-secret-for-ci" in workflow


def test_dockerfile_has_runtime_healthcheck_and_flutter_metadata_is_project_specific():
    dockerfile = read(BACKEND / "Dockerfile")
    pubspec = read(FLUTTER / "pubspec.yaml")

    assert "HEALTHCHECK" in dockerfile
    assert "http://127.0.0.1:8000/" in dockerfile
    assert "GET /ready" in dockerfile
    assert 'description: "A new Flutter project."' not in pubspec
    assert "DocSort intelligent document processing system" in pubspec


def test_release_hygiene_uses_project_app_id_and_safe_upload_logging():
    gradle = read(FLUTTER / "android/app/build.gradle.kts")
    upload_provider = read(
        FLUTTER / "lib/features/upload/presentation/providers/upload_provider.dart"
    )

    assert 'applicationId = "com.docsort.app"' in gradle
    assert "Background upload error for $path: $e" not in upload_provider
    assert "if (kDebugMode) debugPrint('Background batch upload failed.');" in upload_provider
