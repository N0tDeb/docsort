"""Regression checks for the domain-neutral product contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "docsort-backend"
FLUTTER = ROOT / "docsort"


def test_ai_prompt_uses_generic_document_taxonomy():
    text = (BACKEND / "app/services/ocr_service.py").read_text(encoding="utf-8")
    assert "organizational records" in text
    for doc_type in [
        "Invoice", "Receipt", "Resume", "Contract", "Certificate",
        "Application Form", "Identity Document", "Report",
    ]:
        assert doc_type in text


def test_sample_departments_are_generic():
    schema = (BACKEND / "schema.sql").read_text(encoding="utf-8")
    for code, name in [
        ("FIN", "Finance"),
        ("HR", "Human Resources"),
        ("LEGAL", "Legal"),
        ("ADMIN", "Administration"),
        ("RECORDS", "Records"),
    ]:
        assert f"('{code}', '{name}'" in schema


def test_flutter_visible_examples_are_generic():
    upload = (FLUTTER / "lib/features/upload/presentation/screens/upload_screen.dart").read_text(encoding="utf-8")
    for doc_type in ["Invoice", "Receipt", "Resume", "Contract", "Certificate"]:
        assert f"_buildChip('{doc_type}')" in upload
    home = (FLUTTER / "lib/features/home/presentation/screens/home_screen.dart").read_text(encoding="utf-8")
    assert "Member Dashboard" in home

    graph = (FLUTTER / "lib/features/graph/presentation/screens/graph_screen.dart").read_text(encoding="utf-8")
    assert "People & Document Map" in graph
    assert "Experimental identity-linking view" in graph
    assert "No linked people yet" in graph


def test_readme_describes_domain_neutral_product():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "domain-neutral" in readme
    assert "A DocSort deployment represents one organization" in readme
