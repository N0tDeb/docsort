# Contributing to DocSort

DocSort is a final-year academic project, but changes should still preserve its security and human-review boundaries.

## Before changing code

1. Read `README.md`, `SETUP.md`, and `docsort-backend/ARCHITECTURE.md`.
2. Trace API changes through the Flutter caller, FastAPI route, service/database layer, tests, and documentation.
3. Reuse `app/core/document_access.py` for document authorization rather than introducing route-local access rules.

## Validation

Backend:

```bash
cd docsort-backend
python -m venv venv
# activate venv, then:
pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q app tests evaluation
pytest -q
```

Flutter (CI baseline: Flutter 3.47.2):

```bash
cd docsort
flutter pub get
flutter analyze
flutter test
flutter build web --release --dart-define=API_BASE_URL=https://api.example.invalid
```

Never commit `.env`, Supabase service-role keys, Gemini API keys, signing keystores, private evaluation documents, generated build output, or real document data.
