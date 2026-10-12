"""Public sharing must keep sync database/crypto/Storage work off the event loop."""

import asyncio
import threading

from fastapi import Response

from app.api import share


async def _wait_until_started(started: threading.Event) -> None:
    for _ in range(200):
        if started.is_set():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("blocking share operation never started")


def test_public_share_access_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_access(_token, _password=None):
        started.set()
        release.wait(timeout=0.5)
        return {
            "password_required": False,
            "document": {"id": "doc-1", "filename": "report.pdf", "doc_type": "Report"},
            "expires_at": "2099-01-01T00:00:00+00:00",
            "download_url": "https://example.invalid/signed",
        }

    monkeypatch.setattr(share.share_service, "access_public_link", blocking_access)

    async def scenario():
        response = Response()
        task = asyncio.create_task(share.access_shared_document("token-1", response))
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        result = await task
        return result, response

    result, response = asyncio.run(scenario())
    assert result["document"]["id"] == "doc-1"
    assert response.headers["Cache-Control"] == "no-store"


def test_share_document_authorization_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_document(_db, _document_id, _user, _columns):
        started.set()
        release.wait(timeout=0.5)
        return {"id": "doc-1", "filename": "report.pdf"}

    monkeypatch.setattr(share, "get_writable_document", blocking_document)
    monkeypatch.setattr(
        share.share_service,
        "create_public_link",
        lambda **_kwargs: {
            "share_id": "share-1",
            "token": "token-1",
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(share.activity_service, "log_share", lambda *_args: None)

    from app.schemas.share_schema import ShareLinkCreate

    async def scenario():
        task = asyncio.create_task(
            share.create_share_link(
                payload=ShareLinkCreate(document_id="doc-1"),
                user={"id": "user-1", "role": "user", "department_id": "dept-1"},
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    result = asyncio.run(scenario())
    assert result["share_id"] == "share-1"


def test_share_link_listing_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(share, "get_supabase_sync", lambda: object())
    monkeypatch.setattr(
        share,
        "get_writable_document",
        lambda *_args, **_kwargs: {"id": "doc-1"},
    )

    def blocking_list(_document_id):
        started.set()
        release.wait(timeout=0.5)
        return []

    monkeypatch.setattr(share.share_service, "list_public_links", blocking_list)

    async def scenario():
        task = asyncio.create_task(
            share.list_share_links(
                "doc-1",
                user={"id": "user-1", "role": "user", "department_id": "dept-1"},
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) == []


def test_share_revocation_lookup_yields_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_metadata(_share_id):
        started.set()
        release.wait(timeout=0.5)
        return {"share_id": "share-1", "document_id": "doc-1", "is_active": True}

    monkeypatch.setattr(share.share_service, "get_public_link_metadata", blocking_metadata)
    monkeypatch.setattr(share, "get_supabase_sync", lambda: object())
    monkeypatch.setattr(
        share,
        "get_writable_document",
        lambda *_args, **_kwargs: {"id": "doc-1"},
    )
    monkeypatch.setattr(
        share.share_service,
        "revoke_public_link",
        lambda _share_id: {"share_id": "share-1", "is_active": False},
    )
    monkeypatch.setattr(share.activity_service, "log", lambda *_args, **_kwargs: None)

    async def scenario():
        task = asyncio.create_task(
            share.revoke_share_link(
                "share-1",
                user={"id": "user-1", "role": "user", "department_id": "dept-1"},
            )
        )
        await _wait_until_started(started)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(scenario()) == {"share_id": "share-1", "is_active": False}
