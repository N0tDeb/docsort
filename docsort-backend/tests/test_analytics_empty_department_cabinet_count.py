import asyncio
from dataclasses import dataclass

from app.api import analytics


@dataclass
class _Response:
    data: list
    count: int | None = None


class _Query:
    def __init__(self, table_name: str, responses: dict[str, _Response], calls: list[tuple]):
        self.table_name = table_name
        self.responses = responses
        self.calls = calls

    def select(self, *args, **kwargs):
        self.calls.append((self.table_name, "select", args, kwargs))
        return self

    def eq(self, *args, **kwargs):
        self.calls.append((self.table_name, "eq", args, kwargs))
        return self

    def gte(self, *args, **kwargs):
        self.calls.append((self.table_name, "gte", args, kwargs))
        return self

    def or_(self, *args, **kwargs):
        self.calls.append((self.table_name, "or", args, kwargs))
        return self

    def execute(self):
        self.calls.append((self.table_name, "execute", (), {}))
        return self.responses[self.table_name]


class _Supabase:
    def __init__(self):
        self.calls: list[tuple] = []
        self.responses = {
            "documents": _Response(data=[], count=0),
            "upload_jobs": _Response(data=[]),
            "users": _Response(data=[]),
            "folders": _Response(data=[{"id": "needs-review"}], count=1),
        }

    def table(self, name: str):
        return _Query(name, self.responses, self.calls)


def test_empty_department_analytics_reports_existing_system_folder():
    supabase = _Supabase()
    user = {
        "id": "user-1",
        "department_id": "department-1",
        "role": "admin",
    }

    result = asyncio.run(
        analytics.get_department_analytics(supabase=supabase, user=user)
    )

    assert result["total_documents"] == 0
    assert result["cabinets_count"] == 1
    assert any(call[0] == "folders" and call[1] == "execute" for call in supabase.calls)
