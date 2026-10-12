"""Repository-level regression tests for final release blockers and hardening."""
from __future__ import annotations

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]
FLUTTER = ROOT / "docsort"
BACKEND = ROOT / "docsort-backend"


def test_all_relative_dart_imports_resolve():
    failures = []
    pattern = re.compile(r"(?:import|export|part)\s+['\"]([^'\"]+)['\"]")
    for source in (FLUTTER / "lib").rglob("*.dart"):
        for target in pattern.findall(source.read_text(encoding="utf-8")):
            if not target.startswith("."):
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.exists():
                failures.append(f"{source.relative_to(ROOT)} -> {target}")
    assert not failures, "Unresolved Dart imports:\n" + "\n".join(failures)


def test_scanner_has_web_safe_conditional_boundaries():
    service = (FLUTTER / "lib/features/scanner/services/scanner_service.dart").read_text(encoding="utf-8")
    preview = (FLUTTER / "lib/features/scanner/widgets/scan_preview_image.dart").read_text(encoding="utf-8")
    mobile_service = (FLUTTER / "lib/features/scanner/services/scanner_service_io.dart").read_text(encoding="utf-8")
    mobile_preview = (FLUTTER / "lib/features/scanner/widgets/scan_preview_image_io.dart").read_text(encoding="utf-8")

    assert "if (dart.library.io) 'scanner_service_io.dart'" in service
    assert "if (dart.library.io) 'scan_preview_image_io.dart'" in preview
    assert "cunning_document_scanner" not in service
    assert "dart:io" not in preview
    assert "cunning_document_scanner" in mobile_service
    assert "dart:io" in mobile_preview


def test_ios_scanner_permission_and_pod_configuration_present():
    info = (FLUTTER / "ios/Runner/Info.plist").read_text(encoding="utf-8")
    podfile = (FLUTTER / "ios/Podfile").read_text(encoding="utf-8")
    assert "NSCameraUsageDescription" in info
    assert "platform :ios, '13.0'" in podfile
    assert "PERMISSION_CAMERA=1" in podfile


def test_flutter_ci_is_versioned_and_builds_web():
    workflow_path = ROOT / ".github/workflows/flutter-checks.yml"
    parsed = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert parsed
    source = workflow_path.read_text(encoding="utf-8")
    assert 'flutter-version: "3.47.2"' in source
    assert "flutter pub get" in source
    assert "flutter analyze" in source
    assert "flutter test" in source
    assert "flutter build web --release" in source


def test_backend_ci_checks_dependency_consistency():
    source = (ROOT / ".github/workflows/backend-tests.yml").read_text(encoding="utf-8")
    assert "python -m pip check" in source
    assert "pytest -q" in source


def test_backend_runs_as_non_root_in_container():
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "adduser --system" in dockerfile
    assert "USER docsort" in dockerfile
    assert dockerfile.index("USER docsort") < dockerfile.index('CMD ["uvicorn"')


def test_public_repository_has_license():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "DocSort Contributors" in license_text


def test_pubspec_direct_dependencies_are_exact_and_curated():
    pubspec = (FLUTTER / "pubspec.yaml").read_text(encoding="utf-8")
    for disallowed_dependency in (
        "google_fonts", "supabase_flutter", "confetti", "image_picker",
        "open_filex", "path_provider", "shimmer", "build_runner", "freezed",
        "json_serializable",
    ):
        assert disallowed_dependency not in pubspec
    for line in pubspec.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.endswith(":"):
            continue
        if stripped.startswith("sdk:") or stripped.startswith("image_path:"):
            continue
        if ":" in stripped and not stripped.startswith(("name:", "description:", "publish_to:", "version:")):
            value = stripped.split(":", 1)[1].strip()
            assert not value.startswith("^"), f"Direct dependency is not exact-pinned: {stripped}"


def test_resource_limits_are_documented_in_env_example():
    env = (BACKEND / ".env.example").read_text(encoding="utf-8")
    for name in (
        "MAX_PDF_PAGES", "MAX_IMAGE_PIXELS", "MAX_AI_PAGES",
        "MAX_CONCURRENT_UPLOAD_PROCESSING_JOBS",
        "MAX_FOLDER_PAGE_SIZE", "MAX_FOLDER_EXPORT_DOCUMENTS",
        "MAX_FOLDER_EXPORT_BYTES",
        "EXPORT_SPOOL_MEMORY_BYTES",
    ):
        assert name in env


def test_flutter_application_lockfile_is_committed_and_ci_enforced():
    assert (FLUTTER / "pubspec.lock").is_file()
    workflow = (ROOT / ".github/workflows/flutter-checks.yml").read_text(encoding="utf-8")
    assert "flutter pub get --enforce-lockfile" in workflow




def test_lockfile_matches_exact_direct_dependency_versions():
    pubspec = yaml.safe_load((FLUTTER / "pubspec.yaml").read_text(encoding="utf-8"))
    lock = yaml.safe_load((FLUTTER / "pubspec.lock").read_text(encoding="utf-8"))
    packages = lock["packages"]
    for section in ("dependencies", "dev_dependencies"):
        for name, constraint in pubspec[section].items():
            if isinstance(constraint, dict):  # Flutter SDK dependencies
                continue
            assert packages[name]["version"] == str(constraint)
            expected_kind = "direct main" if section == "dependencies" else "direct dev"
            assert packages[name]["dependency"] == expected_kind


def test_android_signing_secrets_are_gitignored():
    ignore = (FLUTTER / "android/.gitignore").read_text(encoding="utf-8")
    assert "key.properties" in ignore
    assert "*.keystore" in ignore
    assert "*.jks" in ignore


def test_android_release_does_not_reuse_debug_signing_key():
    source = (FLUTTER / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert 'signingConfig = signingConfigs.getByName("debug")' not in source
    assert 'rootProject.file("key.properties")' in source
    assert 'signingConfigs.getByName("release")' in source


def test_backend_api_metadata_matches_project_version():
    pubspec = (FLUTTER / "pubspec.yaml").read_text(encoding="utf-8")
    main = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "version: 1.0.0+1" in pubspec
    assert 'from app.core.version import APP_VERSION, SERVICE_NAME' in main
    assert 'version=APP_VERSION' in main
    assert '"service": SERVICE_NAME' in main
    version_module = (BACKEND / "app/core/version.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "1.0.0"' in version_module
    assert 'SERVICE_NAME = f"DocSort API v{APP_VERSION}"' in version_module


def test_auth_me_and_flutter_live_session_rehydration_are_wired():
    backend = (BACKEND / "app/api/auth.py").read_text(encoding="utf-8")
    frontend = (FLUTTER / "lib/features/auth/presentation/providers/auth_provider.dart").read_text(encoding="utf-8")
    assert '@router.get("/me"' in backend
    assert "Depends(get_current_user)" in backend
    assert "dio.get('/auth/me')" in frontend
    assert "JwtDecoder.isExpired(token)" in frontend


def test_final_year_release_document_is_feature_frozen_and_honest():
    release = ROOT / "docs/FINAL_YEAR_RELEASE.md"
    assert release.is_file()
    text = release.read_text(encoding="utf-8")
    for required in (
        "DocSort 1.0.0",
        "Feature freeze",
        "Demo checklist",
        "Verification boundary",
        "Known limitations",
        "Future scope",
        "flutter analyze",
        "flutter test",
    ):
        assert required in text


def test_final_release_openapi_inventory_is_documented():
    report = (ROOT / "docs/FINAL_IMPLEMENTATION_REPORT.md").read_text(encoding="utf-8")
    assert "41 HTTP paths" in report
    assert "46 HTTP operations" in report
