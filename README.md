# DocSort

**DocSort is an intelligent document processing and management system using OCR and generative AI.**
Users can scan or upload documents; the backend extracts text, classifies the document,
extracts structured fields, auto-organizes it into a departmental folder, supports human
review, and makes the resulting records searchable and exportable. The project is
domain-neutral and is demonstrated with common organizational records such as invoices,
receipts, resumes, contracts, certificates, application forms, identity documents, and reports.

## Final-year release status

**Current release: DocSort 1.0.0 (feature frozen for BTech IT final-year submission).**
The implementation is intentionally scoped as a complete academic system rather than an enterprise SaaS platform. New product/architecture features should be deferred unless final validation finds a real defect. See [`docs/FINAL_YEAR_RELEASE.md`](docs/FINAL_YEAR_RELEASE.md) for the demo checklist, verification boundary, known limitations, and future scope.

## Architecture

- **`docsort/`** — Flutter app (Dart). Riverpod for state/DI,
  go_router for navigation, Dio for HTTP, secure storage for the auth token,
  and the `cunning_document_scanner` plugin for Android/iOS camera capture. Flutter Web uses the file-upload flow instead of the mobile scanner.
- **`docsort-backend/`** — Python / FastAPI. Supabase (Postgres + object
  storage), Tesseract OCR + Google Gemini 3.8 Flash (`gemini-3.8-flash`) for AI-assisted document understanding, bcrypt + JWT auth.
- **`docs/`** — documentation index, end-to-end flow, evaluation guide, final-year pitch, and final implementation report.
- **`scripts/`** — dev/utility scripts (ADB tunnel, one-off DB helpers).


## Documentation

Start with [`docs/README.md`](docs/README.md) for the current documentation map.
The backend security and policy boundary is described in
[`docsort-backend/ARCHITECTURE.md`](docsort-backend/ARCHITECTURE.md), while
[`docs/FLOW.md`](docs/FLOW.md) follows one document through the full product workflow.
The completed implementation/validation summary is in [`docs/FINAL_IMPLEMENTATION_REPORT.md`](docs/FINAL_IMPLEMENTATION_REPORT.md), and the feature-freeze/demo checklist is in [`docs/FINAL_YEAR_RELEASE.md`](docs/FINAL_YEAR_RELEASE.md). Security reporting guidance is in [`SECURITY.md`](SECURITY.md), and contribution/validation steps are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Backend setup

```bash
cd docsort-backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in real values
```

For a **fresh Supabase database**, run `docsort-backend/schema.sql` in the SQL
editor. It is the current bootstrap snapshot and creates the migration ledger
(`schema_migrations`) together with the full current schema.

For an **existing database**, apply pending files from
`docsort-backend/migrations/` in lexical order instead of treating the snapshot
as an ad-hoc upgrade script. Check `schema_migrations` before and after the
upgrade, never skip versions, and never edit a migration that has already been
applied. The first migration installs database uniqueness invariants for exact
document duplicates and AutoSort-created system folders. If existing rows
conflict with those invariants, it fails closed rather than deleting data;
reconcile the rows deliberately and retry. See
`docsort-backend/migrations/README.md` for the upgrade procedure.

Create a **private Supabase Storage bucket named `docsort`** before processing
uploads. The upload API accepts PDF, PNG, JPG, and JPEG sources; it checks file
signatures as well as extensions and stores only sanitized basenames. Source-file storage is a required part of the document record; if the
bucket is missing or unavailable, the upload job is marked failed rather than
creating a document that points at a nonexistent object.

Folder ZIP exports are bounded by both `MAX_FOLDER_EXPORT_DOCUMENTS` (250 by
default) and `MAX_FOLDER_EXPORT_BYTES` (100 MiB of source payload by default).
The ZIP is completed before response bytes are sent. If any source object is
missing or cannot be downloaded, the API fails the export explicitly instead of
returning a partial archive that could be mistaken for a complete backup.

