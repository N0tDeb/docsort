"""Regression tests for live account-state enforcement during JWT auth."""
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import database
from app.api.auth import current_user_profile
from app.core.security import create_access_token, get_current_user, resolve_authenticated_user


class _Result:
    def __init__(self, data):
        self.data = data


class _UsersQuery:
    def __init__(self, rows):
        self.rows = rows
        self.user_id = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        assert column == "id"
        self.user_id = str(value)
        return self

    def limit(self, _count):
        return self

    def execute(self):
        return _Result([
            row for row in self.rows if str(row.get("id")) == self.user_id
        ])


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "users"
        return _UsersQuery(self.rows)


def _patch_users(monkeypatch, rows):
    fake = _FakeDB(rows)
    monkeypatch.setattr(database, "get_supabase_sync", lambda: fake)
    return fake


def _verified_user(**overrides):
    row = {
        "id": "user-1",
        "email": "live@example.com",
        "name": "Live User",
        "designation": "Staff",
        "status": "verified",
        "role": "user",
        "department_id": "dept-live",
        "is_active": True,
    }
    row.update(overrides)
    return row


def test_live_database_state_overrides_stale_jwt_claims(monkeypatch):
    _patch_users(monkeypatch, [_verified_user()])

    user = resolve_authenticated_user({
        "sub": "user-1",
        "email": "stale@example.com",
        "role": "admin",
        "department_id": "dept-b",
    })

    assert user["email"] == "live@example.com"
    assert user["role"] == "user"
    assert user["department_id"] == "dept-live"
    assert user["name"] == "Live User"
    assert user["designation"] == "Staff"


@pytest.mark.parametrize("account_status", ["banned", "pending", None])
def test_inactive_account_is_rejected_even_with_valid_identity(monkeypatch, account_status):
    _patch_users(monkeypatch, [_verified_user(status=account_status)])

    with pytest.raises(HTTPException) as exc:
        resolve_authenticated_user({"sub": "user-1", "role": "admin"})

    assert exc.value.status_code == 401



def test_is_active_false_is_rejected_even_when_status_is_verified(monkeypatch):
    _patch_users(monkeypatch, [_verified_user(is_active=False)])

    with pytest.raises(HTTPException) as exc:
        resolve_authenticated_user({"sub": "user-1", "role": "user"})

    assert exc.value.status_code == 401
    assert "not active" in str(exc.value.detail).lower()

def test_deleted_account_is_rejected(monkeypatch):
    _patch_users(monkeypatch, [])

    with pytest.raises(HTTPException) as exc:
        resolve_authenticated_user({"sub": "user-1"})

    assert exc.value.status_code == 401


def test_http_dependency_uses_live_role_and_department(monkeypatch):
    _patch_users(monkeypatch, [_verified_user(role="admin", department_id="dept-new")])
    token = create_access_token({
        "sub": "user-1",
        "email": "inactive@example.com",
        "role": "user",
        "department_id": "dept-b",
    })
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = asyncio.run(get_current_user(credentials))

    assert user["role"] == "admin"
    assert user["department_id"] == "dept-new"
    assert user["email"] == "live@example.com"


def test_auth_me_response_preserves_designation():
    profile = asyncio.run(current_user_profile({
        "id": "user-1",
        "email": "live@example.com",
        "role": "user",
        "department_id": "dept-live",
        "name": "Live User",
        "designation": "Staff",
    }))

    assert profile["designation"] == "Staff"
