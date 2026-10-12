"""Filename, upload-type, and export safety helpers.

User-supplied filenames cross several trust boundaries: multipart upload, object
storage URLs, ZIP members, CSV exports, and HTTP response headers.  Keep the
normalization rules in one place so those boundaries cannot drift apart.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import quote
from io import BytesIO
import re
import unicodedata

from PIL import Image, UnidentifiedImageError


_ALLOWED_UPLOADS = {
    ".pdf": ("application/pdf", lambda data: data.startswith(b"%PDF-")),
    ".png": ("image/png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    ".jpg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
    ".jpeg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
}

_DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _basename(value: str | None) -> str:
    # PurePosixPath alone does not treat a Windows backslash as a separator on
    # Linux, so normalize separators first.
    normalized = unicodedata.normalize("NFKC", (value or "")).replace("\\", "/")
    return PurePosixPath(normalized).name


def sanitize_filename(value: str | None, fallback: str = "document") -> str:
    """Return a safe basename suitable for Storage and ZIP members.

    The result never contains path separators, control characters, dot-segments,
    or header metacharacters. Unicode letters/digits are kept so legitimate
    non-English filenames remain readable.
    """
    name = _CONTROL_RE.sub("", _basename(value)).strip()
    if not name or name in {".", ".."}:
        name = fallback

    cleaned_chars: list[str] = []
    for char in name:
        if char.isalnum() or char in {" ", ".", "_", "-", "(", ")", "[", "]"}:
            cleaned_chars.append(char)
        else:
            cleaned_chars.append("_")

    cleaned = "".join(cleaned_chars).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback

    # Keep object names comfortably below common filesystem/header limits while
    # preserving the extension where possible.
    if len(cleaned) > 180:
        suffix = PurePosixPath(cleaned).suffix[:20]
        stem_limit = max(1, 180 - len(suffix))
        cleaned = cleaned[:stem_limit].rstrip(" .") + suffix
    return cleaned


def validate_upload(filename: str | None, data: bytes) -> tuple[str, str]:
    """Validate an uploaded source and return ``(safe_filename, media_type)``.

    Validation uses both the declared filename extension and a small magic-byte
    signature so direct API callers cannot bypass the Flutter file picker.
    """
    original = _basename(filename)
    suffix = PurePosixPath(original).suffix.lower()
    rule = _ALLOWED_UPLOADS.get(suffix)
    if rule is None:
        raise ValueError("Unsupported file type. Upload PDF, PNG, JPG, or JPEG files only.")

    media_type, signature_matches = rule
    if not signature_matches(data):
        raise ValueError("File contents do not match the filename type.")

    safe_name = sanitize_filename(original, fallback=f"document{suffix}")
    # Sanitization can only alter the stem for a validated upload; nevertheless
    # retain the validated suffix if an unusual filename normalized it away.
    if PurePosixPath(safe_name).suffix.lower() != suffix:
        safe_name = f"{PurePosixPath(safe_name).stem or 'document'}{suffix}"
    return safe_name, media_type



def validate_document_structure(
    filename: str,
    data: bytes,
    *,
    max_pdf_pages: int,
    max_image_pixels: int,
    pdf_dpi: int = 200,
) -> None:
    """Reject malformed or resource-amplifying PDF/image uploads early.

    Magic bytes alone only prove a prefix. This function opens the document with
    the same parser family used later and enforces bounded page/pixel dimensions
    before a background job is queued.
    """
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".pdf":
        try:
            import pymupdf as fitz
            with fitz.open(stream=data, filetype="pdf") as doc:
                if doc.page_count < 1:
                    raise ValueError("PDF contains no pages.")
                if doc.page_count > max_pdf_pages:
                    raise ValueError(f"PDF exceeds the {max_pdf_pages}-page processing limit.")
                scale = pdf_dpi / 72.0
                for page in doc:
                    estimated_pixels = int(page.rect.width * scale) * int(page.rect.height * scale)
                    if estimated_pixels > max_image_pixels:
                        raise ValueError("A PDF page exceeds the safe rendered-pixel limit.")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Invalid or unreadable PDF.") from exc
        return

    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError("Image has invalid dimensions.")
            if width * height > max_image_pixels:
                raise ValueError("Image exceeds the safe pixel limit.")
            image.verify()
    except ValueError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Image exceeds the safe pixel limit.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Invalid or unreadable image.") from exc

def media_type_for_filename(filename: str) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    return _ALLOWED_UPLOADS.get(suffix, ("application/octet-stream", None))[0]


def csv_safe(value):
    """Neutralize spreadsheet-formula prefixes in exported CSV text."""
    if value is None:
        return ""
    text = str(value)
    stripped = text.lstrip()
    if stripped.startswith(_DANGEROUS_CSV_PREFIXES):
        return "'" + text
    return text


def content_disposition(filename: str) -> str:
    """Build a safe attachment header with ASCII and UTF-8 filename forms."""
    safe = sanitize_filename(filename)
    ascii_name = safe.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._()\- ]", "_", ascii_name).strip(" .") or "download"
    encoded = quote(safe, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'
