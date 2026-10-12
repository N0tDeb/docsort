# DocSort — Setup & Run Guide

This guide gets DocSort running from a fresh checkout. It has two parts that run
together: the **backend** (Python / FastAPI) and the **frontend** (Flutter app).
You will also need a **Supabase** project; a **Google Gemini API** key is recommended for the full AI pipeline.

---

## 1. Prerequisites

Install these once on your machine:

| Tool | Version | Notes |
|---|---|---|
| Python | 3.10+ | For the backend |
| Flutter SDK | 3.x (stable) | For the app; includes Dart |
| Tesseract OCR | 5.x | System package — see below |
| A Supabase project | — | Free tier is fine |
| A Google Gemini API key | — | Recommended for Gemini 3.8 Flash extraction/classification; OCR-only fallback works without it |
| (Android) Android Studio + a device/emulator | — | To run the app |

### Tesseract (important)

The backend reads documents in **Marathi, Hindi, and English**, so Tesseract
needs those language packs, not just the default English.

- **Ubuntu/Debian:**
  ```bash
  sudo apt-get install tesseract-ocr tesseract-ocr-mar tesseract-ocr-hin
  ```
- **macOS (Homebrew):**
  ```bash
  brew install tesseract tesseract-lang
  ```
- **Windows:** install from the UB-Mannheim Tesseract build, tick the Marathi
  and Hindi language data during setup, and note the install path — you'll point
  `TESSERACT_CMD` at `tesseract.exe` in your `.env`.

Verify: `tesseract --list-langs` should include `eng`, `hin`, and `mar`.

---

## 2. Supabase setup (do this first)

The backend expects a database and a storage bucket to already exist.

1. Create a project at supabase.com and open it.
2. **Database:** for a fresh project, open the SQL editor and run
   `docsort-backend/schema.sql`. This bootstrap snapshot creates the tables
   (departments, users, folders, documents, document_fields, upload_jobs,
   citizens, and so on), plus the `schema_migrations` ledger. The schema keeps
   RLS enabled with no permissive anon/authenticated data policies; application
   data access is expected to go through the FastAPI backend using the
   service-role key.

   For an existing DocSort database, do **not** use the snapshot as the normal
   upgrade mechanism. Inspect `schema_migrations`, then apply every pending SQL
   file from `docsort-backend/migrations/` in lexical order. A pre-migration
   database may not have the ledger yet; `0001` creates it. Review and back up
   the database first, never skip versions, and never edit an already-applied
   migration. See `docsort-backend/migrations/README.md` for the full procedure.
3. **Storage:** create a **bucket named exactly `docsort`**. The code uploads
   and reads files from this bucket by that name, so the name must match.
4. **Credentials:** from Project Settings → API, copy:
   - the **Project URL** → `SUPABASE_URL`
   - the **service_role key** → `SUPABASE_SERVICE_KEY` (server-side only; never
     ship this in the app)

---

## 3. Backend — setup & run

```bash
cd docsort-backend

# create and activate a virtual environment
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate

# install dependencies
pip install -r requirements.txt

# create your environment file from the template
cp .env.example .env
```

Now edit `.env` and fill in the required runtime values. The backend intentionally
fails fast if `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, or `JWT_SECRET` is missing;
this prevents a deployment that appears healthy but fails on its first database call.
`GEMINI_API_KEY` is recommended for the full AI extraction/classification pipeline, with `GEMINI_MODEL=gemini-3.8-flash`.
Without it, Tesseract OCR still runs and the document falls back to **Needs Review**.

Generate a strong secret (the backend requires at least 32 bytes for HS256):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Your `.env` should look like:

```
APP_ENVIRONMENT=development
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_KEY=<your service_role key>
JWT_SECRET=<the value you just generated>
GEMINI_API_KEY=<your Gemini API key>
GEMINI_MODEL=gemini-3.8-flash
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
# Windows only, if tesseract isn't on PATH:
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# Optional AI request bounds (defaults shown)
# MAX_AI_PAGES=8
# MAX_AI_OCR_CHARS=20000
```

The backend uses the official `google-genai` Python SDK and calls Gemini only server-side. `GEMINI_MODEL` is centralized in backend settings and defaults to the stable `gemini-3.8-flash` model. The AI request combines bounded Tesseract OCR text with selected rendered page images; it does not replace local OCR. If the key is missing, invalid, rate-limited, timed out, or Gemini returns invalid structured data, the upload is preserved and routed through the existing **Needs Review** fallback. Never place `GEMINI_API_KEY` in Flutter. For free-tier/demo use, check Google's current Gemini API data-use terms before sending confidential documents.

For local development, `APP_ENVIRONMENT=development` permits an HTTP Supabase
emulator such as `http://127.0.0.1:54321`. For a deployed project set
`APP_ENVIRONMENT=production`; startup will then fail unless `SUPABASE_URL` uses
HTTPS, protecting the service-role credential and document traffic from plaintext
transport.

