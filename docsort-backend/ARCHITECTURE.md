# DocSort Backend Architecture & Security Guide

This document describes the current backend architecture and the security boundaries that matter to developers and reviewers. It is intentionally implementation-oriented: the executable source code and tests remain the final authority.

## 1. System boundary

DocSort uses a Flutter client, a FastAPI backend, and Supabase for PostgreSQL plus private object storage. The backend talks to Supabase with the service-role key, so **FastAPI is the application authorization boundary**. Supabase RLS is not treated as the primary policy layer for backend operations; instead, application tables keep RLS enabled with **no permissive anon/authenticated policies**, so direct PostgREST client access defaults to deny while the trusted service-role backend applies route-level authorization.

That design has two consequences:

- backend routes must scope every document read or mutation explicitly;
- the service-role key must never be exposed to Flutter or committed to source control.
- organization-wide analytics are administrator-only; regular members use department/personal analytics.

The custom Supabase adapter keeps one reusable synchronous `httpx.Client` on the process-level `SupabaseClient`, so PostgREST and Storage calls share keep-alive connections instead of opening a new HTTP client for every operation. Current request-time HTTP/WebSocket paths that perform synchronous Supabase/Storage/service work are routed through `app/core/concurrency.py` to Starlette's worker pool: live-account resolution, Auth signup/login repository and password work, upload parser validation/job admission, public sharing, analytics, Cabinet/Search/Upload-status reads, Admin/People Map/Export reads, Cabinet/Admin/People Map mutations, and AutoSort folder operations. Mutation sequencing remains explicit: authorization checks precede writes, database deletion precedes best-effort Storage cleanup, and atomic field replacement remains one PostgreSQL RPC before reclassification. The persistence adapter itself is still synchronous, so worker-pool capacity remains a production scaling constraint and this is not a native async database client. Direct `.execute()` calls remain in synchronous helpers that are invoked through the worker boundary and in `_process_document_async`. Upload background work passes through an async process-level capacity limiter before consuming a Starlette worker thread, so at most `MAX_CONCURRENT_UPLOAD_PROCESSING_JOBS` processors run concurrently and excess admitted jobs remain `queued`. The processor itself is still in-process, synchronous-I/O-heavy, and non-durable.

The shared document policy lives in `app/core/document_access.py`.

### Document access policy

- A member without a department can access only their own documents.
- A member in a department can read non-private documents in that department plus their own private documents.
- A department-scoped administrator can read all documents in their assigned department.
- Mutations are stricter: regular members can modify only their own documents; administrators can modify documents in their assigned department.
- Cross-department document access is rejected.

Organization-administration routes such as account approval are separate from document-content authorization. The `admin` role is not a blanket bypass for every document route.

## 2. Authentication and account state

Password login issues a JWT after successful bcrypt verification. The JWT establishes identity, but protected HTTP and WebSocket requests re-read the current user row so account status, role, and department changes take effect without waiting for token expiry.

The authenticated WebSocket channel tracks exact socket sets per user and enforces a process-local `MAX_WEBSOCKET_CONNECTIONS_PER_USER` cap (default `3`). Slots are reserved before the handshake await, rolled back on failed accepts, and released in endpoint `finally` cleanup so concurrent or abnormal connections cannot bypass or permanently consume the bound. Excess authenticated connections are rejected with WebSocket close code `1013`. This is deliberately a per-process resource guard; horizontally scaled deployments still require shared connection/rate state for a cluster-wide limit. No application-level idle-timeout/heartbeat contract is imposed yet because the current Flutter application does not consume this dormant channel.

Pending, banned, inactive, or deleted accounts are rejected. Password authentication plus JWT/live-account verification is the application login boundary.

Signup intentionally does not reveal whether an email address is already registered. Department input is validated before the account lookup, and both a pre-existing account and a concurrent unique-email race return the same generic HTTP 201 registration response. The existing-account path still performs the password-hash cost under the signup rate limit to reduce the most obvious timing distinction. This is enumeration resistance for the academic application; it is not a claim of side-channel-proof authentication.

