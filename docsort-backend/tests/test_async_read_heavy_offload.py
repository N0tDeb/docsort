"""Read-heavy Admin/Graph/Export routes must not block the FastAPI event loop."""

import asyncio
import hashlib
import threading

from app.api import admin, export, graph


class _Result:
    def __init__(self, data):
        self.data = data
        self.count = None


class _BlockingQuery:
    def __init__(self, data, started: threading.Event, release: threading.Event):
        self._data = data
        self._started = started
        self._release = release

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def or_(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def lt(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def range(self, *_args, **_kwargs):
        return self

    def execute(self):
        self._started.set()
        self._release.wait(timeout=0.5)
        return _Result(self._data)


class _BlockingDB:
    def __init__(self, data, started: threading.Event, release: threading.Event):
        self._data = data
        self._started = started
        self._release = release

    def table(self, _name: str):
        return _BlockingQuery(self._data, self._started, self._release)


async def _wait_until_started(started: threading.Event) -> None:
    for _ in range(200):
        if started.is_set():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("blocking database operation never started")


def _admin_user() -> dict:
    return {
        "id": "admin-1",
        "name": "Admin",
        "role": "admin",
        "department_id": "dept-1",
    }


def _normal_user() -> dict:
    return {
        "id": "user-1",
        "name": "User",
        "role": "user",
        "department_id": "dept-1",
    }


def test_admin_presence_read_yields_event_loop():
    started = threading.Event()
    release = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            admin.get_presence(
                supabase=_BlockingDB([], started, release),
                admin=_admin_user(),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) == []


def test_graph_person_read_yields_event_loop():
    started = threading.Event()
    release = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            graph.get_citizen(
                citizen_id="person-1",
                user=_normal_user(),
                db=_BlockingDB([], started, release),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        try:
            await task
        except Exception as exc:
            # The empty result is expected to resolve as the route's 404 only
            # after the blocked database operation has completed.
            assert getattr(exc, "status_code", None) == 404
            return
        raise AssertionError("expected person-not-found response")

    asyncio.run(scenario())


def test_export_single_document_authorization_yields_event_loop():
    started = threading.Event()
    release = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            export.export_single_document(
                doc_id="doc-1",
                supabase=_BlockingDB([], started, release),
                user=_normal_user(),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        try:
            await task
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404
            return
        raise AssertionError("expected document-not-found response")

    asyncio.run(scenario())


class _ImmediateQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def or_(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _Result(self._data)


class _BlockingBucket:
    def __init__(self, started: threading.Event, release: threading.Event):
        self._started = started
        self._release = release

    def download_to_file(self, _path: str, sink, *, chunk_size: int = 64 * 1024):
        self._started.set()
        self._release.wait(timeout=0.5)
        sink.write(b"pdf-bytes")
        return len(b"pdf-bytes")


class _StorageFacade:
    def __init__(self, bucket):
        self._bucket = bucket

    def from_(self, _bucket_name: str):
        return self._bucket


class _ExportDB:
    def __init__(self, started: threading.Event, release: threading.Event):
        self.storage = _StorageFacade(_BlockingBucket(started, release))

    def table(self, name: str):
        if name != "documents":
            raise AssertionError(f"unexpected table: {name}")
        return _ImmediateQuery(
            [{
                "filename": "report.pdf",
                "storage_path": "dept-1/report.pdf",
                "user_id": "user-1",
                "department_id": "dept-1",
                "is_private": False,
                "file_hash": hashlib.sha256(b"pdf-bytes").hexdigest(),
            }]
        )


def test_export_storage_download_yields_event_loop():
    started = threading.Event()
    release = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            export.export_single_document(
                doc_id="doc-1",
                supabase=_ExportDB(started, release),
                user=_normal_user(),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        response = await task

        # Consume the StreamingResponse body as an ASGI server/client would.
        # This also executes iter_file()'s finally block and closes its spool.
        async for _ in response.body_iterator:
            pass

        return response

    response = asyncio.run(scenario())
    assert response.media_type == "application/pdf"
