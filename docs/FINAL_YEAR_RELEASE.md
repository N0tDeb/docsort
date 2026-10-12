# DocSort 1.0.0 — Final-Year Release

## Release purpose

DocSort 1.0.0 is the **feature-frozen BTech IT final-year project release**. The goal of this release is a complete, demonstrable, technically defensible academic system rather than an enterprise-scale SaaS platform. New architecture or product features should not be added before submission unless final validation discovers a real defect in an existing workflow.

## Feature freeze

The implementation scope is frozen around the demonstrated document lifecycle: authentication, upload/scan, source validation and private storage, OCR, optional AI-assisted structured extraction/classification, AutoSort, human review, cabinet/search, analytics, People Map, secure export, public sharing/revocation, administration, integrity verification, and audit/operational safeguards.

After this release, changes should be limited to verified bug fixes, submission documentation, screenshots, demo data, presentation material, and viva preparation.

## Demo checklist

Use deterministic sample data and rehearse this path before the final presentation:

1. Start the backend and verify `GET /` returns liveness and `GET /ready` reports dependencies.
2. Log in with a prepared approved member account.
3. Upload a known PDF or image and show the processing stages.
4. Open the result in **Needs Review**, correct at least one extracted field, and save it as **Verified**.
5. Show the document in the Cabinet and retrieve it through Search.
6. Open Analytics and explain that displayed counts are application data, not model-accuracy claims.
7. Demonstrate one optional differentiator: People Map, secure share/revocation, or export.
8. Show an administrator workflow such as account approval/security review if time permits.
9. Keep one known-good local sample document and backup screenshots available in case an external AI/network dependency is unavailable during the demo.

Do not depend on a live AI call for the only successful demo path: OCR and human review remain valid when optional AI enrichment is unavailable.

## Verification boundary

The final repository was validated on the Windows development machine used for the live demonstration. The release checks included the complete backend regression suite, dependency validation, live readiness checks against Supabase/Tesseract, Flutter lockfile resolution, static analysis, Flutter tests, and a release Web build.

For a fresh checkout, run the same client verification commands:

```bash
cd docsort
flutter pub get --enforce-lockfile
flutter analyze
flutter test
flutter build web --release --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

Also configure a new Supabase project, private `docsort` Storage bucket, Tesseract language data, JWT secret, and Gemini key as described in `SETUP.md`, then verify `GET /ready` before the demonstration.

### Final local verification snapshot

- backend regression suite: **432 passed, 0 failed**; one non-failing Starlette test-client deprecation warning;
- `pip check`: **No broken requirements found**;
- live `/ready`: **database=ok, storage=ok, ocr=ok**;
- `flutter pub get --enforce-lockfile`: **passed**;
- `flutter analyze`: **No issues found**;
- `flutter test`: **33 passed**;
- Flutter Web release build: **passed**;
- live application checks: image/PDF processing, 20-page PDF processing, review/save/search, duplicate reuse, invalid-file rejection, session persistence/logout, and member/admin authorization: **passed**.

Docker and native Android/iOS builds remain outside this validation snapshot.

## Known limitations

These are intentional scope boundaries, not hidden defects:

- upload processing uses process-local FastAPI `BackgroundTasks` with bounded concurrency rather than a crash-durable distributed worker queue;
- rate limiting and WebSocket connection caps are process-local rather than shared across multiple API replicas;
- search ranks a bounded authorized candidate set in Python rather than relying on production-tuned PostgreSQL FTS/trigram plans;
- large People Map layouts can still be limited by client-side graph-layout cost;
- centralized monitoring, external error tracking, automated backup/restore, CD/rollback, and multi-organization tenancy are outside the final-year implementation scope;
- real quality metrics require a privacy-safe labelled evaluation dataset and must not be invented from unit-test fixtures.

## Future scope

Appropriate future work after academic submission includes a durable claim/lease/retry/idempotent worker design, real PostgreSQL integration/load testing and query-plan-led indexing, optional centralized monitoring/error tracking, backup/restore automation, shared multi-replica rate/connection state, richer Flutter test coverage, and large-scale search/graph optimization.

These items should be presented as production-scale evolution of the current architecture, not as missing requirements for the BTech final-year release.
