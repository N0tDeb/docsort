"""Regression tests for findings discovered during the project-wide CHANGE AUDIT."""
import asyncio
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import admin, cabinet
from app.api.admin import BulkReviewPayload


ROOT = Path(__file__).resolve().parents[1]


class Result:
    def __init__(self, data):
        self.data = data
        self.count = None


class Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.or_filter = None
        self.action = "select"
        self.body = None

    def select(self, *_args, **_kwargs):
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
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, {str(v) for v in values}))
        return self

    def or_(self, expression):
        self.or_filter = expression
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def range(self, *_args, **_kwargs):
        return self

    def execute(self):
        rows = [dict(row) for row in self.db.tables.get(self.table, [])]
        for op, column, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(column)) == str(value)]
            elif op == "in":
                rows = [r for r in rows if str(r.get(column)) in value]

        if self.or_filter:
            # The audit tests only need the standard document visibility OR.
            parts = self.or_filter.split(",")
            visible = []
            for row in rows:
                allowed = False
                for part in parts:
                    if part == "is_private.eq.false" and not bool(row.get("is_private")):
                        allowed = True
                    elif part.startswith("user_id.eq.") and str(row.get("user_id")) == part.split("user_id.eq.", 1)[1]:
                        allowed = True
                if allowed:
                    visible.append(row)
            rows = visible

        if self.action == "select":
            return Result(rows)

        ids = {row["id"] for row in rows if row.get("id")}
        if self.action == "update":
            updated = []
            for stored in self.db.tables.get(self.table, []):
                if stored.get("id") in ids:
                    stored.update(self.body)
                    updated.append(dict(stored))
            return Result(updated)

        if self.action == "delete":
            deleted = [dict(row) for row in self.db.tables.get(self.table, []) if row.get("id") in ids]
            self.db.tables[self.table] = [row for row in self.db.tables.get(self.table, []) if row.get("id") not in ids]
            return Result(deleted)

        raise AssertionError(self.action)


class StorageBucket:
    def __init__(self, db):
        self.db = db

    def remove(self, paths):
        self.db.removed_storage.extend(paths)
        return {"removed": list(paths)}


class Storage:
    def __init__(self, db):
        self.db = db

    def from_(self, bucket):
        assert bucket == "docsort"
        return StorageBucket(self.db)


class DB:
    def __init__(self):
        self.tables = {
            "documents": [
                {
                    "id": "own",
                    "user_id": "u1",
                    "department_id": "dept-a",
                    "folder_id": "review-a",
                    "doc_type": "Invoice",
                    "is_private": False,
                    "is_tampered": True,
                    "tamper_flags": ["flag"],
                    "document_fields": [],
                    "storage_path": "documents/dept-a/own.pdf",
                },
                {
                    "id": "peer",
                    "user_id": "u2",
                    "department_id": "dept-a",
                    "folder_id": "review-a",
                    "doc_type": "Invoice",
                    "is_private": False,
                    "is_tampered": True,
                    "tamper_flags": ["flag"],
                    "document_fields": [],
                    "storage_path": "documents/dept-a/peer.pdf",
                },
                {
                    "id": "other",
                    "user_id": "u3",
                    "department_id": "dept-b",
                    "folder_id": "review-a",  # deliberately malformed cross-dept folder link
                    "doc_type": "Invoice",
                    "is_private": False,
                    "is_tampered": True,
                    "tamper_flags": ["flag"],
                    "document_fields": [],
                },
            ],
            "folders": [
                {"id": "review-a", "department_id": "dept-a", "is_default_review": True},
            ],
        }
        self.removed_storage = []
        self.storage = Storage(self)

    def table(self, name):
        return Query(self, name)


USER_A = {"id": "u1", "role": "user", "department_id": "dept-a", "name": "User"}
ADMIN_A = {"id": "admin-a", "role": "admin", "department_id": "dept-a", "name": "Admin"}


def test_admin_tamper_resolution_cannot_mutate_other_department_document():
    db = DB()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin.resolve_tamper_flag("other", supabase=db, admin=ADMIN_A))

    assert exc.value.status_code == 404
    other = next(row for row in db.tables["documents"] if row["id"] == "other")
    assert other["is_tampered"] is True


