"""WebSocket authentication and login rate-limiting tests."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as m
from app.core.security import create_access_token

client = TestClient(m.app, raise_server_exceptions=False)


def _ws_accepts(url, token=None):
    subprotocols = ["docsort.jwt", token] if token else None
    try:
        with client.websocket_connect(url, subprotocols=subprotocols):
            return True
    except WebSocketDisconnect:
        return False


def test_ws_rejects_missing_token():
    assert _ws_accepts("/ws/user-123") is False


def test_ws_rejects_bad_token():
    assert _ws_accepts("/ws/user-123", "garbage") is False


def test_ws_rejects_query_string_token():
    tok = create_access_token({"sub": "user-123"})
    assert _ws_accepts("/ws/user-123?token=" + tok) is False


def test_ws_rejects_token_for_other_user():
    tok = create_access_token({"sub": "user-123"})
    assert _ws_accepts("/ws/other-user", tok) is False


def test_ws_accepts_valid_matching_token(monkeypatch):
    monkeypatch.setattr(
        m, "resolve_authenticated_user",
        lambda payload: {"id": payload["sub"]},
    )
    tok = create_access_token({"sub": "user-123"})
    assert _ws_accepts("/ws/user-123", tok) is True


def test_ws_rejects_inactive_live_account(monkeypatch):
    def _reject(_payload):
        raise HTTPException(status_code=401, detail="Account is not active")

    monkeypatch.setattr(m, "resolve_authenticated_user", _reject)
    tok = create_access_token({"sub": "user-123"})
    assert _ws_accepts("/ws/user-123", tok) is False


def test_login_is_rate_limited():
    # 5/minute cap -> a 429 must appear within a burst of requests.
    codes = [client.post("/auth/login",
                         json={"email": "a@b.com", "password": "x"}).status_code
             for _ in range(8)]
    assert 429 in codes
