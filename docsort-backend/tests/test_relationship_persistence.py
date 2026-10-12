import asyncio

from app.core.database import SupabaseClient, _QueryBuilder, _Result
from app.services.relationship_service import _link_document_to_citizen


def test_citizen_document_link_uses_supported_conflict_upsert(monkeypatch):
    calls = []

    def fake_execute(self):
        calls.append({
            "action": self._action,
            "params": self._build_params(),
            "body": self._body,
            "prefer": self._headers.get("Prefer", ""),
        })
        return _Result([{"id": "link-1"}])

    monkeypatch.setattr(_QueryBuilder, "execute", fake_execute)
    db = SupabaseClient("http://sb.local", "service-key")

    asyncio.run(_link_document_to_citizen(db, "citizen-1", "document-1"))

    assert len(calls) == 1
    call = calls[0]
    assert call["action"] == "upsert"
    assert call["params"]["on_conflict"] == "citizen_id,document_id"
    assert call["body"] == {
        "citizen_id": "citizen-1",
        "document_id": "document-1",
        "role": "subject",
    }
    assert "resolution=merge-duplicates" in call["prefer"]
