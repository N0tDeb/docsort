"""Regression tests for source-file durability in the upload pipeline."""
import asyncio

from app.api import upload


class FakeResult:
    def __init__(self, data=None):
        self.data = data or []


class JobBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.payload = None
        self.filters = []
        self.action = None

    def update(self, payload):
        self.action = "update"
        self.payload = dict(payload)
        return self

    def insert(self, payload):
        self.action = "insert"
        self.payload = dict(payload)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.table != "upload_jobs":
            self.db.unexpected_table_writes.append((self.table, self.action, self.payload))
            raise AssertionError(f"unexpected write to {self.table}")

        if self.action == "update":
            self.db.job_updates.append(dict(self.payload))
            return FakeResult([dict(self.payload)])
        raise AssertionError(f"unexpected upload_jobs action: {self.action}")


class FailingStorageBucket:
    def __init__(self, db):
        self.db = db

    def upload(self, path, data, options=None):
        self.db.storage_attempts.append((path, data))
        raise RuntimeError("simulated storage outage with internal-details")


class FailingStorage:
    def __init__(self, db):
        self.db = db

    def from_(self, bucket):
        assert bucket == "docsort"
        return FailingStorageBucket(self.db)


class FakeSupabase:
    def __init__(self):
        self.job_updates = []
        self.storage_attempts = []
        self.unexpected_table_writes = []
        self.storage = FailingStorage(self)

    def table(self, name):
        return JobBuilder(self, name)


def test_storage_failure_aborts_processing_and_marks_job_failed(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(upload, "get_supabase_sync", lambda: db)
    monkeypatch.setattr(upload.tamper_service, "compute_hash", lambda _: "hash")
    monkeypatch.setattr(
        upload.tamper_service,
        "check_duplicate",
        lambda _hash, _user_id, _department_id: {"is_duplicate": False, "duplicate_of": None, "filename": None},
    )

    ocr_called = False

    async def must_not_run_ocr(**kwargs):
        nonlocal ocr_called
        ocr_called = True
        raise AssertionError("OCR must not run when source storage failed")

    monkeypatch.setattr(upload.ocr_service, "process_document", must_not_run_ocr)

    asyncio.run(
        upload._process_document_async(
            job_id="job-1",
            user_id="user-1",
            department_id="dept-1",
            file_bytes=b"source-file",
            filename="invoice.pdf",
            language_hint="eng",
            doc_type_hint="Invoice",
        )
    )

    assert db.storage_attempts == [
        ("documents/dept-1/job-1/invoice.pdf", b"source-file")
    ]
    assert ocr_called is False
    assert db.unexpected_table_writes == []

    final_update = db.job_updates[-1]
    assert final_update["status"] == "failed"
    assert final_update["error_message"] == "Document processing failed. Please retry."
    assert "internal-details" not in final_update["error_message"]
    assert final_update["progress"]["processing_ms"] >= 0
    assert not any(update.get("status") == "done" for update in db.job_updates)


def test_exact_duplicate_skips_storage_and_ocr(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(upload, "get_supabase_sync", lambda: db)
    monkeypatch.setattr(upload.tamper_service, "compute_hash", lambda _: "same-hash")
    def scoped_duplicate_check(file_hash, user_id, department_id):
        assert file_hash == "same-hash"
        assert user_id == "user-1"
        assert department_id == "dept-1"
        return {
            "is_duplicate": True,
            "duplicate_of": "existing-doc-1",
            "filename": "existing.pdf",
        }

    monkeypatch.setattr(
        upload.tamper_service,
        "check_duplicate",
        scoped_duplicate_check,
    )

    async def must_not_run_ocr(**kwargs):
        raise AssertionError("OCR must not run for an exact duplicate")

    monkeypatch.setattr(upload.ocr_service, "process_document", must_not_run_ocr)

    asyncio.run(
        upload._process_document_async(
            job_id="job-duplicate",
            user_id="user-1",
            department_id="dept-1",
            file_bytes=b"duplicate-source",
            filename="copy.pdf",
            language_hint="eng",
            doc_type_hint="",
        )
    )

    assert db.storage_attempts == []
    assert db.unexpected_table_writes == []
    final_update = db.job_updates[-1]
    assert final_update["status"] == "done"
    assert final_update["document_id"] == "existing-doc-1"
    assert final_update["step"] == 5
    assert final_update["progress_pct"] == 1.0
    assert final_update["progress"]["duplicate_reused"] is True
    assert final_update["progress"]["processing_ms"] >= 0
