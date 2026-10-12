"""Regression coverage for DB-backed duplicate/folder concurrency invariants."""
import asyncio
from pathlib import Path

from app.api import upload
from app.services.autosort_service import AutoSortService


SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")


class FakeResult:
    def __init__(self, data=None):
        self.data = data or []


class UploadBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.action = "select"
        self.payload = None
        self.filters = []

    def select(self, *args, **kwargs):
        self.action = "select"
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = dict(payload)
        return self

    def insert(self, payload):
        self.action = "insert"
        self.payload = dict(payload)
        return self

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, value):
        return self

    def execute(self):
        if self.table == "upload_jobs" and self.action == "update":
            self.db.job_updates.append(dict(self.payload))
            return FakeResult([dict(self.payload)])
        if self.table == "documents" and self.action == "insert":
            self.db.document_insert_attempts += 1
            raise RuntimeError(
                'HTTP 409 on insert documents: duplicate key value violates unique constraint '
                '"uq_documents_owner_department_hash"'
            )
        if self.table == "documents" and self.action == "select":
            if self.db.committed_doc_id:
                return FakeResult([{"id": self.db.committed_doc_id}])
            return FakeResult([])
        if self.table == "documents" and self.action == "delete":
            self.db.cleanup_filters.append(list(self.filters))
            return FakeResult([])
        raise AssertionError(f"unexpected operation: {self.table} {self.action}")


class StorageBucket:
    def __init__(self, db):
        self.db = db

    def upload(self, path, data, options=None):
        self.db.uploaded_paths.append(path)
        return {"path": path}

    def remove(self, paths):
        self.db.removed_paths.extend(paths)
        return []


class Storage:
    def __init__(self, db):
        self.db = db

    def from_(self, bucket):
        assert bucket == "docsort"
        return StorageBucket(self.db)


class UploadDB:
    def __init__(self, *, committed_doc_id=None):
        self.job_updates = []
        self.committed_doc_id = committed_doc_id
        self.document_insert_attempts = 0
        self.cleanup_filters = []
        self.uploaded_paths = []
        self.removed_paths = []
        self.storage = Storage(self)

    def table(self, name):
        return UploadBuilder(self, name)


class FolderBuilder:
    def __init__(self, db):
        self.db = db
        self.action = "select"
        self.filters = []

    def select(self, *args, **kwargs):
        self.action = "select"
        return self

    def insert(self, payload):
        self.action = "insert"
        self.db.insert_payloads.append(dict(payload))
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, value):
        return self

    def execute(self):
        if self.action == "insert":
            raise RuntimeError(
                'HTTP 409 on insert folders: duplicate key value violates unique constraint '
                '"uq_system_folders_department_name"'
            )
        self.db.select_calls += 1
        if self.db.select_calls == 1:
            return FakeResult([])
        return FakeResult([{"id": "folder-winner"}])


class FolderDB:
    def __init__(self):
        self.select_calls = 0
        self.insert_payloads = []

    def table(self, name):
        assert name == "folders"
        return FolderBuilder(self)


def test_duplicate_conflict_detection_is_limited_to_named_invariants():
    assert upload._is_duplicate_document_conflict(
        RuntimeError('duplicate constraint "uq_documents_owner_department_hash"')
    )
    assert upload._is_duplicate_document_conflict(
        RuntimeError('duplicate constraint "uq_documents_owner_unassigned_hash"')
    )
    assert not upload._is_duplicate_document_conflict(
        RuntimeError('HTTP 409 on a different unique constraint')
    )


def test_schema_enforces_duplicate_document_uniqueness_for_assigned_and_unassigned_users():
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_owner_department_hash" in SCHEMA
    assert "ON documents(user_id, department_id, file_hash)" in SCHEMA
    assert "department_id IS NOT NULL" in SCHEMA
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_owner_unassigned_hash" in SCHEMA
    assert "ON documents(user_id, file_hash)" in SCHEMA
    assert "department_id IS NULL" in SCHEMA


def test_schema_enforces_one_system_folder_name_per_department():
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_system_folders_department_name" in SCHEMA
    assert "ON folders(department_id, name)" in SCHEMA
    assert "is_system = true" in SCHEMA.lower()


