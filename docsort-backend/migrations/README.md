# DocSort database migrations

`schema.sql` is the current **fresh-install snapshot**. Existing databases must
be upgraded with the immutable SQL files in this directory instead of using the
snapshot as an ad-hoc migration mechanism.

## Applying upgrades

1. Back up the database and review the pending migration SQL.
2. In the Supabase SQL editor, inspect the migration ledger:
   ```sql
   SELECT version, name, applied_at FROM schema_migrations ORDER BY version;
   ```
   A database created before migration tracking may not have this table yet;
   migration `0001` creates it.
3. Apply every missing `NNNN_name.sql` file in **lexical order**. Do not skip a
   version and do not edit a migration that has already been applied anywhere.
4. Re-run the ledger query and verify each expected version is recorded before
   deploying backend code that depends on that migration.

Each migration is transactional where practical and records itself in
`schema_migrations` only after its schema changes succeed. A failed migration is
not permission to delete production data: investigate the reported conflict,
reconcile it deliberately, and retry the same migration.

For a brand-new database, run `docsort-backend/schema.sql` instead. The snapshot
contains all currently committed migration effects and marks those versions as
already applied.
