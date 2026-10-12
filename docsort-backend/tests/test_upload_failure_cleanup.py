"""Regression tests for cleanup of partially processed uploads."""
import asyncio

from app.api import upload


class FakeResult:
    def __init__(self, data=None):
        self.data = data or []


class FakeBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.action = None
        self.payload = None
        self.filters = []

    def update(self, payload):
        self.action = "update"
        self.payload = dict(payload)
        return self

    def insert(self, payload):
        self.action = "insert"
        self.payload = payload
        return self

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.table == "upload_jobs" and self.action == "update":
            self.db.job_updates.append(dict(self.payload))
            return FakeResult([dict(self.payload)])

        if self.table == "documents" and self.action == "insert":
            self.db.events.append("document_insert")
            return FakeResult([{"id": "doc-1", **dict(self.payload)}])

        if self.table == "documents" and self.action == "delete":
            self.db.events.append("document_delete")
            self.db.document_delete_filters.append(list(self.filters))
            if self.db.fail_document_cleanup:
                raise RuntimeError("simulated database cleanup outage")
            return FakeResult([{"id": "doc-1"}])

        if self.table == "document_fields" and self.action == "insert":
            self.db.events.append("field_insert")
            if self.db.fail_field_insert:
                raise RuntimeError("simulated field insert failure")
            return FakeResult(self.payload)

        raise AssertionError(f"unexpected operation: {self.table} {self.action}")


class FakeStorageBucket:
    def __init__(self, db):
        self.db = db

    def upload(self, path, data, options=None):
        self.db.events.append("storage_upload")
        self.db.storage_path = path
        return {"path": path}

    def remove(self, paths):
        self.db.events.append("storage_remove")
        self.db.removed_paths.extend(paths)
        return []


class FakeStorage:
    def __init__(self, db):
        self.db = db

    def from_(self, bucket):
        assert bucket == "docsort"
        return FakeStorageBucket(self.db)


class FakeSupabase:
    def __init__(self, *, fail_field_insert=False, fail_document_cleanup=False):
        self.job_updates = []
        self.events = []
        self.document_delete_filters = []
        self.removed_paths = []
        self.storage_path = None
        self.fail_field_insert = fail_field_insert
        self.fail_document_cleanup = fail_document_cleanup
        self.storage = FakeStorage(self)

    def table(self, name):
        return FakeBuilder(self, name)


def _patch_nonduplicate(monkeypatch):
    monkeypatch.setattr(upload.tamper_service, "compute_hash", lambda _: "hash-1")
    monkeypatch.setattr(
        upload.tamper_service,
        "check_duplicate",
        lambda _hash, _user_id, _department_id: {
            "is_duplicate": False,
            "duplicate_of": None,
            "filename": None,
        },
    )


def test_ocr_failure_removes_uploaded_source_after_db_cleanup(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(upload, "get_supabase_sync", lambda: db)
    _patch_nonduplicate(monkeypatch)

    async def fail_ocr(**kwargs):
        raise RuntimeError("simulated OCR failure")

    monkeypatch.setattr(upload.ocr_service, "process_document", fail_ocr)

    asyncio.run(
        upload._process_document_async(
            job_id="job-1",
            user_id="user-1",
            department_id="dept-1",
            file_bytes=b"source",
            filename="invoice.pdf",
            language_hint="eng",
            doc_type_hint="Invoice",
        )
    )

    assert db.events == ["storage_upload", "document_delete", "storage_remove"]
    assert db.document_delete_filters == [[("job_id", "job-1")]]
    assert db.removed_paths == ["documents/dept-1/job-1/invoice.pdf"]
    assert db.job_updates[-1]["status"] == "failed"


def test_field_insert_failure_rolls_back_partial_document_then_storage(monkeypatch):
    db = FakeSupabase(fail_field_insert=True)
    monkeypatch.setattr(upload, "get_supabase_sync", lambda: db)
    _patch_nonduplicate(monkeypatch)

    async def successful_ocr(**kwargs):
        return {
            "doc_type": "Invoice",
            "language": "eng",
            "confidence": 0.95,
            "tamper_flags": [],
            "suggested_folder": "Finance",
            "fields": [{"label": "total", "value": "100", "confidence": 0.9}],
        }

    async def classify(**kwargs):
        return "folder-1", 0.95

    monkeypatch.setattr(upload.ocr_service, "process_document", successful_ocr)
    monkeypatch.setattr(upload.autosort_service, "classify", classify)

    asyncio.run(
        upload._process_document_async(
            job_id="job-2",
            user_id="user-1",
            department_id="dept-1",
            file_bytes=b"source",
            filename="invoice.pdf",
            language_hint="eng",
            doc_type_hint="Invoice",
        )
    )

    assert db.events == [
        "storage_upload",
        "document_insert",
        "field_insert",
        "document_delete",
        "storage_remove",
    ]
    assert db.removed_paths == ["documents/dept-1/job-2/invoice.pdf"]
    assert db.job_updates[-1]["status"] == "failed"


def test_storage_is_retained_if_partial_document_cleanup_fails(monkeypatch):
    db = FakeSupabase(fail_document_cleanup=True)

    cleaned = upload._cleanup_failed_processing(
        db,
        job_id="job-3",
        storage_path="documents/dept-1/job-3/file.pdf",
    )

    assert cleaned is False
    assert db.events == ["document_delete"]
    assert db.removed_paths == []
