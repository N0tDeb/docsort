# DocSort End-to-End Flow

This is the current high-level execution flow for the domain-neutral DocSort project. For security and implementation details, see [`../docsort-backend/ARCHITECTURE.md`](../docsort-backend/ARCHITECTURE.md).

## 1. Authentication

1. A user signs up with an optional human-facing department code.
2. The backend resolves that code to the department UUID and creates a pending account.
3. An Organization Administrator approves the account.
4. Login verifies the password and returns a JWT.
5. Protected requests use the JWT for identity and re-check the live user row for current status, role, and department.

## 2. Upload

1. Flutter sends the PDF/image to `POST /upload`.
2. FastAPI validates the caller, size, allowed extension, and file signature (PDF/PNG/JPG/JPEG), sanitizes the filename, creates an `upload_jobs` row, and returns the job ID.
3. FastAPI schedules in-process background processing. Flutter polls `GET /upload/status/{job_id}`.

## 3. Processing pipeline

### Step 1 — Integrity & Duplicate Check

- SHA-256 is computed from the original bytes.
- Exact duplicate reuse is limited to the same uploader and department context.
- A duplicate reuses the existing document and skips Storage/OCR/AI work.

### Step 2 — Secure File Storage

- The original source is uploaded to the private Supabase Storage bucket `docsort`.
- If Storage upload fails, processing stops and the job is marked failed.

### Step 3 — OCR & AI Extraction

- Every PDF page is rendered to an image for processing; image uploads retain their real JPEG/PNG media type.
- Tesseract extracts raw OCR text and real word-level confidence values using the requested/configured OCR language set.
- When Gemini is configured, Google Gemini 3.8 Flash (`gemini-3.8-flash`) receives bounded Tesseract OCR text plus the selected rendered page images and proposes document type, structured fields, language, classification confidence, a suggested folder, and review-oriented anomaly flags. The backend requests structured JSON and validates it again with Pydantic.
- If AI extraction is unavailable/fails, the result falls back conservatively to review rather than being treated as verified.

### Step 4 — Anomaly Check

- Potential anomaly/tamper flags are stored separately from human review state.
- These flags are indicators for review, not proof of fraud.

### Step 5 — Classification & Filing

- The generic document taxonomy maps the proposed type to folders such as Finance, Human Resources, Legal, Certificates, Applications, Identity Documents, and Reports.
- Low-confidence results are routed to `Needs Review`.

## 4. Persistence and optional linking

The backend stores:

- source Storage path
- raw OCR text
- document type and language
- OCR and sort confidence
- SHA-256 hash
- anomaly flags
- extracted fields
- `review_status = needs_review`

After the durable document exists, the optional People & Document Map may link supported person-centric records. Failure of that optional feature does not delete or invalidate the document.

## 5. Human review

The Review screen lets the user correct:

- document type
- extracted field labels/values

Field replacement is performed atomically through the database RPC. Successful review marks the document `verified`, after which the UI presents it as human-verified.

## 6. Retrieval and organization

Documents can be accessed through:

- Cabinet folders
- Document Search
- Analytics
- Export
- Secure time-limited public share links

Read/write authorization is enforced by the backend because it uses the Supabase service-role key. Application tables also keep RLS enabled with no permissive anon/authenticated policies, so direct PostgREST access defaults to deny.

## 7. Failure and retry behavior

If processing fails before a durable document is established, DocSort performs best-effort database/Storage cleanup and marks the upload job failed. Flutter keeps the failure visible and offers **Retry Processing** or **Back to Upload**.

## 8. Evaluation evidence

Real processing duration is recorded in `upload_jobs.progress.processing_ms`. The evaluation tools under `docsort-backend/evaluation/` use labelled records and benchmark runs to calculate academic metrics; no result is treated as measured until such evidence exists.