## 3. Upload and processing flow

`POST /upload` validates the caller and source file, rate-limits admission, checks the extension/signature and parser-readable structure, enforces page/pixel/size limits, creates an `upload_jobs` record, returns the job identifier, and schedules processing with FastAPI `BackgroundTasks`.

**Important operational limitation:** this is in-process background execution, not a durable external queue. A process-level capacity limiter bounds active processors (default `2`) so excess admitted jobs remain `queued` rather than all consuming OCR/worker capacity at once. If the server process stops, queued or in-flight tasks are not guaranteed to resume. For the final-year project this keeps the architecture simple; a production-scale deployment would move processing to a durable worker/queue with claim/lease/retry semantics.

The visible five-stage pipeline is:

1. **Integrity & Duplicate Check** — compute SHA-256 and look for an exact duplicate owned by the same user in the same department context. Exact duplicates reuse the existing durable document before Storage/OCR/AI work.
2. **Secure File Storage** — upload the source file to the private `docsort` Supabase Storage bucket. Storage failure is fatal; DocSort never marks a document complete with a dead `storage_path`.
3. **OCR & AI Extraction** — every PDF page (or the uploaded image) is processed with Tesseract for raw text and word confidence. When `GEMINI_API_KEY` is configured, the backend sends bounded OCR text plus at most `MAX_AI_PAGES` rendered page images to Google Gemini 3.8 Flash (`GEMINI_MODEL=gemini-3.8-flash`) through the official `google-genai` Interactions API. Gemini returns schema-constrained JSON for document type, language, classification confidence, a suggested folder, structured fields, and review-oriented anomaly indicators; the backend validates the JSON again with Pydantic. If Gemini extraction fails or no API key is usable, the document falls back conservatively toward review instead of being presented as verified.
4. **Anomaly Check** — persist anomaly/tamper flags returned by the extraction stage separately from review status.
5. **Classification & Filing** — map the proposed document type to a generic organizational folder. Results below the configured auto-sort confidence threshold are routed to `Needs Review`.

After classification, the backend persists the document, raw OCR text, extracted fields, review state, integrity hash, and Storage path. The optional People & Document Map runs after the durable document exists and is non-fatal if it fails. Activity logging and upload-job completion are then recorded.

Processing duration is stored in `upload_jobs.progress.processing_ms` for the academic evaluation framework.

## 4. OCR, AI, and confidence semantics

Tesseract is the OCR engine. The default configured languages are English, Hindi, and Marathi (`eng+hin+mar`). The upload language hint is honored when supplied. PDF pages are rendered and OCR-processed incrementally: one page image is produced, OCR runs, and the rendered bytes are released unless that page is inside the configured AI-image subset. This preserves all-page OCR while bounding retained rendered-page memory to `MAX_AI_PAGES` rather than the full PDF page count. JPG/JPEG and PNG uploads retain their matching media type when sent to the AI stage.

The AI stage proposes structured output for general organizational records such as invoices, receipts, resumes, contracts, certificates, application forms, identity documents, and reports.

DocSort intentionally keeps these concepts separate:

- **OCR confidence** is the mean of valid Tesseract word confidences, normalized to `0.0–1.0`; it is an OCR-quality signal, not accuracy.
- **Auto-sort confidence** is a routing score. AI folder suggestions use the model-provided classification confidence; low-confidence suggestions are routed to `Needs Review`. Deterministic fallback mappings remain heuristic and are not academic accuracy measurements.
- **Review status** indicates whether a human has completed verification.
- **Anomaly flags** indicate potential inconsistencies; they are not proof of fraud.

No confidence value should be reported as ground-truth accuracy without an independent labelled evaluation dataset.

## 5. Human-in-the-loop review

Newly processed documents start with:

`review_status = needs_review`

A reviewer can correct the document type and extracted fields. Field replacement uses the PostgreSQL `replace_document_fields` RPC so delete-and-reinsert occurs atomically. A successful review marks the document:

`review_status = verified`

