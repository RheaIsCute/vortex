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

## 2026-09-01 — Codex — v5.5.34 release preparation

Changed:

- Bumped the authoritative application version in `backend/version.py` and the updater manifest in `version.json` to `5.5.34`.
- Synchronized the Inno Setup fallback version and documented the release/tag/asset verification checklist.
- Kept update discovery release-based: the updater compares the manifest version fetched from jsDelivr/GitHub Raw and downloads the manifest’s `VortexSetup.exe` release asset.
- Added GitHub’s latest-release API as the first update source so CDN-stale manifests cannot hide a newly published stable release; arbitrary commits remain excluded.

Build:

- `build.bat` produced the v5.5.34 PyInstaller bundle (3,846 internal files) and `dist_installer/VortexSetup.exe` successfully.

## 2026-09-01 — Codex — v5.5.34 release published and verified

Changed:

- Published tag/release `v5.5.34` with the production `VortexSetup.exe` asset.
- Hardened update discovery with GitHub’s latest stable release API ahead of CDN manifest mirrors, preserving release-only update semantics.

Verification:

- Release asset is 277,127,879 bytes, starts with the Windows `MZ` signature, and matches the local installer SHA-256 `58b093f999c4fccde951c8e540326d4c498e726967d0e78bf80ee15545eccfaf`.
- A simulated v5.5.33 updater detected v5.5.34 and the exact release asset URL; a v5.5.34 updater correctly reported current.
- The real updater download path fetched and validated `VortexUpdateSetup-5.5.34.exe` successfully (temporary file removed afterward).
- The currently running legacy Vortex process prevented a second GUI instance from being launched for an in-place upgrade test; no running user process was terminated. Source/API and downloaded-production-asset checks passed instead.
- The production installer was also run silently into an isolated temporary directory with application closing disabled; it exited 0, produced `Vortex.exe`, and wrote `installed_version.txt` as `5.5.34`. The temporary installation was removed after verification.
