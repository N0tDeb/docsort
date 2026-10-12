from __future__ import annotations

import asyncio
import time
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.core import readiness
from app.core.database import SupabaseClient


class _Response:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code
        self.text = "probe failure"


class _HTTP:
    def __init__(self, statuses: list[int]):
        self.statuses = list(statuses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.statuses.pop(0))

    def close(self):
        pass


def _client_with_http(statuses: list[int]) -> tuple[SupabaseClient, _HTTP]:
    client = SupabaseClient("https://example.supabase.co", "service-key")
    client._http.close()
    fake = _HTTP(statuses)
    client._http = fake
    client.storage._client = fake
    return client, fake


def test_supabase_readiness_probes_are_minimal_and_short_lived():
    client, http = _client_with_http([200, 200])

    client.check_database_ready(timeout=1.25)
    client.check_storage_ready(bucket="docsort", timeout=1.25)

    assert http.calls == [
        (
            "https://example.supabase.co/rest/v1/departments",
            {
                "params": {"select": "id", "limit": "1"},
                "headers": client._headers,
                "timeout": 1.25,
            },
        ),
        (
            "https://example.supabase.co/storage/v1/bucket/docsort",
            {"headers": client._headers, "timeout": 1.25},
        ),
    ]


def test_supabase_readiness_probe_normalizes_remote_failure():
    client, _ = _client_with_http([503])

    with pytest.raises(RuntimeError, match="database readiness check failed"):
        client.check_database_ready(timeout=0.5)


def test_collect_readiness_reports_only_component_status(monkeypatch):
    class FakeSupabase:
        def check_database_ready(self, *, timeout):
            raise RuntimeError("https://secret-project.example/rest/v1 leaked detail")

        def check_storage_ready(self, *, bucket, timeout):
            assert bucket == "docsort"

    monkeypatch.setattr(readiness, "get_supabase_sync", lambda: FakeSupabase())
    monkeypatch.setattr(readiness.shutil, "which", lambda command: "/usr/bin/tesseract")

    report = asyncio.run(readiness.collect_readiness())

    assert report == {
        "status": "not_ready",
        "service": "DocSort API v1.0.0",
        "checks": {"database": "error", "storage": "ok", "ocr": "ok"},
    }
    assert "secret-project" not in repr(report)


def test_collect_readiness_remote_probe_does_not_block_event_loop(monkeypatch):
    class FakeSupabase:
        def check_database_ready(self, *, timeout):
            time.sleep(0.25)

        def check_storage_ready(self, *, bucket, timeout):
            pass

    monkeypatch.setattr(readiness, "get_supabase_sync", lambda: FakeSupabase())
    monkeypatch.setattr(readiness.shutil, "which", lambda command: "/usr/bin/tesseract")

    async def exercise():
        loop = asyncio.get_running_loop()
        started = loop.time()
        heartbeat_at = None

        async def heartbeat():
            nonlocal heartbeat_at
            await asyncio.sleep(0.05)
            heartbeat_at = loop.time() - started

        report, _ = await asyncio.gather(readiness.collect_readiness(), heartbeat())
        return report, heartbeat_at

    report, heartbeat_at = asyncio.run(exercise())

    assert report["status"] == "ready"
    assert heartbeat_at is not None and heartbeat_at < 0.15


def test_collect_readiness_marks_missing_ocr_binary_not_ready(monkeypatch):
    class FakeSupabase:
        def check_database_ready(self, *, timeout):
            pass

        def check_storage_ready(self, *, bucket, timeout):
            pass

    monkeypatch.setattr(readiness, "get_supabase_sync", lambda: FakeSupabase())
    monkeypatch.setattr(readiness.shutil, "which", lambda command: None)

    report = asyncio.run(readiness.collect_readiness())

    assert report["status"] == "not_ready"
    assert report["checks"] == {"database": "ok", "storage": "ok", "ocr": "error"}


def test_ready_endpoint_returns_200_or_503_without_affecting_liveness(monkeypatch):
    reports = iter(
        [
            {
                "status": "ready",
                "service": "DocSort API v1.0.0",
                "checks": {"database": "ok", "storage": "ok", "ocr": "ok"},
            },
            {
                "status": "not_ready",
                "service": "DocSort API v1.0.0",
                "checks": {"database": "error", "storage": "ok", "ocr": "ok"},
            },
        ]
    )

    async def fake_collect_readiness():
        return next(reports)

    monkeypatch.setattr(main, "collect_readiness", fake_collect_readiness)

    with TestClient(main.app, raise_server_exceptions=False) as client:
        healthy = client.get("/ready", headers={"X-Request-ID": "ready-ok"})
        degraded = client.get("/ready", headers={"X-Request-ID": "ready-bad"})
        liveness = client.get("/")

    assert healthy.status_code == 200
    assert healthy.headers["cache-control"] == "no-store"
    assert healthy.headers["x-request-id"] == "ready-ok"
    assert healthy.json()["status"] == "ready"

    assert degraded.status_code == 503
    assert degraded.headers["cache-control"] == "no-store"
    assert degraded.headers["x-request-id"] == "ready-bad"
    assert degraded.json()["checks"]["database"] == "error"

    assert liveness.status_code == 200
    assert liveness.json() == {"status": "ok", "service": "DocSort API v1.0.0"}
