"""Regression tests for document deletion authorization and cascade safety."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import cabinet


class FakeResult:
    def __init__(self, data):
        self.data = data


class DeleteBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.action = "select"

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        assert self.action == "delete"
        assert self.table == "documents", "route must not delete child fields directly"

        matched = [
            row for row in self.db.documents
            if all(str(row.get(col)) == str(value) for col, value in self.filters)
        ]
        matched_ids = {row["id"] for row in matched}
        self.db.documents = [row for row in self.db.documents if row["id"] not in matched_ids]

        # Simulate schema.sql: document_fields.document_id REFERENCES documents(id)
        # ON DELETE CASCADE.
        self.db.fields = [
            row for row in self.db.fields if row["document_id"] not in matched_ids
        ]
        return FakeResult(matched)


class FakeSupabase:
    def __init__(self):
        self.documents = [
            {"id": "doc-own", "user_id": "u1", "department_id": "dept-a"},
            {"id": "doc-peer", "user_id": "u2", "department_id": "dept-a"},
            {"id": "doc-other-dept", "user_id": "u3", "department_id": "dept-b"},
        ]
        self.fields = [
            {"id": "f1", "document_id": "doc-own"},
            {"id": "f2", "document_id": "doc-peer"},
            {"id": "f3", "document_id": "doc-other-dept"},
        ]
        self.tables_requested = []

    def table(self, name):
        self.tables_requested.append(name)
        return DeleteBuilder(self, name)


def run_delete(sb, user, doc_id):
    return asyncio.run(cabinet.delete_document(doc_id=doc_id, supabase=sb, user=user))


def test_regular_user_cannot_delete_another_users_fields_or_document():
    sb = FakeSupabase()

    with pytest.raises(HTTPException) as exc:
        run_delete(sb, {"id": "u1", "role": "user", "department_id": "dept-a"}, "doc-peer")

    assert exc.value.status_code == 404
    assert any(row["id"] == "doc-peer" for row in sb.documents)
    assert any(row["document_id"] == "doc-peer" for row in sb.fields)
    assert sb.tables_requested == ["documents"]


def test_regular_user_can_delete_owned_document_and_fields_cascade():
    sb = FakeSupabase()

    result = run_delete(
        sb,
        {"id": "u1", "role": "user", "department_id": "dept-a"},
        "doc-own",
    )

    assert result is None
    assert all(row["id"] != "doc-own" for row in sb.documents)
    assert all(row["document_id"] != "doc-own" for row in sb.fields)
    assert sb.tables_requested == ["documents"]


def test_department_admin_cannot_delete_document_from_another_department():
    sb = FakeSupabase()

    with pytest.raises(HTTPException) as exc:
        run_delete(
            sb,
            {"id": "admin-a", "role": "admin", "department_id": "dept-a"},
            "doc-other-dept",
        )

    assert exc.value.status_code == 404
    assert any(row["id"] == "doc-other-dept" for row in sb.documents)
    assert any(row["document_id"] == "doc-other-dept" for row in sb.fields)


def test_department_admin_can_delete_peer_document_in_same_department():
    sb = FakeSupabase()

    run_delete(
        sb,
        {"id": "admin-a", "role": "admin", "department_id": "dept-a"},
        "doc-peer",
    )

    assert all(row["id"] != "doc-peer" for row in sb.documents)
    assert all(row["document_id"] != "doc-peer" for row in sb.fields)
