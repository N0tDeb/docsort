import asyncio
import inspect
import threading

from app.api import upload


def _job_args(index: int):
    return (
        f"job-{index}",
        "user-1",
        "dept-1",
        b"source",
        f"file-{index}.pdf",
        "eng",
        "Report",
    )


def test_background_task_entrypoint_is_async_backpressure_gate():
    assert inspect.iscoroutinefunction(upload._process_document)
    assert not inspect.iscoroutinefunction(upload._process_document_worker)
    assert inspect.iscoroutinefunction(upload._process_document_async)


def test_upload_processing_concurrency_is_bounded_without_starting_waiting_workers(monkeypatch):
    started = 0
    active = 0
    max_active = 0
    lock = threading.Lock()
    two_started = threading.Event()
    release = threading.Event()

    def fake_worker(*_args):
        nonlocal started, active, max_active
        with lock:
            started += 1
            active += 1
            max_active = max(max_active, active)
            if started >= 2:
                two_started.set()
        release.wait(timeout=2.0)
        with lock:
            active -= 1

    monkeypatch.setattr(upload, "_process_document_worker", fake_worker)
    monkeypatch.setattr(
        upload,
        "_upload_processing_limiter",
        upload.CapacityLimiter(2),
    )

    async def scenario():
        tasks = [
            asyncio.create_task(upload._process_document(*_job_args(index)))
            for index in range(3)
        ]
        for _ in range(200):
            if two_started.is_set():
                break
            await asyncio.sleep(0.005)
        assert two_started.is_set(), "two processing slots should become active"
        await asyncio.sleep(0.02)
        with lock:
            assert started == 2
            assert active == 2
        assert sum(task.done() for task in tasks) == 0
        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(scenario())

    assert started == 3
    assert max_active == 2


def test_upload_processing_limit_is_documented_in_env_example():
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    env_example = (backend / ".env.example").read_text()
    assert "MAX_CONCURRENT_UPLOAD_PROCESSING_JOBS" in env_example


def test_upload_processing_limit_must_be_positive():
    import pytest
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(
            _env_file=None,
            jwt_secret="test-secret-value-at-least-32-bytes-12345",
            supabase_url="https://example.supabase.co",
            supabase_service_key="service-key",
            max_concurrent_upload_processing_jobs=0,
        )
