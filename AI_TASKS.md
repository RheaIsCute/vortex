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

Scope: Fix role-icon overlap in the shared recent-match row while preserving the established match-history layout.

Files likely owned: `frontend/styles.css`, `frontend/app.js`, `tests/test_settings_and_ui.py`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies:

Notes: Completed 2026-09-02. The shared recent-match row now gives the agent portrait its own selector and keeps the role icon as a 15px lower-right badge with readable contrast. Match-row data and responsive column layout were preserved.

### Claude

Status: DONE

Scope: Match history — one shared `matchCardHtml` grid row for ALL entry points (Account Manager, Dashboard / Live Stats, player-profile lookup); readable over any map; `game_date` on every path. Plus (v5.5.38) simplify the closed-game dashboard to a single theme-coloured "Play VALORANT" button (no top PLAY, no "VALORANT isn't running" card). v5.5.36 → v5.5.38.

Files owned: `frontend/app.js`, `frontend/styles.css`, `backend/valorant_client.py`, `backend/version.py`, `version.json`, `installer/vortex_setup.iss`, `tests/test_valorant_client.py`, `tests/test_settings_and_ui.py`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: Continued from `v5.5.35`.

Notes: v5.5.38 rebuilt `matchCardHtml` as a fixed CSS grid, folded the player-profile lookup into it, and deleted the last two rival row implementations. Closed/running dashboard is now driven purely by `live.valorant_running`. Verified live via CDP screenshots. No endpoint/contract change. See `AI_CHANGES.md` entries through "One match-history row everywhere … v5.5.38".

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
