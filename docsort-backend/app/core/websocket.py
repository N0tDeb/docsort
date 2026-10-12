from typing import Dict, Set

from fastapi import WebSocket, status

from app.core.config import settings


class ConnectionManager:
    def __init__(self, max_connections_per_user: int = 3):
        if max_connections_per_user <= 0:
            raise ValueError("max_connections_per_user must be positive")
        self.max_connections_per_user = max_connections_per_user
        # A user can have more than one active tab/device connection at once,
        # but the set is bounded so one authenticated principal cannot consume
        # unbounded WebSocket resources on this API process.
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        subprotocol: str | None = None,
    ) -> bool:
        connections = self.active_connections.setdefault(user_id, set())
        if len(connections) >= self.max_connections_per_user:
            # Reject before accepting the handshake. 1013 communicates a
            # temporary capacity condition without treating the authenticated
            # client as a policy violator.
            await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
            return False

        # Reserve the slot before the await so two concurrent handshakes for
        # the same user cannot both observe spare capacity and overrun the cap.
        connections.add(websocket)
        try:
            await websocket.accept(subprotocol=subprotocol)
        except BaseException:
            self.disconnect(user_id, websocket)
            raise
        return True

    def disconnect(self, user_id: str, websocket: WebSocket):
        connections = self.active_connections.get(user_id)
        if not connections:
            return

        connections.discard(websocket)
        if not connections:
            del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, user_id: str):
        for connection in tuple(self.active_connections.get(user_id, ())):
            await connection.send_json(message)

    async def broadcast(self, message: dict):
        connections = tuple(
            connection
            for user_connections in self.active_connections.values()
            for connection in user_connections
        )
        for connection in connections:
            await connection.send_json(message)


manager = ConnectionManager(settings.max_websocket_connections_per_user)
