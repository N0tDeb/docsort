# DocSort Flutter Client

This directory contains the Flutter client for **DocSort**, an intelligent document processing and management system.

The client supports authentication, scan/upload, processing progress, human review, cabinet browsing, document search, analytics, administration, and the optional experimental People & Document Map.

For full project setup, backend configuration, database provisioning, and development commands, see [`../SETUP.md`](../SETUP.md) and the root [`../README.md`](../README.md).

The backend base URL is configured at runtime with `API_BASE_URL`:

```bash
flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
```


## Testing

The Flutter client includes focused final-year-project regressions for the most important user-state workflows rather than only model parsing. Coverage includes saved-session restoration, login/logout/registration persistence, role-aware route guards, upload admission and status polling, transient upload-status failure handling, debounced search/error behavior, analytics error-vs-empty states, presence labels, and People Map models.

```bash
flutter pub get --enforce-lockfile
flutter analyze
flutter test
```

GitHub Actions pins Flutter 3.47.2 and runs the same analysis/test path plus a release Web build. Run the Flutter tests in CI or on a Flutter-equipped development machine before the final submission demo.
