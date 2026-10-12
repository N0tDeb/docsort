from app.core.config import settings
from app.services.analytics_service import AnalyticsService


def test_department_analytics_uses_configured_autosort_threshold(monkeypatch):
    monkeypatch.setattr(settings, "autosort_confidence_threshold", 0.90)

    result = AnalyticsService().compute_department(
        documents=[
            {
                "doc_type": "Vendor Invoice",
                "ocr_confidence": 0.95,
                "sort_confidence": 0.80,
                "created_at": "2000-01-01T00:00:00+00:00",
            },
            {
                "doc_type": "Service Contract",
                "ocr_confidence": 0.90,
                "sort_confidence": 0.95,
                "created_at": "2000-01-01T00:00:00+00:00",
            },
        ],
        jobs=[],
        active_users=[],
    )

    # Only the 0.95 document meets the configured 0.90 AutoSort threshold.
    assert result["autosort_rate"] == 0.5
