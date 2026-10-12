"""Final-year privacy/security regressions for signup and operational audit data."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app.api import auth
from app.services import activity_service as activity_module


GENERIC_REGISTRATION_MESSAGE = (
    "Registration request received. Check with an administrator for approval status."
)


class Result:
    def __init__(self, data=None):
        self.data = [] if data is None else data


def test_signup_existing_and_new_email_have_same_public_response(monkeypatch):
    lookups = [[{"id": "existing-user"}], []]
    hashes: list[str] = []
    created: list[dict] = []

    monkeypatch.setattr(auth, "_resolve_signup_department_id", lambda _data: None)
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: lookups.pop(0))
    monkeypatch.setattr(
        auth,
        "hash_password",
        lambda password: hashes.append(password) or "stored-hash",
    )
    monkeypatch.setattr(auth, "create_user", lambda payload: created.append(payload) or payload)

    with TestClient(main.app, raise_server_exceptions=True) as client:
        existing = client.post(
            "/auth/signup",
            json={"email": "same@example.com", "password": "correct-horse"},
        )
        new = client.post(
            "/auth/signup",
            json={"email": "new@example.com", "password": "correct-horse"},
        )

    assert existing.status_code == 201
    assert new.status_code == 201
    assert existing.json() == new.json() == {"message": GENERIC_REGISTRATION_MESSAGE}
    # Existing-account requests still perform the password-cost work so the
    # obvious timing difference is reduced under the endpoint's rate limit.
    assert hashes == ["correct-horse", "correct-horse"]
    assert len(created) == 1
    assert created[0]["email"] == "new@example.com"


def test_signup_unique_email_race_is_normalized_to_same_public_response(monkeypatch):
    monkeypatch.setattr(auth, "_resolve_signup_department_id", lambda _data: None)
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: [])
    monkeypatch.setattr(auth, "hash_password", lambda _password: "stored-hash")

    def duplicate_insert(_payload):
        raise RuntimeError(
            'HTTP 409 on insert users: duplicate key value violates unique constraint "users_email_key" (23505)'
        )

    monkeypatch.setattr(auth, "create_user", duplicate_insert)

    with TestClient(main.app, raise_server_exceptions=True) as client:
        response = client.post(
            "/auth/signup",
            json={"email": "raced@example.com", "password": "correct-horse"},
        )

    assert response.status_code == 201
    assert response.json() == {"message": GENERIC_REGISTRATION_MESSAGE}


def test_signup_department_validation_does_not_depend_on_account_existence(monkeypatch):
    lookup_called = False

    def invalid_department(_data):
        raise HTTPException(status_code=400, detail="Invalid department code.")

    def lookup(_email):
        nonlocal lookup_called
        lookup_called = True
        return [{"id": "existing-user"}]

    monkeypatch.setattr(auth, "_resolve_signup_department_id", invalid_department)
    monkeypatch.setattr(auth, "get_user_by_email", lookup)

    with TestClient(main.app, raise_server_exceptions=True) as client:
        response = client.post(
            "/auth/signup",
            json={
                "email": "same@example.com",
                "password": "correct-horse",
                "department_code": "NOT-A-DEPT",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid department code."
    # Validate request-scoped department data before the email lookup, so an
    # invalid department cannot become a side channel for account existence.
    assert lookup_called is False


def test_activity_details_do_not_persist_filename_recipient_or_freeform_metadata(monkeypatch):
    rows: list[dict] = []

    class InsertBuilder:
        def insert(self, payload):
            rows.append(payload)
            return self

        def execute(self):
            return Result()

    class ActivitySupabase:
        def table(self, name):
            assert name == "activity_log"
            return InsertBuilder()

    monkeypatch.setattr(activity_module, "get_supabase_sync", lambda: ActivitySupabase())
    service = activity_module.ActivityService()

    service.log_upload("user-1", "dept-1", "doc-1")
    service.log_view("user-1", "dept-1", "doc-1")
    service.log_share("user-1", "dept-1", "doc-1")
    service.log("user-1", "dept-1", "move", "doc-1")
    service.log("user-1", "dept-1", "share_revoke", "doc-1")

    assert [row["detail"] for row in rows] == [
        "Document uploaded",
        "Document viewed",
        "Public share link created",
        "Document moved",
        "Public share link revoked",
    ]
    assert all(row["metadata"] == {} for row in rows)
    serialized = repr(rows)
    assert "secret.pdf" not in serialized
    assert "recipient@example.com" not in serialized
    assert "share-token" not in serialized


def test_activity_logging_failure_does_not_emit_raw_exception_text(monkeypatch):
    rendered: list[str] = []

    def failing_supabase():
        raise RuntimeError("secret.pdf token=super-secret storage_path=private/object")

    def capture_warning(message, *args):
        rendered.append(message % args if args else message)

    monkeypatch.setattr(activity_module, "get_supabase_sync", failing_supabase)
    monkeypatch.setattr(activity_module.logger, "warning", capture_warning)

    activity_module.ActivityService().log_login("user-1", None)

    assert len(rendered) == 1
    assert "RuntimeError" in rendered[0]
    assert "secret.pdf" not in rendered[0]
    assert "super-secret" not in rendered[0]
    assert "private/object" not in rendered[0]


def test_flutter_registration_copy_does_not_disclose_account_existence():
    repo = Path(__file__).resolve().parents[2]
    provider = (
        repo
        / "docsort/lib/features/auth/presentation/providers/auth_provider.dart"
    ).read_text(encoding="utf-8").lower()
    screen = (
        repo
        / "docsort/lib/features/auth/presentation/screens/register_screen.dart"
    ).read_text(encoding="utf-8").lower()

    assert "account exists" not in provider
    assert "already registered" not in provider
    assert "account created!" not in screen
    assert "registration request received" in screen