def test_autosort_recovers_winning_folder_after_concurrent_insert_conflict():
    db = FolderDB()
    folder_id = asyncio.run(
        AutoSortService()._get_or_create_folder("dept-1", "Finance", db)
    )

    assert folder_id == "folder-winner"
    assert db.insert_payloads == [{
        "department_id": "dept-1",
        "name": "Finance",
        "is_system": True,
    }]


def test_concurrent_duplicate_insert_reuses_winner_and_removes_losing_source(monkeypatch):
    db = UploadDB()
    monkeypatch.setattr(upload, "get_supabase_sync", lambda: db)
    monkeypatch.setattr(upload.tamper_service, "compute_hash", lambda _data: "same-hash")

    duplicate_checks = iter([
        {"is_duplicate": False, "duplicate_of": None, "filename": None},
        {"is_duplicate": True, "duplicate_of": "doc-winner", "filename": "original.pdf"},
    ])
    monkeypatch.setattr(
        upload.tamper_service,
        "check_duplicate",
        lambda _hash, _user, _dept: next(duplicate_checks),
    )

    async def fake_ocr(**kwargs):
        return {
            "doc_type": "Invoice",
            "language": "eng",
            "raw_text": "invoice",
            "ocr_confidence": 0.9,
            "classification_confidence": 0.9,
            "suggested_folder": "Finance",
            "fields": [],
            "tamper_flags": [],
        }

    async def fake_classify(**kwargs):
        return "folder-finance", 0.9

    monkeypatch.setattr(upload.ocr_service, "process_document", fake_ocr)
    monkeypatch.setattr(upload.autosort_service, "classify", fake_classify)

    asyncio.run(
        upload._process_document_async(
            job_id="job-loser",
            user_id="user-1",
            department_id="dept-1",
            file_bytes=b"same bytes",
            filename="copy.pdf",
            language_hint="eng",
            doc_type_hint="Invoice",
        )
    )

    assert db.document_insert_attempts == 1
    assert db.uploaded_paths == ["documents/dept-1/job-loser/copy.pdf"]
    assert db.removed_paths == ["documents/dept-1/job-loser/copy.pdf"]
    assert db.cleanup_filters == [[("job_id", "job-loser")]]

    final = db.job_updates[-1]
    assert final["status"] == "done"
    assert final["document_id"] == "doc-winner"
    assert final["progress"]["duplicate_reused"] is True


def test_retry_conflict_from_same_job_keeps_committed_document_and_source(monkeypatch):
    db = UploadDB(committed_doc_id="doc-committed")
    monkeypatch.setattr(upload, "get_supabase_sync", lambda: db)
    monkeypatch.setattr(upload.tamper_service, "compute_hash", lambda _data: "same-hash")

    calls = 0
    def duplicate_check(_hash, _user, _dept):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("same-job recovery must not look for a competing duplicate")
        return {"is_duplicate": False, "duplicate_of": None, "filename": None}

    monkeypatch.setattr(upload.tamper_service, "check_duplicate", duplicate_check)

    async def fake_ocr(**kwargs):
        return {
            "doc_type": "Invoice",
            "language": "eng",
            "raw_text": "invoice",
            "ocr_confidence": 0.9,
            "classification_confidence": 0.9,
            "suggested_folder": "Finance",
            "fields": [],
            "tamper_flags": [],
        }

    async def fake_classify(**kwargs):
        return "folder-finance", 0.9

    async def fake_relationships(**kwargs):
        assert kwargs["document_id"] == "doc-committed"
        return {
            "people_linked": 0,
            "citizens_created": 0,
            "edges_created": 0,
            "duplicate_found": False,
        }

    monkeypatch.setattr(upload.ocr_service, "process_document", fake_ocr)
    monkeypatch.setattr(upload.autosort_service, "classify", fake_classify)
    monkeypatch.setattr(upload, "process_relationships", fake_relationships)
    monkeypatch.setattr(upload.activity_service, "log_upload", lambda *args, **kwargs: None)

    asyncio.run(
        upload._process_document_async(
            job_id="job-retried",
            user_id="user-1",
            department_id="dept-1",
            file_bytes=b"same bytes",
            filename="copy.pdf",
            language_hint="eng",
            doc_type_hint="Invoice",
        )
    )

    assert db.removed_paths == []
    final = db.job_updates[-1]
    assert final["status"] == "done"
    assert final["document_id"] == "doc-committed"
    assert final["progress"].get("duplicate_reused") is not True
