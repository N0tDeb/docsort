"""Folder ZIP compression must not occupy the FastAPI event-loop thread."""

import asyncio
import hashlib
import threading
import time

from app.api import export


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table: str, documents: list[dict]):
        self._table = table
        self._documents = documents

    def select(self, *_args, **_kwargs): return self
    def eq(self, *_args, **_kwargs): return self
    def or_(self, *_args, **_kwargs): return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, *_args, **_kwargs): return self

    def execute(self):
        if self._table == "folders":
            return _Result([{"id": "folder-1", "name": "Finance"}])
        if self._table == "documents":
            return _Result(self._documents)
        raise AssertionError(self._table)


class _Bucket:
    def download(self, _path: str) -> bytes:
        return b"payload" * 128


class _Storage:
    def from_(self, bucket: str):
        assert bucket == "docsort"
        return _Bucket()


class _DB:
    def __init__(self):
        self.storage = _Storage()
        self.documents = [{
            "id": "doc-1",
            "user_id": "user-1",
            "department_id": "dept-1",
            "is_private": False,
            "filename": "report.pdf",
            "storage_path": "documents/dept-1/report.pdf",
            "doc_type": "Report",
            "created_at": "2026-01-01T00:00:00Z",
            "is_tampered": False,
            "ocr_confidence": 0.9,
            "users": {"name": "User"},
            "document_fields": [],
            "file_hash": hashlib.sha256(b"payload" * 128).hexdigest(),
        }]

    def table(self, name: str):
        return _Query(name, self.documents)


async def _wait_until_started(started: threading.Event) -> None:
    for _ in range(200):
        if started.is_set():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("ZIP compression never started")


def test_folder_zip_compression_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    original_writestr = export.zipfile.ZipFile.writestr

    def blocking_writestr(self, *args, **kwargs):
        started.set()
        release.wait(timeout=0.5)
        return original_writestr(self, *args, **kwargs)

    monkeypatch.setattr(export.zipfile.ZipFile, "writestr", blocking_writestr)

    async def scenario():
        loop_started = time.monotonic()
        task = asyncio.create_task(
            export.export_folder(
                folder_id="folder-1",
                format="zip",
                supabase=_DB(),
                user={"id": "user-1", "department_id": "dept-1", "role": "user"},
            )
        )
        await _wait_until_started(started)
        # If writestr executes on the event-loop thread, this 50 ms sleep cannot
        # resume until the blocking 500 ms wait above times out. Worker-pool
        # compression keeps the scheduling delay comfortably below that bound.
        await asyncio.sleep(0.05)
        elapsed = time.monotonic() - loop_started
        assert elapsed < 0.25, f"ZIP compression stalled the event loop for {elapsed:.3f}s"
        release.set()
        response = await task

        # Consume the StreamingResponse body as an ASGI server/client would.
        # This also executes iter_zip()'s finally block and closes its spool.
        async for _ in response.body_iterator:
            pass

        return response

    response = asyncio.run(scenario())
    assert response.media_type == "application/zip"
