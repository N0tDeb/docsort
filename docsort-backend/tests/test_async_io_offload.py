"""Regression coverage for keeping synchronous network I/O off the event loop."""

import asyncio
import threading

from fastapi.security import HTTPAuthorizationCredentials
from starlette.websockets import WebSocketDisconnect

import app.main as main
from app.core import security


def _resolved_live_user(payload: dict) -> dict:
    return {
        "id": str(payload["sub"]),
        "email": "live@example.com",
        "role": "user",
        "department_id": "dept-1",
        "name": "Live User",
        "designation": "Staff",
    }


async def _wait_until_started(started: threading.Event) -> None:
    for _ in range(200):
        if started.is_set():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("blocking operation never started")


def _blocking_live_user(started: threading.Event, release: threading.Event):
    def resolve(payload: dict) -> dict:
        started.set()
        release.wait(timeout=0.5)
        return _resolved_live_user(payload)

    return resolve


def test_http_auth_live_lookup_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        security,
        "resolve_authenticated_user",
        _blocking_live_user(started, release),
    )
    token = security.create_access_token({"sub": "user-1"})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    async def scenario():
        auth_task = asyncio.create_task(security.get_current_user(credentials))
        await _wait_until_started(started)

        # If get_current_user called the synchronous resolver directly, the
        # event loop could not reach this assertion until the wait timed out.
        assert not auth_task.done()
        release.set()
        return await auth_task

    user = asyncio.run(scenario())
    assert user["id"] == "user-1"


class _FakeWebSocket:
    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}
        self.closed = []

    async def close(self, code: int):
        self.closed.append(code)

    async def receive_text(self):
        raise WebSocketDisconnect()


class _FakeManager:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    async def connect(self, websocket, user_id: str, subprotocol=None):
        self.connected.append((websocket, user_id, subprotocol))
        return True

    def disconnect(self, user_id: str, websocket):
        self.disconnected.append((user_id, websocket))


def test_websocket_live_lookup_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        main,
        "resolve_authenticated_user",
        _blocking_live_user(started, release),
    )
    fake_manager = _FakeManager()
    monkeypatch.setattr(main, "manager", fake_manager)

    token = security.create_access_token({"sub": "user-1"})
    websocket = _FakeWebSocket(token)

    async def scenario():
        ws_task = asyncio.create_task(main.websocket_endpoint(websocket, "user-1"))
        await _wait_until_started(started)
        assert not ws_task.done()
        release.set()
        await ws_task

    asyncio.run(scenario())

    assert websocket.closed == []
    assert fake_manager.connected == [(websocket, "user-1", None)]
    assert fake_manager.disconnected == [("user-1", websocket)]


class _SlowAnalyticsResult:
    def __init__(self, data):
        self.data = data
        self.count = None


class _SlowAnalyticsQuery:
    def __init__(self, data, started: threading.Event, release: threading.Event):
        self._data = data
        self._started = started
        self._release = release

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        self._started.set()
        self._release.wait(timeout=0.5)
        return _SlowAnalyticsResult(self._data)


class _SlowAnalyticsDB:
    def __init__(self, started: threading.Event, release: threading.Event):
        self._started = started
        self._release = release

    def table(self, name: str):
        if name in {"documents", "upload_jobs"}:
            return _SlowAnalyticsQuery([], self._started, self._release)
        raise AssertionError(f"unexpected table: {name}")


def test_department_analytics_blocking_queries_yield_event_loop():
    from app.api.analytics import get_department_analytics

    started = threading.Event()
    release = threading.Event()

    async def scenario():
        analytics_task = asyncio.create_task(
            get_department_analytics(
                supabase=_SlowAnalyticsDB(started, release),
                user={"id": "user-1", "department_id": None, "role": "user"},
            )
        )
        await _wait_until_started(started)
        assert not analytics_task.done()
        release.set()
        return await analytics_task

    result = asyncio.run(scenario())
    assert result["total_documents"] == 0
    assert result["active_users_24h"] == 1
