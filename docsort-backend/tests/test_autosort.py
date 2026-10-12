"""Auto-sort classification and confidence-threshold behavior."""
import asyncio
from app.services.autosort_service import AutoSortService

THRESHOLD = 0.75  # settings.autosort_confidence_threshold


def make_service():
    svc = AutoSortService()
    async def fake_folder(dept, name, sb): return f"folder::{name}"
    svc._get_or_create_folder = fake_folder
    return svc


def classify(doc_type, suggested, suggestion_confidence=None):
    svc = make_service()
    fid, conf = asyncio.run(svc.classify(
        doc_type=doc_type, fields=[], department_id="dept1",
        suggested_folder_name=suggested, suggestion_confidence=suggestion_confidence,
        supabase=object(),
    ))
    return fid, conf


def test_ai_suggestion_autofiles_only_with_real_confidence():
    fid, conf = classify("Invoice", "Finance", 0.88)
    assert conf == 0.88 and conf >= THRESHOLD
    assert fid == "folder::Finance"


def test_low_confidence_ai_suggestion_routes_to_review():
    fid, conf = classify("Invoice", "Finance", 0.42)
    assert conf == 0.42 and conf < THRESHOLD
    assert fid == "folder::Needs Review"


def test_missing_ai_confidence_does_not_invent_point_95():
    fid, conf = classify("Invoice", "Finance")
    assert conf == 0.90
    assert fid == "folder::Finance"


def test_explicit_needs_review_is_respected():
    fid, conf = classify("Invoice", "Needs Review", 0.40)
    assert conf == 0.40 and conf < THRESHOLD
    assert fid == "folder::Needs Review"


def test_keyword_fallback_autofiles_when_no_ai_folder_decision_exists():
    fid, conf = classify("Invoice", None)
    assert conf == 0.90 and conf >= THRESHOLD


def test_unknown_goes_to_review():
    fid, conf = classify("Totally Unknown Thing", "Needs Review")
    assert conf == 0.0 and conf < THRESHOLD
    assert fid == "folder::Needs Review"
