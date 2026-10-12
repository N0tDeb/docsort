"""Auth and upload admission must not block FastAPI's event loop on sync work."""

import asyncio
import inspect
import threading
from io import BytesIO

from fastapi import BackgroundTasks, UploadFile
from starlette.requests import Request

from app.api import auth, upload
from app.schemas.auth_schema import LoginRequest, SignupRequest


class _Result:
    def __init__(self, data):
        self.data = data


async def _wait_until_started(started: threading.Event) -> None:
    for _ in range(200):
        if started.is_set():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("blocking operation never started")


def _request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })


def _blocking_callable(result, started: threading.Event, release: threading.Event):
    def call(*_args, **_kwargs):
        started.set()
        release.wait(timeout=0.5)
        return result

    return call


def test_signup_user_lookup_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        auth,
        "get_user_by_email",
        _blocking_callable([], started, release),
    )
    monkeypatch.setattr(auth, "_resolve_signup_department_id", lambda _data: None)
    monkeypatch.setattr(auth, "hash_password", lambda _password: "hashed")
    monkeypatch.setattr(auth, "create_user", lambda _data: {})

    async def scenario():
        task = asyncio.create_task(
            auth.signup(
                request=_request("/auth/signup"),
                data=SignupRequest(email="new@example.com", password="correct-horse"),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    result = asyncio.run(scenario())
    assert result["message"].startswith("Registration request received")


def test_login_password_verification_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    user = {
        "id": "user-1",
        "email": "user@example.com",
        "password": "stored-hash",
        "role": "user",
        "status": "verified",
        "is_active": True,
        "department_id": None,
    }
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: [user])
    monkeypatch.setattr(
        auth,
        "verify_password",
        _blocking_callable(True, started, release),
    )
    monkeypatch.setattr(auth, "create_access_token", lambda _claims: "token")
    monkeypatch.setattr(auth, "_record_login_activity", lambda _user: None)

    async def scenario():
        task = asyncio.create_task(
            auth.login(
                request=_request("/auth/login"),
                data=LoginRequest(email="user@example.com", password="correct-horse"),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    result = asyncio.run(scenario())
    assert result["access_token"] == "token"


def test_signup_password_hash_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: [])
    monkeypatch.setattr(auth, "_resolve_signup_department_id", lambda _data: None)
    monkeypatch.setattr(
        auth,
        "hash_password",
        _blocking_callable("hashed", started, release),
    )
    monkeypatch.setattr(auth, "create_user", lambda _data: {})

    async def scenario():
        task = asyncio.create_task(
            auth.signup(
                request=_request("/auth/signup"),
                data=SignupRequest(email="new@example.com", password="correct-horse"),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    result = asyncio.run(scenario())
    assert result["message"].startswith("Registration request received")


def test_login_activity_write_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    user = {
        "id": "user-1",
        "email": "user@example.com",
        "password": "stored-hash",
        "role": "user",
        "status": "verified",
        "is_active": True,
        "department_id": None,
    }
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: [user])
    monkeypatch.setattr(auth, "verify_password", lambda _password, _hash: True)
    monkeypatch.setattr(auth, "create_access_token", lambda _claims: "token")
    monkeypatch.setattr(
        auth,
        "_record_login_activity",
        _blocking_callable(None, started, release),
    )

    async def scenario():
        task = asyncio.create_task(
            auth.login(
                request=_request("/auth/login"),
                data=LoginRequest(email="user@example.com", password="correct-horse"),
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    result = asyncio.run(scenario())
    assert result["access_token"] == "token"


class _BlockingInsert:
    def __init__(self, started: threading.Event, release: threading.Event):
        self._started = started
        self._release = release
        self._payload = None

    def insert(self, payload):
        self._payload = dict(payload)
        return self

    def execute(self):
        self._started.set()
        self._release.wait(timeout=0.5)
        return _Result([{"id": "job-1", **self._payload}])


class _UploadDB:
    def __init__(self, started: threading.Event, release: threading.Event):
        self._started = started
        self._release = release

    def table(self, name: str):
        assert name == "upload_jobs"
        return _BlockingInsert(self._started, self._release)


def test_upload_job_admission_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    tasks = BackgroundTasks()
    file = UploadFile(filename="report.pdf", file=BytesIO(b"source"))
    monkeypatch.setattr(upload, "validate_upload", lambda name, _data: (name, "application/pdf"))
    monkeypatch.setattr(upload, "validate_document_structure", lambda *_args, **_kwargs: None)

    async def scenario():
        task = asyncio.create_task(
            upload.upload_document(
                request=_request("/upload"),
                background_tasks=tasks,
                file=file,
                language_hint="eng",
                doc_type_hint="Report",
                supabase=_UploadDB(started, release),
                user={"id": "user-1", "department_id": "dept-1"},
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    result = asyncio.run(scenario())
    assert result["id"] == "job-1"
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].func is upload._process_document


def test_upload_parser_validation_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    tasks = BackgroundTasks()
    file = UploadFile(filename="report.pdf", file=BytesIO(b"source"))
    monkeypatch.setattr(upload, "validate_upload", lambda name, _data: (name, "application/pdf"))
    monkeypatch.setattr(
        upload,
        "validate_document_structure",
        _blocking_callable(None, started, release),
    )

    class ImmediateInsert:
        def insert(self, payload):
            self.payload = dict(payload)
            return self

        def execute(self):
            return _Result([{"id": "job-1", **self.payload}])

    class ImmediateDB:
        def table(self, name):
            assert name == "upload_jobs"
            return ImmediateInsert()

    async def scenario():
        task = asyncio.create_task(
            upload.upload_document(
                request=_request("/upload"),
                background_tasks=tasks,
                file=file,
                language_hint="eng",
                doc_type_hint="Report",
                supabase=ImmediateDB(),
                user={"id": "user-1", "department_id": "dept-1"},
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario())["id"] == "job-1"


def test_upload_background_processor_uses_async_backpressure_gate_and_sync_worker():
    assert inspect.iscoroutinefunction(upload._process_document)
    assert not inspect.iscoroutinefunction(upload._process_document_worker)
    assert inspect.iscoroutinefunction(upload._process_document_async)
