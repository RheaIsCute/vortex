# Shared AI Task Board

Read this file before editing. Do not assume an assignment from stale chat context.

## Status values

- `TODO` — ready to start.
- `IN PROGRESS` — actively being changed; listed files should be treated as owned.
- `BLOCKED` — cannot continue without a decision or external dependency.
- `DONE` — complete and validated; record details in `AI_CHANGES.md`.

## Active Tasks

### Claude (density + accent discipline pass)

Status: DONE

Scope: Frontend presentation pass driven by inspection of the rendered UI —
roster/hero density (first row 583px → 430px), true column alignment across
roster rows, accent reserved for the primary action, removal of chrome that
carries no information (row `PLAYABLE` chip, empty premades panel, per-row
match-stat captions), and the layout defects that inspection turned up
(`.field-help code` flex container, header labels clipping below 1120px,
mismatched track/cell counts at the roster breakpoints, the table's Actions
column scrolling off the right edge, unreadable match-row agent avatars,
orphaned filter-chip rows, duplicated Settings labels).

Files owned: `frontend/styles.css`, `frontend/index.html`, `frontend/app.js`
(presentational only), `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: Builds on the earlier design-system and workspace-roster
redesigns. `buildAccountView()` filtering/eligibility, the shared
`matchCardHtml` row, the Live Match lifecycle and all API contracts are
untouched.

Notes: Completed 2026-09-05. **Outstanding: `pytest -q` and `.\build.bat` were
not run — Python is not installed on this machine.** `tests/` is also absent
from this checkout. `buildAccountView()` gained a presentational `statusChip`
field and `renderMatchHistoryList()` now emits a header row, so
`tests/test_settings_and_ui.py` should be re-run before release; no existing
asserted selector was removed. Verified by rendering the real frontend against
a Node mock of the API in headless Chrome over CDP across
1600/1440/1300/1200/1120/1024/900px — zero console errors, zero failed
requests. See `AI_CHANGES.md`.

### Codex

Status: DONE

Scope: Make Riot credential/window/state detection faster and more reliable,
optimize single and sequential batch credential submission, and require
Administrator elevation before all Vortex initialization.

Files owned: `app.py`, `vortex.manifest`, `build_exe.spec`, `build.bat`,
`installer/vortex_setup.iss`, `backend/elevation.py`,
`backend/client_launcher.py`, `backend/server.py`, `backend/database.py`,
`frontend/app.js`, `tests/test_login_flow.py`,
`tests/test_batch_account_check.py`,
`tests/test_account_import_and_eligibility.py`, elevation-related tests,
`tools/verify_executable_manifest.py`, `AI_CHANGES.md`, `AI_TASKS.md`,
`AI_CONTRACTS.md`

Dependencies: Preserve the v5.5.44 background-first login, popup, cancellation,
progress, banned-account, updater, installer, and compatibility contracts.
Coordinate the overlapping `build_exe.spec`, backend, and shared-log files with
the active cleanup task immediately below before editing them.

Notes: Completed 2026-09-05. The ready-control credential path is event-driven
and background-first, sequential batch dead time is state-aware, and both the
frozen manifest and source bootstrap now enforce elevation. The canonical
onedir build passed embedded-manifest and bundle-completeness checks; details
and environment limitations are in `AI_CHANGES.md`.

### Codex

Status: DONE

Scope: Backend/infrastructure cleanup and measured build-footprint reduction.

Files owned: `backend/database.py`, `backend/server.py`, `backend/paths.py`,
`build_exe.spec`, `requirements.txt`, `frontend/app.js`,
`frontend/assets/valorant-api/maps/`, `tests/test_database.py`,
`tests/test_resource_paths.py`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: Preserve all documented HTTP, SQLite, frozen-path, updater, and
external-only contracts. Asset removal requires a reference audit first.

Notes: Completed 2026-09-05. The focused audit excluded 18 unused weapon-only
images (289,696 bytes) from the frozen bundle and retained 71 skin images used
by the Inventory view. Total packaged static-asset savings are now 30,421,739
bytes (21.22%). Frozen-build validation remains unavailable in this checkout;
details are recorded in `AI_CHANGES.md`.

### Codex

Status: DONE

Scope: Build and publish the completed batch-login reliability work as v5.5.44.

Files owned: `backend/version.py`, `version.json`,
`installer/vortex_setup.iss`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: The completed background batch verification change directly below.

Notes: Completed 2026-09-03. Built and published v5.5.44 from commit
`a712427`; installer ProductVersion is 5.5.44 and the GitHub release contains
`VortexSetup.exe`.

### Codex

Status: DONE

Scope: Repair multi-account credential entry; use event-driven login progress,
mid-entry popup checks, background-first UI Automation input, explicit batch
Stop UI, and a user-global banned-username registry for batch skip decisions.

Files owned: `backend/client_launcher.py`, `backend/server.py`,
`backend/database.py`, `frontend/index.html`, `frontend/app.js`,
`tests/test_login_flow.py`, `tests/test_batch_account_check.py`,
`tests/test_account_import_and_eligibility.py`, `AI_CHANGES.md`, `AI_TASKS.md`,
`AI_CONTRACTS.md`

Dependencies: Preserve single-account Login / Check Account behavior and the
existing local banned-account store.

Notes: Completed 2026-09-03. Batch entry now uses background-first UIA,
event-driven stage waits, mid-fill popup checks, worker cancellation, an
explicit Stop state, and a credential-free global banned-username registry.
Validated with 104 passing tests plus Python/JS/diff checks.

### Codex

Status: DONE

Scope: Frontend performance / smoothness pass: audit and make targeted,
contract-preserving improvements to rendering, navigation, listeners, timers,
loading states, filtering/search, assets, match-history lifecycle, and motion.

Files owned: `frontend/app.js`, `frontend/styles.css`, `AI_CHANGES.md`,
`AI_TASKS.md`

Dependencies: Preserve the completed live-match lifecycle and external-only
filesystem/runtime audit changes already present in the worktree.

Notes: Completed 2026-09-02. Graphify/source audit found and fixed the forward
dashboard-render pause, repeated roster/modal/grid work, stale modal responses,
overlapping polls, unowned launch timers, broad CSS transitions, animated blur,
and eager below-fold assets. Validated with 98 passing tests, JS/Python checks,
HTTP smoke tests, and a successful Vortex/installer build. Browser screenshot
verification was unavailable in this environment; no Overwolf/VAL Tracker
lifecycle behavior was changed.

### Codex

Status: DONE

Scope: Publish the completed role-icon overlap fix as the v5.5.41 auto-update release.

Files likely owned: `backend/version.py`, `version.json`, `installer/vortex_setup.iss`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies:

Notes: Completed 2026-09-01. Published v5.5.41 with the role-icon overlap fix; preserved the existing match-row data and responsive layout.

### Codex

Status: DONE

Scope: Complete the Enable Live Match Features authority contract: consolidate
the legacy setting aliases and safely restore only Vortex-recorded startup
registrations when re-enabled.

Files owned: `backend/database.py`, `backend/overwolf.py`, `backend/server.py`,
`frontend/app.js`, `tests/test_overwolf_lifecycle.py`,
`tests/test_settings_and_ui.py`, `AI_CHANGES.md`, `AI_TASKS.md`,
`AI_CONTRACTS.md`

Dependencies: Preserve the completed filesystem-safety audit changes already
present in `backend/overwolf.py` and related files.

Notes: Completed 2026-09-02. `live_hud_enabled` is the authoritative persisted
Live Match Features value; historical provider keys are compatibility mirrors.
The observed `HKCU Run\Overwolf` registration is now restored only from
Vortex-recorded metadata, without overwriting a later user/installer entry.
Validated by a regenerated backend lifecycle graph and 98 passing tests.

### Claude

Status: DONE

Scope: Match history — one shared `matchCardHtml` grid row for ALL entry points (Account Manager, Dashboard / Live Stats, player-profile lookup); readable over any map; `game_date` on every path. Plus (v5.5.38) simplify the closed-game dashboard to a single theme-coloured "Play VALORANT" button (no top PLAY, no "VALORANT isn't running" card). v5.5.36 → v5.5.38.

Files owned: `frontend/app.js`, `frontend/styles.css`, `backend/valorant_client.py`, `backend/version.py`, `version.json`, `installer/vortex_setup.iss`, `tests/test_valorant_client.py`, `tests/test_settings_and_ui.py`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: Continued from `v5.5.35`.

Notes: v5.5.38 rebuilt `matchCardHtml` as a fixed CSS grid, folded the player-profile lookup into it, and deleted the last two rival row implementations. Closed/running dashboard is now driven purely by `live.valorant_running`. Verified live via CDP screenshots. No endpoint/contract change. See `AI_CHANGES.md` entries through "One match-history row everywhere … v5.5.38".

### Claude (audit)

Status: DONE

Scope: Full repo audit for Riot/VALORANT/Vanguard file or process tampering. Confirmed Vortex is external-only (no injection, no game-file writes). Added `backend/path_safety.py` guardrails + opt-in `VORTEX_AUDIT_FS` logging, wired into all computed write/delete sites, and corrected stale "config bridge" docs.

Files owned: `backend/path_safety.py`, `backend/game_config.py`, `backend/updater.py`, `backend/overwolf.py`, `backend/database.py`, `tests/test_path_safety.py`, `AI_CONTEXT.md`, `AI_CONTRACTS.md`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: None.

Notes: Completed 2026-09-02. No behavior change to accounts/login/updater/installer. 83 tests pass (79 + 4 new). See `AI_CHANGES.md` "External-only audit + path-safety guardrails".

### Claude (deep runtime audit)

Status: DONE

Scope: Deep runtime audit for any VALORANT/Riot/Vanguard process interference beyond the earlier static pass — traced actual execution (ctypes, pywin32, COM/UIA, subprocess, bundled binaries, deps, Overwolf extension, frontend overlay). Added opt-in runtime forensic logging.

Files owned: `backend/runtime_audit.py`, `backend/elevation.py`, `backend/client_launcher.py`, `backend/valorant_client.py`, `backend/overwolf.py`, `backend/server.py`, `backend/updater.py`, `tests/test_runtime_audit.py`, `AI_CONTEXT.md`, `AI_CONTRACTS.md`, `AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: Built on the earlier external-only audit + `backend/path_safety.py`.