Run the server:

```bash
uvicorn app.main:app --reload --port 8000
```

Check it's up:

- Liveness: open `http://127.0.0.1:8000/` → should return a small JSON status without contacting external dependencies.
- Readiness: open `http://127.0.0.1:8000/ready` → returns HTTP 200 only when PostgREST, the private `docsort` Storage bucket, and the configured Tesseract executable are available; otherwise it returns HTTP 503 with component-level `ok`/`error` states. Use this endpoint for load-balancer/orchestrator readiness checks.
- API docs: open `http://127.0.0.1:8000/docs` (interactive Swagger UI).

> **Note:** the frontend expects the backend at **port 8000** by default, so keep
> it on 8000 unless you also change the app's API URL (see §4).

### Optional backend settings

These have sensible defaults in `app/core/config.py` and can be overridden in
`.env`:

- `CORS_ORIGINS` — comma-separated browser origins allowed to call the API.
- `AUTOSORT_CONFIDENCE_THRESHOLD` — default `0.75`; above this, documents are
  filed automatically, below it they go to "Needs Review".
- `MAX_UPLOAD_BYTES` — default 20 MB; larger uploads are rejected.
- `OCR_LANGUAGES` — default `mar+hin+eng`.
- `ACCESS_TOKEN_EXPIRE_MINUTES` — default 1440 (24 hours).

### Optional: run the backend with Docker

The repository includes `docsort-backend/Dockerfile`, which installs Tesseract with
English, Hindi, and Marathi language data. Build and run it from the backend directory:

```bash
cd docsort-backend
docker build -t docsort-backend .
docker run --rm --env-file .env -p 8000:8000 docsort-backend
```

Keep `.env` outside the image. The Docker build deliberately does not copy secrets,
tests, or local caches into the runtime image.

---

## 4. Frontend — setup & run

Use Flutter **3.47.2**, which is also pinned in GitHub Actions. Direct package versions are exact-pinned in `pubspec.yaml`.


```bash
cd docsort

flutter pub get
flutter run
```

By default the app talks to the backend at `http://127.0.0.1:8000`. To point it
somewhere else (for example, your machine's LAN IP when testing on a phone over
Wi-Fi), pass it at run time:

```bash
flutter run --dart-define=API_BASE_URL=http://192.168.1.50:8000
```

For Flutter web, use a deterministic local port that matches the default backend CORS
allowlist, or update `CORS_ORIGINS` to the exact web origin:

```bash
flutter run -d chrome --web-port 3000
```

The Web client supports **file upload** using picker-provided bytes, so browser selections are not treated as local filesystem paths. Camera scanning is intentionally mobile-only; the scanner implementation is conditionally isolated so the Web build does not import `dart:io` or the Android/iOS scanner package implementation. Before the final demonstration, run the release Web build and smoke-test one PDF and one image upload in a browser against the demo backend.

For Android, cleartext HTTP is allowed only in **debug** builds for local development.
Release builds use Android's secure default and should point `API_BASE_URL` at an
**HTTPS** backend. This avoids accidentally shipping a production app that permits
unencrypted API traffic.

Android release signing also fails closed: the Gradle configuration never reuses
the debug key for a release build. For a distributable Android artifact, keep the
keystore outside version control and create `docsort/android/key.properties` locally:

```properties
storePassword=<your-keystore-password>
keyPassword=<your-key-password>
keyAlias=<your-key-alias>
storeFile=<absolute-or-android-relative-path-to-your-keystore>
```

`key.properties`, `*.jks`, and `*.keystore` are gitignored. If `key.properties`
is absent, no release signing configuration is attached; this prevents an
accidental debug-signed production release while keeping private signing material
out of the repository.

### Running on a physical Android device over USB

If the phone reaches the backend through the USB cable (so `127.0.0.1` on the
phone maps to your laptop), set up ADB reverse port-forwarding:

```bash
adb reverse tcp:8000 tcp:8000
```

