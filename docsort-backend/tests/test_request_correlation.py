import logging
import re

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

from app.core.observability import RequestCorrelationMiddleware
from app.utils.logger import get_request_id, logger


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _make_app(captured_background_ids=None):
    inner = FastAPI()

    @inner.get("/items/{item_id}")
    async def item(item_id: str):
        logger.info("item handler invoked")
        return {"item_id": item_id, "request_id": get_request_id()}

    @inner.get("/boom/{secret}")
    async def boom(secret: str):
        logger.info("boom handler invoked")
        raise RuntimeError("synthetic failure")

    @inner.get("/background/{item_id}")
    async def background(item_id: str, background_tasks: BackgroundTasks):
        def record_background_context():
            captured_background_ids.append(get_request_id())
            logger.info("background task invoked")

        background_tasks.add_task(record_background_context)
        return {"ok": True}

    return RequestCorrelationMiddleware(inner)


def test_request_id_is_returned_and_attached_to_application_logs():
    capture = _CaptureHandler()
    logger.addHandler(capture)
    try:
        app = _make_app([])
        with TestClient(app) as client:
            response = client.get(
                "/items/123",
                headers={"X-Request-ID": "trace-ABC_123"},
            )

        assert response.status_code == 200
        assert response.headers["x-request-id"] == "trace-ABC_123"
        assert response.json()["request_id"] == "trace-ABC_123"

        correlated = [r for r in capture.records if r.getMessage() == "item handler invoked"]
        assert len(correlated) == 1
        assert correlated[0].request_id == "trace-ABC_123"

        completion = [r for r in capture.records if "request completed" in r.getMessage()]
        assert len(completion) == 1
        assert completion[0].request_id == "trace-ABC_123"
        assert "route=/items/{item_id}" in completion[0].getMessage()
        assert "/items/123" not in completion[0].getMessage()
    finally:
        logger.removeHandler(capture)


def test_missing_or_unsafe_request_id_is_replaced_with_server_generated_id():
    app = _make_app([])
    with TestClient(app) as client:
        generated = client.get("/items/one")
        unsafe = client.get("/items/two", headers={"X-Request-ID": "contains spaces"})

    for response in (generated, unsafe):
        request_id = response.headers["x-request-id"]
        assert re.fullmatch(r"[0-9a-f]{32}", request_id)
        assert response.json()["request_id"] == request_id

    assert generated.headers["x-request-id"] != unsafe.headers["x-request-id"]


def test_request_context_survives_background_task_then_resets():
    background_ids = []
    capture = _CaptureHandler()
    logger.addHandler(capture)
    try:
        app = _make_app(background_ids)
        with TestClient(app) as client:
            response = client.get(
                "/background/secret-value",
                headers={"X-Request-ID": "background-42"},
            )

        assert response.status_code == 200
        assert background_ids == ["background-42"]

        background_logs = [r for r in capture.records if r.getMessage() == "background task invoked"]
        assert len(background_logs) == 1
        assert background_logs[0].request_id == "background-42"

        messages = [r.getMessage() for r in capture.records]
        completion_index = next(i for i, message in enumerate(messages) if "request completed" in message)
        background_index = messages.index("background task invoked")
        assert completion_index < background_index

        # The request-local context must not leak into later unrelated logs.
        logger.info("outside request")
        outside = [r for r in capture.records if r.getMessage() == "outside request"][-1]
        assert outside.request_id == "-"
    finally:
        logger.removeHandler(capture)



def test_framework_generated_500_keeps_request_id_without_logging_concrete_path():
    capture = _CaptureHandler()
    logger.addHandler(capture)
    try:
        app = _make_app([])
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/boom/sensitive-capability-value",
                headers={"X-Request-ID": "failure-500"},
            )

        assert response.status_code == 500
        assert response.headers["x-request-id"] == "failure-500"
        completion = [r for r in capture.records if "request completed" in r.getMessage()]
        assert len(completion) == 1
        assert completion[0].request_id == "failure-500"
        assert "route=/boom/{secret}" in completion[0].getMessage()
        assert "sensitive-capability-value" not in completion[0].getMessage()
    finally:
        logger.removeHandler(capture)

def test_request_log_formatter_includes_request_id_field():
    stream_handlers = [handler for handler in logger.handlers if handler.formatter]
    assert stream_handlers
    assert any("request_id=%(request_id)s" in handler.formatter._fmt for handler in stream_handlers)
