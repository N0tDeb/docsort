"""Keyword-map fallback classification (autosort)."""
import asyncio
import pytest
from app.services.autosort_service import AutoSortService, fallback_folder_for_doc_type


def classify(doc_type):
    svc = AutoSortService()
    async def fake_folder(dept, name, sb): return f"folder::{name}"
    svc._get_or_create_folder = fake_folder
    # No AI folder decision: exercise the deterministic keyword fallback.
    return asyncio.run(svc.classify(
        doc_type=doc_type, fields=[], department_id="d1",
        suggested_folder_name=None, supabase=object(),
    ))


@pytest.mark.parametrize("doc_type,folder", [
    ("Invoice",              "Finance"),
    ("Purchase Order",       "Finance"),
    ("Resume",               "Human Resources"),
    ("Employment Contract",  "Human Resources"),
    ("Contract",             "Legal"),
    ("Certificate",          "Certificates"),
    ("Application Form",     "Applications"),
    ("Identity Document",    "Identity Documents"),
    ("Annual Report",        "Reports"),
])
def test_keyword_map_routes_correctly(doc_type, folder):
    fid, conf = classify(doc_type)
    assert fid == f"folder::{folder}"
    assert conf == 0.90


def test_unknown_type_goes_to_review():
    fid, conf = classify("Some Unknown Paper")
    assert conf == 0.50


def test_fallback_helper_handles_realistic_type_phrases():
    assert fallback_folder_for_doc_type("Vendor Tax Invoice") == ("Finance", 0.90)
    assert fallback_folder_for_doc_type("Candidate Resume") == ("Human Resources", 0.90)
    assert fallback_folder_for_doc_type("Service Agreement") == ("Legal", 0.90)
    assert fallback_folder_for_doc_type("Unknown Scan") == ("Needs Review", 0.50)
