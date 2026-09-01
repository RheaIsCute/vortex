# Shared AI Task Board

Read this file before editing. Do not assume an assignment from stale chat context.

## Status values

- `TODO` — ready to start.
- `IN PROGRESS` — actively being changed; listed files should be treated as owned.
- `BLOCKED` — cannot continue without a decision or external dependency.
- `DONE` — complete and validated; record details in `AI_CHANGES.md`.

## Active Tasks

### Codex

Status: DONE

Scope: Prepare, publish, and verify the v5.5.34 production release and auto-update flow.

Files likely owned: `backend/version.py`, `version.json`, `installer/vortex_setup.iss`, `docs/BUILD.md`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies:

Notes: Updater uses GitHub latest-release API first with version.json mirrors as fallback; release-based updates remain intentional. v5.5.34 is built, pushed, tagged, published, and verified. The installer passed an isolated temporary install test; an in-place GUI upgrade was not run because an existing legacy Vortex process could not be safely terminated in this session.

### Claude

Status: DONE

Scope: Match history — (v5.5.36) unify Dashboard / Live Stats with the Account-Manager version via one shared `matchCardHtml` component + `game_date` on both paths; (v5.5.37) fix the map splash washing out the row stats/date and show a dash for matches with no combat line.

Files owned: `frontend/app.js`, `frontend/styles.css`, `backend/valorant_client.py`, `backend/version.py`, `version.json`, `installer/vortex_setup.iss`, `tests/test_valorant_client.py`, `tests/test_settings_and_ui.py`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: Continued from `v5.5.35`.

Notes: The dashboard path never had a date field; `_parse_match` now formats a `game_date` string like the Account-Manager (HenrikDev) path, and both UIs render through `matchCardHtml`. The v5.5.37 follow-up: the row's readability bug was the map splash painted as the card's own `background-image` under a mask that faded to 0.35 opacity right where the numbers are — now a 0.35-opacity `::before` layer behind a near-opaque scrim. No endpoint/contract shape change. See both `AI_CHANGES.md` entries (Unify… v5.5.36 / Match-card readability… v5.5.37).

### Gemini

Status: TODO

Scope:

Files likely owned:

Dependencies:

Notes:

## Backlog

- Split oversized `backend/server.py`, `backend/valorant_client.py`, `frontend/app.js`, and `frontend/styles.css` only through planned, contract-preserving feature extractions.
- Decide whether cached Valorant API assets should have a documented refresh process.

## Completed

- 2026-09-01 — Workspace documentation and collaboration baseline; see `AI_CHANGES.md`.
