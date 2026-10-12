"""Regression tests for admin account mutations through the real HTTP stack."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.core.database import get_supabase
from app.core.security import get_current_admin


class Result:
    def __init__(self, data):
        self.data = data


class UserUpdateBuilder:
    def __init__(self, db: "AdminSupabase"):
        self.db = db
        self.payload: dict | None = None
        self.filters: list[tuple[str, object]] = []

    def update(self, payload):
        self.payload = dict(payload)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        rows = list(self.db.users)
        for column, value in self.filters:
            rows = [row for row in rows if str(row.get(column)) == str(value)]

        if self.payload is None:
            raise AssertionError("expected update() before execute()")

        changed = []
        for row in rows:
            row.update(self.payload)
            changed.append(dict(row))
        self.db.updates.append((dict(self.payload), list(self.filters)))
        return Result(changed)


class AdminSupabase:
    def __init__(self, users):
        self.users = [dict(row) for row in users]
        self.updates: list[tuple[dict, list[tuple[str, object]]]] = []

    def table(self, name):
        assert name == "users"
        return UserUpdateBuilder(self)


ADMIN = {
    "id": "admin-1",
    "email": "admin@example.com",
    "role": "admin",
    "department_id": "dept-1",
    "name": "Admin One",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    main.app.dependency_overrides.clear()
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def _override_dependencies(db: AdminSupabase) -> None:
    async def current_admin_override():
        return ADMIN

    async def supabase_override():
        return db

    main.app.dependency_overrides[get_current_admin] = current_admin_override
    main.app.dependency_overrides[get_supabase] = supabase_override


@pytest.mark.parametrize(
    ("path", "expected_payload"),
    [
        ("/admin/ban-user/missing-user", {"status": "banned"}),
        ("/admin/approve-user/missing-user", {"status": "verified"}),
        ("/admin/promote-user/missing-user", {"role": "admin"}),
    ],
)
def test_admin_mutations_return_404_when_target_does_not_exist(client, path, expected_payload):
    db = AdminSupabase([])
    _override_dependencies(db)

    response = client.post(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}
    assert db.updates == [(expected_payload, [("id", "missing-user")])]


@pytest.mark.parametrize(
    ("path", "expected_payload", "expected_message"),
    [
        ("/admin/ban-user/user-2", {"status": "banned"}, "User banned"),
        ("/admin/approve-user/user-2", {"status": "verified"}, "User approved"),
        ("/admin/promote-user/user-2", {"role": "admin"}, "User promoted to organization admin"),
    ],
)
def test_admin_mutations_keep_success_contract_when_target_is_updated(
    client, path, expected_payload, expected_message
):
    db = AdminSupabase([{"id": "user-2", "status": "pending", "role": "user"}])
    _override_dependencies(db)

    response = client.post(path)

    assert response.status_code == 200
    assert response.json() == {"message": expected_message}
    assert db.updates == [(expected_payload, [("id", "user-2")])]


@pytest.mark.parametrize(
    "path",
    [
        "/admin/ban-user/admin-1",
        "/admin/approve-user/admin-1",
        "/admin/promote-user/admin-1",
    ],
)
def test_admin_mutations_still_reject_self_targeting(client, path):
    db = AdminSupabase([{"id": "admin-1", "status": "verified", "role": "admin"}])
    _override_dependencies(db)

    response = client.post(path)

    assert response.status_code == 400
    assert db.updates == []
