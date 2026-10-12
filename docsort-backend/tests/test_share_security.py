import asyncio
import hashlib

import pytest
from fastapi import HTTPException, Request, Response

from app.api import share
from app.schemas.share_schema import ShareLinkAccess, ShareLinkCreate
from app.services.share_service import ShareService


SOURCE_BYTES = b"share-source-bytes"
SOURCE_HASH = hashlib.sha256(SOURCE_BYTES).hexdigest()


class Result:
    def __init__(self, data):
        self.data = data


class Builder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.payload = None
        self.limit_value = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        if self.table == "documents":
            rows = list(self.db.documents)
            for column, value in self.filters:
                rows = [r for r in rows if str(r.get(column)) == str(value)]
            return Result(rows)
        if self.table == "shared_links" and self.payload is not None:
            self.db.inserted_link = self.payload
            return Result([{"id": "share-1", **self.payload}])
        if self.table == "shared_links":
            rows = list(self.db.links)
            for column, value in self.filters:
                rows = [r for r in rows if str(r.get(column)) == str(value)]
            return Result(rows[: self.limit_value or len(rows)])
        raise AssertionError(self.table)


class Bucket:
    def __init__(self, db):
        self.db = db

    def compute_sha256(self, path, *, chunk_size=64 * 1024):
        self.db.hash_calls.append(path)
        return SOURCE_HASH

    def create_signed_url(self, path, expires_in):
        self.db.signed_calls.append((path, expires_in))
        return {"signedURL": "https://signed.example/document"}


class Storage:
    def __init__(self, db):
        self.db = db

    def from_(self, bucket):
        assert bucket == "docsort"
        return Bucket(self.db)


class FakeDB:
    def __init__(self):
        self.documents = [
            {"id": "own", "filename": "own.pdf", "user_id": "u1", "department_id": "d1"},
            {"id": "peer", "filename": "peer.pdf", "user_id": "u2", "department_id": "d1"},
        ]
        self.links = []
        self.inserted_link = None
        self.signed_calls = []
        self.hash_calls = []
        self.storage = Storage(self)

    def table(self, name):
        return Builder(self, name)


USER = {"id": "u1", "role": "user", "department_id": "d1"}
ADMIN = {"id": "admin", "role": "admin", "department_id": "d1"}


def test_regular_user_can_share_only_owned_document(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(share, "get_supabase_sync", lambda: db)
    monkeypatch.setattr(share.activity_service, "log_share", lambda *a, **k: None)
    monkeypatch.setattr(
        share.share_service,
        "create_public_link",
        lambda **kwargs: {"share_id": "s", "token": "t", "expires_at": "2099-01-01T00:00:00+00:00"},
    )

    ok = asyncio.run(share.create_share_link(ShareLinkCreate(document_id="own"), user=USER))
    assert ok["url"] == "/share/access/t"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(share.create_share_link(ShareLinkCreate(document_id="peer"), user=USER))
    assert exc.value.status_code == 404


def test_department_admin_can_share_department_document(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(share, "get_supabase_sync", lambda: db)
    monkeypatch.setattr(share.activity_service, "log_share", lambda *a, **k: None)
    monkeypatch.setattr(
        share.share_service,
        "create_public_link",
        lambda **kwargs: {"share_id": "s", "token": "t", "expires_at": "2099-01-01T00:00:00+00:00"},
    )

    ok = asyncio.run(share.create_share_link(ShareLinkCreate(document_id="peer"), user=ADMIN))
    assert ok["share_id"] == "s"


def test_password_is_hashed_not_stored_plaintext(monkeypatch):
    db = FakeDB()
    service = ShareService()
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)

    service.create_public_link("own", "u1", password="secret12")

    stored = db.inserted_link["password"]
    assert stored != "secret12"
    assert stored.startswith("pbkdf2_sha256$")
    assert service._verify_password(stored, "secret12") is True
    assert service._verify_password(stored, "wrongpass") is False


def test_passwordless_public_access_returns_short_lived_signed_url(monkeypatch):
    db = FakeDB()
    db.links = [{
        "id": "s1",
        "token": "token",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "password": None,
        "is_active": True,
        "documents": {
            "id": "own",
            "filename": "own.pdf",
            "doc_type": "Invoice",
            "storage_path": "documents/d1/own.pdf",
            "file_hash": SOURCE_HASH,
        },
    }]
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)

    result = ShareService().access_public_link("token")

    assert result["download_url"] == "https://signed.example/document"
    assert result["document"] == {"id": "own", "filename": "own.pdf", "doc_type": "Invoice"}
    assert "storage_path" not in result["document"]
    assert db.signed_calls[0][0] == "documents/d1/own.pdf"
    assert 1 <= db.signed_calls[0][1] <= 900


