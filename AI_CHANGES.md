# Shared AI Change Log

Append a new section for each completed task. Keep entries factual and concise.

## 2026-09-01 — Codex — Workspace reorganization baseline

Changed:

- Established `docs/` as the documentation home while preserving current runtime-critical source and packaging paths.
- Added collaboration context, task, rule, change-log, and contract documents.
- Expanded ignore coverage for test reports, temporary files, crash dumps, and ordinary logs while retaining the Overwolf telemetry exception.

Files:

- `AI_CONTEXT.md`, `AI_TASKS.md`, `AI_RULES.md`, `AI_CONTRACTS.md`, `AI_CHANGES.md`
- `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, `docs/BUILD.md`
- `README.md`, `.gitignore`

New APIs/contracts:

- None; documented existing boundaries only.

Integration notes:

- Root, `backend/`, `frontend/`, `installer/`, and `overwolf/` paths remain stable because the desktop host, PyInstaller spec, installer, updater, and tests reference them directly.

Tests:

- `python -m compileall -q app.py backend tests` passed.
- `python -m pytest -q` passed: 59 tests (2 existing FastAPI deprecation warnings).
- Loopback Uvicorn smoke test passed: `GET /` returned HTTP 200.
- `build.bat` passed: PyInstaller produced `dist/Vortex/Vortex.exe` and Inno Setup produced the installer.

Known issues:

- Large feature modules remain candidates for future incremental extraction.

## 2026-09-01 — Codex — Raw import and Ranked eligibility backend

Changed:

- Added named raw-combo import support and `/api/import-raw`; rows trim whitespace, skip blanks/comments, split on the first colon, report malformed lines, and reuse duplicate/storage behavior.
- Added persisted Riot queue-eligibility metadata and derived `ranked_capable` / `is_legacy_ranked_eligible` account fields.
- Used Riot's read-only party eligible-queues response as the only legacy Ranked signal; unavailable responses remain unknown rather than being guessed.
- Kept confirmed eligibility from being erased by partial refreshes and synchronized automatic Ranked/Unrated categorization and summary counts.
- Reduced warm sign-out teardown delay from 1.5s to 0.2s and client restart release delay from 1.2s to 0.7s. Login stages now log elapsed time for measurement.

Tests:

- `python -m pytest -q` passed: 63 tests (2 existing FastAPI deprecation warnings).
- `python -m compileall -q app.py backend tests` passed.
- `git diff --check` passed.
- `build.bat` passed: PyInstaller and Inno Setup completed successfully.

Limitations:

- Riot's local party endpoint can be unavailable outside a usable VALORANT session; the account remains `competitive_queue_eligible: null` in that case. No Beta/legacy label is inferred from account age, level, or rank history alone.

## 2026-09-01 — Codex — Final UI and repository synchronization

Changed:

- Finalized the accumulated UI, settings, raw-import, Ranked eligibility, Riot Client recovery, documentation, and test updates in this workspace.
- Made the Account Manager-to-Dashboard slide start from the synchronous view-state update; agent ownership refreshes after the animation is scheduled rather than delaying it.
- Removed the embedded HenrikDev API-key default. New installations require a user-provided value in Advanced / Developer Settings.

Security:

- No credentials, account data, logs, build artifacts, caches, or machine-local files were staged. The existing local database, backups, build output, installer output, and login log remain ignored.

Tests:

- `python -m pytest -q` passed: 63 tests (2 existing FastAPI deprecation warnings).
- `python -m compileall -q app.py backend tests` and `git diff --check` passed.
- `build.bat` passed: PyInstaller created a 3,846-file runtime bundle and Inno Setup created `dist_installer/VortexSetup.exe`.
- Loopback Uvicorn smoke test passed: `GET /` returned HTTP 200; account and settings APIs responded.