Human verification does not automatically clear a separate anomaly flag.

## 6. Storage and failure handling

The source file is stored in the private `docsort` bucket. Public access uses short-lived signed URLs; the internal `storage_path` is not exposed through the public share response.

If processing fails after Storage upload but before a durable document is established, DocSort first attempts to remove any partial database document and then removes the Storage object. If database cleanup fails, the Storage object is retained so the application does not deliberately create a database row pointing at a deleted source file.

## 7. Search, export, and sharing

Search applies department/document visibility rules and filters candidates at the database layer before ranking the bounded candidate set in Python. This is suitable for the current project scale; very large cabinets should evaluate PostgreSQL FTS and/or trigram-indexed search with representative data and real query plans before changing the active path.

Exports reuse the same document access policy. Export filenames are reduced to safe basenames, response headers are encoded safely, ZIP members cannot contain traversal paths, spreadsheet-formula prefixes are neutralized in CSV metadata, folder exports are document-count bounded, and ZIP data is spooled/streamed instead of being retained entirely in memory. Before any original source bytes are released, DocSort recomputes SHA-256 and requires an exact match with the document's stored `file_hash` baseline; missing or invalid stored baselines fail closed. Folder ZIP construction aborts completely on any mismatch. Storage downloads and ZIP compression/archive writes are executed through the worker-pool boundary so folder export does not block the FastAPI event loop while fetching, hashing, or deflating source files. Archive construction remains serial and complete-or-fail, preserving cumulative source-byte limits and avoiding deceptively partial backups. Single-document export also stages the private Storage object incrementally into a bounded `SpooledTemporaryFile`: small sources remain in memory, larger sources spill to disk, the staged source is hashed before the response begins, and no success response starts unless the complete object matches its baseline. This avoids whole-object RAM buffering while preserving fail-closed delivery; it is bounded-memory staging rather than direct pass-through streaming from Storage. Folder document listing is paginated.

Sharing is intentionally small in scope:

- only users with document write-level authority can create an external share link;
- links are high-entropy, time-limited capability tokens;
- optional passwords are stored using PBKDF2-HMAC-SHA256 with a per-link salt;
- passwords are submitted in a POST body, not a URL;
- successful access first stream-hashes the private Storage object and requires it to match the stored document SHA-256 baseline, then returns a short-lived signed Storage URL with `Cache-Control: no-store`;
- authenticated callers with the same document write authority required for link creation can list link metadata and revoke links for that document;
- management responses expose link IDs/status/timestamps and whether a password is configured, but never capability tokens or stored password hashes;
- revocation sets `is_active=false`, so subsequent public access fails through the existing active-link check;
- the active public-sharing workflow is limited to secure time-limited links, lifecycle management, and signed Storage downloads.

## 8. Organization/admin model

One DocSort deployment represents one organization. `departments` are internal work units. The active role model is deliberately small:

- `user` — Member
- `admin` — Organization Administrator

Organization administrators can manage account approval and operational views, while document-content access remains controlled by department/document policy.

## 9. Experimental People & Document Map

The graph feature is optional and secondary to the document-processing workflow. It links supported person-centric documents to people and can flag **potential identity matches** using conservative name/date-of-birth similarity.

Internal database/API identifiers such as `citizens`, `citizen_edges`, and `/graph/citizen/...` back the optional People Map. The visible product contract remains domain-neutral.

Department graph loading batches people-to-document links and readable document fields instead of querying once per person/document. Excluding the normal authentication lookup, the graph-data path performs at most four PostgREST queries (people, links/doc metadata, fields for authorized documents, and edges), so database query count stays bounded independently of `N + M`. Document visibility is still checked before field rows are fetched. The Flutter force-layout remains client-side and can still become expensive for very large graphs.

The feature does not fabricate demo people for an empty database and does not infer domain-specific property/family relationships from unrelated documents.

## 10. Database structures that matter most

