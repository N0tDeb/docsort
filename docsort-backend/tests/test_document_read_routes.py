"""Regression tests for document privacy on read/export/share routes."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import cabinet, export, share
from app.schemas.share_schema import ShareLinkCreate


class FakeResult:
    def __init__(self, data):
        self.data = data


class ReadBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.privacy_or = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def or_(self, expression):
        self.privacy_or = expression
        return self

    def execute(self):
        assert self.table == "documents"
        rows = list(self.db.documents)
        for column, value in self.filters:
            rows = [row for row in rows if str(row.get(column)) == str(value)]

        if self.privacy_or:
            # The shared policy emits: is_private.eq.false,user_id.eq.<caller>.
            owner_id = self.privacy_or.split("user_id.eq.", 1)[1]
            rows = [
                row for row in rows
                if not bool(row.get("is_private")) or str(row.get("user_id")) == owner_id
            ]
        return FakeResult(rows)


class FakeStorageBucket:
    def __init__(self, db):
        self.db = db

    def download_to_file(self, path, sink, *, chunk_size=64 * 1024):
        self.db.downloads.append(path)
        sink.write(b"file-bytes")
        return len(b"file-bytes")


class FakeStorage:
    def __init__(self, db):
        self.db = db

    def from_(self, bucket):
        assert bucket == "docsort"
        return FakeStorageBucket(self.db)


class FakeSupabase:
    def __init__(self):
        self.documents = [
            {
                "id": "public-peer",
                "filename": "public.pdf",
                "storage_path": "documents/dept-a/public.pdf",
                "user_id": "u2",
                "department_id": "dept-a",
                "is_private": False,
                "document_fields": [],
            },
            {
                "id": "private-peer",
                "filename": "private.pdf",
                "storage_path": "documents/dept-a/private.pdf",
                "user_id": "u2",
                "department_id": "dept-a",
                "is_private": True,
                "document_fields": [],
            },
            {
                "id": "private-own",
                "filename": "mine.pdf",
                "storage_path": "documents/dept-a/mine.pdf",
                "user_id": "u1",
                "department_id": "dept-a",
                "is_private": True,
                "document_fields": [],
            },
        ]
        self.downloads = []
        self.storage = FakeStorage(self)

    def table(self, name):
        return ReadBuilder(self, name)


USER = {"id": "u1", "role": "user", "department_id": "dept-a", "name": "User"}


def test_document_detail_hides_peer_private_document():
    sb = FakeSupabase()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(cabinet.get_document("private-peer", supabase=sb, user=USER))

    assert exc.value.status_code == 404


def test_document_detail_allows_own_private_document():
    sb = FakeSupabase()

    doc = asyncio.run(cabinet.get_document("private-own", supabase=sb, user=USER))

    assert doc["id"] == "private-own"


def test_single_export_does_not_download_peer_private_document():
    sb = FakeSupabase()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(export.export_single_document("private-peer", supabase=sb, user=USER))

    assert exc.value.status_code == 404
    assert sb.downloads == []


def test_share_link_cannot_be_created_for_peer_private_document(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr(share, "get_supabase_sync", lambda: sb)

    def must_not_share(**kwargs):
        raise AssertionError("share service must not run for an unshareable document")

    monkeypatch.setattr(share.share_service, "create_public_link", must_not_share)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            share.create_share_link(
                ShareLinkCreate(document_id="private-peer"),
                user=USER,
            )
        )

    assert exc.value.status_code == 404
