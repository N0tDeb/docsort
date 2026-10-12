# DocSort — Final Implementation Report

## Final project identity

**DocSort — An Intelligent Document Processing and Management System Using OCR and Generative AI**

DocSort 1.0.0 is a domain-neutral final-year BTech IT project for document intake, OCR/AI extraction, classification, human review, organization, search, analytics, export, and secure time-limited sharing. One deployment represents one organization with internal departments. The optional People & Document Map is experimental and secondary to the core document workflow.

## Implemented release surface

The final repository contains:

- a Flutter client using Riverpod, go_router, Dio, secure token storage, file upload, and Android/iOS camera scanning;
- a FastAPI backend that owns authentication, authorization, upload orchestration, search, export, sharing, analytics, administration, and the optional graph API;
- Supabase PostgreSQL plus private Storage accessed only through the trusted backend service role;
- Tesseract OCR with configurable English/Hindi/Marathi language support;
- Google Gemini 3.8 Flash (`gemini-3.8-flash`) structured document-type/field proposals through the official `google-genai` SDK when `GEMINI_API_KEY` is configured;
- a human-in-the-loop review workflow that separates OCR confidence, filing confidence, anomaly evidence, and explicit verification state;
- an offline academic evaluation framework for classification, fields, OCR CER/WER, correction burden, processing latency, duplicate reuse, and authenticated search latency;
- backend and Flutter GitHub Actions workflows, repository-quality regression tests, Docker packaging, setup documentation, and an MIT license.

## Security and correctness posture

Important controls in the release include:

- bcrypt password hashing, bounded signup passwords, HS256 JWTs with a minimum 32-byte secret, and live account-state verification on protected access;
- signup enumeration resistance: existing/new emails and concurrent unique-email races receive the same generic registration response, with request-scoped department validation performed before the account lookup;
- centralized document read/write scoping based on owner, department, privacy, and role;
- default-deny direct anon/authenticated database RLS while the service-role backend applies application policy;
- source filename sanitization, extension/signature checks, parser-readable PDF/image validation, PDF page/pixel limits, and upload admission rate limiting;
- source Storage failure treated as fatal, with ordered partial-failure cleanup;
- PBKDF2-protected optional share passwords, high-entropy expiring share tokens, POST password verification, delivery-time SHA-256 verification before signed Storage URLs are minted, and owner/admin lifecycle management that can list safe link metadata and revoke capabilities without exposing tokens or password hashes;
- safe Content-Disposition filenames, traversal-safe ZIP member names, CSV formula neutralization, folder ZIP limits on both document count and cumulative source bytes, source SHA-256 revalidation before original bytes are exported, explicit failure instead of silent partial archives, and spooled ZIP streaming;
- WebSocket credentials carried through an Authorization header or dedicated subprotocol instead of URL query parameters;
- per-process WebSocket connection caps per authenticated user, with race-safe slot reservation, exact-socket cleanup, and `1013` rejection when the configured bound is reached;
- non-root Docker runtime execution;
- exact-pinned direct Flutter dependencies, a committed application `pubspec.lock`, and CI pinned to Flutter 3.47.2 with lockfile enforcement.

The project remains a final-year prototype and does not claim production certification or formal security assurance.

## Human-in-the-loop workflow

```text
Upload / Scan
    ↓
Integrity & Duplicate Check
    ↓
Secure File Storage
    ↓
OCR & AI Extraction
    ↓
Anomaly Check
    ↓
Classification & Filing
    ↓
Needs Review
    ↓
Human correction / verification
    ↓
Verified
    ↓
Cabinet / Search / Analytics / Export / Secure Share
```

Tesseract word confidence is normalized and stored as OCR confidence. AI classification confidence is kept separate and controls whether an AI filing proposal may be accepted; low-confidence proposals route to `Needs Review`. `verified` is created only by the explicit review workflow.

Every accepted PDF page is OCR-processed up to the configured page limit. PDF rendering proceeds incrementally: each page is rendered, OCR-processed, and released before the next page is retained, except that only the first configured `MAX_AI_PAGES` rendered images are kept for the optional AI image stage. Combined OCR text and word confidence still cover all accepted pages. This reduces peak rendered-image memory while preserving document-wide OCR evidence and the existing AI page cap.

## Client/platform behavior

The CI baseline is **Flutter 3.47.2**.

- **Android:** camera scan and file upload are supported.
- **iOS:** camera scan and file upload are supported by source configuration; the project targets iOS 13+, includes `NSCameraUsageDescription`, and includes the CocoaPods camera-permission macro required by the scanner dependency.
- **Web:** file upload is implemented with picker-provided bytes for browser selections rather than relying on a local filesystem path. The mobile scanner and local-file preview are isolated through conditional Dart imports so Web compilation does not import `dart:io` or the mobile scanner implementation. A release Web build and browser upload smoke test remain required in a Flutter-equipped environment before the final demonstration.

Cabinet detail requests use backend pagination (`limit`/`offset`) and expose Previous/Next navigation rather than loading an arbitrarily large folder response.

## Operational observability

