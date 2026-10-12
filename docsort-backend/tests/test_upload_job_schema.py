"""Regression tests for the upload_jobs database/API contract.

The upload API persists and selects ``step`` and ``progress_pct``.  Keep the
SQL bootstrap schema aligned with that public job-status contract so a clean
DocSort database can accept uploads without manual, undocumented ALTERs.
"""

from pathlib import Path
import re


SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")


def _upload_jobs_create_block() -> str:
    match = re.search(
        r"CREATE TABLE IF NOT EXISTS upload_jobs\s*\((.*?)\n\);",
        SCHEMA,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert match, "upload_jobs CREATE TABLE definition is missing from schema.sql"
    return match.group(1)


def test_upload_jobs_schema_declares_runtime_progress_columns():
    block = _upload_jobs_create_block()

    assert re.search(r"\bstep\s+SMALLINT\b", block, flags=re.IGNORECASE)
    assert re.search(r"\bprogress_pct\s+NUMERIC\s*\(\s*4\s*,\s*3\s*\)", block, flags=re.IGNORECASE)


def test_upload_jobs_progress_columns_have_safe_bounds():
    block = _upload_jobs_create_block()

    assert re.search(r"CHECK\s*\(\s*step\s+BETWEEN\s+0\s+AND\s+5\s*\)", block, flags=re.IGNORECASE)
    assert re.search(
        r"CHECK\s*\(\s*progress_pct\s+BETWEEN\s+0\s+AND\s+1\s*\)",
        block,
        flags=re.IGNORECASE,
    )


def test_schema_upgrades_existing_upload_jobs_tables_idempotently():
    """Re-running schema.sql ensures required columns exist on an existing table."""
    assert re.search(
        r"ALTER TABLE upload_jobs\s+ADD COLUMN IF NOT EXISTS step\b",
        SCHEMA,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert re.search(
        r"ALTER TABLE upload_jobs\s+ADD COLUMN IF NOT EXISTS progress_pct\b",
        SCHEMA,
        flags=re.DOTALL | re.IGNORECASE,
    )
