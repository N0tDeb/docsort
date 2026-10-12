"""Read-only route regressions for keeping sync Supabase waits off the event loop."""

import asyncio
import threading

from app.api import cabinet, search, upload


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

    def ilike(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
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


def _user() -> dict:
    return {
        "id": "user-1",
        "name": "User One",
        "role": "user",
        "department_id": "dept-1",
    }


def test_cabinet_recent_read_yields_event_loop():
    started = threading.Event()
    release = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            cabinet.list_recent_documents(
                limit=5,
                supabase=_BlockingDB([], started, release),
                user=_user(),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) == []


def test_search_candidate_read_yields_event_loop():
    started = threading.Event()
    release = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            search.search_documents(
                q="passport",
                doc_type=None,
                folder_id=None,
                limit=20,
                offset=0,
                supabase=_BlockingDB([], started, release),
                user=_user(),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) == []


def test_upload_active_jobs_read_yields_event_loop():
    started = threading.Event()
    release = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            upload.get_active_jobs(
                supabase=_BlockingDB([], started, release),
                user=_user(),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) == []


class _StatusDB:
    def __init__(self, started: threading.Event, release: threading.Event):
        self._started = started
        self._release = release

    def table(self, name: str):
        if name == "upload_jobs":
            return _ImmediateQuery(
                [{
                    "id": "job-1",
                    "status": "done",
                    "step": "done",
                    "progress_pct": 100,
                    "progress": 100,
                    "document_id": "doc-1",
                    "error_message": None,
                }]
            )
        if name == "documents":
            return _BlockingQuery(
                [{
                    "id": "doc-1",
                    "user_id": "user-1",
                    "department_id": "dept-1",
                    "is_private": False,
                    "document_fields": [],
                }],
                self._started,
                self._release,
            )
        raise AssertionError(f"unexpected table: {name}")


class _ImmediateQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _Result(self._data)


def test_upload_completed_document_reauthorization_yields_event_loop():
    started = threading.Event()
    release = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            upload.get_status(
                job_id="job-1",
                supabase=_StatusDB(started, release),
                user=_user(),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    result = asyncio.run(scenario())
    assert result["extracted_data"]["id"] == "doc-1"
