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

Scope: Final integration, dashboard transition responsiveness, security review, verification, and GitHub synchronization.

Files likely owned: `frontend/app.js`, `backend/database.py`, `backend/scraper.py`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies:

Notes: Reviewed complete workspace diff; tests, build, and loopback application smoke test passed. Dashboard transition now schedules immediately before live-agent refresh work.

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