Notes: Completed 2026-09-02. Conclusion: **Vortex is external-only** — no code inside VALORANT, no memory access, no injection/hooks, no drivers, only `PROCESS_QUERY_LIMITED_INFORMATION` process handles, Riot interaction via official local/PVP APIs + OS window/input automation + `taskkill`/`Popen`. Aim HUD is a separate click-through pywebview window. `native_autofill.cs` is dead code (never built). Added `VORTEX_AUDIT_RUNTIME=1` forensic log. No behaviour removed. 94 tests pass. See `AI_CHANGES.md` for the full evidence-backed report and A/B test procedure.

### Claude (UI/UX redesign)

Status: DONE

Scope: Frontend visual/UI design layer only — design-system consolidation
(spacing + type + alpha + modal-width scales, fixed 6 undefined CSS tokens,
shared `.surface` / `.chip` / `.btn-cta` / `.state-block` / `.spinner`
primitives, one global focus ring), `stateBlock()` + `credRows()` helpers
replacing ~11 hand-rolled fragments, modal a11y (focus trap / scroll lock /
return focus + `scrollbar-gutter` anti-jump), modal size tokens, Settings grouped
into 6 labelled sections, default accent theme blue → purple (+ purple-forward
brand wordmark), Legacy-ranked white bloom → quiet frost ring, card-badge /
stat-pill chip consolidation, dead code removed (Active Session Bar,
`matchTeamScore`, `openTrackerUrl`). No backend behaviour, no app.js
data/polling/state logic, no `live_overlay.*`, no Live Match lifecycle.

