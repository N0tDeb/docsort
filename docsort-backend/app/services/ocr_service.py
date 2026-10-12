import base64
from statistics import mean
from io import BytesIO
from collections.abc import Iterator

import pytesseract
from PIL import Image
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

try:
    from google import genai
except ImportError:  # pragma: no cover - dependency is installed in supported environments
    genai = None

from app.core.config import settings
from app.utils.file_safety import media_type_for_filename
from app.utils.logger import logger

try:
    import pymupdf as fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

AI_PROMPT = """You are a document analysis system for organizational records.
Analyze all supplied document page images together with the raw Tesseract OCR text.
Return structured data that matches the supplied JSON schema.

Classification guidance:
- doc_type: Invoice | Receipt | Resume | Contract | Certificate | Application Form | Identity Document | Report | Other
- language: English | Hindi | Marathi | Other | Mixed
- classification_confidence: a number from 0.0 to 1.0 representing confidence in the document-type classification, not OCR accuracy and not human verification.
- suggested_folder: choose a concise professional category such as Finance, Human Resources, Legal, Certificates, Applications, Identity Documents, or Reports. You may choose another concise category when the document clearly belongs elsewhere. If uncertain, use Needs Review.
- fields: dynamically extract important fields actually present in the document using clear, human-readable labels.
- tamper_flags: review-oriented anomaly indicators only. Do not claim fraud, authenticity, or forensic proof. Use an empty list when there is no meaningful indicator.

Examples of useful fields include invoice number/vendor/date/total, receipt number/merchant/date/amount, candidate name/email/skills/experience, contract parties/effective date/expiry/agreement type, certificate holder/type/date/issuer, application name/number/date, identity holder/document number/date of birth/expiry, and report title/author/date/reference.

Use the OCR text as evidence, cross-check it against the supplied page images where helpful, and avoid inventing values that are not supported by the document."""


class AIExtractedField(BaseModel):
    """Validated field emitted by the optional AI extraction step."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    label: str = Field(min_length=1)
    value: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AIExtractionResult(BaseModel):
    """Stable internal contract for untrusted model output.

    Gemini structured output is constrained to this schema, and the returned
    JSON is validated again by Pydantic before it can reach AutoSort or storage.
    Any invalid response follows the conservative Needs Review fallback.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    doc_type: str = Field(min_length=1)
    language: str = Field(min_length=1)
    classification_confidence: float = Field(
        validation_alias=AliasChoices("classification_confidence", "confidence"),
        ge=0.0,
        le=1.0,
    )
    tamper_flags: list[str]
    suggested_folder: str = Field(min_length=1)
    fields: list[AIExtractedField]


