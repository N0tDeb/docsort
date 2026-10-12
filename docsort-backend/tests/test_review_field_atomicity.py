"""Regression coverage for atomic manual-review field replacement."""
import asyncio
from pathlib import Path
import re

import pytest

from app.api import cabinet
from app.api.cabinet import FieldUpdateItem


SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")


class FakeResult:
    def __init__(self, data):
        self.data = data


class TableBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.action = "select"
        self.body = None

    def select(self, *args, **kwargs):
        self.action = "select"
        return self

    def delete(self):
        self.action = "delete"
        self.db.direct_field_mutations += int(self.table == "document_fields")
        return self

    def insert(self, body):
        self.action = "insert"
        self.body = body
        self.db.direct_field_mutations += int(self.table == "document_fields")
        return self

    def update(self, body):
        self.action = "update"
        self.body = body
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.table == "documents":
            rows = [
                row for row in self.db.documents
                if all(str(row.get(k)) == str(v) for k, v in self.filters)
            ]
            if self.action == "update":
                for row in rows:
                    row.update(self.body or {})
            return FakeResult([dict(row) for row in rows])
        if self.table == "document_fields":
            rows = [
                row for row in self.db.fields
                if all(str(row.get(k)) == str(v) for k, v in self.filters)
            ]
            return FakeResult([dict(row) for row in rows])
        raise AssertionError(f"Unexpected table: {self.table}")


class RpcBuilder:
    def __init__(self, db, function, params):
        self.db = db
        self.function = function
        self.params = params

    def execute(self):
        self.db.rpc_calls.append((self.function, self.params))
        if self.db.rpc_error:
            raise RuntimeError("simulated atomic replacement failure")
        self.db.fields = [
            {"document_id": self.params["p_document_id"], **field}
            for field in self.params["p_fields"]
        ]
        return FakeResult([dict(row) for row in self.db.fields])


class FakeSupabase:
    def __init__(self, *, rpc_error=False):
        self.documents = [{
            "id": "doc-1",
            "user_id": "u1",
            "department_id": "dept-a",
            "doc_type": "Invoice",
            "sort_confidence": 0.42,
        }]
        self.fields = [
            {"document_id": "doc-1", "label": "amount", "value": "100", "confidence": 0.8},
            {"document_id": "doc-1", "label": "system_suggested_folder", "value": "Finance", "confidence": 0.9},
        ]
        self.rpc_error = rpc_error
        self.rpc_calls = []
        self.direct_field_mutations = 0

    def table(self, name):
        return TableBuilder(self, name)

    def rpc(self, function, params=None):
        return RpcBuilder(self, function, params or {})


USER = {"id": "u1", "role": "user", "department_id": "dept-a", "name": "User"}


async def _no_sort(self, **kwargs):
    return None, 0.0


async def _review_reclassify(self, **kwargs):
    return "folder-finance", 0.99


def test_manual_review_uses_single_atomic_rpc_and_preserves_system_field(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr("app.services.autosort_service.AutoSortService.classify", _no_sort)

    result = asyncio.run(
        cabinet.update_document_fields(
            "doc-1",
            [FieldUpdateItem(label="amount", value="125")],
            supabase=sb,
            user=USER,
        )
    )

    assert result["status"] == "verified"
    assert "reviewed and verified" in result["message"].lower()
    assert sb.direct_field_mutations == 0
    assert len(sb.rpc_calls) == 1
    function, params = sb.rpc_calls[0]
    assert function == "replace_document_fields"
    assert params["p_document_id"] == "doc-1"
    assert params["p_fields"] == [
        {"label": "amount", "value": "125", "confidence": 1.0},
        {"label": "system_suggested_folder", "value": "Finance", "confidence": 1.0},
    ]
    assert sb.documents[0]["review_status"] == "verified"



def test_human_review_does_not_overwrite_original_auto_sort_confidence(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr("app.services.autosort_service.AutoSortService.classify", _review_reclassify)

    asyncio.run(
        cabinet.update_document_fields(
            "doc-1",
            [FieldUpdateItem(label="amount", value="125")],
            supabase=sb,
            user=USER,
        )
    )

    assert sb.documents[0]["folder_id"] == "folder-finance"
    assert sb.documents[0]["sort_confidence"] == 0.42

def test_atomic_rpc_failure_does_not_fall_back_to_destructive_direct_mutations(monkeypatch):
    sb = FakeSupabase(rpc_error=True)
    original_fields = [dict(row) for row in sb.fields]
    monkeypatch.setattr("app.services.autosort_service.AutoSortService.classify", _no_sort)

    with pytest.raises(RuntimeError, match="simulated atomic replacement failure"):
        asyncio.run(
            cabinet.update_document_fields(
                "doc-1",
                [FieldUpdateItem(label="amount", value="125")],
                supabase=sb,
                user=USER,
            )
        )

    assert sb.direct_field_mutations == 0
    assert sb.fields == original_fields


def test_schema_defines_atomic_replace_document_fields_function():
    match = re.search(
        r"CREATE OR REPLACE FUNCTION replace_document_fields\s*\((.*?)\)\s*"
        r"RETURNS SETOF document_fields(.*?)\$\$;",
        SCHEMA,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert match, "replace_document_fields RPC is missing from schema.sql"
    body = match.group(2)
    assert re.search(r"DELETE FROM document_fields\s+WHERE document_id\s*=\s*p_document_id", body, re.I)
    assert re.search(r"INSERT INTO document_fields", body, re.I)
    assert re.search(r"jsonb_array_elements\(p_fields\)", body, re.I)
