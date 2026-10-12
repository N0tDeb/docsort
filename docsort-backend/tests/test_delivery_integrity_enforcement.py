"""Delivery paths must verify stored SHA-256 baselines before releasing source bytes."""

import asyncio
import hashlib
from io import BytesIO

import pytest
from fastapi import HTTPException

from app.api import export
from app.services.share_service import ShareService


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []

    def select(self, *_args, **_kwargs): return self
    def eq(self, column, value): self.filters.append((column, value)); return self
    def or_(self, *_args, **_kwargs): return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, *_args, **_kwargs): return self

    def execute(self):
        if self.table == "folders":
            return _Result([{"id": "folder-1", "name": "Finance"}])
        if self.table == "documents":
            rows = list(self.db.documents)
            for column, value in self.filters:
                rows = [r for r in rows if str(r.get(column)) == str(value)]
            return _Result(rows)
        if self.table == "shared_links":
            rows = list(self.db.links)
            for column, value in self.filters:
                rows = [r for r in rows if str(r.get(column)) == str(value)]
            return _Result(rows)
        raise AssertionError(self.table)


class _Bucket:
    def __init__(self, db):
        self.db = db

    def download(self, path):
        return self.db.payloads[path]

    def download_to_file(self, path, sink, *, chunk_size=64 * 1024):
        payload = self.db.payloads[path]
        sink.write(payload)
        return len(payload)

    def compute_sha256(self, path, *, chunk_size=64 * 1024):
        self.db.hash_calls.append(path)
        return hashlib.sha256(self.db.payloads[path]).hexdigest()

    def create_signed_url(self, path, expires_in):
        self.db.signed_calls.append((path, expires_in))
        return {"signedURL": "https://signed.example/document"}


class _Storage:
    def __init__(self, db): self.db = db
    def from_(self, bucket):
        assert bucket == "docsort"
        return _Bucket(self.db)


class _DB:
    def __init__(self, *, stored_payload=b"trusted", actual_payload=b"tampered"):
        path = "documents/dept-1/report.pdf"
        self.documents = [{
            "id": "doc-1",
            "filename": "report.pdf",
            "storage_path": path,
            "file_hash": hashlib.sha256(stored_payload).hexdigest(),
            "user_id": "user-1",
            "department_id": "dept-1",
            "folder_id": "folder-1",
            "is_private": False,
            "doc_type": "Report",
            "created_at": "2026-01-01T00:00:00Z",
            "is_tampered": False,
            "ocr_confidence": 0.9,
            "document_fields": [],
            "users": {"name": "User"},
        }]
        self.payloads = {path: actual_payload}
        self.links = [{
            "id": "share-1",
            "token": "public-token",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "password": None,
            "is_active": True,
            "documents": {
                "id": "doc-1",
                "filename": "report.pdf",
                "doc_type": "Report",
                "storage_path": path,
                "file_hash": self.documents[0]["file_hash"],
            },
        }]
        self.hash_calls = []
        self.signed_calls = []
        self.storage = _Storage(self)

    def table(self, name): return _Query(self, name)


USER = {"id": "user-1", "role": "user", "department_id": "dept-1"}


async def _body(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks)


def test_single_export_rejects_source_hash_mismatch_before_response():
    db = _DB()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(export.export_single_document("doc-1", supabase=db, user=USER))
    assert exc_info.value.status_code == 409
    assert "integrity" in exc_info.value.detail.lower()


def test_folder_export_fails_closed_when_any_source_hash_mismatches():
    db = _DB()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(export.export_folder("folder-1", "zip", db, USER))
    assert exc_info.value.status_code == 409
    assert "integrity" in exc_info.value.detail.lower()


def test_public_share_never_signs_mismatched_source(monkeypatch):
    db = _DB()
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)

    result = ShareService().access_public_link("public-token")

    assert result is None
    assert db.hash_calls == ["documents/dept-1/report.pdf"]
    assert db.signed_calls == []


def test_matching_hash_still_allows_export_and_share(monkeypatch):
    payload = b"trusted"
    db = _DB(stored_payload=payload, actual_payload=payload)
    response = asyncio.run(export.export_single_document("doc-1", supabase=db, user=USER))
    assert asyncio.run(_body(response)) == payload

    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)
    result = ShareService().access_public_link("public-token")
    assert result["download_url"] == "https://signed.example/document"
    assert db.hash_calls == ["documents/dept-1/report.pdf"]


def test_missing_integrity_baseline_fails_closed_for_export_and_share(monkeypatch):
    payload = b"trusted"
    db = _DB(stored_payload=payload, actual_payload=payload)
    db.documents[0]["file_hash"] = None
    db.links[0]["documents"]["file_hash"] = None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(export.export_single_document("doc-1", supabase=db, user=USER))
    assert exc_info.value.status_code == 409

    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)
    assert ShareService().access_public_link("public-token") is None
    assert db.signed_calls == []
