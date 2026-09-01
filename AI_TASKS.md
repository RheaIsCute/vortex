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

Notes: Updater uses GitHub latest-release API first with version.json mirrors as fallback; release-based updates remain intentional. v5.5.34 is built, pushed, tagged, published, and verified. An in-place GUI upgrade was not run because an existing legacy Vortex process could not be safely terminated in this session.

### Claude

Status: TODO

Scope:

Files likely owned:

Dependencies:

Notes:

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
