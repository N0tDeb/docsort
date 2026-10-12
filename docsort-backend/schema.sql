-- ═══════════════════════════════════════════════════════════════════════════
-- DocSort — Complete Supabase / PostgreSQL Schema
-- Run this in Supabase SQL Editor for a fresh setup. Existing deployments should apply
-- versioned files from migrations/ in lexical order rather than using this snapshot as an
-- ad-hoc migration mechanism. Alignment statements are idempotent for safe reruns.
-- ═══════════════════════════════════════════════════════════════════════════

-- Enable uuid extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Version ledger for incremental upgrades. Fresh installations use this complete
-- snapshot and mark included migrations only after their corresponding DDL succeeds.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 1. DEPARTMENTS ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS departments (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code        TEXT UNIQUE NOT NULL,       -- e.g. "FIN" or "HR" — human-facing department code
    name        TEXT NOT NULL,              -- e.g. "Information Technology Department"
    city        TEXT,
    state       TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ── 2. USERS ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT UNIQUE NOT NULL,
    password        TEXT NOT NULL,
    name            TEXT,
    department_id   UUID REFERENCES departments(id),
    designation     TEXT,                   -- e.g. "Analyst", "Team Lead"
    employee_id     TEXT,                   -- Organization employee ID
    role            TEXT DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    status          TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'banned')),
    is_active       BOOLEAN DEFAULT true,
    last_seen       TIMESTAMPTZ,               -- last authenticated activity; NULL until first activity
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Normalize the unsupported `officer` value before enforcing the runtime role set.
-- The application distinguishes members (`user`) from organization administrators (`admin`).
UPDATE users SET role = 'user' WHERE role = 'officer';
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('user', 'admin'));

-- ── 3. FOLDERS (Cabinet) ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS folders (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    department_id       UUID REFERENCES departments(id),
    name                TEXT NOT NULL,
    doc_type_affinity   TEXT,
    color               TEXT DEFAULT '#1A6BFF',
    icon                TEXT DEFAULT 'folder',
    is_system           BOOLEAN DEFAULT false,       -- true = created by autosort, not user
    is_default_review   BOOLEAN DEFAULT false,       -- true = the "Needs Review" fallback folder
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- ── 4. UPLOAD JOBS ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS upload_jobs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id),
    department_id   UUID REFERENCES departments(id),
    status          TEXT DEFAULT 'queued',   -- queued | processing | done | failed
    filename        TEXT,
    document_id     UUID,                    -- populated when status = 'done'
    error_message   TEXT,
    step            SMALLINT DEFAULT 0 CHECK (step BETWEEN 0 AND 5),
    progress_pct    NUMERIC(4,3) DEFAULT 0.000 CHECK (progress_pct BETWEEN 0 AND 1),
    progress        JSONB DEFAULT '{}',      -- stores granular processing state
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Idempotent alignment for existing deployments. CREATE TABLE IF NOT EXISTS
-- does not add missing columns to an existing table, so the required upload-job
-- fields are ensured explicitly.
ALTER TABLE upload_jobs
    ADD COLUMN IF NOT EXISTS step SMALLINT DEFAULT 0 CHECK (step BETWEEN 0 AND 5);

ALTER TABLE upload_jobs
    ADD COLUMN IF NOT EXISTS progress_pct NUMERIC(4,3) DEFAULT 0.000
        CHECK (progress_pct BETWEEN 0 AND 1);

-- ── 5. DOCUMENTS ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id          UUID REFERENCES upload_jobs(id),
    user_id         UUID REFERENCES users(id),
    department_id   UUID REFERENCES departments(id),
    folder_id       UUID REFERENCES folders(id),
    filename        TEXT NOT NULL,
    storage_path    TEXT,
    doc_type        TEXT,
    language        TEXT,
    raw_text        TEXT,
    ocr_confidence  NUMERIC(4,3),
    sort_confidence NUMERIC(4,3),
    review_status   TEXT NOT NULL DEFAULT 'needs_review'
                    CHECK (review_status IN ('needs_review', 'verified')),
    file_hash       TEXT,                    -- SHA-256 tamper baseline
    tamper_flags    JSONB DEFAULT '[]',
    is_tampered     BOOLEAN DEFAULT false,
    is_private      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Idempotent alignment ensures review workflow status is available in existing
-- deployments. Documents without an explicit status default to needing review.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'needs_review'
    CHECK (review_status IN ('needs_review', 'verified'));

