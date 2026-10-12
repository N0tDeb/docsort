"""Regression checks for the Google Gemini provider contract."""
from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.config import Settings
from app.services import ocr_service as ocr_module
from app.services.ocr_service import AIExtractionResult, OCRService

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "docsort-backend"
FLUTTER = ROOT / "docsort"


def _jpeg_bytes():
    buf = BytesIO()
    Image.new("RGB", (16, 16), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _payload(**overrides):
    value = {
        "doc_type": "Invoice",
        "language": "English",
        "classification_confidence": 0.91,
        "tamper_flags": ["Layout inconsistency for manual review"],
        "suggested_folder": "Finance",
        "fields": [
            {"label": "Invoice Number", "value": "INV-123", "confidence": 0.88},
            {"label": "Total Amount", "value": "100.00"},
        ],
    }
    value.update(overrides)
    return value


class FakeInteractions:
    def __init__(self, payload=None, *, raw_text=None, error=None):
        self.payload = payload
        self.raw_text = raw_text
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        output = self.raw_text if self.raw_text is not None else json.dumps(self.payload)
        return SimpleNamespace(output_text=output)


class FakeGeminiClient:
    def __init__(self, payload=None, *, raw_text=None, error=None):
        self.interactions = FakeInteractions(payload, raw_text=raw_text, error=error)


def _service(payload=None, *, raw_text=None, error=None):
    service = OCRService(gemini_client=FakeGeminiClient(payload or _payload(), raw_text=raw_text, error=error))
    return service


def _stub_ocr(monkeypatch, service, text="Invoice INV-123 total 100.00", confidence=0.86):
    monkeypatch.setattr(service, "_extract_page_ocr", lambda *_args: (text, [confidence]))


def test_gemini_settings_defaults_and_model_are_centralized():
    settings = Settings(
        _env_file=None,
        jwt_secret="test-secret-value-at-least-32-bytes-12345",
        supabase_url="https://example.supabase.co",
        supabase_service_key="service-key",
    )
    assert settings.gemini_api_key == ""
    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.max_ai_pages == 8
    assert settings.max_ai_ocr_chars == 20_000
    assert settings.autosort_confidence_threshold == 0.75


def test_gemini_client_initialization_uses_server_side_api_key(monkeypatch):
    created = []
    sentinel = object()

    def fake_client(*, api_key):
        created.append(api_key)
        return sentinel

    monkeypatch.setattr(ocr_module, "genai", SimpleNamespace(Client=fake_client))
    monkeypatch.setattr(ocr_module.settings, "gemini_api_key", "server-only-test-key")
    service = OCRService()

    assert service._get_gemini_client() is sentinel
    assert service._get_gemini_client() is sentinel
    assert created == ["server-only-test-key"]


def test_missing_gemini_key_degrades_to_needs_review(monkeypatch):
    monkeypatch.setattr(ocr_module.settings, "gemini_api_key", "")
    service = OCRService()
    _stub_ocr(monkeypatch, service)

    result = asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng", "Invoice"))

    assert result["doc_type"] == "Invoice"
    assert result["suggested_folder"] == "Needs Review"
    assert result["classification_confidence"] == 0.0
    assert result["raw_text"].startswith("Invoice")


def test_configured_gemini_model_is_used(monkeypatch):
    client = FakeGeminiClient(_payload())
    service = OCRService(gemini_client=client)
    _stub_ocr(monkeypatch, service)
    monkeypatch.setattr(ocr_module.settings, "gemini_model", "gemini-3.8-flash")

    asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    assert client.interactions.calls[0]["model"] == "gemini-3.8-flash"


def test_successful_structured_extraction_preserves_expected_contract(monkeypatch):
    client = FakeGeminiClient(_payload())
    service = OCRService(gemini_client=client)
    _stub_ocr(monkeypatch, service)

    result = asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    assert result["doc_type"] == "Invoice"
    assert result["language"] == "English"
    assert result["classification_confidence"] == 0.91
    assert result["suggested_folder"] == "Finance"
    assert result["tamper_flags"] == ["Layout inconsistency for manual review"]
    assert result["fields"][0] == {
        "label": "Invoice Number", "value": "INV-123", "confidence": 0.88
    }
    assert result["fields"][1]["confidence"] is None


def test_gemini_request_enforces_structured_json_schema(monkeypatch):
    client = FakeGeminiClient(_payload())
    service = OCRService(gemini_client=client)
    _stub_ocr(monkeypatch, service)

    asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    response_format = client.interactions.calls[0]["response_format"]
    assert response_format["type"] == "text"
    assert response_format["mime_type"] == "application/json"
    schema = response_format["schema"]
    assert set(("doc_type", "language", "classification_confidence", "tamper_flags", "suggested_folder", "fields")) <= set(schema["properties"])


def test_pydantic_validation_rejects_out_of_range_confidence():
    with pytest.raises(Exception):
        AIExtractionResult.model_validate(_payload(classification_confidence=1.5))


def test_malformed_json_falls_back_without_losing_ocr(monkeypatch):
    service = _service(raw_text="{definitely not json")
    _stub_ocr(monkeypatch, service, text="preserved OCR", confidence=0.77)

    result = asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    assert result["raw_text"] == "preserved OCR"
    assert result["ocr_confidence"] == 0.77
    assert result["suggested_folder"] == "Needs Review"


def test_schema_mismatch_falls_back(monkeypatch):
    service = _service({"doc_type": "Invoice"})
    _stub_ocr(monkeypatch, service)

    result = asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    assert result["classification_confidence"] == 0.0
    assert result["fields"] == []
    assert result["suggested_folder"] == "Needs Review"


@pytest.mark.parametrize("error", [TimeoutError("timeout"), ConnectionError("network"), RuntimeError("quota/rate limit")])
def test_gemini_api_failures_degrade_gracefully(monkeypatch, error):
    service = _service(error=error)
    _stub_ocr(monkeypatch, service, text="document survives", confidence=0.81)

    result = asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    assert result["raw_text"] == "document survives"
    assert result["ocr_confidence"] == 0.81
    assert result["suggested_folder"] == "Needs Review"
    assert result["classification_confidence"] == 0.0


def test_empty_gemini_response_degrades_gracefully(monkeypatch):
    service = _service(raw_text="")
    _stub_ocr(monkeypatch, service)

    result = asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    assert result["suggested_folder"] == "Needs Review"
    assert result["classification_confidence"] == 0.0


def test_ocr_text_is_included_in_ai_input(monkeypatch):
    client = FakeGeminiClient(_payload())
    service = OCRService(gemini_client=client)
    _stub_ocr(monkeypatch, service, text="UNIQUE OCR EVIDENCE")

    asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    text_part = next(part for part in client.interactions.calls[0]["input"] if part["type"] == "text")
    assert "UNIQUE OCR EVIDENCE" in text_part["text"]


def test_ocr_text_sent_to_gemini_is_bounded(monkeypatch):
    client = FakeGeminiClient(_payload())
    service = OCRService(gemini_client=client)
    monkeypatch.setattr(ocr_module.settings, "max_ai_ocr_chars", 10)
    _stub_ocr(monkeypatch, service, text="1234567890SHOULD_NOT_BE_SENT")

    asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    text_part = next(part for part in client.interactions.calls[0]["input"] if part["type"] == "text")
    assert "1234567890" in text_part["text"]
    assert "SHOULD_NOT_BE_SENT" not in text_part["text"]


def test_max_ai_pages_is_respected_while_all_pages_are_ocrd(monkeypatch):
    client = FakeGeminiClient(_payload(doc_type="Report", suggested_folder="Reports"))
    service = OCRService(gemini_client=client)
    pages = [f"page-{i}".encode() for i in range(5)]
    seen = []
    monkeypatch.setattr(service, "_iter_pdf_image_pages", lambda _pdf: iter(pages))
    monkeypatch.setattr(ocr_module.settings, "max_ai_pages", 2)

    def fake_ocr(page, _language):
        seen.append(page)
        return page.decode(), [0.9]

    monkeypatch.setattr(service, "_extract_page_ocr", fake_ocr)

    result = asyncio.run(service.process_document(b"pdf", "report.pdf", "eng"))

    assert seen == pages
    assert result["raw_text"] == "\n\n".join(p.decode() for p in pages)
    image_parts = [p for p in client.interactions.calls[0]["input"] if p["type"] == "image"]
    assert len(image_parts) == 2


def test_jpeg_and_pdf_images_use_correct_gemini_mime_types(monkeypatch):
    image_client = FakeGeminiClient(_payload())
    image_service = OCRService(gemini_client=image_client)
    _stub_ocr(monkeypatch, image_service)
    asyncio.run(image_service.process_document(_jpeg_bytes(), "scan.jpeg", "eng"))
    image_part = next(p for p in image_client.interactions.calls[0]["input"] if p["type"] == "image")
    assert image_part["mime_type"] == "image/jpeg"

    pdf_client = FakeGeminiClient(_payload(doc_type="Report", suggested_folder="Reports"))
    pdf_service = OCRService(gemini_client=pdf_client)
    monkeypatch.setattr(pdf_service, "_iter_pdf_image_pages", lambda _pdf: iter((b"rendered-png",)))
    monkeypatch.setattr(pdf_service, "_extract_page_ocr", lambda *_args: ("pdf text", [0.9]))
    asyncio.run(pdf_service.process_document(b"pdf", "report.pdf", "eng"))
    pdf_part = next(p for p in pdf_client.interactions.calls[0]["input"] if p["type"] == "image")
    assert pdf_part["mime_type"] == "image/png"


def test_request_does_not_send_api_key_or_uncontrolled_generation_parameters(monkeypatch):
    client = FakeGeminiClient(_payload())
    service = OCRService(gemini_client=client)
    _stub_ocr(monkeypatch, service)

    asyncio.run(service.process_document(_jpeg_bytes(), "invoice.jpg", "eng"))

    call = client.interactions.calls[0]
    assert set(call) == {"model", "input", "response_format"}
    assert "api_key" not in json.dumps(call).lower()


def test_provider_dependency_uses_google_genai_exclusively():
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    lines = requirements.splitlines()

    ai_heading = "# " + "\u2500" * 2 + " AI "
    security_heading = "# " + "\u2500" * 2 + " Security "

    ai_start = next(
        i for i, line in enumerate(lines)
        if line.startswith(ai_heading)
    )
    security_start = next(
        i
        for i, line in enumerate(lines[ai_start + 1 :], start=ai_start + 1)
        if line.startswith(security_heading)
    )

    packages = [
        line.strip()
        for line in lines[ai_start + 1 : security_start]
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert packages == ["google-genai>=2.24,<3.0"]

def test_environment_example_uses_gemini_configuration_only():
    env_example = (BACKEND / ".env.example").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=" in env_example
    assert "GEMINI_MODEL=gemini-3.8-flash" in env_example
    assert "MAX_AI_OCR_CHARS=20000" in env_example
    provider_key_lines = [
        line.strip()
        for line in env_example.splitlines()
        if line.strip().endswith("API_KEY=")
    ]
    assert provider_key_lines == ["GEMINI_API_KEY="]


def test_gemini_credentials_are_not_exposed_to_flutter():
    dart_source = "\n".join(path.read_text(encoding="utf-8") for path in (FLUTTER / "lib").rglob("*.dart"))
    assert "GEMINI_API_KEY" not in dart_source
    assert "gemini_api_key" not in dart_source.lower()
    assert "google.genai" not in dart_source.lower()


def test_backend_application_uses_google_genai_interactions_api():
    ocr_source = (BACKEND / "app/services/ocr_service.py").read_text(encoding="utf-8")
    assert "from google import genai" in ocr_source
    assert "genai.Client(api_key=settings.gemini_api_key)" in ocr_source
    assert ".interactions.create(" in ocr_source
