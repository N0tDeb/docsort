-- DocSort database migration 0001
-- Add database-enforced concurrency invariants for upload and AutoSort operations.
-- This migration is intentionally non-destructive: if existing rows conflict with
-- an invariant, it fails and requires an operator to reconcile those rows explicitly
-- before retrying.

BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;

DO $migration$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = 1) THEN
        RAISE NOTICE 'DocSort migration 0001 already applied';
        RETURN;
    END IF;

    IF to_regclass('public.documents') IS NULL OR to_regclass('public.folders') IS NULL THEN
        RAISE EXCEPTION 'DocSort migration 0001 requires the existing DocSort schema; use schema.sql for a fresh database';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM documents
        WHERE file_hash IS NOT NULL AND department_id IS NOT NULL
        GROUP BY user_id, department_id, file_hash
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'DocSort migration 0001 blocked: duplicate assigned-user document hashes must be reconciled first';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM documents
        WHERE file_hash IS NOT NULL AND department_id IS NULL
        GROUP BY user_id, file_hash
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'DocSort migration 0001 blocked: duplicate unassigned-user document hashes must be reconciled first';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM folders
        WHERE is_system = true AND department_id IS NOT NULL
        GROUP BY department_id, name
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'DocSort migration 0001 blocked: duplicate system-folder names must be reconciled first';
    END IF;

    CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_owner_department_hash
        ON documents(user_id, department_id, file_hash)
        WHERE file_hash IS NOT NULL AND department_id IS NOT NULL;

    CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_owner_unassigned_hash
        ON documents(user_id, file_hash)
        WHERE file_hash IS NOT NULL AND department_id IS NULL;

    CREATE UNIQUE INDEX IF NOT EXISTS uq_system_folders_department_name
        ON folders(department_id, name)
        WHERE is_system = true AND department_id IS NOT NULL;

    INSERT INTO schema_migrations (version, name)
    VALUES (1, 'concurrency_invariants');
END
$migration$;

COMMIT;
