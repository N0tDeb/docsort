"""Dependency-aware readiness checks for orchestration and load balancers.

Liveness (``GET /``) intentionally answers without touching dependencies.
Readiness verifies the minimum external/runtime capabilities required for
normal document service: PostgREST, the private Storage bucket, and Tesseract.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Literal, TypedDict

from app.core.concurrency import run_blocking_io
from app.core.config import settings
from app.core.database import get_supabase_sync
from app.core.version import SERVICE_NAME


READINESS_TIMEOUT_SECONDS = 2.0
_STORAGE_BUCKET = "docsort"


class ReadinessReport(TypedDict):
    status: Literal["ready", "not_ready"]
    service: str
    checks: dict[str, Literal["ok", "error"]]


def _probe_database(supabase) -> None:
    supabase.check_database_ready(timeout=READINESS_TIMEOUT_SECONDS)


def _probe_storage(supabase) -> None:
    supabase.check_storage_ready(
        bucket=_STORAGE_BUCKET,
        timeout=READINESS_TIMEOUT_SECONDS,
    )


def _probe_ocr() -> bool:
    return shutil.which(settings.tesseract_cmd) is not None


async def collect_readiness() -> ReadinessReport:
    """Return a privacy-safe readiness report without leaking probe details."""
    checks: dict[str, Literal["ok", "error"]] = {
        "database": "error",
        "storage": "error",
        "ocr": "ok" if _probe_ocr() else "error",
    }

    try:
        supabase = get_supabase_sync()
    except Exception:
        supabase = None

    if supabase is not None:
        database_result, storage_result = await asyncio.gather(
            run_blocking_io(_probe_database, supabase),
            run_blocking_io(_probe_storage, supabase),
            return_exceptions=True,
        )
        checks["database"] = "error" if isinstance(database_result, Exception) else "ok"
        checks["storage"] = "error" if isinstance(storage_result, Exception) else "ok"

    status: Literal["ready", "not_ready"] = (
        "ready" if all(value == "ok" for value in checks.values()) else "not_ready"
    )
    return {"status": status, "service": SERVICE_NAME, "checks": checks}
