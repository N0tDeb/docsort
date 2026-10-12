from app.services.analytics_service import AnalyticsService


def test_department_analytics_uses_generic_autosort_categories():
    svc = AnalyticsService()
    result = svc.compute_department(
        documents=[
            {"doc_type": "Vendor Invoice", "ocr_confidence": 0.9, "sort_confidence": 0.9, "created_at": "2000-01-01T00:00:00+00:00"},
            {"doc_type": "Candidate Resume", "ocr_confidence": 0.8, "sort_confidence": 0.9, "created_at": "2000-01-01T00:00:00+00:00"},
            {"doc_type": "Service Contract", "ocr_confidence": 0.7, "sort_confidence": 0.9, "created_at": "2000-01-01T00:00:00+00:00"},
        ],
        jobs=[],
        active_users=[],
    )
    assert result["doc_type_distribution"]["Finance"] == 1
    assert result["doc_type_distribution"]["Human Resources"] == 1
    assert result["doc_type_distribution"]["Legal"] == 1
