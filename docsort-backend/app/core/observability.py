"""Lightweight request correlation for application logs and HTTP responses."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.utils.logger import logger, reset_request_id, set_request_id


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_REQUEST_ID_HEADER = b"x-request-id"


def _request_id_from_scope(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name.lower() != _REQUEST_ID_HEADER:
            continue
        try:
            candidate = value.decode("ascii")
        except UnicodeDecodeError:
            break
        if _SAFE_REQUEST_ID.fullmatch(candidate):
            return candidate
        break
    return uuid.uuid4().hex


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "<unmatched>"


class RequestCorrelationMiddleware:
    """Bind one correlation ID to an HTTP request and all work it spawns.

    The wrapper intentionally logs matched route templates rather than raw paths
    so capability tokens, document IDs, and other path parameters are not copied
    into generic access logs. Query strings and request bodies are never logged.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    def __getattr__(self, name: str) -> Any:
        # Keep FastAPI attributes such as dependency_overrides/state available to
        # the existing test suite and deployment code after outer wrapping.
        return getattr(self.app, name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_scope(scope)
        token = set_request_id(request_id)
        started = time.perf_counter()
        status_code = 500
        completion_logged = False

        def log_completion() -> None:
            nonlocal completion_logged
            if completion_logged:
                return
            completion_logged = True
            duration_ms = (time.perf_counter() - started) * 1000
            level = logging_level_for_status(status_code)
            logger.log(
                level,
                "request completed method=%s route=%s status=%s duration_ms=%.1f",
                scope.get("method", "?"),
                _route_template(scope),
                status_code,
                duration_ms,
            )

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                # Measure client-response completion, not any BackgroundTasks that
                # Starlette runs after the final body has already been emitted.
                log_completion()

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            # Defensive fallback for abnormal ASGI exits that never emitted a final
            # body message. Normal requests log from send_with_request_id above.
            log_completion()
            reset_request_id(token)


def logging_level_for_status(status_code: int) -> int:
    # Imported lazily by value rather than configuring a second logger stack.
    import logging

    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    return logging.INFO
