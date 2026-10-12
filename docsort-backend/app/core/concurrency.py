"""Small async boundary helpers for synchronous I/O.

The custom Supabase adapter is synchronous. Async FastAPI entry points should use :func:`run_blocking_io` when calling a blocking
operation so network waits do not occupy the event-loop thread.
"""

from collections.abc import Callable
from typing import TypeVar

from starlette.concurrency import run_in_threadpool


T = TypeVar("T")


async def run_blocking_io(func: Callable[..., T], *args, **kwargs) -> T:
    """Execute one synchronous blocking operation in Starlette's worker pool."""
    return await run_in_threadpool(func, *args, **kwargs)
