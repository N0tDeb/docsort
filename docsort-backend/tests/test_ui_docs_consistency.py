from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLUTTER = ROOT / "docsort" / "lib"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_core_ui_uses_truthful_processing_and_confidence_copy():
    home = read("docsort/lib/features/home/presentation/screens/home_screen.dart")
    processing = read("docsort/lib/features/upload/presentation/screens/processing_screen.dart")
    result = read("docsort/lib/features/upload/presentation/screens/result_screen.dart")
    upload = read("docsort/lib/features/upload/presentation/screens/upload_screen.dart")

    for label in (
        "Integrity & Duplicate Check",
        "Secure File Storage",
        "OCR & AI Extraction",
        "Anomaly Check",
        "Classification & Filing",
    ):
        assert label in home
        assert label in processing

    assert "OCR Confidence" in result
    assert "AI Confidence" not in result
    assert "Use the camera scanner to crop & enhance" in upload
    assert "Use AI camera" not in upload


def test_recent_documents_respect_review_state():
    home = read("docsort/lib/features/home/presentation/screens/home_screen.dart")
    assert "doc['review_status'] == 'verified'" in home
    assert "isVerified ? 'View' : 'Review'" in home
    assert "isVerified ? '/result/${doc['id']}' : '/review/${doc['id']}'" in home


def test_search_clear_button_clears_real_text_controller():
    search = read("docsort/lib/features/search/presentation/screens/search_screen.dart")
    assert "ConsumerStatefulWidget" in search
    assert "TextEditingController" in search
    assert "controller: _searchController" in search
    assert "_searchController.clear();" in search
    assert "Document Search" in search
    assert "Global Search" not in search
    assert "Needs a controller" not in search


def test_development_helper_uses_backend_default_port():
    script = read("scripts/start_dev.ps1")
    setup = read("SETUP.md")
    assert "$port = 8000" in script
    assert "37926" not in script
    assert "37926" not in setup
    assert "adb reverse tcp:8000 tcp:8000" in setup


def test_public_docs_use_only_current_domain_neutral_material():
    pitch = read("docs/PITCH.md")
    flutter_readme = read("docsort/README.md")
    docs_index = read("docs/README.md")
    flow = read("docs/FLOW.md")
    architecture = read("docsort-backend/ARCHITECTURE.md")

    assert "Final-Year Project Pitch" in pitch
    assert "human-in-the-loop" in pitch.lower()
    assert "A new Flutter project" not in flutter_readme
    assert "DocSort Flutter Client" in flutter_readme
    assert "End-to-End Flow" in flow
    assert "FastAPI is the application authorization boundary" in architecture
    assert "current documentation set" in docs_index
