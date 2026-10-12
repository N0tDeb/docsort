"""Whole-cabinet keyword search tests."""
import asyncio
from app.api import search as S
from tests.conftest import FakeSupabase


def run(sb, user, **kw):
    return asyncio.run(S.search_documents(supabase=sb, user=user, **kw))


def test_finds_field_only_match(sample_docs, user_dept1):
    # 'Ramesh' appears only inside extracted fields, not doc_type/filename.
    # Search must find authorized matches outside a small recency window.
    sb = FakeSupabase(sample_docs)
    r = run(sb, user_dept1, q="Ramesh", doc_type=None, folder_id=None, limit=20, offset=0)
    assert sorted(d["id"] for d in r) == ["d1", "d3"]


def test_department_isolation(sample_docs, user_dept1):
    sb = FakeSupabase(sample_docs)
    r = run(sb, user_dept1, q="Invoice", doc_type=None, folder_id=None, limit=20, offset=0)
    assert sorted(d["id"] for d in r) == ["d1"]  # d4 is dept2, must not leak


def test_doc_type_filter(sample_docs, user_dept1):
    sb = FakeSupabase(sample_docs)
    r = run(sb, user_dept1, q="Ramesh", doc_type="Certificate", folder_id=None, limit=20, offset=0)
    assert [d["id"] for d in r] == ["d3"]


def test_highlight_markers(sample_docs, user_dept1):
    sb = FakeSupabase(sample_docs)
    r = run(sb, user_dept1, q="Ramesh", doc_type=None, folder_id=None, limit=20, offset=0)
    assert any("^^Ramesh^^" in h["snippet"] for h in r[0]["match_highlights"])


def test_newest_first_and_pagination(sample_docs, user_dept1):
    sb = FakeSupabase(sample_docs)
    r = run(sb, user_dept1, q="Ramesh", doc_type=None, folder_id=None, limit=1, offset=0)
    assert r[0]["id"] == "d3"  # 2024-03 newer than 2024-01


def test_no_match_returns_empty(sample_docs, user_dept1):
    sb = FakeSupabase(sample_docs)
    r = run(sb, user_dept1, q="zzznothing", doc_type=None, folder_id=None, limit=20, offset=0)
    assert r == []


def test_search_hides_peer_private_document_but_keeps_own_private_document():
    docs = [
        {"id": "public-peer", "doc_type": "Invoice", "filename": "shared-invoice.pdf",
         "department_id": "dept1", "user_id": "u2", "is_private": False,
         "folder_id": "f1", "created_at": "2024-01-01", "document_fields": [],
         "users": {"name": "peer"}, "folders": {"name": "Finance"}},
        {"id": "private-peer", "doc_type": "Invoice", "filename": "private-invoice.pdf",
         "department_id": "dept1", "user_id": "u2", "is_private": True,
         "folder_id": "f1", "created_at": "2024-02-01", "document_fields": [],
         "users": {"name": "peer"}, "folders": {"name": "Finance"}},
        {"id": "private-own", "doc_type": "Invoice", "filename": "my-invoice.pdf",
         "department_id": "dept1", "user_id": "u1", "is_private": True,
         "folder_id": "f1", "created_at": "2024-03-01", "document_fields": [],
         "users": {"name": "me"}, "folders": {"name": "Finance"}},
    ]
    sb = FakeSupabase(docs)
    user = {"id": "u1", "role": "user", "department_id": "dept1"}

    r = run(sb, user, q="Invoice", doc_type=None, folder_id=None, limit=20, offset=0)

    assert {d["id"] for d in r} == {"public-peer", "private-own"}


def test_field_candidate_limit_is_applied_after_authorization_scope(monkeypatch):
    """Inaccessible rows must not consume the global candidate ceiling."""
    monkeypatch.setattr(S, "_CANDIDATE_CAP", 2)
    docs = [
        {"id": "other-1", "doc_type": "Report", "filename": "a.pdf",
         "department_id": "dept2", "user_id": "x1", "is_private": False,
         "folder_id": "f2", "created_at": "2024-01-01",
         "document_fields": [{"label": "Name", "value": "Needle"}],
         "users": {"name": "other"}, "folders": {"name": "Elsewhere"}},
        {"id": "other-2", "doc_type": "Report", "filename": "b.pdf",
         "department_id": "dept2", "user_id": "x2", "is_private": False,
         "folder_id": "f2", "created_at": "2024-01-02",
         "document_fields": [{"label": "Name", "value": "Needle"}],
         "users": {"name": "other"}, "folders": {"name": "Elsewhere"}},
        {"id": "mine", "doc_type": "Report", "filename": "mine.pdf",
         "department_id": "dept1", "user_id": "u1", "is_private": False,
         "folder_id": "f1", "created_at": "2024-01-03",
         "document_fields": [{"label": "Name", "value": "Needle"}],
         "users": {"name": "me"}, "folders": {"name": "Mine"}},
    ]
    sb = FakeSupabase(docs)
    user = {"id": "u1", "role": "user", "department_id": "dept1"}

    r = run(sb, user, q="Needle", doc_type=None, folder_id=None, limit=20, offset=0)

    assert [d["id"] for d in r] == ["mine"]


def test_private_peer_rows_do_not_consume_filename_candidate_limit(monkeypatch):
    monkeypatch.setattr(S, "_CANDIDATE_CAP", 1)
    docs = [
        {"id": "private-peer", "doc_type": "Invoice", "filename": "needle.pdf",
         "department_id": "dept1", "user_id": "u2", "is_private": True,
         "folder_id": "f1", "created_at": "2024-01-01", "document_fields": [],
         "users": {"name": "peer"}, "folders": {"name": "Finance"}},
        {"id": "public-mine", "doc_type": "Invoice", "filename": "needle-public.pdf",
         "department_id": "dept1", "user_id": "u1", "is_private": False,
         "folder_id": "f1", "created_at": "2024-01-02", "document_fields": [],
         "users": {"name": "me"}, "folders": {"name": "Finance"}},
    ]
    sb = FakeSupabase(docs)
    user = {"id": "u1", "role": "user", "department_id": "dept1"}

    r = run(sb, user, q="needle", doc_type=None, folder_id=None, limit=20, offset=0)

    assert [d["id"] for d in r] == ["public-mine"]


def test_folder_filter_is_applied_before_candidate_limit(monkeypatch):
    monkeypatch.setattr(S, "_CANDIDATE_CAP", 1)
    docs = [
        {"id": "wrong-folder", "doc_type": "Invoice", "filename": "needle-first.pdf",
         "department_id": "dept1", "user_id": "u1", "is_private": False,
         "folder_id": "other", "created_at": "2024-01-01", "document_fields": [],
         "users": {"name": "me"}, "folders": {"name": "Other"}},
        {"id": "target", "doc_type": "Invoice", "filename": "needle-target.pdf",
         "department_id": "dept1", "user_id": "u1", "is_private": False,
         "folder_id": "wanted", "created_at": "2024-01-02", "document_fields": [],
         "users": {"name": "me"}, "folders": {"name": "Wanted"}},
    ]
    sb = FakeSupabase(docs)
    user = {"id": "u1", "role": "user", "department_id": "dept1"}

    r = run(sb, user, q="needle", doc_type=None, folder_id="wanted", limit=20, offset=0)

    assert [d["id"] for d in r] == ["target"]