HTTP requests carry a correlation identifier through the backend. Safe caller/ingress `X-Request-ID` values are preserved; missing or unsafe values are replaced with a server-generated identifier. The ID is returned to the client, exposed through CORS, and attached to application log records through request-local context so worker-pool and background-task logs can be correlated with the originating request.

The response-completion log records method, matched route template, HTTP status, and elapsed milliseconds when the final response body is sent, so later FastAPI background-task work is not misreported as request latency. Raw query strings, request bodies, and concrete path-parameter values are not copied into this generic access log, preventing share capability tokens or document identifiers from being exposed merely for correlation.

Activity/audit records use fixed action descriptions instead of copying filenames, recipients, share tokens, storage paths, or free-form metadata into the log row. Structured `document_id` remains where needed for authorized accountability. Operational failure logs similarly avoid raw exception messages and record only an exception class alongside request correlation, reducing accidental exposure of database URLs, object paths, OCR/provider content, or other sensitive details in stdout.

Operational health distinguishes liveness from dependency readiness. `GET /` remains a no-dependency liveness check. `GET /ready` performs short, non-retrying probes for PostgREST, the private `docsort` Storage bucket, and Tesseract, returning HTTP 503 when any critical dependency is unavailable. The readiness payload reports only component `ok`/`error` states and is not cacheable; it does not surface upstream exception text or credentials. The Docker image uses liveness for its container `HEALTHCHECK`, while deployment orchestrators can use `/ready` to remove a live-but-unready instance from traffic.

This provides debugging and deployment health signaling but is not a production observability platform: logs remain stdout-based and the repository still has no centralized log aggregation, metrics/alerting backend, distributed tracing, or external error-tracking integration.

## Academic evaluation

`docs/EVALUATION.md` and `docsort-backend/evaluation/` define:

- classification accuracy and confusion matrix;
- field precision, recall, F1, and strict document match;
- OCR character error rate (CER) and word error rate (WER);
- reviewer correction rates;
- full-processing latency and duplicate-reuse latency as separate populations;
- authenticated search-latency summaries.

No project accuracy, CER/WER, F1, or latency result is claimed without an independent labelled dataset and live experiment. Unit-test fixture values are not presented as project performance.

## Final validation snapshot

Final validation was completed on the Windows development machine used for the live project demonstration:

- `pytest -q`: **432 passed, 0 failed**. Pytest reported one non-failing `StarletteDeprecationWarning` from the current FastAPI/Starlette test-client dependency stack.
- `pip check`: **No broken requirements found**.
- FastAPI release metadata remained **DocSort API v1.0.0**, with **41 HTTP paths** and **46 HTTP operations** in the generated OpenAPI inventory.
- `GET /ready`: **ready**, with **database=ok**, **storage=ok**, and **ocr=ok** against the configured Supabase project and local Tesseract installation.
- `flutter pub get --enforce-lockfile`: **passed** with the committed `pubspec.lock`.
- `flutter analyze`: **No issues found**.
- `flutter test`: **33 tests passed**.
- `flutter build web --release --dart-define=API_BASE_URL=http://127.0.0.1:8000`: **passed** and produced `build/web`.
- Live browser smoke tests covered registration, administrator approval, member/admin login, session restoration, logout/session clearing, image upload, single-page PDF upload, a 20-page PDF upload, OCR, Gemini-assisted classification/field extraction, human review, Cabinet filing, Search, duplicate reuse, and invalid-file rejection with visible client feedback.
- The invalid `.txt` upload returned HTTP 400 and produced no document row or Storage object.
- Authorization was checked both through the Flutter route guards and by direct API calls: a normal member received HTTP 403 from administrator/global-analytics/People-Map endpoints, while an assigned administrator could access the People Map successfully.

Environment-dependent validation that remains outside this snapshot:

- Docker image build/run was not part of the final Windows validation pass.
- Native Android and iOS device builds were not executed; the final executable client validation used Flutter Web.
- A fresh-machine setup with newly created Supabase/Gemini/JWT credentials remains the recommended final portability check before submission.

`pubspec.lock` is resolved for Flutter 3.47.2 and verified with `flutter pub get --enforce-lockfile`. CI uses the same lockfile-enforced dependency step before analyze/test/Web-build commands.

## Flutter workflow validation

The client exposes its secure session store behind a minimal injectable boundary, keeping `FlutterSecureStorage` as the production implementation while allowing deterministic authentication tests without a platform keychain. Role/session route decisions are isolated in a pure redirect function, and the search notifier cancels pending debounce timers when disposed and treats whitespace-only input as an empty query. These choices support deterministic testing and reliable client behavior.

The Flutter suite focuses on final-year-project demo risks: saved-session validation against `/auth/me`, expired-session cleanup, login token/role/user persistence, generic registration flow, logout cleanup, user/admin routing, upload admission and backend status transitions, transient poll failures, reset behavior, search debounce/latest-query behavior, analytics failures versus legitimate zero data, presence semantics, and People Map parsing.

## Release quality and maintainability