Files owned: `frontend/styles.css`, `frontend/index.html`, `frontend/app.js`
(presentational only), `backend/database.py` (the single `theme` default
string), `AI_CHANGES.md`, `AI_TASKS.md`. `tests/test_settings_and_ui.py` not
modified (no asserted string/selector changed).

Dependencies: Preserved the completed Live Match lifecycle work (merged Settings
switch, `#settings-live-match-enabled` triple-write, field-help copy), the
match-history unification (`matchCardHtml` single shared row) and the role-badge
fix — all untouched.

Notes: Completed 2026-09-02 on branch `ui/redesign-design-system`. 98 tests pass
(unchanged); `tests/test_settings_and_ui.py` 7/7 green throughout. Verified live
via headless-Chrome/CDP screenshots (zero console errors) and a Graphify
before/after diff (dead modules gone, no new hubs, no new frontend→backend
edges). Deferred (documented in `AI_CHANGES.md`): full dashboard-CSS
tokenisation, physical §11 fold, responsive-breakpoint consolidation, the
dashboard-internal half of the chip migration. Plan:
`~/.claude/plans/before-making-any-changes-mossy-ember.md`.

### Claude (workspace roster redesign)

Status: DONE

Scope: Structural UI/UX redesign of the Account Manager workspace — stats moved
out of the header into a clickable status strip, the account-card wall replaced
by dense roster rows, credentials revealed on demand, and the orphaned CSS from
the retired card removed.

Files owned: `frontend/index.html`, `frontend/styles.css`, `frontend/app.js`
(presentational + filter wiring only), `tests/test_settings_and_ui.py`,
`AI_CHANGES.md`, `AI_TASKS.md`

Dependencies: Preserved the shared `matchCardHtml` row, the Live Match
lifecycle contract, the hero/active-session card and the table view.

Notes: Completed 2026-09-03. `buildAccountView()` was deliberately left
untouched, so filtering/sorting/eligibility behaviour is identical. Verified
with 99 passing tests and headless-Chrome/CDP rendering against the real
backend (zero console errors). See `AI_CHANGES.md`.

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
