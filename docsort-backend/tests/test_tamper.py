"""Tamper service: hashing (pure) + duplicate/integrity checks (mocked DB)."""
import hashlib
from app.services.tamper_service import TamperService

svc = TamperService()


def test_compute_hash_matches_sha256():
    data = b"hello world"
    assert svc.compute_hash(data) == hashlib.sha256(data).hexdigest()


def test_compute_hash_is_deterministic():
    assert svc.compute_hash(b"abc") == svc.compute_hash(b"abc")


def test_compute_hash_changes_with_content():
    assert svc.compute_hash(b"abc") != svc.compute_hash(b"abd")


class _Chain:
    def __init__(self, data):
        self._data = data
        self.filters = []
        self.limit_value = None

    def select(self, *a, **k): return self
    def eq(self, col, value):
        self.filters.append(("eq", col, value))
        return self
    def is_(self, col, value):
        self.filters.append(("is", col, value))
        return self
    def limit(self, value):
        self.limit_value = value
        return self
    def execute(self):
        rows = list(self._data)
        for op, col, value in self.filters:
            if op == "eq":
                rows = [row for row in rows if row.get(col) == value]
            elif op == "is" and value == "null":
                rows = [row for row in rows if row.get(col) is None]
        if self.limit_value is not None:
            rows = rows[:self.limit_value]
        class R: pass
        r = R(); r.data = rows; return r


class _FakeDB:
    def __init__(self, data): self._data = data
    def table(self, *_): return _Chain(self._data)


def test_check_duplicate_found_only_for_same_owner_and_department(monkeypatch):
    fake = _FakeDB([
        {"id": "other-user", "filename": "other.pdf", "created_at": "2024", "file_hash": "somehash", "user_id": "u2", "department_id": "d1"},
        {"id": "other-dept", "filename": "baseline.pdf", "created_at": "2024", "file_hash": "somehash", "user_id": "u1", "department_id": "d2"},
        {"id": "doc9", "filename": "a.pdf", "created_at": "2024", "file_hash": "somehash", "user_id": "u1", "department_id": "d1"},
    ])
    monkeypatch.setattr("app.services.tamper_service.get_supabase_sync", lambda: fake)
    out = svc.check_duplicate("somehash", "u1", "d1")
    assert out["is_duplicate"] is True and out["duplicate_of"] == "doc9"


def test_check_duplicate_does_not_reuse_other_users_document(monkeypatch):
    fake = _FakeDB([
        {"id": "doc9", "filename": "a.pdf", "created_at": "2024", "file_hash": "samehash", "user_id": "u2", "department_id": "d1"},
    ])
    monkeypatch.setattr("app.services.tamper_service.get_supabase_sync", lambda: fake)
    out = svc.check_duplicate("samehash", "u1", "d1")
    assert out == {"is_duplicate": False, "duplicate_of": None, "filename": None}


def test_check_duplicate_does_not_reuse_same_users_other_department_document(monkeypatch):
    fake = _FakeDB([
        {"id": "doc9", "filename": "a.pdf", "created_at": "2024", "file_hash": "samehash", "user_id": "u1", "department_id": "d2"},
    ])
    monkeypatch.setattr("app.services.tamper_service.get_supabase_sync", lambda: fake)
    out = svc.check_duplicate("samehash", "u1", "d1")
    assert out == {"is_duplicate": False, "duplicate_of": None, "filename": None}


def test_check_duplicate_without_department_only_reuses_unassigned_document(monkeypatch):
    fake = _FakeDB([
        {"id": "other-dept-baseline", "filename": "baseline.pdf", "created_at": "2024", "file_hash": "samehash", "user_id": "u1", "department_id": "d2"},
        {"id": "unassigned", "filename": "own.pdf", "created_at": "2024", "file_hash": "samehash", "user_id": "u1", "department_id": None},
    ])
    monkeypatch.setattr("app.services.tamper_service.get_supabase_sync", lambda: fake)
    out = svc.check_duplicate("samehash", "u1", None)
    assert out["is_duplicate"] is True and out["duplicate_of"] == "unassigned"


def test_check_duplicate_not_found(monkeypatch):
    monkeypatch.setattr("app.services.tamper_service.get_supabase_sync", lambda: _FakeDB([]))
    out = svc.check_duplicate("nohash", "u1", "d1")
    assert out["is_duplicate"] is False and out["duplicate_of"] is None


def test_verify_integrity_detects_match_and_tamper(monkeypatch):
    original = b"the real file"
    stored = svc.compute_hash(original)
    monkeypatch.setattr("app.services.tamper_service.get_supabase_sync",
                        lambda: _FakeDB([{"id": "doc1", "file_hash": stored}]))
    ok = svc.verify_integrity("doc1", original)
    assert ok["is_tampered"] is False
    bad = svc.verify_integrity("doc1", b"a modified file")
    assert bad["is_tampered"] is True
