"""Regression checks for the optional People & Document Map contract."""
import asyncio
from pathlib import Path

from app.services import relationship_service as relationships

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "docsort-backend"
FLUTTER = ROOT / "docsort"


def test_relationship_service_only_targets_generic_person_centric_documents():
    assert relationships._is_person_centric_document("Identity Document")
    assert relationships._is_person_centric_document("Resume")
    assert relationships._is_person_centric_document("Certificate")
    assert relationships._is_person_centric_document("Application Form")
    assert not relationships._is_person_centric_document("Invoice")
    assert not relationships._is_person_centric_document("Receipt")
    assert not relationships._is_person_centric_document("Report")


def test_generic_person_field_extraction():
    name, dob, identifier = relationships._extract_person_identity(
        "Identity Document",
        [
            {"label": "Holder Name", "value": "Asha Rao"},
            {"label": "Date of Birth", "value": "2001-03-04"},
            {"label": "Document Number", "value": "ID-2048"},
        ],
    )
    assert (name, dob, identifier) == ("Asha Rao", "2001-03-04", "ID-2048")

    name, _, identifier = relationships._extract_person_identity(
        "Resume",
        [{"label": "Candidate Name", "value": "Mira Shah"}],
    )
    assert name == "Mira Shah"
    assert identifier is None


def test_unsupported_document_does_not_create_people(monkeypatch):
    async def should_not_run(*args, **kwargs):
        raise AssertionError("unsupported document type must not touch people graph")

    monkeypatch.setattr(relationships, "_find_or_create_citizen", should_not_run)
    result = asyncio.run(
        relationships.process_relationships(
            db=object(),
            document_id="doc-1",
            dept_id="dept-1",
            doc_type="Invoice",
            extracted_fields=[{"label": "Vendor Name", "value": "ACME"}],
        )
    )
    assert result["people_linked"] == 0
    assert result["duplicate_found"] is False


def test_supported_document_links_person_without_inventing_relationships(monkeypatch):
    calls = []

    async def fake_find(db, dept_id, name, dob, document_id, uid_number=None):
        calls.append((dept_id, name, dob, document_id, uid_number))
        return "person-1"

    async def no_duplicate(*args, **kwargs):
        return None

    monkeypatch.setattr(relationships, "_find_or_create_citizen", fake_find)
    monkeypatch.setattr(relationships, "_check_duplicate", no_duplicate)

    result = asyncio.run(
        relationships.process_relationships(
            db=object(),
            document_id="doc-2",
            dept_id="dept-1",
            doc_type="Resume",
            extracted_fields=[{"label": "Candidate Name", "value": "Mira Shah"}],
        )
    )

    assert calls == [("dept-1", "Mira Shah", None, "doc-2", None)]
    assert result["people_linked"] == 1
    assert result["citizens_created"] == 1  # API compatibility field
    assert result["edges_created"] == 0


def test_relationship_service_declares_experimental_people_linking():
    text = (BACKEND / "app/services/relationship_service.py").read_text(encoding="utf-8").lower()
    assert "experimental people/document linking" in text
    assert "person-centric documents" in text


def test_people_map_is_visibly_experimental_and_domain_neutral():
    screen = (FLUTTER / "lib/features/graph/presentation/screens/graph_screen.dart").read_text(encoding="utf-8")
    home = (FLUTTER / "lib/features/home/presentation/screens/home_screen.dart").read_text(encoding="utf-8")
    detail = (FLUTTER / "lib/features/graph/presentation/widgets/citizen_detail_sheet.dart").read_text(encoding="utf-8")
    guard = (FLUTTER / "lib/core/router/auth_route_guard.dart").read_text(encoding="utf-8")

    assert "People & Document Map" in screen
    assert "Experimental identity-linking view" in screen
    assert "Potential Identity Matches" in screen
    assert "No linked people yet" in screen
    assert "People Map β" in home
    assert "if (authState.isAdmin)" in home
    assert "location == '/admin'" in guard
    assert "location == '/graph'" in guard
    assert "Identifier:" in detail

def test_graph_ocr_confidence_remains_normalized_in_flutter():
    models = (FLUTTER / "lib/features/graph/domain/graph_models.dart").read_text(encoding="utf-8")
    painter = (FLUTTER / "lib/features/graph/presentation/widgets/graph_painter.dart").read_text(encoding="utf-8")
    detail = (FLUTTER / "lib/features/graph/presentation/widgets/citizen_detail_sheet.dart").read_text(encoding="utf-8")

    assert "final double confidence;" in models
    assert ".toDouble() ?? 0.0" in models
    assert "confidence >= 0.85" in models
    assert "conf >= 0.85" in painter
    assert "confidence >= 0.85" in detail
    assert "confidence * 100" in detail
