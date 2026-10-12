-- DocSort database migration 0002
-- Stop treating account creation time as user presence. `last_seen` is retained
-- as the last authenticated activity timestamp and remains nullable until the
-- user successfully logs in or makes an authenticated request.

BEGIN;

DO $migration$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = 2) THEN
        RAISE NOTICE 'DocSort migration 0002 already applied';
        RETURN;
    END IF;

    IF to_regclass('public.users') IS NULL THEN
        RAISE EXCEPTION 'DocSort migration 0002 requires the existing DocSort users table; use schema.sql for a fresh database';
    END IF;

    ALTER TABLE users ALTER COLUMN last_seen DROP DEFAULT;

    INSERT INTO schema_migrations (version, name)
    VALUES (2, 'presence_activity_semantics');
END
$migration$;

COMMIT;