Storage operations use the shared `SupabaseClient` adapter as the single backend Storage abstraction. Demo-critical Flutter screens provide task-specific retry guidance without rendering raw Dart/Dio exception objects. Upload admission preserves backend-provided validation messages (for example, unsupported file type or size limits) when they are intentionally returned as public API detail, while transport/internal failures fall back to generic user-facing copy.

The documentation treats durable workers as a production architecture concern requiring durable handoff, claim/lease semantics, retry/recovery, and idempotency, and clearly distinguishes PostgreSQL full-text search from trigram-indexed search.

## Final-year release freeze

DocSort 1.0.0 is the feature-frozen BTech IT final-year release. The final engineering focus is stability, demonstrability, documentation, and honest verification rather than adding production-only infrastructure. The executable product scope is locked around the end-to-end document workflow and its supporting administration, analytics, sharing/export, integrity, and optional People Map features.

The submission/demo checklist and explicit verification boundary are maintained in `FINAL_YEAR_RELEASE.md`. Any post-freeze code change should be a verified bug fix in an existing workflow rather than a new feature or architectural expansion.

## Known architectural limits

- Runtime configuration distinguishes `development`, `test`, and `production`. `APP_ENVIRONMENT=production` fails startup when `SUPABASE_URL` is plaintext HTTP, while local development/test retain support for an HTTP Supabase emulator. This closes the source-level plaintext-production configuration gap without making local final-year-project setup unnecessarily complex.
- HTTP request correlation is built in, and `/ready` provides dependency-aware readiness for PostgREST, private Storage, and Tesseract while `/` remains pure liveness. Response-completion logging uses route templates rather than raw parameter values and excludes later background-task runtime from request latency. Logs are still stdout-only; centralized aggregation, metrics, distributed tracing, alerting, and external error tracking remain deployment concerns.
- FastAPI `BackgroundTasks` is in-process rather than a crash-durable queue/worker.
- Supabase REST/Storage calls reuse one pooled synchronous `httpx.Client` per process-level `SupabaseClient`. Audited request-time HTTP/WebSocket paths offload synchronous database/Storage/service work to Starlette's worker pool, including live-account resolution, Auth signup/login repository and password work, upload validation/admission, public sharing, analytics, Cabinet/Search/Upload-status, Admin/People Map/Export reads, Cabinet/Admin/People Map mutations, and AutoSort folder operations. Mutation order and cleanup semantics are preserved. The adapter is still synchronous, so thread-pool capacity remains a production scaling constraint rather than a native-async solution. Remaining direct `.execute()` calls in API source are inside synchronous helpers invoked through that boundary or inside the upload processor. Upload background execution applies a process-level capacity limit before dispatching processors into the Starlette worker pool, so excess jobs remain `queued` and do not consume OCR/worker capacity until a slot is available. Upload work is still in-process and non-durable, so process failure can strand queued or in-flight jobs.
- Search applies authorization scope and explicit filters before bounded candidate limits, then ranks/highlights in Python; very large installations should move ranking further into PostgreSQL FTS/trigram queries.
- People Map department graph loading batches people/document links and readable document fields into a constant number of graph-data queries (at most four, excluding authentication). Field rows are fetched only for documents that pass the existing read policy. Very large visual graphs can still be limited by the client-side force layout.
- Folder export offloads both Storage downloads and ZIP compression/archive writes from the FastAPI event loop. Export is serial, document-count/source-byte bounded, spooled, and complete-or-fail while preserving archive integrity semantics.
- Single-document export streams the private Storage response through a bounded spool threshold (spilling larger files to disk), the staged object is SHA-256 checked against the stored `file_hash`, and the API begins the client response only after staging and integrity verification succeed. Folder ZIP sources receive the same baseline check before archive insertion. Public share access stream-hashes the private object before minting a signed URL; this preserves the existing signed-URL response contract at the cost of one verification read before client download. Rows without a valid integrity baseline fail closed until repaired or re-ingested.
- Database evolution uses ordered SQL files under `docsort-backend/migrations/` with a `schema_migrations` ledger; `schema.sql` remains the fresh-install snapshot. Live PostgreSQL migration execution is still environment-dependent and should be verified before production rollout.
- Android production distribution still requires a real private release keystore configured outside source control.
- Internal `citizens*` identifiers remain behind the optional People Map.
- A privacy-safe labelled evaluation corpus is still required before reporting real numerical quality results.

## Release status

The final source is regression-protected across key security and correctness boundaries: folder ZIP exports are cumulatively bounded and fail closed on missing or integrity-mismatched source objects; single export and public sharing revalidate the stored SHA-256 source baseline before release; search authorization/filter scope precedes candidate limiting; repeated PostgREST predicates are preserved; `/auth/me` preserves designation; API metadata aligns with project version 1.0.0; Android release builds require release signing configuration rather than debug signing; and the application lockfile is committed and CI-enforced. Runtime integrations such as Flutter builds, Docker execution, and live Supabase/Gemini connectivity should be verified in the environment used for the final demonstration.

For setup instructions see `../SETUP.md`; for architecture see `../docsort-backend/ARCHITECTURE.md`; for the documentation map see `README.md`.
