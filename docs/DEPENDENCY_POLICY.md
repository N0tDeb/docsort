# Dependency and supply-chain policy

DocSort is distributed under the MIT License. Runtime dependencies must therefore
be reviewed for security, maintenance, and license compatibility before they are
added or upgraded. This document is an engineering policy, not legal advice.

## Rules

- Flutter direct dependencies are exact-pinned in `docsort/pubspec.yaml`; the
  committed `pubspec.lock` pins the resolved graph and CI uses
  `flutter pub get --enforce-lockfile`.
- Python runtime dependencies use bounded compatible ranges in
  `docsort-backend/requirements.txt`. CI performs `pip check` and `pip-audit`;
  Dependabot opens update pull requests. Production release certification must
  record the exact resolved Python environment used to build/deploy the release.
- GitHub Actions from external repositories are pinned to immutable 40-character
  commit SHAs. `scripts/repository_sanity.py` enforces this.
- Strong-copyleft runtime libraries must not be introduced accidentally into this
  MIT-licensed distribution. A deliberate exception requires a separate license
  review and an explicit project licensing decision.
- Secrets, private signing material, local SDK paths, generated build output, and
  real document/evaluation data must remain outside source control.
- CI checkout steps disable persisted Git credentials and third-party Actions are
  commit-SHA pinned; production containers suppress the default Uvicorn server
  banner and exclude local credential material from the Docker build context.

## PDF runtime

DocSort uses `pypdfium2` to validate and render PDF pages. `pypdfium2` is offered
under Apache-2.0/BSD-3-Clause terms and bundles PDFium plus its dependency notices
in binary wheels. Anyone redistributing those binaries must preserve the license
materials shipped with the selected wheel/build.

`PyMuPDF` is intentionally not used. Its open-source distribution is AGPL-3.0,
which does not match DocSort's current MIT runtime-dependency policy. The
repository sanity checks and regression tests guard against accidental
reintroduction.


## Mobile scanner and native services

The Flutter client currently exact-pins `cunning_document_scanner` 1.4.0. On
Android, that plugin version integrates Google Play services ML Kit Document
Scanner 16.0.0; the checked-in Android/iOS camera permission declarations are
therefore treated as part of the exact-pin integration contract for this release.
Do not remove or change those declarations merely because a later plugin release
changed its permission model. Any scanner upgrade must regenerate the Flutter
lockfile with the pinned toolchain and revalidate camera denial/unavailability,
scanner launch, returned files, and Android/iOS device behavior.

Native scanner and Google service dependencies may have platform terms, privacy
requirements, and binary notices beyond the Dart wrapper license. Release
packaging must preserve notices/terms shipped with the resolved native artifacts
and review any data-flow changes introduced by an upgrade. DocSort also sends
bounded OCR text and selected rendered document pages to Google Gemini when a
server-side Gemini key is configured; confidential-document deployments must
review the applicable provider terms and organizational privacy requirements.

## Automated update/security gates

- Dependabot: Python, Dart/Flutter, GitHub Actions, Docker, and Gradle.
- Backend CI: compile, full tests, `pip check`, and `pip-audit`.
- Flutter CI: lockfile enforcement, formatting, analyzer, tests, Web release build,
  and Android release build verification.
- CodeQL: pinned Python analysis on relevant pushes/PRs plus a weekly schedule.
- Dependency Review: pinned action on public-repository dependency-changing pull
  requests, failing on newly introduced high/critical vulnerabilities. Private
  repositories can enable the same gate when their GitHub plan supports it.

Dependency/license metadata changes over time. Re-run the release dependency
audit before each tagged release rather than treating this document as a frozen
license inventory.