def test_bulk_review_invalid_action_stays_400_not_500():
    db = DB()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin.bulk_review(
            BulkReviewPayload(document_ids=["own"], action="invalid"),
            supabase=db,
            admin=ADMIN_A,
        ))

    assert exc.value.status_code == 400


def test_bulk_reject_is_limited_to_admin_department():
    db = DB()

    result = asyncio.run(admin.bulk_review(
        BulkReviewPayload(document_ids=["peer", "other"], action="reject"),
        supabase=db,
        admin=ADMIN_A,
    ))

    remaining = {row["id"] for row in db.tables["documents"]}
    assert "peer" not in remaining
    assert "other" in remaining
    assert "1 documents" in result["message"]


def test_autosort_regular_user_cannot_refile_peer_documents(monkeypatch):
    db = DB()

    async def classify(**_kwargs):
        return "finance-a", 0.90

    monkeypatch.setattr(cabinet.autosort_service, "classify", classify)

    result = asyncio.run(cabinet.run_autosort(supabase=db, user=USER_A))

    own = next(row for row in db.tables["documents"] if row["id"] == "own")
    peer = next(row for row in db.tables["documents"] if row["id"] == "peer")
    other = next(row for row in db.tables["documents"] if row["id"] == "other")
    assert own["folder_id"] == "finance-a"
    assert peer["folder_id"] == "review-a"
    assert other["folder_id"] == "review-a"
    assert result["sorted"] == 1


def test_folder_listing_reapplies_department_scope_to_documents():
    db = DB()

    result = asyncio.run(cabinet.list_folder_documents(
        "review-a", supabase=db, user=ADMIN_A
    ))

    assert {row["id"] for row in result} == {"own", "peer"}


def test_authorized_document_delete_cleans_up_private_source_object():
    db = DB()

    result = asyncio.run(cabinet.delete_document("own", supabase=db, user=USER_A))

    assert result is None
    assert "own" not in {row["id"] for row in db.tables["documents"]}
    assert db.removed_storage == ["documents/dept-a/own.pdf"]


def test_bulk_reject_cleans_storage_only_for_in_scope_deleted_rows():
    db = DB()

    asyncio.run(admin.bulk_review(
        BulkReviewPayload(document_ids=["peer", "other"], action="reject"),
        supabase=db,
        admin=ADMIN_A,
    ))

    assert db.removed_storage == ["documents/dept-a/peer.pdf"]


def test_global_analytics_is_admin_only_and_flutter_members_use_department_stats():
    backend = (ROOT / "app/api/analytics.py").read_text(encoding="utf-8")
    flutter = (ROOT.parent / "docsort/lib/features/analytics/presentation/screens/analytics_screen.dart").read_text(encoding="utf-8")

    assert "user: dict = Depends(get_current_admin)" in backend
    assert re.search(
        r"authState\.isAdmin\s*\?\s*ref\.watch\(analyticsGlobalProvider\)\s*:\s*null",
        flutter,
    )
    assert "quickStatsAsync = globalAsync ?? deptAsync" in flutter


def test_login_checks_password_before_revealing_inactive_state():
    source = (ROOT / "app/api/auth.py").read_text(encoding="utf-8")
    verify_at = source.index("if not await run_blocking_io(verify_password")
    inactive_at = source.index('if user.get("is_active") is False')
    assert verify_at < inactive_at


def test_department_folder_mutations_are_admin_only():
    source = (ROOT / "app/api/cabinet.py").read_text(encoding="utf-8")
    assert source.count("Depends(get_current_admin)") >= 3
    assert "Administrator has no assigned department." in source


def test_schema_enforces_default_deny_rls_contract():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")

    assert "ALTER TABLE departments     ENABLE ROW LEVEL SECURITY" in schema
    assert 'DROP POLICY IF EXISTS "users_read_dept" ON users' in schema
    assert 'DROP POLICY IF EXISTS "docs_read_dept" ON documents' in schema
    assert 'DROP POLICY IF EXISTS "citizens_auth" ON citizens' in schema
    assert 'FOR SELECT USING (true)' not in schema
    assert "auth.role() = 'authenticated'" not in schema
    assert 'CREATE POLICY "users_read_dept"' not in schema
    assert 'CREATE POLICY "docs_read_dept"' not in schema
