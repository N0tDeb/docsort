"""Mutation routes/services must keep synchronous persistence off the event loop."""

import asyncio
import threading
from datetime import datetime, timezone
from uuid import UUID

from app.api import admin, cabinet, graph
from app.schemas.graph_schema import CitizenCreate
from app.services.autosort_service import AutoSortService


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

    def insert(self, *_args, **_kwargs):
        return self

    def update(self, *_args, **_kwargs):
        return self

    def delete(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def or_(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
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
    raise AssertionError("blocking mutation never started")


def _user() -> dict:
    return {
        "id": "user-1",
        "name": "User",
        "role": "user",
        "department_id": "dept-1",
    }


def _admin() -> dict:
    return {
        "id": "admin-1",
        "name": "Admin",
        "role": "admin",
        "department_id": "dept-1",
    }


def test_cabinet_delete_mutation_yields_event_loop():
    started = threading.Event()
    release = threading.Event()
    db = _BlockingDB([{"id": "doc-1", "storage_path": None}], started, release)

    async def scenario():
        task = asyncio.create_task(
            cabinet.delete_document(doc_id="doc-1", supabase=db, user=_user())
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) is None


def test_admin_account_mutation_yields_event_loop():
    started = threading.Event()
    release = threading.Event()
    db = _BlockingDB([{"id": "user-2", "status": "banned"}], started, release)

    async def scenario():
        task = asyncio.create_task(
            admin.ban_user(user_id="user-2", supabase=db, admin=_admin())
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) == {"message": "User banned"}


def test_graph_create_person_mutation_yields_event_loop():
    started = threading.Event()
    release = threading.Event()
    person_id = "11111111-1111-1111-1111-111111111111"
    dept_id = "22222222-2222-2222-2222-222222222222"
    row = {
        "id": person_id,
        "dept_id": dept_id,
        "full_name": "Asha Patil",
        "dob": None,
        "uid_number": None,
        "gender": None,
        "address": None,
        "phone": None,
        "is_flagged": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db = _BlockingDB([row], started, release)
    body = CitizenCreate(dept_id=UUID(dept_id), full_name="Asha Patil")
    user = {**_user(), "department_id": dept_id}

    async def scenario():
        task = asyncio.create_task(graph.create_citizen(body=body, user=user, db=db))
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    result = asyncio.run(scenario())
    assert str(result.id) == person_id


def test_autosort_folder_lookup_yields_event_loop():
    started = threading.Event()
    release = threading.Event()
    db = _BlockingDB([{"id": "folder-1"}], started, release)
    service = AutoSortService()

    async def scenario():
        task = asyncio.create_task(
            service.classify(
                doc_type="invoice",
                fields=[],
                department_id="dept-1",
                supabase=db,
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) == ("folder-1", 0.9)


class _ImmediateMutationQuery:
    def __init__(self, data):
        self._data = data

    def delete(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def or_(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _Result(self._data)


class _BlockingRemoveBucket:
    def __init__(self, started: threading.Event, release: threading.Event):
        self._started = started
        self._release = release

    def remove(self, _paths):
        self._started.set()
        self._release.wait(timeout=0.5)
        return None


class _StorageFacade:
    def __init__(self, bucket):
        self._bucket = bucket

    def from_(self, _bucket_name: str):
        return self._bucket


class _DeleteWithBlockingStorageDB:
    def __init__(self, started: threading.Event, release: threading.Event):
        self.storage = _StorageFacade(_BlockingRemoveBucket(started, release))

    def table(self, name: str):
        if name != "documents":
            raise AssertionError(f"unexpected table: {name}")
        return _ImmediateMutationQuery(
            [{"id": "doc-1", "storage_path": "dept-1/doc-1.pdf"}]
        )


def test_cabinet_delete_storage_cleanup_yields_event_loop():
    started = threading.Event()
    release = threading.Event()
    db = _DeleteWithBlockingStorageDB(started, release)

    async def scenario():
        task = asyncio.create_task(
            cabinet.delete_document(doc_id="doc-1", supabase=db, user=_user())
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) is None
