import asyncio
from app.api import admin as admin_api


class _Result:
    def __init__(self, data):
        self.data = data


class _UsersQuery:
    def __init__(self, rows):
        self.rows = rows
        self.selected = None
        self.filters = []

    def select(self, columns):
        self.selected = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        rows = list(self.rows)
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]

        if self.selected and self.selected != "*":
            fields = [field.strip() for field in self.selected.split(",")]
            rows = [{field: row.get(field) for field in fields} for row in rows]
        return _Result(rows)


class _FakeSupabase:
    def __init__(self, users):
        self.users_query = _UsersQuery(users)

    def table(self, name):
        assert name == "users"
        return self.users_query


def test_admin_user_listing_does_not_select_or_return_password_hash():
    db = _FakeSupabase([
        {
            "id": "u1",
            "email": "person@example.com",
            "password": "bcrypt-hash-that-must-never-leave-server",
            "name": "Person",
            "department_id": "dept-a",
            "designation": "Staff",
            "employee_id": "E-1",
            "role": "user",
            "status": "pending",
            "is_active": True,
            "last_seen": "2026-09-12T12:00:00Z",
            "created_at": "2026-09-10T12:00:00Z",
        }
    ])

    result = asyncio.run(admin_api.list_users(
        status="pending",
        supabase=db,
        admin={"id": "admin-a", "role": "admin", "department_id": "dept-a"},
    ))

    assert db.users_query.selected != "*"
    assert "password" not in db.users_query.selected
    assert result[0]["email"] == "person@example.com"
    assert "password" not in result[0]


def test_debug_activity_route_is_not_exposed():
    paths = {route.path for route in admin_api.router.routes}
    assert "/admin/activity/debug" not in paths
