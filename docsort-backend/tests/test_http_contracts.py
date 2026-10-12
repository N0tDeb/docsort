"""FastAPI HTTP-contract regressions for security-sensitive public routes.

Most backend tests call route functions directly against fakes. These tests go
through TestClient so request parsing, dependency injection, middleware,
response serialization, path matching, and HTTP status behavior are exercised
together. Database behavior is still fake-backed; real Supabase/PostgreSQL
integration belongs in a separate environment-backed layer.
"""
from __future__ import annotations

from collections.abc import Iterator
import struct
import zlib

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.api import share
from app.core.database import get_supabase
from app.core.security import get_current_user


class Result:
    def __init__(self, data):
        self.data = data


class Builder:
    def __init__(self, db: "FakeSupabase", table: str):
        self.db = db
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.privacy_or: str | None = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def or_(self, expression):
        self.privacy_or = expression
        return self

    def execute(self):
        rows = list(self.db.rows.get(self.table, []))
        for column, value in self.filters:
            rows = [row for row in rows if str(row.get(column)) == str(value)]

        if self.table == "documents" and self.privacy_or:
            owner_id = self.privacy_or.split("user_id.eq.", 1)[1]
            rows = [
                row
                for row in rows
                if not bool(row.get("is_private"))
                or str(row.get("user_id")) == str(owner_id)
            ]
        return Result(rows)


class FakeSupabase:
    def __init__(self, *, jobs=None, documents=None):
        self.rows = {
            "upload_jobs": list(jobs or []),
            "documents": list(documents or []),
        }
        self.table_calls: list[str] = []

    def table(self, name):
        self.table_calls.append(name)
        return Builder(self, name)


ASSIGNED_USER = {
    "id": "user-1",
    "email": "user@example.com",
    "role": "user",
    "department_id": "dept-new",
    "name": "User One",
    "designation": "Reviewer",
}


def _oversized_png_header(width: int = 20_000, height: int = 20_000) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


@pytest.fixture
def client() -> Iterator[TestClient]:
    main.app.dependency_overrides.clear()
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def _override_user(user: dict) -> None:
    async def current_user_override():
        return user

    main.app.dependency_overrides[get_current_user] = current_user_override


def _override_supabase(db: FakeSupabase) -> None:
    async def supabase_override():
        return db

    main.app.dependency_overrides[get_supabase] = supabase_override


def test_health_contract_runs_through_http_stack(client):
    response = client.get(
        "/",
        headers={
            "X-Request-ID": "http-contract-1",
            "Origin": "http://localhost:3000",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "http-contract-1"
    assert response.headers["access-control-expose-headers"] == "X-Request-ID"
    assert response.json() == {"status": "ok", "service": "DocSort API v1.0.0"}


def test_auth_me_serializes_live_dependency_state(client):
    _override_user(ASSIGNED_USER)

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": "user-1",
        "email": "user@example.com",
        "role": "user",
        "department_id": "dept-new",
        "name": "User One",
        "designation": "Reviewer",
    }


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/auth/me", {}),
        ("GET", "/cabinet/documents", {}),
        ("GET", "/search?q=invoice", {}),
        ("GET", "/upload/status/job-1", {}),
        ("GET", "/export/document/doc-1", {}),
        ("POST", "/share/link", {"json": {"document_id": "doc-1"}}),
        ("GET", "/admin/users", {}),
    ],
)
def test_protected_http_surfaces_reject_invalid_bearer_token(client, method, path, kwargs):
    response = client.request(
        method,
        path,
        headers={"Authorization": "Bearer definitely-not-a-jwt"},
        **kwargs,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


def test_non_admin_cannot_access_people_map_through_http(client):
    _override_user(ASSIGNED_USER)
    _override_supabase(FakeSupabase())

    response = client.get("/graph/department")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Admin access required for this action."
    }



def test_assigned_user_cannot_reach_synthetic_folder_through_http(client):
    db = FakeSupabase()
    _override_user(ASSIGNED_USER)
    _override_supabase(db)

    response = client.get("/cabinet/personal_Invoices/documents")

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found."}
    assert db.table_calls == []


def test_upload_decompression_bomb_is_controlled_http_400(client):
    db = FakeSupabase()
    _override_user(ASSIGNED_USER)
    _override_supabase(db)

    response = client.post(
        "/upload",
        files={"file": ("bomb.png", _oversized_png_header(), "image/png")},
    )

    assert response.status_code == 400
    assert "safe pixel limit" in response.json()["detail"]
    assert db.table_calls == []


def test_upload_status_reauthorizes_embedded_document_through_http(client):
    db = FakeSupabase(
        jobs=[
            {
                "id": "job-old",
                "user_id": "user-1",
                "status": "done",
                "step": 5,
                "progress_pct": 1.0,
                "progress": {},
                "document_id": "doc-old",
                "error_message": None,
            }
        ],
        documents=[
            {
                "id": "doc-old",
                "user_id": "user-1",
                "department_id": "dept-old",
                "is_private": False,
                "filename": "historical.pdf",
                "document_fields": [{"label": "Secret", "value": "old-department"}],
            }
        ],
    )
    _override_user(ASSIGNED_USER)
    _override_supabase(db)

    response = client.get("/upload/status/job-old")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == "doc-old"
    assert payload["extracted_data"] is None
    assert db.table_calls == ["upload_jobs", "documents"]


def test_search_query_validation_is_enforced_by_http_contract(client):
    db = FakeSupabase()
    _override_user(ASSIGNED_USER)
    _override_supabase(db)

    response = client.get("/search?q=&limit=0&offset=-1")

    assert response.status_code == 422
    # The endpoint must not execute a database query when query parameters are invalid.
    assert db.table_calls == []


def test_share_password_query_parameter_is_never_treated_as_password(client, monkeypatch):
    calls = []

    def fake_access(token, password=None):
        calls.append((token, password))
        return {"password_required": True}

    monkeypatch.setattr(share.share_service, "access_public_link", fake_access)

    response = client.get("/share/access/public-token?password=secret12")

    assert response.status_code == 401
    assert calls == [("public-token", None)]


def test_share_password_post_body_reaches_service_and_marks_response_no_store(client, monkeypatch):
    calls = []

    def fake_access(token, password=None):
        calls.append((token, password))
        return {
            "password_required": False,
            "document": {"id": "doc-1", "filename": "one.pdf", "doc_type": "Invoice"},
            "expires_at": "2099-01-01T00:00:00+00:00",
            "download_url": "https://signed.example/document",
        }

    monkeypatch.setattr(share.share_service, "access_public_link", fake_access)

    response = client.post(
        "/share/access/public-token",
        json={"password": "secret12"},
    )

    assert response.status_code == 200
    assert calls == [("public-token", "secret12")]
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["download_url"] == "https://signed.example/document"
