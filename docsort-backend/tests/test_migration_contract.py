"""Static contract coverage for the versioned SQL migration system."""
import re
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
MIGRATIONS = BACKEND / "migrations"
SCHEMA = BACKEND / "schema.sql"


def _migration_files():
    return sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def test_migrations_are_strictly_versioned_and_contiguous():
    files = _migration_files()
    assert files, "at least one versioned database migration must be committed"
    versions = [int(path.name.split("_", 1)[0]) for path in files]
    assert versions == list(range(1, len(files) + 1))
    assert len({path.name for path in files}) == len(files)


def test_each_migration_records_exactly_its_file_version():
    for path in _migration_files():
        version = int(path.name.split("_", 1)[0])
        sql = path.read_text(encoding="utf-8")
        inserts = re.findall(
            r"INSERT\s+INTO\s+schema_migrations\s*\(\s*version\s*,\s*name\s*\)\s*"
            r"VALUES\s*\(\s*(\d+)\s*,",
            sql,
            flags=re.IGNORECASE,
        )
        assert inserts == [str(version)], f"{path.name} must record version {version} exactly once"


def test_fresh_schema_tracks_all_committed_migrations():
    schema = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in schema
    assert "ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY" in schema

    for path in _migration_files():
        version = int(path.name.split("_", 1)[0])
        assert re.search(
            rf"INSERT\s+INTO\s+schema_migrations\s*\(\s*version\s*,\s*name\s*\).*?"
            rf"VALUES\s*\(\s*{version}\s*,",
            schema,
            flags=re.IGNORECASE | re.DOTALL,
        ), f"fresh schema must mark migration {version} as already applied"


def test_first_migration_moves_concurrency_invariants_without_deleting_data():
    migration = MIGRATIONS / "0001_concurrency_invariants.sql"
    sql = migration.read_text(encoding="utf-8")
    lowered = sql.lower()

    assert "uq_documents_owner_department_hash" in sql
    assert "uq_documents_owner_unassigned_hash" in sql
    assert "uq_system_folders_department_name" in sql
    assert "having count(*) > 1" in lowered
    assert "raise exception" in lowered
    assert "delete from documents" not in lowered
    assert "delete from folders" not in lowered


def test_docs_distinguish_fresh_bootstrap_from_existing_database_upgrades():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    setup = (ROOT / "SETUP.md").read_text(encoding="utf-8")
    implementation_report = (ROOT / "docs/FINAL_IMPLEMENTATION_REPORT.md").read_text(encoding="utf-8")

    for text in (readme, setup):
        assert "docsort-backend/schema.sql" in text
        assert "docsort-backend/migrations/" in text
        assert "schema_migrations" in text
        assert "lexical order" in text.lower()

    assert "Database evolution uses ordered SQL files" in implementation_report
    assert "docsort-backend/migrations/" in implementation_report
    assert "schema_migrations" in implementation_report


def test_presence_activity_migration_removes_account_creation_default():
    migration = MIGRATIONS / "0002_presence_activity_semantics.sql"
    migration_sql = migration.read_text(encoding="utf-8").lower()
    schema_sql = SCHEMA.read_text(encoding="utf-8").lower()

    assert "alter column last_seen drop default" in migration_sql
    assert "last_seen       timestamptz," in schema_sql
    assert "last_seen       timestamptz default now()" not in schema_sql