Then start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `JWT_SECRET` are **required** — the
server fails fast when they are missing instead of starting with a broken database/storage
configuration. `APP_ENVIRONMENT` defaults to `development`; set it to `production` for a
production-style deployment, where the backend refuses any non-HTTPS `SUPABASE_URL`. `GEMINI_API_KEY` is recommended for the full AI extraction/classification
pipeline. The model is configured centrally with `GEMINI_MODEL=gemini-3.8-flash`; without a usable key, Tesseract OCR still runs and the result falls back to **Needs Review**.
Department cabinet folder creation/renaming/deletion is administrator-only; ordinary members can still upload, review, search, and manage documents within their document permissions.
The cloud AI provider is **Google Gemini 3.8 Flash** (`gemini-3.8-flash`) via the official `google-genai` Python SDK. Gemini is called only from FastAPI; no Gemini credential is compiled into Flutter. The AI request combines bounded Tesseract OCR text (`MAX_AI_OCR_CHARS`, default 20,000 characters) with at most `MAX_AI_PAGES` rendered page images (default 8), requests structured JSON matching the existing extraction schema, and validates the returned JSON again with Pydantic. AI anomaly/tamper flags are review indicators only, not forensic proof. For academic/free-tier use, review Google's current Gemini API data terms before sending real confidential documents and prefer synthetic or consented demo data.

Generate a JWT secret of at least 32 bytes with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The backend can also be containerized with the included Dockerfile:

```bash
cd docsort-backend
docker build -t docsort-backend .
docker run --rm --env-file .env -p 8000:8000 docsort-backend
```

## Frontend setup

The CI baseline is **Flutter 3.47.2**. Direct application dependencies are exact-pinned in `pubspec.yaml`.

```bash
cd docsort
flutter pub get
flutter run
```

The app talks to the backend at the URL in `lib/core/utils/constants.dart`
(defaults to `http://127.0.0.1:8000` via ADB reverse port-forwarding). Android
permits cleartext HTTP only in debug builds for this local workflow; release builds
should be compiled with an **HTTPS** `API_BASE_URL`.

Supported client paths are:

- **Android:** camera scan or file upload.
- **iOS:** camera scan or file upload; the project includes the required camera usage description and CocoaPods permission configuration.
- **Web:** file upload only. Browser-picked files are uploaded from picker-provided bytes rather than treated as local filesystem paths; the mobile scanner remains isolated behind conditional imports so the Web build does not import `dart:io` or the mobile scanner implementation. Run on port 3000 or add the exact origin to `CORS_ORIGINS`. Run the release Web build and a browser upload smoke test before the final demonstration.

The application `pubspec.lock` is committed so developers and CI use the same resolved dependency graph. CI runs `flutter pub get --enforce-lockfile`; update the lockfile deliberately with the pinned Flutter toolchain when dependency constraints change.

Android release builds never fall back to the debug signing key. For a distributable
Android release, create a local, gitignored `docsort/android/key.properties` that
references your private keystore as described in [`SETUP.md`](SETUP.md). Without
that private file, the repository remains buildable for unsigned release/static
verification without embedding development signing credentials.

Registration accepts the human-facing department `code` (for example a value
stored in `departments.code`). The backend resolves that code to the department
UUID before creating the pending user account; clients do not need to know or
guess database UUIDs.

### Organization and roles

A DocSort deployment represents one organization. `departments` are internal work
units such as Finance, Human Resources, Legal, or Records. The active role model
is intentionally small:

- **Member (`user`)** — works with documents inside their assigned department,
  subject to ownership/privacy rules.
- **Organization administrator (`admin`)** — manages accounts, approvals, presence,
  and organization-wide operational/security views. Document cabinet, sharing, and
  experimental People Map operations still apply their explicit department/document
  access policies instead of treating the admin role as an unrestricted database bypass.

Supported runtime roles are `user` and `admin`. During schema bootstrap, any
unsupported `officer` value is normalized to `user`, and the role constraint is
set to `user`/`admin`.

## Security notes

