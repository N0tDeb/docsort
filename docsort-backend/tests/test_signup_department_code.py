"""Regression tests for department-code resolution during signup."""

import pytest
from fastapi import HTTPException

from app.api import auth
from app.schemas.auth_schema import SignupRequest


class _Result:
    def __init__(self, data):
        self.data = data


class _DepartmentsQuery:
    def __init__(self, rows):
        self.rows = rows
        self._mode = None
        self._value = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        assert column == "id"
        self._mode = "id"
        self._value = str(value)
        return self

    def limit(self, _count):
        return self

    def execute(self):
        if self._mode == "id":
            rows = [r for r in self.rows if str(r.get("id")) == self._value]
        else:
            rows = self.rows
        return _Result(rows[:1])


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "departments"
        return _DepartmentsQuery(self.rows)




def _patch_departments(monkeypatch, rows):
    monkeypatch.setattr(auth, "get_supabase_sync", lambda: _FakeDB(rows))


def _request(**overrides):
    payload = {
        "email": "person@example.com",
        "password": "password123",
        "name": "Person",
    }
    payload.update(overrides)
    return SignupRequest(**payload)


def test_department_code_resolves_to_uuid_case_insensitively(monkeypatch):
    rows = [
        {"id": "11111111-1111-1111-1111-111111111111", "code": "FIN"},
    ]
    _patch_departments(monkeypatch, rows)

    resolved = auth._resolve_signup_department_id(
        _request(department_code="  fin  ")
    )

    assert resolved == "11111111-1111-1111-1111-111111111111"


def test_unknown_department_code_is_rejected(monkeypatch):
    _patch_departments(monkeypatch, [])

    with pytest.raises(HTTPException) as exc:
        auth._resolve_signup_department_id(_request(department_code="UNKNOWN"))

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid department code."


def test_department_id_parameter_is_supported_and_validated(monkeypatch):
    department_id = "11111111-1111-1111-1111-111111111111"
    _patch_departments(monkeypatch, [{"id": department_id, "code": "FIN"}])

    assert auth._resolve_signup_department_id(
        _request(department_id=department_id)
    ) == department_id


def test_unknown_department_id_is_rejected(monkeypatch):
    _patch_departments(monkeypatch, [])

    with pytest.raises(HTTPException) as exc:
        auth._resolve_signup_department_id(
            _request(department_id="99999999-9999-9999-9999-999999999999")
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid department ID."


def test_conflicting_code_and_id_are_rejected(monkeypatch):
    resolved_id = "11111111-1111-1111-1111-111111111111"
    _patch_departments(monkeypatch, [{"id": resolved_id, "code": "FIN"}])

    with pytest.raises(HTTPException) as exc:
        auth._resolve_signup_department_id(
            _request(
                department_code="FIN",
                department_id="22222222-2222-2222-2222-222222222222",
            )
        )

    assert exc.value.status_code == 400
    assert "do not match" in exc.value.detail


def test_blank_department_input_keeps_signup_unassigned(monkeypatch):
    _patch_departments(monkeypatch, [])

    assert auth._resolve_signup_department_id(
        _request(department_code="   ")
    ) is None