> There's a helper at `scripts/start_dev.ps1` (Windows) that keeps the
> `adb reverse tcp:8000 tcp:8000` tunnel alive while a device is connected.

Make sure the OS grants the app **camera** permission the first time you scan.

For iOS, the project targets iOS 13+, includes `NSCameraUsageDescription`, and includes the CocoaPods camera permission macro required by the scanner dependency. On macOS, run `flutter pub get` before `pod install`/building iOS so Flutter generates `ios/Flutter/Generated.xcconfig`.

The application `pubspec.lock` is committed. Normal development can use `flutter pub get`; CI uses `flutter pub get --enforce-lockfile` so an invalid or silently changing resolution fails instead of rewriting the lockfile.

---

### Folder export safety limits

Folder ZIP export is bounded independently from upload size. By default it accepts
at most 250 documents and at most 100 MiB of combined source-file bytes
(`MAX_FOLDER_EXPORT_DOCUMENTS` and `MAX_FOLDER_EXPORT_BYTES`). The archive is
finished before streaming begins. If one or more Storage objects are missing or
unavailable, the request fails instead of returning a silent partial archive.

## 5. Running validation

Backend:

```bash
cd docsort-backend
pip install -r requirements-dev.txt
python -m compileall -q app tests
pytest -q
```

Flutter:

```bash
cd docsort
flutter pub get
flutter analyze
flutter test
flutter build web --release --dart-define=API_BASE_URL=https://api.example.invalid
```

The repository also runs these checks in GitHub Actions. Backend tests use
in-memory fakes for external services where appropriate, so normal CI does not
need production Supabase or Gemini credentials.

---

## 6. First run — bootstrap and sanity check

1. Start the backend (`uvicorn ...`) and confirm `/docs` loads.
2. Start the app (`flutter run`).
3. Register the account that will become the first organization administrator.
   New accounts intentionally start as `pending`, so a brand-new installation has no
   administrator yet. For department-scoped administrator features, register with a valid
   department code (for example `RECORDS`) or assign the department during bootstrap.
   In the Supabase SQL editor, bootstrap **that one known account**:

   ```sql
   UPDATE users
   SET role = 'admin',
       status = 'verified',
       is_active = true,
       department_id = COALESCE(
           department_id,
           (SELECT id FROM departments WHERE code = 'RECORDS' LIMIT 1)
       )
   WHERE email = 'your-admin@example.com';
   ```

   Replace the email and, if needed, the sample `RECORDS` code with the department that
   administrator should manage. `python scripts/get_depts.py` lists the configured codes.
   Do not create or store a plaintext password in SQL; registration has already created
   the bcrypt hash. An administrator with no `department_id` can still authenticate but
   cannot use department-scoped features such as the People Map or shared cabinet-folder
   management.
4. Sign in as that administrator and approve later member registrations from the app.
5. Scan or upload a document and watch the processing progress.
6. Review/correct the extracted document so it becomes **Verified**.
7. Confirm it appears in the cabinet and can be found with Document Search.

Useful local diagnostics from the repository root:

```bash
python scripts/get_depts.py       # show configured department codes/IDs
python scripts/check_supabase.py   # verify the documents table is reachable
```

Both scripts load the backend configuration from `docsort-backend/.env`.

---

## 7. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Server won't start, error about `JWT_SECRET` | `.env` is missing `JWT_SECRET`, it is still the placeholder, or it is shorter than 32 bytes. Generate a strong value as shown above. |
| Uploads fail / bucket errors | The Supabase storage bucket isn't named exactly `docsort`, or the service key is wrong. |
| OCR returns nothing / language error | Tesseract language packs missing. Check `tesseract --list-langs` for `mar` and `hin`. On Windows set `TESSERACT_CMD`. |
| App can't reach the backend | Backend not on port 8000, or on a phone you skipped `adb reverse tcp:8000 tcp:8000`. |
| Backend refuses to start with Supabase config error | Set both `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in `docsort-backend/.env`. |
| Release Android build cannot use an `http://` API URL | Expected security behavior. Deploy the backend behind HTTPS and build with that `API_BASE_URL`. |
| App shows stale name/logo after branding changes | `flutter clean && flutter pub get`, then rebuild. |
| AI classification always falls back to Needs Review | Check `GEMINI_API_KEY` is set and valid, `GEMINI_MODEL=gemini-3.8-flash`, and the Gemini API quota/network is available. |
