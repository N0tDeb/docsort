import pytest

from app.core.websocket import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.accepted_subprotocol = None
        self.messages = []

    async def accept(self, subprotocol=None):
        self.accepted_subprotocol = subprotocol

    async def send_json(self, message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_same_user_can_hold_multiple_connections():
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()

    await manager.connect(first, "user-1")
    await manager.connect(second, "user-1")

    assert manager.active_connections["user-1"] == {first, second}


@pytest.mark.asyncio
async def test_disconnect_removes_only_the_exact_socket():
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()

    await manager.connect(first, "user-1")
    await manager.connect(second, "user-1")

    manager.disconnect("user-1", first)

    assert manager.active_connections["user-1"] == {second}

    manager.disconnect("user-1", second)

    assert "user-1" not in manager.active_connections


@pytest.mark.asyncio
async def test_personal_message_reaches_all_connections_for_user():
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()
    other = FakeWebSocket()

    await manager.connect(first, "user-1")
    await manager.connect(second, "user-1")
    await manager.connect(other, "user-2")

    message = {"type": "refresh"}
    await manager.send_personal_message(message, "user-1")

    assert first.messages == [message]
    assert second.messages == [message]
    assert other.messages == []


@pytest.mark.asyncio
async def test_broadcast_reaches_every_active_socket():
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()
    other = FakeWebSocket()

    await manager.connect(first, "user-1")
    await manager.connect(second, "user-1")
    await manager.connect(other, "user-2")

    message = {"type": "system"}
    await manager.broadcast(message)

    assert first.messages == [message]
    assert second.messages == [message]
    assert other.messages == [message]


@pytest.mark.asyncio
async def test_broadcast_uses_snapshot_when_connection_disconnects_during_send():
    manager = ConnectionManager()

    class SelfDisconnectingWebSocket(FakeWebSocket):
        async def send_json(self, message):
            manager.disconnect("user-1", self)
            await super().send_json(message)

    first = SelfDisconnectingWebSocket()
    second = FakeWebSocket()

    await manager.connect(first, "user-1")
    await manager.connect(second, "user-1")

    message = {"type": "system"}
    await manager.broadcast(message)

    assert first.messages == [message]
    assert second.messages == [message]
    assert manager.active_connections["user-1"] == {second}
