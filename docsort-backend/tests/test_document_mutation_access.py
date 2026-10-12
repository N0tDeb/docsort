"""Regression tests for document mutation authorization in cabinet routes."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import cabinet
from app.api.cabinet import DocumentReviewUpdate, FieldUpdateItem


class FakeResult:
    def __init__(self, data):
        self.data = data


class MutationBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.action = "select"
        self.body = None

    def select(self, *args, **kwargs):
        self.action = "select"
        return self

    def update(self, body):
        self.action = "update"
        self.body = body
        return self

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.table == "documents":
            rows = [
                row for row in self.db.documents
                if all(str(row.get(col)) == str(value) for col, value in self.filters)
            ]
            if self.action == "select":
                return FakeResult([dict(row) for row in rows])
            if self.action == "update":
                for row in rows:
                    row.update(self.body)
                return FakeResult([dict(row) for row in rows])
            if self.action == "delete":
                ids = {row["id"] for row in rows}
                self.db.documents = [row for row in self.db.documents if row["id"] not in ids]
                return FakeResult([dict(row) for row in rows])

        if self.table == "folders":
            rows = [
                row for row in self.db.folders
                if all(str(row.get(col)) == str(value) for col, value in self.filters)
            ]
            return FakeResult([dict(row) for row in rows])

        if self.table == "document_fields":
            # These operations must never be reached in the unauthorized field test.
            self.db.field_operations += 1
            return FakeResult([])

        raise AssertionError(f"unexpected table/action: {self.table}/{self.action}")


class FakeSupabase:
    def __init__(self):
        self.documents = [
            {
                "id": "own",
                "user_id": "u1",
                "department_id": "dept-a",
                "doc_type": "Invoice",
                "folder_id": "folder-a",
            },
            {
                "id": "peer",
                "user_id": "u2",
                "department_id": "dept-a",
                "doc_type": "Invoice",
                "folder_id": "folder-a",
            },
            {
                "id": "other-dept",
                "user_id": "u3",
                "department_id": "dept-b",
                "doc_type": "Invoice",
                "folder_id": "folder-b",
            },
        ]
        self.folders = [
            {"id": "folder-a", "department_id": "dept-a"},
            {"id": "folder-a-2", "department_id": "dept-a"},
            {"id": "folder-b", "department_id": "dept-b"},
        ]
        self.field_operations = 0

    def table(self, name):
        return MutationBuilder(self, name)


USER = {"id": "u1", "role": "user", "department_id": "dept-a", "name": "User"}
ADMIN_A = {"id": "admin-a", "role": "admin", "department_id": "dept-a", "name": "Admin"}


def test_regular_user_cannot_move_peer_document(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr(cabinet.activity_service, "log", lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            cabinet.move_document(
                "peer", "folder-a-2", supabase=sb, user=USER
            )
        )

    assert exc.value.status_code == 404
    assert next(row for row in sb.documents if row["id"] == "peer")["folder_id"] == "folder-a"


def test_owner_can_move_own_document_within_department(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr(cabinet.activity_service, "log", lambda *args, **kwargs: None)

    result = asyncio.run(
        cabinet.move_document("own", "folder-a-2", supabase=sb, user=USER)
    )

    assert result["folder_id"] == "folder-a-2"
    assert next(row for row in sb.documents if row["id"] == "own")["folder_id"] == "folder-a-2"


def test_department_admin_can_move_peer_document_in_same_department(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr(cabinet.activity_service, "log", lambda *args, **kwargs: None)

    result = asyncio.run(
        cabinet.move_document("peer", "folder-a-2", supabase=sb, user=ADMIN_A)
    )

    assert result["folder_id"] == "folder-a-2"


def test_department_admin_cannot_update_document_in_other_department():
    sb = FakeSupabase()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            cabinet.update_document(
                "other-dept",
                DocumentReviewUpdate(doc_type="Contract"),
                supabase=sb,
                user=ADMIN_A,
            )
        )

    assert exc.value.status_code == 404
    assert next(row for row in sb.documents if row["id"] == "other-dept")["doc_type"] == "Invoice"


def test_owner_can_update_own_document_metadata():
    sb = FakeSupabase()

    result = asyncio.run(
        cabinet.update_document(
            "own",
            DocumentReviewUpdate(doc_type="Contract", is_private=True),
            supabase=sb,
            user=USER,
        )
    )

    assert result["doc_type"] == "Contract"
    assert result["is_private"] is True


def test_regular_user_cannot_replace_peer_document_fields():
    sb = FakeSupabase()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            cabinet.update_document_fields(
                "peer",
                [FieldUpdateItem(label="amount", value="100")],
                supabase=sb,
                user=USER,
            )
        )

    assert exc.value.status_code == 404
    assert sb.field_operations == 0
