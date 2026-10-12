from datetime import datetime, timezone

import app.services.analytics_service as analytics_module
from app.services.analytics_service import AnalyticsService


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = cls(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
        return fixed if tz is not None else fixed.replace(tzinfo=None)


def test_daily_uploads_returns_exact_last_seven_calendar_days(monkeypatch):
    monkeypatch.setattr(analytics_module, "datetime", _FixedDateTime)

    result = AnalyticsService().compute_department(
        documents=[
            {"created_at": "2026-09-09T23:59:59+00:00"},  # outside the 7-day calendar window
            {"created_at": "2026-09-10T08:00:00+00:00"},
            {"created_at": "2026-09-12T09:00:00+00:00"},
            {"created_at": "2026-09-12T10:00:00+00:00"},
            {"created_at": "2026-09-16T11:59:59+00:00"},
        ],
        jobs=[],
        active_users=[],
    )

    assert result["daily_uploads"] == [
        {"date": "2026-09-10", "count": 1},
        {"date": "2026-09-11", "count": 0},
        {"date": "2026-09-12", "count": 2},
        {"date": "2026-09-13", "count": 0},
        {"date": "2026-09-14", "count": 0},
        {"date": "2026-09-15", "count": 0},
        {"date": "2026-09-16", "count": 1},
    ]


def test_daily_uploads_includes_seven_zero_slots_when_empty(monkeypatch):
    monkeypatch.setattr(analytics_module, "datetime", _FixedDateTime)

    result = AnalyticsService().compute_department(
        documents=[],
        jobs=[],
        active_users=[],
    )

    assert [item["date"] for item in result["daily_uploads"]] == [
        "2026-09-10",
        "2026-09-11",
        "2026-09-12",
        "2026-09-13",
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
    ]
    assert [item["count"] for item in result["daily_uploads"]] == [0] * 7


def test_empty_department_response_keeps_explicit_daily_slots(monkeypatch):
    import app.api.analytics as analytics_api

    monkeypatch.setattr(analytics_module, "datetime", _FixedDateTime)
    result = analytics_api._empty_department_analytics()

    assert len(result["daily_uploads"]) == 7
    assert result["daily_uploads"][0] == {"date": "2026-09-10", "count": 0}
    assert result["daily_uploads"][-1] == {"date": "2026-09-16", "count": 0}
