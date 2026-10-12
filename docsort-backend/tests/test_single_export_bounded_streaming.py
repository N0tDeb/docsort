"""Single-document export must not buffer the whole Storage object in RAM."""

import asyncio
import hashlib

import pytest
from fastapi import HTTPException

from app.api import export


class _Result:
    def __init__(self, data):
        self.data = data


class _DocumentQuery:
    def __init__(self, file_hash):
        self.file_hash = file_hash

    def select(self, *_args, **_kwargs): return self
    def eq(self, *_args, **_kwargs): return self
    def or_(self, *_args, **_kwargs): return self

    def execute(self):
        return _Result([{
            "id": "doc-1",
            "filename": "report.pdf",
            "storage_path": "documents/dept-1/report.pdf",
            "user_id": "user-1",
            "department_id": "dept-1",
            "is_private": False,
            "file_hash": self.file_hash,
        }])


class _Bucket:
    def __init__(self, *, payload: bytes = b"", fail_after_first_chunk: bool = False):
        self.payload = payload
        self.fail_after_first_chunk = fail_after_first_chunk
        self.used_streaming_copy = False
        self.rolled_to_disk = False
        self.sink_closed_after_failure = None

    def download(self, _path: str):
        raise AssertionError("single-document export must not use whole-object download()")

    def download_to_file(self, _path: str, sink, *, chunk_size: int = 64 * 1024):
        self.used_streaming_copy = True
        split = max(1, len(self.payload) // 2)
        sink.write(self.payload[:split])
        if self.fail_after_first_chunk:
            try:
                raise OSError("storage stream interrupted")
            finally:
                # The route owns the sink and must close it after this method unwinds.
                self.sink_closed_after_failure = sink
        sink.write(self.payload[split:])
        self.rolled_to_disk = bool(getattr(sink, "_rolled", False))
        return len(self.payload)


class _Storage:
    def __init__(self, bucket):
        self.bucket = bucket

    def from_(self, name: str):
        assert name == "docsort"
        return self.bucket


class _DB:
    def __init__(self, bucket):
        self.bucket = bucket
        self.storage = _Storage(bucket)

    def table(self, name: str):
        assert name == "documents"
        return _DocumentQuery(hashlib.sha256(self.bucket.payload).hexdigest())


USER = {"id": "user-1", "role": "user", "department_id": "dept-1"}


async def _read_response(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks)


def test_single_export_stages_storage_in_bounded_spool_before_streaming(monkeypatch):
    payload = b"0123456789abcdef" * 16
    bucket = _Bucket(payload=payload)
    monkeypatch.setattr(export.settings, "export_spool_memory_bytes", 32)

    response = asyncio.run(export.export_single_document("doc-1", supabase=_DB(bucket), user=USER))

    assert bucket.used_streaming_copy is True
    assert bucket.rolled_to_disk is True
    assert response.media_type == "application/pdf"
    assert asyncio.run(_read_response(response)) == payload


def test_single_export_storage_stream_failure_is_fail_closed(monkeypatch):
    bucket = _Bucket(payload=b"partial-payload", fail_after_first_chunk=True)
    monkeypatch.setattr(export.settings, "export_spool_memory_bytes", 8)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(export.export_single_document("doc-1", supabase=_DB(bucket), user=USER))

    assert exc_info.value.status_code == 500
    assert bucket.used_streaming_copy is True
    assert bucket.sink_closed_after_failure is not None
    assert bucket.sink_closed_after_failure.closed is True
