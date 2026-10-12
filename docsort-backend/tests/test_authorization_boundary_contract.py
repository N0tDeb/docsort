"""Route-level regressions for alternate-path document authorization bypasses."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import cabinet, upload


class FakeResult:
    def __init__(self, data):
        self.data = data


class RouteBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.or_expression = None
        self.limit_n = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def or_(self, expression):
        self.or_expression = expression
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.limit_n = value
        return self

    def execute(self):
        rows = list(self.db.tables.get(self.table, []))
        for column, value in self.filters:
            rows = [row for row in rows if str(row.get(column)) == str(value)]
        if self.or_expression and "is_private.eq.false" in self.or_expression:
            owner_id = self.or_expression.split("user_id.eq.", 1)[1]
            rows = [
                row
                for row in rows
                if not bool(row.get("is_private"))
                or str(row.get("user_id")) == str(owner_id)
            ]
        if self.limit_n is not None:
            rows = rows[: self.limit_n]
        self.db.executed.append((self.table, tuple(self.filters)))
        return FakeResult(rows)


class RouteSupabase:
    def __init__(self, *, documents=None, upload_jobs=None):
        self.tables = {
            "documents": documents or [],
            "upload_jobs": upload_jobs or [],
        }
        self.executed = []

    def table(self, name):
        return RouteBuilder(self, name)


CURRENT_DEPT_USER = {
    "id": "user-1",
    "role": "user",
    "department_id": "dept-b",
    "name": "Current User",
}


def test_department_user_cannot_read_historical_docs_through_synthetic_folder():
    sb = RouteSupabase(
        documents=[
            {
                "id": "historical-doc",
                "user_id": "user-1",
                "department_id": "dept-a",
                "doc_type": "Invoice",
                "is_private": False,
                "document_fields": [{"label": "Amount", "value": "100"}],
                "users": {"name": "Current User", "designation": "Analyst"},
            }
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            cabinet.list_folder_documents(
                "personal_Finance",
                supabase=sb,
                user=CURRENT_DEPT_USER,
            )
        )

    assert exc.value.status_code == 404
    assert not any(table == "documents" for table, _ in sb.executed)


def test_unassigned_user_can_still_read_own_docs_through_synthetic_folder():
    sb = RouteSupabase(
        documents=[
            {
                "id": "own-doc",
                "user_id": "user-1",
                "department_id": None,
                "doc_type": "Other",
                "is_private": True,
                "document_fields": [],
                "users": {"name": "Current User", "designation": ""},
            },
            {
                "id": "peer-doc",
                "user_id": "user-2",
                "department_id": None,
                "doc_type": "Other",
                "is_private": False,
                "document_fields": [],
                "users": {"name": "Peer", "designation": ""},
            },
        ]
    )
    user = {**CURRENT_DEPT_USER, "department_id": None}

    docs = asyncio.run(
        cabinet.list_folder_documents("unassigned", supabase=sb, user=user)
    )

    assert [doc["id"] for doc in docs] == ["own-doc"]


def test_upload_status_withholds_extraction_after_department_reassignment():
    sb = RouteSupabase(
        upload_jobs=[
            {
                "id": "job-1",
                "user_id": "user-1",
                "status": "done",
                "step": 5,
                "progress_pct": 1.0,
                "progress": 1.0,
                "document_id": "historical-doc",
                "error_message": None,
            }
        ],
        documents=[
            {
                "id": "historical-doc",
                "user_id": "user-1",
                "department_id": "dept-a",
                "is_private": False,
                "document_fields": [{"label": "Secret", "value": "Dept A"}],
            }
        ],
    )

    result = asyncio.run(
        upload.get_status("job-1", supabase=sb, user=CURRENT_DEPT_USER)
    )

    assert result["status"] == "done"
    assert result["document_id"] == "historical-doc"
    assert result["extracted_data"] is None
    document_queries = [
        filters for table, filters in sb.executed if table == "documents"
    ]
    assert ("department_id", "dept-b") in document_queries[-1]


def test_upload_status_still_embeds_currently_authorized_document():
    sb = RouteSupabase(
        upload_jobs=[
            {
                "id": "job-2",
                "user_id": "user-1",
                "status": "done",
                "step": 5,
                "progress_pct": 1.0,
                "progress": 1.0,
                "document_id": "current-doc",
                "error_message": None,
            }
        ],
        documents=[
            {
                "id": "current-doc",
                "user_id": "user-1",
                "department_id": "dept-b",
                "is_private": True,
                "document_fields": [{"label": "Amount", "value": "100"}],
            }
        ],
    )

    result = asyncio.run(
        upload.get_status("job-2", supabase=sb, user=CURRENT_DEPT_USER)
    )

    assert result["extracted_data"]["id"] == "current-doc"