- Secrets live only in `.env` (gitignored). `.env.example` documents every key.
- CORS origins are restricted via the `CORS_ORIGINS` env var.
- JWTs establish identity, while protected HTTP and WebSocket access re-check the
  current user row for account status, role, and department. WebSocket bearer
  credentials are carried in an Authorization header or `Sec-WebSocket-Protocol`,
  not in the URL query string. Banned, pending, or deleted accounts are rejected
  without waiting for an existing token to expire. Each API process also caps
  simultaneous WebSocket connections per authenticated user via
  `MAX_WEBSOCKET_CONNECTIONS_PER_USER` (default `3`); multi-replica deployments
  need shared connection state for a global cap.
- Password authentication plus JWT/session checks are the login boundary. Protected requests use live account state rather than trusting mutable authorization claims from local client state.

### Experimental People & Document Map

The optional `/graph` feature is intentionally secondary to the core document workflow. It links supported person-centric documents (identity documents, resumes, certificates, and application forms) to people and can flag **potential** duplicate identities using conservative name/DOB similarity. It does not fabricate demo identities when no data exists and does not infer domain-specific/property relationships from unrelated document types. Internal `citizens*` database/API identifiers are implementation details behind the user-facing People & Document Map.

## Academic evaluation

DocSort includes a reproducible evaluation framework for classification accuracy, field-extraction correctness, OCR CER/WER, human correction rate, processing latency, and search latency. No evaluation percentages are hard-coded or claimed without a labelled dataset. See [`docs/EVALUATION.md`](docs/EVALUATION.md) and the tools under `docsort-backend/evaluation/`.

## Testing

DocSort validates the backend and Flutter client separately. Backend tests cover
authentication/authorization, document privacy, upload integrity, classification,
review state, sharing, graph isolation, and the custom Supabase REST adapter.

```bash
cd docsort-backend
pip install -r requirements-dev.txt
python -m compileall -q app tests
pytest -q
```

Flutter includes workflow/provider regressions for authentication/session restore, role routing, upload admission/status transitions, debounced search, analytics error/zero states, presence semantics, and People Map models. The release workflow also performs static analysis, the Dart test suite, and a Web compilation check:

```bash
cd docsort
flutter pub get
flutter analyze
flutter test
flutter build web --release --dart-define=API_BASE_URL=https://api.example.invalid
```

GitHub Actions runs both validation paths on changes to their respective project
trees (`backend-tests.yml` and `flutter-checks.yml`). Backend tests use in-memory
fakes for external services where appropriate, so CI does not require production
Supabase or Gemini credentials.

## Known items & future work

- **Scaling document processing.** Uploads are processed via FastAPI
  `BackgroundTasks`, with a process-local concurrency limit that is appropriate
  for the final-year project scope. A production worker design would need a
  durable job handoff plus claim/lease, retry/recovery, and idempotency semantics;
  that infrastructure is intentionally future work rather than a hidden one-line
  queue swap.
- **Keyword search at scale.** Search applies authorization/filters in the
  database and ranks a bounded candidate set in Python. For much larger
  cabinets, validate PostgreSQL FTS and/or trigram indexing with representative
  data and real query plans before changing the active search path.
- **Flutter dependency updates.** `pubspec.lock` is committed and CI enforces it. When changing dependency constraints, regenerate and review the lockfile with the pinned Flutter toolchain before merging.

### Sharing scope

DocSort deliberately keeps sharing small for the final-year scope. Document owners and administrators acting within their assigned document scope can create time-limited public links, list management-safe metadata for links on documents they may modify, and revoke those links. Management responses never expose reusable capability tokens or stored password hashes. Optional link passwords are stored as PBKDF2 hashes, protected links accept passwords only in a POST body, revoked links fail the existing active-link check, and successful access returns a short-lived signed Storage URL.

### Review workflow

DocSort keeps processing state separate from document review state. Upload jobs move through queued/processing/done or failed. Every newly extracted document starts as **Needs Review**; saving reviewed fields (or explicit administrator approval) marks it **Verified**. OCR confidence is derived from Tesseract word confidences and describes text-extraction quality only; it is not presented as a search-match score, classification accuracy, or proof of human verification.


## License

This repository is released under the MIT License. See [`LICENSE`](LICENSE).
