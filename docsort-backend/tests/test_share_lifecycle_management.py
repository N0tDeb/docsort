"""Authenticated share-link lifecycle management regressions."""

import asyncio

import pytest
from fastapi import HTTPException

from app.api import share
from app.services.share_service import ShareService


USER = {"id": "u1", "role": "user", "department_id": "d1"}
ADMIN = {"id": "admin", "role": "admin", "department_id": "d1"}


class Result:
    def __init__(self, data):
        self.data = data


class LifecycleBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.payload = None
        self.action = "select"
        self.limit_value = None

    def select(self, *_args, **_kwargs):
        self.action = "select"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = payload
        return self

    def execute(self):
        assert self.table == "shared_links"
        rows = list(self.db.links)
        for column, value in self.filters:
            rows = [row for row in rows if str(row.get(column)) == str(value)]
        if self.action == "select":
            return Result(rows[: self.limit_value or len(rows)])
        if self.action == "update":
            updated = []
            for row in self.db.links:
                if all(str(row.get(column)) == str(value) for column, value in self.filters):
                    row.update(self.payload)
                    updated.append(dict(row))
            return Result(updated)
        raise AssertionError(self.action)


class LifecycleDB:
    def __init__(self):
        self.links = [
            {
                "id": "share-1",
                "token": "capability-secret",
                "document_id": "own",
                "created_by": "u1",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "password": "pbkdf2_sha256$redacted",
                "is_active": True,
                "created_at": "2026-09-16T00:00:00+00:00",
            },
            {
                "id": "share-2",
                "token": "another-secret",
                "document_id": "own",
                "created_by": "admin",
                "expires_at": "2099-01-02T00:00:00+00:00",
                "password": None,
                "is_active": False,
                "created_at": "2026-09-15T00:00:00+00:00",
            },
        ]

    def table(self, name):
        return LifecycleBuilder(self, name)


def test_service_lists_safe_metadata_without_capability_or_password(monkeypatch):
    db = LifecycleDB()
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)

    rows = ShareService().list_public_links("own")

    assert [row["share_id"] for row in rows] == ["share-1", "share-2"]
    assert rows[0]["password_protected"] is True
    assert rows[1]["password_protected"] is False
    assert all("token" not in row for row in rows)
    assert all("password" not in row for row in rows)


def test_service_revocation_is_idempotent_and_fails_closed_on_missing_row(monkeypatch):
    db = LifecycleDB()
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)
    service = ShareService()

    first = service.revoke_public_link("share-1")
    second = service.revoke_public_link("share-1")
    missing = service.revoke_public_link("does-not-exist")

    assert first == {"share_id": "share-1", "is_active": False}
    assert second == {"share_id": "share-1", "is_active": False}
    assert missing is None


def test_owner_can_list_links_but_peer_document_is_hidden(monkeypatch):
    monkeypatch.setattr(share, "get_supabase_sync", lambda: object())
    monkeypatch.setattr(
        share,
        "get_writable_document",
        lambda _db, document_id, user, _columns: (
            {"id": document_id} if document_id == "own" and user["id"] == "u1" else None
        ),
    )
    monkeypatch.setattr(
        share.share_service,
        "list_public_links",
        lambda document_id: [{
            "share_id": "share-1",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "is_active": True,
            "created_at": "2026-09-16T00:00:00+00:00",
            "password_protected": False,
        }],
    )

    rows = asyncio.run(share.list_share_links("own", user=USER))
    assert rows[0]["share_id"] == "share-1"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(share.list_share_links("peer", user=USER))
    assert exc.value.status_code == 404


def test_department_admin_can_manage_peer_document_links(monkeypatch):
    monkeypatch.setattr(share, "get_supabase_sync", lambda: object())
    monkeypatch.setattr(
        share,
        "get_writable_document",
        lambda _db, document_id, user, _columns: (
            {"id": document_id}
            if document_id == "peer" and user["role"] == "admin" and user["department_id"] == "d1"
            else None
        ),
    )
    monkeypatch.setattr(share.share_service, "list_public_links", lambda _document_id: [])

    assert asyncio.run(share.list_share_links("peer", user=ADMIN)) == []


def test_revoke_requires_current_document_write_authority_and_logs_no_token(monkeypatch):
    monkeypatch.setattr(share, "get_supabase_sync", lambda: object())
    monkeypatch.setattr(
        share.share_service,
        "get_public_link_metadata",
        lambda share_id: {"share_id": share_id, "document_id": "own", "is_active": True},
    )
    monkeypatch.setattr(
        share,
        "get_writable_document",
        lambda _db, document_id, user, _columns: (
            {"id": document_id} if document_id == "own" and user["id"] == "u1" else None
        ),
    )
    monkeypatch.setattr(
        share.share_service,
        "revoke_public_link",
        lambda share_id: {"share_id": share_id, "is_active": False},
    )
    logged = []
    monkeypatch.setattr(share.activity_service, "log", lambda *args, **kwargs: logged.append((args, kwargs)))

    result = asyncio.run(share.revoke_share_link("share-1", user=USER))

    assert result == {"share_id": "share-1", "is_active": False}
    assert logged
    serialized_log = repr(logged)
    assert "capability-secret" not in serialized_log

    with pytest.raises(HTTPException) as exc:
        asyncio.run(share.revoke_share_link("share-1", user={**USER, "id": "u2"}))
    assert exc.value.status_code == 404


def test_missing_share_id_is_404_and_never_runs_document_authorization(monkeypatch):
    monkeypatch.setattr(share.share_service, "get_public_link_metadata", lambda _share_id: None)
    monkeypatch.setattr(
        share,
        "get_writable_document",
        lambda *_args, **_kwargs: pytest.fail("document authorization must not run for a missing share"),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(share.revoke_share_link("missing", user=USER))
    assert exc.value.status_code == 404


def test_revocation_immediately_invalidates_public_capability(monkeypatch):
    db = LifecycleDB()
    monkeypatch.setattr("app.services.share_service.get_supabase_sync", lambda: db)
    service = ShareService()

    assert service.get_public_link("capability-secret") is not None
    assert service.revoke_public_link("share-1") == {"share_id": "share-1", "is_active": False}
    assert service.get_public_link("capability-secret") is None


def test_share_management_routes_are_registered():
    routes = {(route.path, frozenset(route.methods or [])) for route in share.router.routes}
    assert ("/share/links/{document_id}", frozenset({"GET"})) in routes
    assert ("/share/link/{share_id}", frozenset({"DELETE"})) in routes