-- ── 6. DOCUMENT FIELDS ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS document_fields (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    label       TEXT,
    value       TEXT,
    confidence  NUMERIC(4,3),
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Atomically replace all extracted fields for one document. PostgREST exposes
-- PostgreSQL functions under /rest/v1/rpc/<function>; one function invocation
-- is one database transaction, so a failed INSERT rolls back the preceding DELETE.
CREATE OR REPLACE FUNCTION replace_document_fields(
    p_document_id UUID,
    p_fields JSONB DEFAULT '[]'::jsonb
)
RETURNS SETOF document_fields
LANGUAGE plpgsql
AS $$
BEGIN
    IF jsonb_typeof(p_fields) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'p_fields must be a JSON array';
    END IF;

    DELETE FROM document_fields WHERE document_id = p_document_id;

    INSERT INTO document_fields (document_id, label, value, confidence)
    SELECT
        p_document_id,
        item->>'label',
        item->>'value',
        COALESCE((item->>'confidence')::NUMERIC, 1.000)
    FROM jsonb_array_elements(p_fields) AS item;

    RETURN QUERY
    SELECT df.*
    FROM document_fields AS df
    WHERE df.document_id = p_document_id
    ORDER BY df.created_at, df.id;
END;
$$;

-- ── 7. ACTIVITY LOG ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activity_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id),
    department_id   UUID REFERENCES departments(id),
    document_id     UUID REFERENCES documents(id) ON DELETE SET NULL,
    action          TEXT,   -- upload | view | share | login | export | ban_user | approve_user | etc.
    detail          TEXT,
    metadata        JSONB DEFAULT '{}',      -- extra structured info
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ── 8. SHARED LINKS ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS shared_links (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    token        TEXT UNIQUE NOT NULL,
    document_id  UUID REFERENCES documents(id) ON DELETE CASCADE,
    created_by   UUID REFERENCES users(id),
    expires_at   TIMESTAMPTZ NOT NULL,
    password     TEXT,   -- PBKDF2 hash for new password-protected links; never plaintext
    is_active    BOOLEAN DEFAULT true,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- ── 9. ACCESS CONTROL (reserved; current sharing API does not use it) ─────────
CREATE TABLE IF NOT EXISTS access_control (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID REFERENCES documents(id) ON DELETE CASCADE,
    user_id      UUID REFERENCES users(id),
    granted_by   UUID REFERENCES users(id),
    permission   TEXT DEFAULT 'view' CHECK (permission IN ('view', 'edit', 'admin')),
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(document_id, user_id)
);

-- ── 10. PENDING INVITES (reserved; not used by document sharing) ─────────────
CREATE TABLE IF NOT EXISTS pending_invites (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id    UUID REFERENCES documents(id) ON DELETE CASCADE,
    invited_email  TEXT NOT NULL,
    invited_by     UUID REFERENCES users(id),
    department_id  UUID REFERENCES departments(id),
    expires_at     TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- ── INDEXES ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_documents_department  ON documents(department_id);
CREATE INDEX IF NOT EXISTS idx_documents_folder      ON documents(folder_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash        ON documents(file_hash);

-- Concurrency invariants. These are intentionally partial so NULL department
-- semantics match the application: the same owner's hash is unique within one
-- assigned department, and separately unique while the owner is unassigned.
-- If existing rows conflict with an invariant, index creation fails closed;
-- inspect/reconcile those rows rather than silently deleting data.
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_owner_department_hash
    ON documents(user_id, department_id, file_hash)
    WHERE file_hash IS NOT NULL AND department_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_owner_unassigned_hash
    ON documents(user_id, file_hash)
    WHERE file_hash IS NOT NULL AND department_id IS NULL;

-- AutoSort system folders are a department-scoped singleton by name. Manual
-- admin folders remain unaffected because the predicate applies only to rows
-- created as system folders.
CREATE UNIQUE INDEX IF NOT EXISTS uq_system_folders_department_name
    ON folders(department_id, name)
    WHERE is_system = true AND department_id IS NOT NULL;

-- schema.sql already contains every effect from migration 0001. Record that
-- version only after the invariant indexes above have been installed successfully.
INSERT INTO schema_migrations (version, name)
VALUES (1, 'concurrency_invariants')
ON CONFLICT (version) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_document_fields_doc   ON document_fields(document_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_dept     ON activity_log(department_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_created  ON activity_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_last_seen        ON users(last_seen);

-- Fresh installs already use nullable/no-default last_seen activity semantics.
INSERT INTO schema_migrations (version, name)
VALUES (2, 'presence_activity_semantics')
ON CONFLICT (version) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_shared_links_token    ON shared_links(token);
CREATE INDEX IF NOT EXISTS idx_shared_links_doc      ON shared_links(document_id);

-- ── FULL-TEXT SEARCH INDEX ────────────────────────────────────────────────────
-- Enables fast full-text search on raw_text and filename
ALTER TABLE documents ADD COLUMN IF NOT EXISTS search_vector TSVECTOR;
CREATE INDEX IF NOT EXISTS idx_documents_fts ON documents USING GIN(search_vector);

CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        coalesce(NEW.filename, '') || ' ' ||
        coalesce(NEW.doc_type, '') || ' ' ||
        coalesce(NEW.raw_text, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_search_vector ON documents;
CREATE TRIGGER trg_search_vector
    BEFORE INSERT OR UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();

-- ── AUTO-CREATE "NEEDS REVIEW" FOLDER ON NEW DEPARTMENT ───────────────────────
CREATE OR REPLACE FUNCTION create_default_review_folder()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO folders (department_id, name, color, icon, is_system, is_default_review)
    VALUES (NEW.id, 'Needs Review', '#FF6B35', 'folder_open', true, true);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS after_department_insert ON departments;
CREATE TRIGGER after_department_insert
    AFTER INSERT ON departments
    FOR EACH ROW EXECUTE FUNCTION create_default_review_folder();

-- ── ROW LEVEL SECURITY ────────────────────────────────────────────────────────
-- The Flutter client never talks to PostgREST directly. All application data
-- access goes through the FastAPI backend using the Supabase service-role key,
-- which bypasses RLS. Therefore client-facing database roles should have no
-- permissive policies at all: RLS is enabled and defaults to deny.
--
-- DROP statements make this section safe to re-run on databases created from
-- older DocSort versions that shipped permissive USING (true) policies.
ALTER TABLE departments     ENABLE ROW LEVEL SECURITY;
ALTER TABLE users           ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents       ENABLE ROW LEVEL SECURITY;
ALTER TABLE folders         ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log    ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_links    ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_control  ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE upload_jobs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_fields ENABLE ROW LEVEL SECURITY;
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "users_read_dept" ON users;
DROP POLICY IF EXISTS "docs_read_dept" ON documents;
DROP POLICY IF EXISTS "activity_insert" ON activity_log;
DROP POLICY IF EXISTS "activity_select" ON activity_log;
DROP POLICY IF EXISTS "activity_no_delete" ON activity_log;

-- No policies are recreated here intentionally. The service-role backend is the
-- application authorization boundary; anon/authenticated PostgREST roles remain
-- denied by RLS even if a public Supabase key is known.

-- ── 11. PEOPLE (INTERNAL TABLE NAME: citizens) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS citizens (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dept_id     UUID REFERENCES departments(id) ON DELETE CASCADE,
    full_name   TEXT NOT NULL,
    dob         DATE,
    uid_number  TEXT,               -- optional external/person identifier (internal column name)
    gender      TEXT CHECK (gender IN ('male','female','other')),
    address     TEXT,
    phone       TEXT,
    is_flagged  BOOLEAN DEFAULT FALSE,  -- potential duplicate/person-match flag
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── 12. PEOPLE GRAPH EDGES (INTERNAL TABLE NAME) ───────────────────────────────
CREATE TABLE IF NOT EXISTS citizen_edges (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    from_citizen    UUID NOT NULL REFERENCES citizens(id) ON DELETE CASCADE,
    to_citizen      UUID NOT NULL REFERENCES citizens(id) ON DELETE CASCADE,
    edge_type       TEXT NOT NULL CHECK (edge_type IN (
                        'parent_of','child_of','spouse_of',
                        'owns_property','duplicate_of','sibling_of'
                    )),
    evidence_doc_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    confidence      FLOAT DEFAULT 1.0,  -- 0-1, lower = inferred
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 13. PERSON-DOCUMENT LINKS (INTERNAL TABLE NAME) ────────────────────────────
CREATE TABLE IF NOT EXISTS citizen_documents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    citizen_id  UUID NOT NULL REFERENCES citizens(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    role        TEXT DEFAULT 'subject',  -- subject | witness | issuer
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(citizen_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_citizens_dept     ON citizens(dept_id);
CREATE INDEX IF NOT EXISTS idx_citizens_name     ON citizens USING GIN(to_tsvector('english', full_name));
CREATE INDEX IF NOT EXISTS idx_citizens_uid      ON citizens(uid_number);
CREATE INDEX IF NOT EXISTS idx_edges_from        ON citizen_edges(from_citizen);
CREATE INDEX IF NOT EXISTS idx_edges_to          ON citizen_edges(to_citizen);
CREATE INDEX IF NOT EXISTS idx_citizen_docs_cit  ON citizen_documents(citizen_id);
CREATE INDEX IF NOT EXISTS idx_citizen_docs_doc  ON citizen_documents(document_id);

ALTER TABLE citizens          ENABLE ROW LEVEL SECURITY;
ALTER TABLE citizen_edges     ENABLE ROW LEVEL SECURITY;
ALTER TABLE citizen_documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "citizens_auth" ON citizens;
DROP POLICY IF EXISTS "edges_auth" ON citizen_edges;
DROP POLICY IF EXISTS "cit_docs_auth" ON citizen_documents;
-- As above, the experimental People Map is backend-only. Direct PostgREST
-- client roles receive no graph policy and therefore no graph rows.

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS citizens_updated_at ON citizens;
CREATE TRIGGER citizens_updated_at
    BEFORE UPDATE ON citizens
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ── SEED: SAMPLE DEPARTMENTS ──────────────────────────────────────────────────
-- Generic demo departments for a final-year/project setup. Replace with the
-- organization-specific structure used by a real deployment.
INSERT INTO departments (code, name, city, state)
VALUES
    ('FIN', 'Finance', NULL, NULL),
    ('HR', 'Human Resources', NULL, NULL),
    ('LEGAL', 'Legal', NULL, NULL),
    ('ADMIN', 'Administration', NULL, NULL),
    ('RECORDS', 'Records', NULL, NULL)
ON CONFLICT (code) DO NOTHING;

-- Keep department state deployment-neutral by ensuring there is no column default.
-- Stored department data is not modified.
ALTER TABLE departments ALTER COLUMN state DROP DEFAULT;
