from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_backend_uses_single_supabase_storage_adapter():
    assert not (ROOT / "docsort-backend/app/services/storage_service.py").exists()
    app_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "docsort-backend/app").rglob("*.py")
    )
    assert "StorageService" not in app_source
    assert "storage_service" not in app_source


def test_demo_critical_flutter_surfaces_do_not_render_raw_exceptions():
    forbidden_by_file = {
        "docsort/lib/features/home/presentation/screens/home_screen.dart": [
            "err.toString()",
        ],
        "docsort/lib/features/cabinet/presentation/screens/cabinet_list_screen.dart": [
            "Failed to load cabinet: $err",
        ],
        "docsort/lib/features/cabinet/presentation/screens/cabinet_detail_screen.dart": [
            "Failed to load documents:\\n$error",
        ],
        "docsort/lib/features/upload/presentation/screens/review_screen.dart": [
            "Failed to save: $e",
            "Failed to load document\\n$e",
        ],
        "docsort/lib/features/upload/presentation/screens/result_screen.dart": [
            "Text('$e'",
        ],
        "docsort/lib/features/search/presentation/screens/search_screen.dart": [
            "Search failed: $err",
        ],
        "docsort/lib/features/scanner/screens/preview_screen.dart": [
            "Error: $e",
        ],
        "docsort/lib/features/admin/presentation/screens/bulk_review_screen.dart": [
            "Failed to process documents: $e",
        ],
        "docsort/lib/features/admin/presentation/screens/admin_screen.dart": [
            "_ErrorState(message: e.toString()",
        ],
        "docsort/lib/features/graph/providers/graph_provider.dart": [
            "error: e.toString()",
        ],
        "docsort/lib/features/upload/presentation/providers/upload_provider.dart": [
            "errorMessage: e.message ?? e.toString()",
            "errorMessage: e.toString()",
        ],
    }

    for relative, forbidden in forbidden_by_file.items():
        source = read(relative)
        for snippet in forbidden:
            assert snippet not in source, f"{relative} still exposes raw exception text: {snippet}"


def test_readme_describes_future_scaling_without_trivializing_it():
    readme = read("README.md")
    assert "is a small change" not in readme
    assert "point the queue at that function" not in readme
    assert "`pg_trgm` full-text index" not in readme
    assert "claim" in readme.lower()
    assert "retry" in readme.lower()
    assert "idempot" in readme.lower()
    assert "FTS" in readme or "full-text" in readme
    assert "trigram" in readme.lower()
