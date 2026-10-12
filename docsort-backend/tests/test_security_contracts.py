"""Regression tests for the final independent security/correctness audit."""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
import struct
import zipfile
import zlib

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from starlette.requests import Request
import pymupdf as fitz

from app.api import export, upload
from app.core.database import _StorageBucket
from app.schemas.auth_schema import SignupRequest
from app.utils.file_safety import content_disposition, csv_safe, sanitize_filename, validate_document_structure, validate_upload




def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/upload",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })


def _valid_pdf_bytes(page_count: int = 1) -> bytes:
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), f"Page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def _oversized_png_header(width: int = 20_000, height: int = 20_000) -> bytes:
    """Build a tiny PNG whose declared dimensions trigger Pillow's bomb guard."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


class Result:
    def __init__(self, data=None):
        self.data = data or []


def test_upload_filename_and_type_validation_blocks_path_and_content_spoofing():
    safe, media_type = validate_upload("../../outside/payload.pdf", b"%PDF-1.7\n")
    assert safe == "payload.pdf"
    assert media_type == "application/pdf"
    assert "/" not in safe and "\\" not in safe and ".." not in safe

    with pytest.raises(ValueError, match="Unsupported file type"):
        validate_upload("payload.exe", b"MZ...")
    with pytest.raises(ValueError, match="do not match"):
        validate_upload("payload.pdf", b"not-a-pdf")


def test_document_structure_rejects_pdf_page_count_over_limit():
    with pytest.raises(ValueError, match="processing limit"):
        validate_document_structure(
            "many-pages.pdf", _valid_pdf_bytes(page_count=2),
            max_pdf_pages=1, max_image_pixels=10_000_000,
        )


def test_document_structure_normalizes_pillow_decompression_bomb():
    with pytest.raises(ValueError, match="safe pixel limit"):
        validate_document_structure(
            "bomb.png", _oversized_png_header(),
            max_pdf_pages=1, max_image_pixels=40_000_000,
        )


def test_storage_object_urls_reject_dot_segments_and_encode_user_characters():
    bucket = _StorageBucket("https://example.supabase.co", "docsort", {})
    with pytest.raises(ValueError, match="Invalid storage object path"):
        bucket._object_url("documents/dept/job/../../outside.pdf")

    url = bucket._object_url("documents/dept/job/My résumé (1).pdf")
    assert ".." not in url
    assert "My%20r%C3%A9sum%C3%A9%20%281%29.pdf" in url


def test_csv_and_content_disposition_are_safe_for_untrusted_text():
    assert csv_safe("=CMD()") == "'=CMD()"
    assert csv_safe("  +2+2") == "'  +2+2"
    assert csv_safe("normal") == "normal"

    header = content_disposition('../../evil"\r\nX-Test: injected.pdf')
    assert "\r" not in header and "\n" not in header
    assert "../" not in header and "\\" not in header
    assert "filename*=UTF-8''" in header


def test_signup_password_has_minimum_and_bcrypt_byte_limit():
    with pytest.raises(ValueError):
        SignupRequest(email="user@example.com", password="short")
    with pytest.raises(ValueError):
        SignupRequest(email="user@example.com", password="é" * 40)  # 80 UTF-8 bytes

    valid = SignupRequest(email="user@example.com", password="correct-horse")
    assert valid.password == "correct-horse"


class UploadBuilder:
    def __init__(self, db):
        self.db = db
        self.payload = None

    def insert(self, payload):
        self.payload = dict(payload)
        return self

    def execute(self):
        self.db.inserted = dict(self.payload)
        return Result([{"id": "job-1", **self.payload}])


class UploadDB:
    def __init__(self):
        self.inserted = None

    def table(self, name):
        assert name == "upload_jobs"
        return UploadBuilder(self)


def test_upload_endpoint_persists_and_processes_only_sanitized_filename():
    db = UploadDB()
    tasks = BackgroundTasks()
    source = UploadFile(filename="../../finance/invoice.pdf", file=BytesIO(_valid_pdf_bytes()))

    result = asyncio.run(upload.upload_document(
        request=_request(),
        background_tasks=tasks,
        file=source,
        language_hint="eng",
        doc_type_hint="Invoice",
        supabase=db,
        user={"id": "user-1", "department_id": "dept-1"},
    ))

    assert result["filename"] == "invoice.pdf"
    assert db.inserted["filename"] == "invoice.pdf"
    assert len(tasks.tasks) == 1
    assert "invoice.pdf" in tasks.tasks[0].args
    assert "../../finance/invoice.pdf" not in tasks.tasks[0].args


def test_upload_endpoint_supports_user_without_department():
    db = UploadDB()
    tasks = BackgroundTasks()
    source = UploadFile(filename="personal.pdf", file=BytesIO(_valid_pdf_bytes()))

    result = asyncio.run(upload.upload_document(
        request=_request(),
        background_tasks=tasks,
        file=source,
        language_hint="eng",
        doc_type_hint="Report",
        supabase=db,
        user={"id": "user-1", "department_id": None},
    ))

    assert result["filename"] == "personal.pdf"
    assert "department_id" not in db.inserted
    assert tasks.tasks[0].args[2] is None


def test_upload_endpoint_rejects_unsupported_type_before_database_write():
    db = UploadDB()
    tasks = BackgroundTasks()
    source = UploadFile(filename="malware.exe", file=BytesIO(b"MZ..."))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(upload.upload_document(
            request=_request(),
        background_tasks=tasks,
            file=source,
            language_hint=None,
            doc_type_hint="",
            supabase=db,
            user={"id": "user-1", "department_id": "dept-1"},
        ))

    assert exc_info.value.status_code == 400
    assert db.inserted is None
    assert tasks.tasks == []


def test_upload_endpoint_rejects_pillow_decompression_bomb_before_database_write():
    db = UploadDB()
    tasks = BackgroundTasks()
    source = UploadFile(filename="bomb.png", file=BytesIO(_oversized_png_header()))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(upload.upload_document(
            request=_request(),
            background_tasks=tasks,
            file=source,
            language_hint=None,
            doc_type_hint="",
            supabase=db,
            user={"id": "user-1", "department_id": "dept-1"},
        ))

    assert exc_info.value.status_code == 400
    assert "safe pixel limit" in exc_info.value.detail
    assert db.inserted is None
    assert tasks.tasks == []


class ExportBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table

    def select(self, *_args, **_kwargs): return self
    def eq(self, *_args, **_kwargs): return self
    def or_(self, *_args, **_kwargs): return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, *_args, **_kwargs): return self

    def execute(self):
        if self.table == "folders":
            return Result([{"id": "folder-1", "name": '../../unsafe"name'}])
        if self.table == "documents":
            rows = []
            for document in self.db.documents:
                row = dict(document)
                path = row.get("storage_path")
                if path and path not in self.db.download_errors:
                    payload = self.db.downloads.get(path, b"document-bytes")
                    row.setdefault("file_hash", hashlib.sha256(payload).hexdigest())
                rows.append(row)
            return Result(rows)
        raise AssertionError(self.table)


class ExportBucket:
    def __init__(self, db):
        self.db = db

    def download(self, path):
        if path in self.db.download_errors:
            raise FileNotFoundError(path)
        return self.db.downloads.get(path, b"document-bytes")


class ExportStorage:
    def __init__(self, db):
        self.db = db

    def from_(self, bucket):
        assert bucket == "docsort"
        return ExportBucket(self.db)


class ExportDB:
    def __init__(self):
        self.download_errors = set()
        self.downloads = {}
        self.storage = ExportStorage(self)
        self.documents = [{
            "id": "doc-1",
            "department_id": "dept-1",
            "filename": "../../outside/payload.txt",
            "storage_path": "documents/dept-1/job-1/payload.txt",
            "doc_type": "=CMD()",
            "created_at": "2026-01-01T00:00:00Z",
            "is_tampered": False,
            "ocr_confidence": 0.8,
            "users": {"name": "+attacker"},
            "document_fields": [{"label": "Amount", "value": "=2+2"}],
        }]

    def table(self, name):
        return ExportBuilder(self, name)


async def _response_bytes(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
    return b"".join(chunks)


def test_folder_export_prevents_zip_traversal_header_injection_and_csv_formulas():
    user = {"id": "admin-1", "department_id": "dept-1", "role": "admin"}
    db = ExportDB()

    zip_response = asyncio.run(export.export_folder("folder-1", "zip", db, user))
    archive = zipfile.ZipFile(BytesIO(asyncio.run(_response_bytes(zip_response))))
    names = archive.namelist()
    assert names == ["metadata.csv", "payload.txt"]
    assert all(".." not in name and not name.startswith(("/", "\\")) for name in names)
    metadata = archive.read("metadata.csv").decode()
    assert "'=CMD()" in metadata
    assert "'+attacker" in metadata
    assert "\r\nX-" not in zip_response.headers["content-disposition"]

    csv_response = asyncio.run(export.export_folder("folder-1", "csv", db, user))
    csv_body = asyncio.run(_response_bytes(csv_response)).decode()
    assert "'=CMD()" in csv_body
    assert "'=2+2" in csv_body
    assert "\r\nX-" not in csv_response.headers["content-disposition"]


def test_folder_export_rejects_cumulative_source_bytes(monkeypatch):
    user = {"id": "admin-1", "department_id": "dept-1", "role": "admin"}
    db = ExportDB()
    first_path = db.documents[0]["storage_path"]
    db.downloads[first_path] = b"1234"
    db.documents.append({
        "id": "doc-2",
        "department_id": "dept-1",
        "filename": "second.pdf",
        "storage_path": "documents/dept-1/job-2/second.pdf",
        "doc_type": "Report",
        "created_at": "2026-01-02T00:00:00Z",
        "is_tampered": False,
        "ocr_confidence": 0.9,
        "users": {"name": "reviewer"},
        "document_fields": [],
    })
    db.downloads["documents/dept-1/job-2/second.pdf"] = b"5678"
    # Each source object is individually below the limit, but the folder total is not.
    monkeypatch.setattr(export.settings, "max_folder_export_bytes", 7)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(export.export_folder("folder-1", "zip", db, user))

    assert exc_info.value.status_code == 413
    assert "source-byte limit" in str(exc_info.value.detail)


def test_folder_export_fails_explicitly_instead_of_returning_partial_archive():
    user = {"id": "admin-1", "department_id": "dept-1", "role": "admin"}
    db = ExportDB()
    db.documents.append({
        "id": "doc-2",
        "department_id": "dept-1",
        "filename": "missing.pdf",
        "storage_path": "documents/dept-1/job-2/missing.pdf",
        "doc_type": "Report",
        "created_at": "2026-01-02T00:00:00Z",
        "is_tampered": False,
        "ocr_confidence": 0.9,
        "users": {"name": "reviewer"},
        "document_fields": [],
    })
    db.download_errors.add("documents/dept-1/job-2/missing.pdf")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(export.export_folder("folder-1", "zip", db, user))

    assert exc_info.value.status_code == 502
    assert "No partial archive was returned" in str(exc_info.value.detail)


def test_folder_export_treats_missing_storage_path_as_incomplete():
    user = {"id": "admin-1", "department_id": "dept-1", "role": "admin"}
    db = ExportDB()
    db.documents[0]["storage_path"] = None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(export.export_folder("folder-1", "zip", db, user))

    assert exc_info.value.status_code == 502

class CabinetBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.or_expression = None

    def select(self, *_args, **_kwargs): return self
    def eq(self, column, value):
        self.filters.append((column, value))
        return self
    def or_(self, expression):
        self.or_expression = expression
        return self
    def order(self, *_args, **_kwargs): return self

    def execute(self):
        if self.table == "folders":
            return Result([{"id": "folder-1", "department_id": "dept-1", "name": "Finance"}])
        if self.table == "documents":
            self.db.document_visibility_expression = self.or_expression
            # Simulate PostgREST applying: public department docs OR caller-owned
            # private docs. A private peer document must not affect the count.
            visible = [
                doc for doc in self.db.documents
                if (not doc["is_private"]) or doc["user_id"] == "user-1"
            ]
            return Result([{"folder_id": doc["folder_id"]} for doc in visible])
        raise AssertionError(self.table)


class CabinetDB:
    def __init__(self):
        self.document_visibility_expression = None
        self.documents = [
            {"folder_id": "folder-1", "user_id": "user-2", "is_private": False},
            {"folder_id": "folder-1", "user_id": "user-1", "is_private": True},
            {"folder_id": "folder-1", "user_id": "user-2", "is_private": True},
        ]

    def table(self, name):
        return CabinetBuilder(self, name)


def test_folder_counts_follow_document_read_visibility():
    from app.api import cabinet

    db = CabinetDB()
    result = asyncio.run(cabinet.list_folders(
        supabase=db,
        user={"id": "user-1", "department_id": "dept-1", "role": "user"},
    ))

    assert result[0]["document_count"] == 2
    assert db.document_visibility_expression == "is_private.eq.false,user_id.eq.user-1"
