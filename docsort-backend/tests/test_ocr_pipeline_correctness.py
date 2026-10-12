"""Regression tests for OCR-confidence, MIME, language, and multi-page handling."""
from __future__ import annotations

import asyncio
import json
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from app.services.ocr_service import OCRService


class FakeInteractions:
    def __init__(self, payload=None, *, error: Exception | None = None, raw_text: str | None = None):
        self.payload = payload
        self.error = error
        self.raw_text = raw_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        output_text = self.raw_text if self.raw_text is not None else json.dumps(self.payload)
        return SimpleNamespace(output_text=output_text)


class FakeGeminiClient:
    def __init__(self, payload=None, *, error: Exception | None = None, raw_text: str | None = None):
        self.interactions = FakeInteractions(payload, error=error, raw_text=raw_text)


def _jpeg_bytes():
    buf = BytesIO()
    Image.new("RGB", (16, 16), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _valid_payload(**overrides):
    payload = {
        "doc_type": "Invoice",
        "language": "English",
        "classification_confidence": 0.82,
        "tamper_flags": [],
        "suggested_folder": "Finance",
        "fields": [],
    }
    payload.update(overrides)
    return payload


def test_tesseract_word_confidence_language_hint_and_jpeg_mime(monkeypatch):
    client = FakeGeminiClient(_valid_payload())
    service = OCRService(gemini_client=client)
    seen = {}

    def fake_image_to_data(_image, *, lang, output_type):
        seen["lang"] = lang
        assert output_type is not None
        return {
            "text": ["Invoice", "123"],
            "conf": ["90", "80"],
            "page_num": [1, 1],
            "block_num": [1, 1],
            "par_num": [1, 1],
            "line_num": [1, 1],
        }

    monkeypatch.setattr("app.services.ocr_service.pytesseract.image_to_data", fake_image_to_data)
    result = asyncio.run(service.process_document(_jpeg_bytes(), "scan.jpg", "hin"))

    assert seen["lang"] == "hin"
    assert result["raw_text"] == "Invoice 123"
    assert result["ocr_confidence"] == 0.85
    assert result["classification_confidence"] == 0.82
    request_input = client.interactions.calls[0]["input"]
    image_part = next(part for part in request_input if part["type"] == "image")
    assert image_part["mime_type"] == "image/jpeg"
    assert image_part["data"]


def test_multi_page_pdf_sends_rendered_pages_and_combines_ocr(monkeypatch):
    client = FakeGeminiClient(_valid_payload(
        doc_type="Report",
        classification_confidence=0.9,
        suggested_folder="Reports",
    ))
    service = OCRService(gemini_client=client)
    monkeypatch.setattr(service, "_iter_pdf_image_pages", lambda _pdf: iter((b"page-one", b"page-two")))

    def fake_extract(page, language):
        assert language == "eng"
        return (("first page" if page == b"page-one" else "second page"), [0.9])

    monkeypatch.setattr(service, "_extract_page_ocr", fake_extract)
    result = asyncio.run(service.process_document(b"%PDF-fake", "report.pdf", "eng"))

    assert result["raw_text"] == "first page\n\nsecond page"
    assert result["ocr_confidence"] == 0.9
    request_input = client.interactions.calls[0]["input"]
    image_parts = [part for part in request_input if part["type"] == "image"]
    assert len(image_parts) == 2
    assert all(part["mime_type"] == "image/png" for part in image_parts)


def test_ai_confidence_alias_does_not_override_ocr_confidence(monkeypatch):
    client = FakeGeminiClient(_valid_payload(classification_confidence=None, confidence=0.99))
    del client.interactions.payload["classification_confidence"]
    service = OCRService(gemini_client=client)
    monkeypatch.setattr(service, "_extract_page_ocr", lambda *_args: ("text", [0.61, 0.79]))

    result = asyncio.run(service.process_document(_jpeg_bytes(), "scan.jpeg", "eng"))
    assert result["classification_confidence"] == 0.99
    assert result["ocr_confidence"] == 0.7
    assert "confidence" not in result


def test_parseable_non_object_ai_output_falls_back_to_needs_review(monkeypatch):
    service = OCRService(gemini_client=FakeGeminiClient([]))
    monkeypatch.setattr(service, "_extract_page_ocr", lambda *_args: ("invoice text", [0.88]))

    result = asyncio.run(
        service.process_document(_jpeg_bytes(), "scan.jpg", "eng", doc_type_hint="Invoice")
    )

    assert result["doc_type"] == "Invoice"
    assert result["language"] == "Unknown"
    assert result["classification_confidence"] == 0.0
    assert result["suggested_folder"] == "Needs Review"
    assert result["tamper_flags"] == []
    assert result["fields"] == []
    assert result["raw_text"] == "invoice text"
    assert result["ocr_confidence"] == 0.88


def test_wrong_shaped_ai_lists_fall_back_to_safe_extraction(monkeypatch):
    service = OCRService(gemini_client=FakeGeminiClient(_valid_payload(
        classification_confidence=0.91,
        tamper_flags=None,
        fields=None,
    )))
    monkeypatch.setattr(service, "_extract_page_ocr", lambda *_args: ("invoice text", [0.74]))

    result = asyncio.run(service.process_document(_jpeg_bytes(), "scan.jpg", "eng"))

    assert result["doc_type"] == "Unknown"
    assert result["language"] == "Unknown"
    assert result["classification_confidence"] == 0.0
    assert result["suggested_folder"] == "Needs Review"
    assert result["tamper_flags"] == []
    assert result["fields"] == []
    assert result["raw_text"] == "invoice text"
    assert result["ocr_confidence"] == 0.74


def test_wrong_shaped_ai_field_entry_falls_back_instead_of_leaking_downstream(monkeypatch):
    service = OCRService(gemini_client=FakeGeminiClient(_valid_payload(
        classification_confidence=0.91,
        fields=["not-a-field-object"],
    )))
    monkeypatch.setattr(service, "_extract_page_ocr", lambda *_args: ("invoice text", [0.8]))

    result = asyncio.run(service.process_document(_jpeg_bytes(), "scan.jpg", "eng"))

    assert result["suggested_folder"] == "Needs Review"
    assert result["fields"] == []
    assert result["classification_confidence"] == 0.0


def test_pdf_pages_are_rendered_and_ocrd_incrementally_with_bounded_ai_retention(monkeypatch):
    """Do not materialize every rendered PDF page before OCR begins."""
    client = FakeGeminiClient(_valid_payload(
        doc_type="Report",
        classification_confidence=0.9,
        suggested_folder="Reports",
    ))
    service = OCRService(gemini_client=client)
    events = []

    class FakePixmap:
        def __init__(self, index):
            self.index = index

        def tobytes(self, _format):
            return f"page-{self.index}".encode()

    class FakeRect:
        width = 100
        height = 100

    class FakePage:
        rect = FakeRect()

        def __init__(self, index):
            self.index = index

        def get_pixmap(self, *, dpi):
            assert dpi == 200
            events.append(f"render-{self.index}")
            return FakePixmap(self.index)

    class FakeDocument:
        page_count = 4

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __getitem__(self, index):
            return FakePage(index + 1)

    monkeypatch.setattr("app.services.ocr_service.fitz.open", lambda **_kwargs: FakeDocument())
    monkeypatch.setattr("app.services.ocr_service.settings.max_ai_pages", 2)

    def fake_extract(page_bytes, language):
        index = page_bytes.decode().split("-")[-1]
        events.append(f"ocr-{index}")
        assert language == "eng"
        return f"text-{index}", [0.9]

    monkeypatch.setattr(service, "_extract_page_ocr", fake_extract)

    result = asyncio.run(service.process_document(b"%PDF-fake", "report.pdf", "eng"))

    assert events == [
        "render-1", "ocr-1",
        "render-2", "ocr-2",
        "render-3", "ocr-3",
        "render-4", "ocr-4",
    ]
    assert result["raw_text"] == "text-1\n\ntext-2\n\ntext-3\n\ntext-4"

    request_input = client.interactions.calls[0]["input"]
    image_parts = [part for part in request_input if part["type"] == "image"]
    assert len(image_parts) == 2
