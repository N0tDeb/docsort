"""Password hashing and JWT token helper tests."""
from app.core.security import (
    hash_password, verify_password, create_access_token, decode_token,
)


def test_password_hash_roundtrip():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_token_roundtrip_carries_subject():
    tok = create_access_token({"sub": "user-123"})
    payload = decode_token(tok)
    assert payload and str(payload["sub"]) == "user-123"


def test_decode_rejects_garbage():
    assert decode_token("not-a-token") is None
    assert decode_token("") is None
    assert decode_token(None) is None
