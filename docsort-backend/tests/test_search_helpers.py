"""Pure helper functions in the search module."""
from app.api.search import _highlight, _build_highlights


def test_highlight_wraps_case_insensitively():
    assert _highlight("Ramesh Kumar", "ramesh") == "^^Ramesh^^ Kumar"


def test_highlight_handles_empty():
    assert _highlight("", "x") == ""
    assert _highlight("abc", "") == "abc"


def test_build_highlights_across_fields():
    doc = {
        "doc_type": "Invoice",
        "filename": "invoice_vendor.pdf",
        "document_fields": [{"label": "Vendor", "value": "Invoice Vendor"}],
    }
    hits = _build_highlights(doc, "invoice")
    fields = {h["field"] for h in hits}
    assert {"Document Type", "Filename", "Vendor"} <= fields


def test_build_highlights_empty_when_no_match():
    doc = {"doc_type": "Resume", "filename": "x.pdf", "document_fields": []}
    assert _build_highlights(doc, "zzz") == []
