from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_backend_ci_compiles_then_runs_pytest():
    workflow = (ROOT / '.github/workflows/backend-tests.yml').read_text()
    assert 'python -m compileall -q app tests' in workflow
    assert 'pytest -q' in workflow
    assert 'requirements-dev.txt' in workflow


def test_flutter_ci_runs_dependency_analysis_and_tests():
    workflow = (ROOT / '.github/workflows/flutter-checks.yml').read_text()
    assert 'flutter pub get' in workflow
    assert 'flutter analyze' in workflow
    assert 'flutter test' in workflow
    assert 'subosito/flutter-action@v2' in workflow


def test_flutter_has_authored_test_suite():
    test_file = ROOT / 'docsort/test/graph_models_test.dart'
    text = test_file.read_text()
    assert test_file.exists()
    assert "preserves normalized OCR confidence" in text
    assert "potential-match wording" in text
    assert "empty graph contains no fabricated people" in text


def test_generated_artifacts_are_ignored_and_not_kept():
    gitignore = (ROOT / '.gitignore').read_text()
    assert '.pytest_cache/' in gitignore
    assert 'analyze_output.txt' in gitignore
    assert not (ROOT / 'docsort/analyze_output.txt').exists()
    assert '__pycache__/' in gitignore


def test_setup_docs_reference_flutter_validation_commands():
    setup = (ROOT / 'SETUP.md').read_text()
    assert 'flutter analyze' in setup
    assert 'flutter test' in setup
    assert 'flutter build web --release' in setup


def test_backend_requirements_include_runtime_dependency_set():
    requirements = (ROOT / 'docsort-backend/requirements.txt').read_text().lower()
    for package in ('fastapi', 'httpx', 'pytesseract', 'google-genai', 'python-dateutil'):
        assert package in requirements
