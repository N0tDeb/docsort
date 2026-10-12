import logging
import sys
from contextvars import ContextVar, Token


_request_id: ContextVar[str] = ContextVar("docsort_request_id", default="-")


def get_request_id() -> str:
    """Return the request correlation ID for the current execution context."""
    return _request_id.get()


def set_request_id(request_id: str) -> Token:
    """Bind a request correlation ID and return the reset token."""
    return _request_id.set(request_id)


def reset_request_id(token: Token) -> None:
    """Restore the previous request correlation context."""
    _request_id.reset(token)


class _RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(isinstance(f, _RequestContextFilter) for f in logger.filters):
        logger.addFilter(_RequestContextFilter())

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s request_id=%(request_id)s %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logger("docsort")