class OCRService:

    def __init__(self, gemini_client=None):
        # Dependency injection keeps unit tests offline. Production creates the
        # official Google GenAI client lazily, so importing the app has no API
        # side effects and a missing key degrades through the normal review path.
        self._gemini_client = gemini_client

    def _get_gemini_client(self):
        if self._gemini_client is None:
            if not settings.gemini_api_key.strip():
                raise RuntimeError("GEMINI_API_KEY is not configured")
            if genai is None:
                raise RuntimeError("google-genai is not installed")
            self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
        return self._gemini_client

    def _iter_pdf_image_pages(self, pdf_bytes: bytes) -> Iterator[bytes]:
        """Render PDF pages one at a time so OCR does not retain every page image."""
        if not PYMUPDF_AVAILABLE:
            raise RuntimeError("PyMuPDF not installed — cannot process PDF")
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.page_count < 1:
                raise ValueError("PDF contains no pages")
            if doc.page_count > settings.max_pdf_pages:
                raise ValueError(f"PDF exceeds the {settings.max_pdf_pages}-page processing limit")
            scale = 200 / 72.0
            for index in range(doc.page_count):
                page = doc[index]
                estimated_pixels = int(page.rect.width * scale) * int(page.rect.height * scale)
                if estimated_pixels > settings.max_image_pixels:
                    raise ValueError("A PDF page exceeds the safe rendered-pixel limit")
                # Yield immediately. Once the caller has OCR'd this page, the
                # bytes can be released unless the page is inside MAX_AI_PAGES.
                yield page.get_pixmap(dpi=200).tobytes("png")

    @staticmethod
    def _ocr_text_from_data(data: dict) -> str:
        """Reconstruct readable line text from pytesseract ``Output.DICT``."""
        lines: list[str] = []
        current_key = None
        current_words: list[str] = []
        texts = data.get("text") or []

        def flush():
            nonlocal current_words
            if current_words:
                lines.append(" ".join(current_words))
                current_words = []

        for index, raw_word in enumerate(texts):
            word = str(raw_word or "").strip()
            if not word:
                continue
            key = tuple(
                (data.get(name) or [None] * len(texts))[index]
                for name in ("page_num", "block_num", "par_num", "line_num")
            )
            if current_key is not None and key != current_key:
                flush()
            current_key = key
            current_words.append(word)
        flush()
        return "\n".join(lines)

    def _extract_page_ocr(self, image_bytes: bytes, language_hint: str) -> tuple[str, list[float]]:
        """Return OCR text plus real normalized Tesseract word confidences."""
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                if image.width * image.height > settings.max_image_pixels:
                    raise ValueError("Image exceeds the safe pixel limit")
                data = pytesseract.image_to_data(
                    image,
                    lang=language_hint,
                    output_type=pytesseract.Output.DICT,
                )
            confidences: list[float] = []
            for raw_conf in data.get("conf") or []:
                try:
                    value = float(raw_conf)
                except (TypeError, ValueError):
                    continue
                if value >= 0:
                    confidences.append(max(0.0, min(1.0, value / 100.0)))
            return self._ocr_text_from_data(data), confidences
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("[ocr] Tesseract failed error_type=%s", type(exc).__name__)
            return "", []

    def _extract_raw_text(self, image_bytes: bytes, language_hint: str | None = None) -> str:
        """Compatibility helper returning text only for a single image."""
        text, _ = self._extract_page_ocr(
            image_bytes,
            (language_hint or settings.ocr_languages).strip() or settings.ocr_languages,
        )
        return text

    @staticmethod
    def _normalized_confidence(value) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _fallback_extraction(doc_type_hint: str) -> dict:
        return {
            "doc_type": doc_type_hint or "Unknown",
            "language": "Unknown",
            "classification_confidence": 0.0,
            "tamper_flags": [],
            "suggested_folder": "Needs Review",
            "fields": [],
        }

    def _gemini_input(self, raw_text: str, image_pages: list[bytes], page_mime: str) -> list[dict]:
        """Build the bounded multimodal request for Gemini Interactions API."""
        bounded_text = raw_text[: settings.max_ai_ocr_chars]
        content: list[dict] = [
            {
                "type": "text",
                "text": f"{AI_PROMPT}\n\nRaw OCR text:\n{bounded_text}",
            }
        ]
        for image_bytes in image_pages:
            content.append(
                {
                    "type": "image",
                    "mime_type": page_mime,
                    "data": base64.b64encode(image_bytes).decode("utf-8"),
                }
            )
        return content

    async def process_document(
        self,
        file_bytes: bytes,
        filename: str,
        language_hint: str = "mar+hin+eng",
        doc_type_hint: str = "",
    ) -> dict:
        language = (language_hint or settings.ocr_languages).strip() or settings.ocr_languages
        is_pdf = filename.lower().endswith(".pdf")
        if is_pdf:
            image_pages = self._iter_pdf_image_pages(file_bytes)
            page_mime = "image/png"
        else:
            image_pages = iter((file_bytes,))
            page_mime = media_type_for_filename(filename)

        raw_text_pages: list[str] = []
        word_confidences: list[float] = []
        ai_image_pages: list[bytes] = []
        for image_bytes in image_pages:
            # AI input is intentionally bounded while Tesseract still processes
            # every allowed page. Pages beyond this cap are released after OCR.
            if len(ai_image_pages) < settings.max_ai_pages:
                ai_image_pages.append(image_bytes)
            page_text, page_confidences = self._extract_page_ocr(image_bytes, language)
            if page_text:
                raw_text_pages.append(page_text)
            word_confidences.extend(page_confidences)

        raw_text = "\n\n".join(raw_text_pages)
        ocr_confidence = round(mean(word_confidences), 4) if word_confidences else None

        try:
            interaction = self._get_gemini_client().interactions.create(
                model=settings.gemini_model,
                input=self._gemini_input(raw_text, ai_image_pages, page_mime),
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": AIExtractionResult.model_json_schema(),
                },
            )
            content = (getattr(interaction, "output_text", None) or "").strip()
            if not content:
                raise ValueError("Gemini returned an empty response")

            # Structured output constrains the remote response, but the model is
            # still an external trust boundary. Validate the returned JSON again
            # with Pydantic before anything reaches AutoSort or persistence.
            extracted = AIExtractionResult.model_validate_json(content).model_dump()
        except Exception as exc:
            if isinstance(exc, ValidationError):
                # ValidationError text can echo model-provided field values, which
                # may contain document-sensitive data. Log only structural detail.
                logger.error(
                    "[ocr] Gemini extraction rejected invalid shape (%s validation errors)",
                    exc.error_count(),
                )
            else:
                # Do not log API keys, OCR text, document images, or returned data.
                logger.error("[ocr] Gemini extraction failed error_type=%s", type(exc).__name__)
            extracted = self._fallback_extraction(doc_type_hint)

        # Keep confidence normalization as a final defensive boundary for callers
        # and for the conservative fallback object above.
        classification_confidence = self._normalized_confidence(
            extracted.get("classification_confidence")
        )
        extracted["classification_confidence"] = classification_confidence
        extracted["ocr_confidence"] = ocr_confidence
        extracted["raw_text"] = raw_text
        return extracted