- `departments` — internal organizational work units
- `users` — accounts, roles, status, department
- `upload_jobs` — processing state, step/progress, timing metadata
- `folders` — department cabinet folders
- `documents` — durable document record, source path, OCR/classification/review metadata
- `document_fields` — extracted/reviewed structured fields
- `activity_log` — operational/audit events
- `shared_links` — expiring public-share capabilities
- `schema_migrations` — backend-only operational ledger for ordered database upgrades
- `citizens*` tables — internal storage for the optional People Map

`access_control` and `pending_invites` are reserved schema tables and are not used by the active sharing workflow.

## 11. Configuration and deployment

Runtime mode is controlled by `APP_ENVIRONMENT` (`development`, `test`, or `production`; default `development`). In production mode the backend fails startup unless `SUPABASE_URL` uses HTTPS, while development/test may use an HTTP local emulator.

Runtime-required environment variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `JWT_SECRET`

`GEMINI_API_KEY` is optional for startup but required for the full Gemini extraction/classification experience; `GEMINI_MODEL` defaults to `gemini-3.8-flash`. See the root `SETUP.md` and `docsort-backend/.env.example` for the complete configuration contract.
Gemini credentials never leave the backend. AI input is bounded by `MAX_AI_PAGES` and `MAX_AI_OCR_CHARS`, model output is schema-constrained and then Pydantic-validated, and model failures are non-fatal to the stored document workflow. Anomaly/tamper outputs are treated as review indicators rather than fraud/authenticity determinations.

Android permits local cleartext HTTP only in debug builds. Release builds should target an HTTPS backend.

## 12. Request correlation and observability

Every HTTP request is assigned a correlation identifier. A caller- or ingress-supplied `X-Request-ID` is preserved only when it matches the backend's restricted safe character/length policy; otherwise the backend generates a fresh 32-character hexadecimal identifier. The same identifier is returned in the `X-Request-ID` response header and is exposed through CORS for the Flutter web client.

Application logging uses a request-local context variable, so logs emitted from async route code, Starlette worker-pool calls, and FastAPI background-task execution inherit the current request ID. The outer ASGI correlation wrapper emits one response-completion record with method, matched route template, status code, and elapsed milliseconds when the final response body is sent; later FastAPI background-task time is not misreported as request latency. It deliberately does **not** log query strings, request bodies, or concrete route parameter values; matched templates such as `/share/public/{token}` are logged instead of capability tokens or document identifiers.

Operational/audit logging is privacy-minimized. `activity_log` keeps structured actor/department/action/document references needed for accountability, but its human-readable detail is selected from fixed action phrases rather than filenames, recipients, capability tokens, storage paths, or arbitrary metadata. Application failure logs record the exception class plus the request correlation ID instead of interpolating raw database, Storage, OCR, or provider exception text that could contain sensitive document context. Authorized admin activity views may still enrich a structured document reference with the current document filename for the admin UI; that is an application authorization decision rather than stdout logging.

DocSort also separates liveness from readiness. `GET /` is process liveness and intentionally performs no external I/O. `GET /ready` performs short, non-retrying checks against PostgREST, the required private `docsort` Storage bucket, and the configured Tesseract executable. It returns HTTP 200 only when all three are available and HTTP 503 otherwise. Readiness responses expose only component `ok`/`error` states and are marked `Cache-Control: no-store`; upstream exception text, project URLs, and credentials are never returned. The Docker `HEALTHCHECK` remains a liveness probe, while production load balancers/orchestrators should use `/ready` as their readiness signal.

This is intentionally lightweight observability rather than a full telemetry stack. Logs still go to stdout and there is no configured centralized log aggregation, metrics backend, distributed tracing across Supabase/Gemini, or external error-tracking service.

## 13. Evaluation and validation

The academic evaluation framework is documented in `../docs/EVALUATION.md` and implemented under `evaluation/`. It can measure classification accuracy, field-extraction metrics, OCR CER/WER, reviewer correction rates, processing latency, and search latency without conflating these with model confidence values.

GitHub Actions contains separate backend and Flutter validation workflows. Environment limitations observed during development are documented rather than converted into stronger claims than the available execution evidence supports.
