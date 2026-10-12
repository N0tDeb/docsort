"""Contract coverage for the explicit human-review workflow and truthful UX labels."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "docsort-backend"
FLUTTER = ROOT / "docsort"


def test_documents_schema_has_review_status_and_upgrade_path():
    schema = (BACKEND / "schema.sql").read_text(encoding="utf-8")
    assert "review_status" in schema
    assert "DEFAULT 'needs_review'" in schema
    assert "review_status IN ('needs_review', 'verified')" in schema
    assert re.search(r"ALTER TABLE documents\s+ADD COLUMN IF NOT EXISTS review_status", schema, re.I)


def test_new_uploads_start_needing_human_review():
    upload = (BACKEND / "app/api/upload.py").read_text(encoding="utf-8")
    assert '"review_status":   "needs_review"' in upload


def test_human_and_admin_review_mark_documents_verified():
    cabinet = (BACKEND / "app/api/cabinet.py").read_text(encoding="utf-8")
    admin = (BACKEND / "app/api/admin.py").read_text(encoding="utf-8")
    assert 'update_payload = {"review_status": "verified"}' in cabinet
    assert admin.count('"review_status": "verified"') >= 2


def test_flutter_review_and_result_do_not_claim_ai_equals_verified():
    review = (FLUTTER / "lib/features/upload/presentation/screens/review_screen.dart").read_text(encoding="utf-8")
    result = (FLUTTER / "lib/features/upload/presentation/screens/result_screen.dart").read_text(encoding="utf-8")
    assert "Document Verified" not in review
    assert "Document Verified" not in result
    assert "Needs Review" in review
    assert "Human review completed." in result
    assert "Review & Verify" in result
    assert "documentDetailProvider" in result
    assert "dio.get('/cabinet/documents/$docId')" in result


def test_review_screen_allows_classification_correction_before_verification():
    review = (FLUTTER / "lib/features/upload/presentation/screens/review_screen.dart").read_text(encoding="utf-8")
    assert "_docTypeController" in review
    assert "Correct the AI classification if needed before verifying." in review
    assert "data: {'doc_type': reviewedDocType}" in review
    assert "OCR $pct%" in review


def test_processing_screen_steps_match_backend_and_failure_is_retryable():
    processing = (FLUTTER / "lib/features/upload/presentation/screens/processing_screen.dart").read_text(encoding="utf-8")
    provider = (FLUTTER / "lib/features/upload/presentation/providers/upload_provider.dart").read_text(encoding="utf-8")
    for label in [
        "Integrity & Duplicate Check",
        "Secure File Storage",
        "OCR & AI Extraction",
        "Anomaly Check",
        "Classification & Filing",
    ]:
        assert label in processing
    assert "Retry Processing" in processing
    assert "Back to Upload" in processing
    assert "sourceFilePath" in provider
    assert "context.go('/upload');" not in processing.split("if (next.status == UploadStatus.error)")[1].split("}", 1)[0]


def test_search_and_cabinet_label_ocr_confidence_truthfully():
    search = (FLUTTER / "lib/features/search/presentation/screens/search_screen.dart").read_text(encoding="utf-8")
    provider = (FLUTTER / "lib/features/search/presentation/providers/search_provider.dart").read_text(encoding="utf-8")
    cabinet = (FLUTTER / "lib/features/cabinet/presentation/screens/cabinet_detail_screen.dart").read_text(encoding="utf-8")
    assert "% Match" not in search
    assert "OCR ${" in search
    assert "ocrConfidence" in provider
    assert "reviewStatus" in provider
    assert "OCR ${(confidence * 100).toInt()}%" in cabinet
    assert "Needs Review" in cabinet


def test_confidence_views_use_runtime_values_and_truthful_metric_labels():
    result = (FLUTTER / "lib/features/upload/presentation/screens/result_screen.dart").read_text(encoding="utf-8")
    cabinet = (FLUTTER / "lib/features/cabinet/presentation/screens/cabinet_detail_screen.dart").read_text(encoding="utf-8")
    analytics = (FLUTTER / "lib/features/analytics/presentation/screens/analytics_screen.dart").read_text(encoding="utf-8")
    assert "ocr_confidence" in result
    assert "ocr_confidence" in cabinet
    assert "avg_ocr_confidence" in analytics
    assert "Auto-sort Accuracy" not in analytics
    assert "High-confidence Auto-sort Rate" in analytics
