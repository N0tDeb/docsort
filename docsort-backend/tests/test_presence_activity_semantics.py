"""Regression coverage for last-activity and presence recency semantics."""
from datetime import datetime, timedelta, timezone

import asyncio

from app.api import admin as admin_api
from app.core import database
from app.core.security import resolve_authenticated_user
from app.services.analytics_service import AnalyticsService


class _Result:
    def __init__(self, data):
        self.data = data


class _UsersQuery:
    def __init__(self, rows, *, operation="select", payload=None, updates=None):
        self.rows = rows
        self.operation = operation
        self.payload = payload or {}
        self.updates = updates if updates is not None else []
        self.user_id = None
        self.selected = None

    def select(self, columns, *_args, **_kwargs):
        self.selected = columns
        return self

    def update(self, payload):
        return _UsersQuery(
            self.rows,
            operation="update",
            payload=payload,
            updates=self.updates,
        )

    def eq(self, column, value):
        assert column == "id"
        self.user_id = str(value)
        return self

    def limit(self, _count):
        return self

    def execute(self):
        matches = [row for row in self.rows if str(row.get("id")) == self.user_id]
        if self.operation == "update":
            self.updates.append((self.user_id, dict(self.payload)))
            for row in matches:
                row.update(self.payload)
        if self.selected and self.selected != "*":
            fields = [field.strip() for field in self.selected.split(",")]
            matches = [{field: row.get(field) for field in fields} for row in matches]
        return _Result(matches)


class _UsersTable:
    def __init__(self, rows, updates):
        self.rows = rows
        self.updates = updates

    def select(self, columns, *_args, **_kwargs):
        return _UsersQuery(self.rows, updates=self.updates).select(columns)

    def update(self, payload):
        return _UsersQuery(
            self.rows,
            operation="update",
            payload=payload,
            updates=self.updates,
        )


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def table(self, name):
        assert name == "users"
        return _UsersTable(self.rows, self.updates)


def _verified_user(last_seen):
    return {
        "id": "user-1",
        "email": "live@example.com",
        "name": "Live User",
        "designation": "Staff",
        "status": "verified",
        "role": "user",
        "department_id": "dept-live",
        "is_active": True,
        "last_seen": last_seen,
    }


def test_authenticated_activity_touches_missing_last_seen(monkeypatch):
    fake = _FakeDB([_verified_user(None)])
    monkeypatch.setattr(database, "get_supabase_sync", lambda: fake)

    resolve_authenticated_user({"sub": "user-1"})

    assert len(fake.updates) == 1
    assert fake.updates[0][0] == "user-1"
    assert fake.updates[0][1]["last_seen"]


def test_authenticated_activity_does_not_write_when_last_seen_is_recent(monkeypatch):
    recent = datetime.now(timezone.utc) - timedelta(seconds=30)
    fake = _FakeDB([_verified_user(recent.isoformat())])
    monkeypatch.setattr(database, "get_supabase_sync", lambda: fake)

    resolve_authenticated_user({"sub": "user-1"})

    assert fake.updates == []


def test_authenticated_activity_refreshes_stale_last_seen(monkeypatch):
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    fake = _FakeDB([_verified_user(stale.isoformat())])
    monkeypatch.setattr(database, "get_supabase_sync", lambda: fake)

    resolve_authenticated_user({"sub": "user-1"})

    assert len(fake.updates) == 1


def test_admin_presence_reports_activity_recency_not_online_state(monkeypatch):
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    rows = [
        {"id": "u1", "name": "A", "designation": "Staff", "role": "user", "last_seen": (now - timedelta(minutes=2)).isoformat()},
        {"id": "u2", "name": "B", "designation": "Staff", "role": "user", "last_seen": (now - timedelta(minutes=20)).isoformat()},
        {"id": "u3", "name": "C", "designation": "Staff", "role": "user", "last_seen": None},
    ]

    class _PresenceQuery:
        def select(self, _columns):
            return self

        def execute(self):
            return _Result(rows)

    class _PresenceDB:
        def table(self, name):
            assert name == "users"
            return _PresenceQuery()

    monkeypatch.setattr(admin_api, "_utc_now", lambda: now)
    result = asyncio.run(admin_api.get_presence(supabase=_PresenceDB(), admin={"role": "admin"}))

    assert [item["presence_status"] for item in result] == ["active", "recent", "inactive"]


def test_department_analytics_exposes_explicit_24h_activity_metric():
    result = AnalyticsService().compute_department(
        documents=[],
        jobs=[],
        active_users=[{"id": "u1"}, {"id": "u2"}],
    )

    assert result["active_users_24h"] == 2
    assert result["active_users_today"] == 2  # API alias