def test_protected_link_requires_posted_password(monkeypatch):
    db = FakeDB()
    service = ShareService()
    hashed = service._hash_password("secret12")
    db.links = [{
        "id": "s1",
        "token": "protected",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "password": hashed,
        "is_active": True,
        "documents": {
            "id": "own",
            "filename": "own.pdf",
            "doc_type": "Invoice",
            "storage_path": "documents/d1/own.pdf",
            "file_hash": SOURCE_HASH,
        },
    }]
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)
    monkeypatch.setattr(share, "share_service", service)

    with pytest.raises(HTTPException) as missing:
        asyncio.run(share.access_shared_document("protected", Response()))
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as wrong:
        asyncio.run(
            share.access_password_protected_document(
                Request({"type": "http", "method": "POST", "path": "/share/access/protected", "headers": []}),
                "protected",
                ShareLinkAccess(password="wrongpass"),
                Response(),
            )
        )
    assert wrong.value.status_code == 401

    response = Response()
    ok = asyncio.run(
        share.access_password_protected_document(
            Request({"type": "http", "method": "POST", "path": "/share/access/protected", "headers": []}),
            "protected",
            ShareLinkAccess(password="secret12"),
            response,
        )
    )
    assert ok["download_url"].startswith("https://signed.example/")
    assert response.headers["cache-control"] == "no-store"


def test_expired_link_never_generates_signed_url(monkeypatch):
    db = FakeDB()
    db.links = [{
        "id": "expired",
        "token": "expired-token",
        "expires_at": "2000-01-01T00:00:00+00:00",
        "password": None,
        "is_active": True,
        "documents": {
            "id": "own",
            "filename": "own.pdf",
            "doc_type": "Invoice",
            "storage_path": "documents/d1/own.pdf",
            "file_hash": SOURCE_HASH,
        },
    }]
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)

    result = ShareService().access_public_link("expired-token")

    assert result is None
    assert db.signed_calls == []


def test_plaintext_password_record_fails_closed(monkeypatch):
    db = FakeDB()
    db.links = [{
        "id": "plaintext-record",
        "token": "plaintext-token",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "password": "plaintext-test-password",
        "is_active": True,
        "documents": {
            "id": "own",
            "filename": "own.pdf",
            "doc_type": "Invoice",
            "storage_path": "documents/d1/own.pdf",
            "file_hash": SOURCE_HASH,
        },
    }]
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)

    result = ShareService().access_public_link("plaintext-token", "plaintext-test-password")

    assert result == {"password_required": True}
    assert db.signed_calls == []


def test_passwordless_route_marks_signed_url_response_no_store(monkeypatch):
    monkeypatch.setattr(
        share.share_service,
        "access_public_link",
        lambda token, password=None: {
            "password_required": False,
            "document": {"id": "own", "filename": "own.pdf", "doc_type": "Invoice"},
            "expires_at": "2099-01-01T00:00:00+00:00",
            "download_url": "https://signed.example/document",
        },
    )
    response = Response()
    result = asyncio.run(share.access_shared_document("token", response))
    assert result["download_url"].startswith("https://signed.example/")
    assert response.headers["cache-control"] == "no-store"


def test_public_sharing_has_no_email_invite_endpoint():
    paths = {(route.path, tuple(sorted(route.methods or []))) for route in share.router.routes}
    assert not any(path == "/share/email" for path, _ in paths)
