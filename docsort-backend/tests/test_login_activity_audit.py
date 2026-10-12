"""Login audit regressions for users without a department."""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main
from app.api import auth


class Result:
    def __init__(self, data=None):
        self.data = [] if data is None else data


class UpdateBuilder:
    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filter = (column, value)
        return self

    def execute(self):
        return Result()


class FakeSupabase:
    def table(self, name):
        assert name == "users"
        return UpdateBuilder()


def _login_user(department_id):
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "email": "unassigned@example.com",
        "password": "stored-hash",
        "role": "user",
        "status": "verified",
        "is_active": True,
        "department_id": department_id,
    }


def test_login_audit_uses_null_department_for_unassigned_user(monkeypatch):
    captured = {}
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: [_login_user(None)])
    monkeypatch.setattr(auth, "verify_password", lambda _password, _hash: True)
    monkeypatch.setattr(auth, "create_access_token", lambda _claims: "test-token")
    monkeypatch.setattr(auth, "get_supabase_sync", lambda: FakeSupabase())
    monkeypatch.setattr(
        auth.activity_service,
        "log_login",
        lambda *, user_id, department_id: captured.update(
            user_id=user_id,
            department_id=department_id,
        ),
    )

    with TestClient(main.app, raise_server_exceptions=True) as client:
        response = client.post(
            "/auth/login",
            json={"email": "unassigned@example.com", "password": "correct-password"},
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "test-token"
    assert captured == {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "department_id": None,
    }


def test_login_audit_preserves_assigned_department(monkeypatch):
    department_id = "22222222-2222-2222-2222-222222222222"
    captured = {}
    monkeypatch.setattr(
        auth,
        "get_user_by_email",
        lambda _email: [_login_user(department_id)],
    )
    monkeypatch.setattr(auth, "verify_password", lambda _password, _hash: True)
    monkeypatch.setattr(auth, "create_access_token", lambda _claims: "test-token")
    monkeypatch.setattr(auth, "get_supabase_sync", lambda: FakeSupabase())
    monkeypatch.setattr(
        auth.activity_service,
        "log_login",
        lambda *, user_id, department_id: captured.update(
            user_id=user_id,
            department_id=department_id,
        ),
    )

    with TestClient(main.app, raise_server_exceptions=True) as client:
        response = client.post(
            "/auth/login",
            json={"email": "unassigned@example.com", "password": "correct-password"},
        )

    assert response.status_code == 200
    assert captured["department_id"] == department_id


def test_activity_service_persists_null_department(monkeypatch):
    from app.services import activity_service as activity_module

    captured = {}

    class InsertBuilder:
        def insert(self, payload):
            captured.update(payload)
            return self

        def execute(self):
            return Result()

    class ActivitySupabase:
        def table(self, name):
            assert name == "activity_log"
            return InsertBuilder()

    monkeypatch.setattr(activity_module, "get_supabase_sync", lambda: ActivitySupabase())

    activity_module.ActivityService().log_login(
        user_id="11111111-1111-1111-1111-111111111111",
        department_id=None,
    )

    assert captured["department_id"] is None
    assert captured["action"] == "login"
