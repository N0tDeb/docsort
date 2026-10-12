import asyncio

import pytest

from app.core.config import Settings
from app.core.websocket import ConnectionManager


class FakeWebSocket:
    def __init__(self, *, fail_accept: bool = False):
        self.fail_accept = fail_accept
        self.accepted = False
        self.accepted_subprotocol = None
        self.closed = []
        self.messages = []

    async def accept(self, subprotocol=None):
        if self.fail_accept:
            raise RuntimeError("accept failed")
        self.accepted = True
        self.accepted_subprotocol = subprotocol

    async def close(self, code: int):
        self.closed.append(code)

    async def send_json(self, message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_per_user_connection_cap_rejects_excess_socket_before_accept():
    manager = ConnectionManager(max_connections_per_user=2)
    first = FakeWebSocket()
    second = FakeWebSocket()
    excess = FakeWebSocket()

    assert await manager.connect(first, "user-1") is True
    assert await manager.connect(second, "user-1") is True
    assert await manager.connect(excess, "user-1") is False

    assert first.accepted is True
    assert second.accepted is True
    assert excess.accepted is False
    assert excess.closed == [1013]
    assert manager.active_connections["user-1"] == {first, second}


@pytest.mark.asyncio
async def test_connection_slot_is_reusable_after_exact_disconnect():
    manager = ConnectionManager(max_connections_per_user=2)
    first = FakeWebSocket()
    second = FakeWebSocket()
    replacement = FakeWebSocket()

    await manager.connect(first, "user-1")
    await manager.connect(second, "user-1")
    manager.disconnect("user-1", first)

    assert await manager.connect(replacement, "user-1") is True
    assert manager.active_connections["user-1"] == {second, replacement}


@pytest.mark.asyncio
async def test_failed_accept_releases_reserved_connection_slot():
    manager = ConnectionManager(max_connections_per_user=1)
    failing = FakeWebSocket(fail_accept=True)

    with pytest.raises(RuntimeError, match="accept failed"):
        await manager.connect(failing, "user-1")

    assert "user-1" not in manager.active_connections

    replacement = FakeWebSocket()
    assert await manager.connect(replacement, "user-1") is True
    assert manager.active_connections["user-1"] == {replacement}


def test_websocket_connection_limit_must_be_positive():
    with pytest.raises(Exception):
        Settings(
            _env_file=None,
            jwt_secret="test-secret-value-at-least-32-bytes-12345",
            supabase_url="https://example.supabase.co",
            supabase_service_key="service-key",
            max_websocket_connections_per_user=0,
        )

@pytest.mark.asyncio
async def test_pending_handshake_reserves_slot_against_concurrent_connect():
    manager = ConnectionManager(max_connections_per_user=1)
    accept_started = asyncio.Event()
    release_accept = asyncio.Event()

    class BlockingAcceptWebSocket(FakeWebSocket):
        async def accept(self, subprotocol=None):
            accept_started.set()
            await release_accept.wait()
            await super().accept(subprotocol=subprotocol)

    first = BlockingAcceptWebSocket()
    second = FakeWebSocket()

    first_task = asyncio.create_task(manager.connect(first, "user-1"))
    await accept_started.wait()

    assert await manager.connect(second, "user-1") is False
    assert second.accepted is False
    assert second.closed == [1013]

    release_accept.set()
    assert await first_task is True
    assert manager.active_connections["user-1"] == {first}


class EndpointWebSocket(FakeWebSocket):
    def __init__(self, *, receive_error: Exception | None = None):
        super().__init__()
        self.headers = {"authorization": "Bearer test-token"}
        self.receive_calls = 0
        self.receive_error = receive_error

    async def receive_text(self):
        self.receive_calls += 1
        if self.receive_error is not None:
            raise self.receive_error
        raise AssertionError("receive loop should not have been entered")


@pytest.mark.asyncio
async def test_websocket_endpoint_returns_immediately_when_user_cap_is_reached(monkeypatch):
    import app.main as main

    manager = ConnectionManager(max_connections_per_user=1)
    existing = FakeWebSocket()
    await manager.connect(existing, "user-1")
    monkeypatch.setattr(main, "manager", manager)
    monkeypatch.setattr(main, "decode_token", lambda _token: {"sub": "user-1"})
    monkeypatch.setattr(
        main,
        "resolve_authenticated_user",
        lambda payload: {"id": payload["sub"]},
    )

    excess = EndpointWebSocket()
    await main.websocket_endpoint(excess, "user-1")

    assert excess.receive_calls == 0
    assert excess.closed == [1013]
    assert manager.active_connections["user-1"] == {existing}


@pytest.mark.asyncio
async def test_websocket_endpoint_always_releases_slot_after_unexpected_receive_error(monkeypatch):
    import app.main as main

    manager = ConnectionManager(max_connections_per_user=1)
    monkeypatch.setattr(main, "manager", manager)
    monkeypatch.setattr(main, "decode_token", lambda _token: {"sub": "user-1"})
    monkeypatch.setattr(
        main,
        "resolve_authenticated_user",
        lambda payload: {"id": payload["sub"]},
    )

    websocket = EndpointWebSocket(receive_error=RuntimeError("socket failed"))
    with pytest.raises(RuntimeError, match="socket failed"):
        await main.websocket_endpoint(websocket, "user-1")

    assert websocket.accepted is True
    assert "user-1" not in manager.active_connections


def test_asgi_websocket_route_enforces_per_user_connection_cap(monkeypatch):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    import app.main as main
    from app.core.security import create_access_token

    manager = ConnectionManager(max_connections_per_user=2)
    monkeypatch.setattr(main, "manager", manager)
    monkeypatch.setattr(
        main,
        "resolve_authenticated_user",
        lambda payload: {"id": payload["sub"]},
    )

    client = TestClient(main.app, raise_server_exceptions=False)
    token = create_access_token({"sub": "user-1"})
    protocols = ["docsort.jwt", token]

    with client.websocket_connect("/ws/user-1", subprotocols=protocols):
        with client.websocket_connect("/ws/user-1", subprotocols=protocols):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/user-1", subprotocols=protocols):
                    pass

            assert exc_info.value.code == 1013
            assert len(manager.active_connections["user-1"]) == 2

    assert "user-1" not in manager.active_connections
