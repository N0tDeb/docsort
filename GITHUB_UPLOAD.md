# Publishing DocSort to GitHub

This archive is a **source-code export** prepared for a new GitHub repository.
Its root folder is `DocSort/`; use the *contents* of that folder as the repository root.

## Before publishing

1. **Do not publish the original project ZIP.** It included a populated
   `docsort-backend/.env`. This export removes that file and local build caches.
2. **Rotate the credentials from the original `.env` if the file was uploaded,
   shared or otherwise disclosed.** Removing a secret from this ZIP does not
   invalidate an exposed credential. Check Supabase service-role, JWT and
   Gemini credentials in particular.
3. Create your own local environment file:
   `cd docsort-backend && cp .env.example .env`. Enter your actual values
   locally. Do not commit `.env` or share keys in issues/screenshots.
4. Review project documentation for any organization-specific information
   before making the repository public.

## Publishing via Git

From the **extracted `DocSort/` directory**:

```bash
git init
git add .
git status --short
git commit -m "Initial commit: DocSort"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

Create the empty GitHub repository before `git remote add origin`; replace
`YOUR_USERNAME/YOUR_REPOSITORY` with your own destination. Never commit a
`.env` file, keystore or secret. If Git warns about identity, configure your
Git name/email using Git's own instructions.

## Project layout and local setup

- `docsort/` — Flutter app (Android, iOS, Web); keep this lowercase.
- `docsort-backend/` — Python FastAPI service.
- `.github/workflows/` — backend tests, Flutter checks and security workflows.
- Start with [`SETUP.md`](SETUP.md) for prerequisites and local run commands.

The Android Gradle wrapper scripts and JAR are included so Android builds do
not depend on a locally generated wrapper. Dependencies, Flutter SDK and
external services must still be installed/configured on the target machine.

**Validation scope:** Export integrity, Python syntax, Git staging and
secret-file exclusion can be checked offline. These checks are not a substitute
for successfully running `pytest`, `flutter analyze`, `flutter test` and
platform builds with their required dependencies and credentials. Review your
GitHub Actions results after the first push.
