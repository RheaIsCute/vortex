# Shared AI Change Log

Append a new section for each completed task. Keep entries factual and concise.

## 2026-09-01 — Codex — WebView2 diagnostic startup build

Changed:

- Forced pywebview 6.2.1 to request `edgechromium` on Windows instead of allowing its registry-based automatic EdgeChromium/MSHTML choice.
- Added startup logging for application/Python/package/Windows versions, packaged WebView2 files, CLR initialization, runtime discovery, selected renderer, writable profile path, and asynchronous WebView2 environment/controller outcomes.
- Added a persistent application-owned WebView2 profile at `%LOCALAPPDATA%\\Vortex\\WebView2` with a real create/write/delete probe before initialization.
- Wrapped pywebview's WebView2 completion callback because 6.2.1 otherwise only logs `InitializationException` and leaves the malformed WinForms window open. Failure now writes the full diagnostic, shows a concise native dialog, and exits the GUI loop. No automatic browser fallback was added; explicit `--browser` mode remains available.
- Bundled Python distribution metadata so frozen logs report the packaged pywebview/pythonnet/clr-loader versions.

Files:

- `app.py`, `webview_diagnostics.py`, `build_exe.spec`
- `tests/test_webview_diagnostics.py`, `AI_CHANGES.md`, `AI_TASKS.md`

Tests/build:

- `python -m pytest -q` passed: 70 tests (2 existing FastAPI deprecation warnings).
- `python -m compileall -q app.py webview_diagnostics.py tests` and `git diff --check` passed.
- Normal source and frozen-bundle smoke tests selected `edgechromium`, discovered WebView2 152.0.4191.53, reported controller success, and started new `msedgewebview2` processes.
- Diagnostic PyInstaller bundle contains 3,868 internal files. Inno Setup produced `dist_installer/VortexSetup.exe` (277,148,848 bytes). No GitHub release was created.

Integration notes:

- The normal `dist` output was locked by an already-running pre-task Vortex instance, so the verified fresh bundle was built in `dist_diagnostic` and staged directly into the existing installer definition. The running user process was not terminated.
- No frontend, updater, account, Riot, or other feature files changed. No cross-module API changed.

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

## 2026-09-01 — Claude — Live Match polish + v5.5.35 release

Changed:

- Insta-lock: switching the selected agent while insta-lock is already armed now re-arms the backend with the new agent (`POST /api/live/instalock`), confirms the returned `instalock.agent_id` matches, and shows a brief `Autolock updated to <Agent>` success toast. On failure it reverts `state.selectedAgentId`, re-reads `/api/live/instalock`, and shows `Failed to update autolock agent`. The bottom INSTALOCK label/pill already re-render from `state.instalock`, so they follow the new target immediately. `selectAgent` is now `async`; clearing the pick or picking while disarmed stays purely local (no request) as before. The backend was already correct — `arm_instalock` calls `disarm_instalock` first, fully stopping the previous watcher — so this was a frontend-only gap.
- Start-a-Match panel: added `#btn-side-play` (reuses `.btn-ranked-cta` markup + styling). When a Riot session exists but `live.valorant_running` is false, `renderQueueControls` hides `#btn-start-ranked` and shows the PLAY action; when VALORANT is running the normal Start Match button returns. Only ever one of the two is visible. The button drives the existing `forceLaunchValorant` / `POST /api/live/launch` flow and shares its launch state.
- Theme-aware PLAY: `.btn-dash-play` no longer hardcodes green (`#16d38a` gradient / `#04160e` text / green shadow). It now uses `var(--grad-primary)` and `rgba(var(--a-rgb), …)` shadows, matching `.btn-ranked-cta` and every other accent surface, so it follows the active Vortex theme. The new side PLAY inherits the same accent by reusing `.btn-ranked-cta`.
- Agent portraits: removed `transform: translateZ(0)` from `.dash-agent-btn img`. The source `displayIcon` assets from valorant-api are already 1024×1024 (full resolution — the backend already prefers `displayIcon` over `displayIconSmall`), so this was a rendering bug: the forced GPU raster layer was not device-pixel-aware and blurred/pixelated the downscaled image on high-DPI displays. Now uses plain `image-rendering: auto` smooth scaling. Added `loading="lazy" decoding="async"` to the picker images. No `image-rendering: pixelated` anywhere.

Version:

- Bumped `backend/version.py`, `version.json`, and `installer/vortex_setup.iss` from `5.5.34` to `5.5.35` and refreshed the manifest changelog.

Files:

- `frontend/app.js`, `frontend/index.html`, `frontend/styles.css`, `tests/test_settings_and_ui.py`
- `backend/version.py`, `version.json`, `installer/vortex_setup.iss`
- `AI_CHANGES.md`, `AI_TASKS.md`

New APIs/contracts:

- None. `POST /api/live/instalock` and `POST /api/live/launch` were already part of the HTTP application boundary; only the frontend's use of them changed.

Tests:

- `python -m pytest -q` passed: 66 tests (2 pre-existing FastAPI deprecation warnings). Added `test_live_match_controls_markup` covering the new markup, the theme-accent PLAY button, the autolock feedback strings, and the smooth agent-image rendering.
- `python -m compileall -q app.py backend tests` passed.
- `build.bat` passed: PyInstaller bundle + `dist_installer/VortexSetup.exe` (installer ProductVersion `5.5.35`).
- Built-app smoke test: `dist\Vortex\Vortex.exe` served `GET /api/app-version` → `{"version":"5.5.35"}`, `GET /` → 200, `GET /api/accounts` → 200.

Limitations:

- The autolock re-arm confirmation reports success as soon as the backend accepts the new target; it does not wait for an in-progress agent-select lock to actually fire (that stays the watcher's job, surfaced through the existing status line).
- The insta-lock agent switch was verified against the live API surface and unit tests; a full in-client agent-select run was not exercised in this environment.

## 2026-09-01 — Claude — Unify dashboard match history + v5.5.36 release

Changed:

- Match history had two fully separate renderers: the Account-Manager modal (`renderMatchHistoryList` → `.match-card`, data from HenrikDev via `backend/scraper.py`: `outcome` VICTORY/DEFEAT, `kdr`, `hs_pct`, and a pre-formatted `game_date` string) and the Dashboard / Live Stats "Match History & Performance" block (`.stat-match*`, data from the local client via `_parse_match`: `result` Win/Loss, `kd`, `hs`, `started_at` epoch millis, **no date field**).
- Extracted one shared row component `matchCardHtml(m, i, source)` plus `matchOutcome(m)` (accepts VICTORY/WIN and DEFEAT/LOSS) and `matchDateLabel(m)` (prefers `game_date`, else formats `started_at` locally with the same wording, else `"Recent"` — the same fallback the Account-Manager rows already use). `renderMatchHistoryList` and the dashboard block now both call `matchCardHtml`; the dashboard uses it inside `.matches-list.matches-list-compact`. The full match-detail modal (`openMatchDetail`, shared by both) now reads `matchDateLabel(m)` instead of `m.game_date || "Recent"`, so dashboard-sourced matches show their real date there too.
- Backend: `_parse_match` now also returns `game_date`, formatted from `gameStartMillis` by a new `_format_match_date()` helper that mirrors HenrikDev's `game_start_patched` style ("Friday, August 29, 2025 5:00 PM"), in local time, "" when the timestamp is missing. `started_at` is unchanged. This makes the two paths agree on the date at the source, not just in the UI.
- Deleted the duplicated `.stat-match*` CSS (~210 lines) and the `.stat-matches` markup; added `.matches-list-compact` overrides that tighten the shared `.match-card` for the narrower dashboard column and let the stat boxes wrap under the row below ~1180px instead of overflowing.

Root causes:

- **Dashboard had no date**: the Account-Manager path gets a ready-made `game_date` string from the HenrikDev API; the local-client path only ever had the raw `gameStartMillis`, and nothing formatted it. Not a timezone/formatting bug — the field simply did not exist on that path.
- **Broken dashboard row layout**: `.stat-match` packed an outcome badge + map + score pill on one line and mode + three metric pills (HS/ADR/ACS) on a second, plus a right-hand KDA column, into the ~680px dashboard-left column. The second row wrapped and collided with the KDA column; the flag/agent art sat flush against text. The Account-Manager `.match-card` is a clean fixed-slot flex row (agent | map+date | score | stats) and does not have this problem.

Files:

- `frontend/app.js`, `frontend/styles.css`
- `backend/valorant_client.py`
- `tests/test_valorant_client.py`, `tests/test_settings_and_ui.py`
- `backend/version.py`, `version.json`, `installer/vortex_setup.iss`
- `AI_CHANGES.md`, `AI_TASKS.md`

New APIs/contracts:

- None. `_parse_match` gains an additive `game_date` field on the existing live-stats `recent[]` payload (already covered by the "Live-match telemetry" contract's "availability/source indicators" — no shape change, only an added optional field). No endpoint changes.

Tests:

- `python -m pytest -q` → 68 passed (2 pre-existing FastAPI deprecation warnings). New: `test_parsed_match_exposes_game_date_like_account_manager` (backend date field + format + empty fallback), `test_match_history_is_unified_between_entry_points` (one shared component, old duplicated markup/CSS gone, single date helper).
- `python -m compileall -q backend` passed.
- `backend.valorant_client._format_match_date` spot-checked: `0 → ""`, `1724956800000 → "Thursday, August 29, 2024 12:40 PM"`.
- `build.bat` → PyInstaller bundle (3846 `_internal` files) + `dist_installer/VortexSetup.exe`.

Limitations:

- A live side-by-side of the same match through both entry points needs VALORANT running and a signed-in account, which was not available in this environment; verified via the unit tests, the backend formatter, code review, and a production build. The in-memory `_MATCH_CACHE` is process-lifetime, so any match cached by a running older build is re-parsed (and gains `game_date`) on the next app start.
- The player-profile lookup modal keeps its own compact `.detail-history-row` mini-list — a different view with a different purpose, explicitly out of scope for this task.

## 2026-09-01 — Claude — Match-card readability fix + v5.5.37 release

Follow-up to the v5.5.36 unification: a screenshot showed the shared
`.match-card` rows (Account-Manager matches modal, and now the dashboard)
with the map splash washing out the right-side stats and the date, even
though the stored `match_history` data was complete (`kills`, `deaths`,
`kdr`, `hs_pct`, `game_date` all present and valid in `database.sqlite`).

Root cause: `.match-card` painted `var(--map-splash)` as its own
`background-image`, and `.match-card-bg-mask` faded to `rgba(...,0.35)` at
the right edge — exactly where K/D/A, KD ratio, headshot % and the date
sit — over `background-position: center right` (the busiest part of the
art). The numbers were rendered but unreadable.

Changed:

- `frontend/styles.css` — the map splash is now a dedicated `.match-card::before`
  layer at `opacity: 0.35` (0.5 on hover), behind a near-opaque
  `.match-card-bg-mask` scrim (`rgba(13,17,23, 0.97 → 0.92 → 0.82)`,
  left→right) with explicit `z-index` stacking (`::before` 0, mask 1, inner 2)
  and `isolation: isolate` on the card. Removed the fragile
  `backdrop-filter: blur(2px)`. Stat values are now `#fff` (was
  `var(--text-main)`), the low-KD variant and the date label moved off
  `var(--text-dim)` to `var(--text-sub)`, and the date label is `white-space: nowrap`.
  Row padding trimmed 12px → 11px.
- `frontend/app.js` (`matchCardHtml`) — a match with no combat line
  (degraded scrape, some placement/TDM rows) now shows `—` for K/D/A, KD
  ratio and headshot instead of a misleading `0 / 0 / 0` / `0.00` / `0%`,
  and the round score is omitted when absent rather than shown as `0 : 0`.
- Version bumped to 5.5.37 across `backend/version.py`, `version.json`,
  `installer/vortex_setup.iss`.

Files:

- `frontend/app.js`, `frontend/styles.css`
- `backend/version.py`, `version.json`, `installer/vortex_setup.iss`
- `tests/test_settings_and_ui.py`, `AI_CHANGES.md`, `AI_TASKS.md`

New APIs/contracts: none.

Tests:

- `python -m pytest -q` → 68 passed (2 pre-existing FastAPI deprecation
  warnings). `test_match_history_is_unified_between_entry_points` extended
  to assert the splash is a low-opacity layer behind a dark scrim and that
  the dash fallback exists.
- `build.bat` → PyInstaller bundle + `dist_installer/VortexSetup.exe`
  (installer ProductVersion 5.5.37); built app `GET /api/app-version` →
  `{"version":"5.5.37"}`.
- Confirmed against real data: `database.sqlite` accounts carry complete
  per-match stats and `game_date` strings — the screenshot's blank values
  were a rendering/contrast bug, not missing data or a missing date field.

Limitations:

- Verified via unit tests, a production build, direct inspection of the
  stored match data, and CSS review. No pixel screenshot of the rendered
  modal was captured in this environment (no browser-automation tooling).

## 2026-09-01 — Claude — One match-history row everywhere + simplified closed-game dashboard + v5.5.38

Two issues from a fresh screenshot pair.

### 1. Match history was still three implementations

`matchCardHtml` (v5.5.36/37) covered the Account-Manager modal and the
Dashboard, but the **player-profile lookup** modal still rendered its own
`.detail-history-row` (a third layout), and `matchCardHtml` itself was a
`justify-content: space-between` flex row whose four `min-width` sections
drifted apart into disconnected columns on a wide modal, with the map
splash painted as the row's own `background-image`.

Changed:

- Rebuilt `matchCardHtml` as **one fixed CSS-grid row** -
  `agent | map+date | result | K/D/A | KD | HS% | >` - so every match reads
  as a single entry. All three entry points now call it:
  `matchCardHtml(m, i, "account" | "dashboard" | "profile")`.
- `profileStatsHtml` no longer builds `.detail-history-row`; it renders
  `matchCardHtml` inside `.matches-list.matches-list-compact`.
- Deleted every superseded row implementation and its CSS:
  `.stat-match*` (already gone), `.detail-history*`, `.detail-agent*`,
  `.detail-outcome-pill`, `.detail-kda-stat`, `.detail-kdr-badge`, and the
  old flex `.match-card-inner` / `.match-agent-section` /
  `.match-stats-section` / `.stat-box*` markup (~260 lines net removed).
- Map art is a `.mh-splash` layer at `opacity: 0.28` behind a near-opaque
  `.mh-scrim` (`rgba(13,17,23, .97 -> .86)`); stat values are `#fff`, the
  date is `var(--text-sub)` (not the dimmest token). Verified on the running
  app via CDP screenshots: values and dates are clearly legible on every
  map, wide (1360px) and narrow (720px).
- Narrow layouts drop the KD / HS% / chevron columns and switch the date
  to a short "Aug 30, 2026" form (`matchDateShort`, which parses the same
  `game_date` string - not a new date source). Full date stays in the
  element `title`.

### 2. Duplicate Play / "VALORANT isn't running" UI

Closed-game dashboard showed the header PLAY button, a "VALORANT CLOSED"
chip, the disabled "Start Competitive Match" button re-labelled "VALORANT
isn't running / Press PLAY...", AND the "Play VALORANT" button - four
things for one action. Root cause: `#btn-start-ranked` was toggled with
the `hidden` attribute, but `.btn-ranked-cta { display: flex }` overrode a
bare `[hidden]`, so it never actually hid; and `renderPlayButton` still
drove the header PLAY button.

Changed:

- `renderPlayButton` now just keeps `#btn-dash-play` hidden - the header
  PLAY button is retired. The "VALORANT CLOSED / RUNNING" chip stays as
  status only.
- `renderQueueControls` keys purely off `live.valorant_running`
  (`const gameRunning = !!live.valorant_running`): not running -> show only
  `#btn-side-play` "Play VALORANT / Starts the game for this account";
  running -> hide it, restore `#btn-start-ranked` and the normal controls.
  The "VALORANT isn't running / Press PLAY" copy is deleted.
- Added `.btn-ranked-cta[hidden], .btn-dash-play[hidden] { display: none !important }`
  so the swap actually takes effect.
- "Play VALORANT" inherits `.btn-ranked-cta`'s `var(--grad-primary)`, so it
  follows the active theme accent (verified violet on the purple theme via
  CDP: `linear-gradient(135deg, rgb(196,113,245) ... rgb(109,40,217))`).

Verified via CDP against the running app: header PLAY hidden, Start-Match
hidden, exactly one violet "Play VALORANT", no warning card, chip reads
"VALORANT closed".

Files:

- `frontend/app.js`, `frontend/styles.css`
- `backend/version.py`, `version.json`, `installer/vortex_setup.iss`
- `tests/test_settings_and_ui.py`, `AI_CHANGES.md`, `AI_TASKS.md`

New APIs/contracts: none.

State logic (final):

- `gameRunning = !!state.live.valorant_running` (the live snapshot's process
  flag) is the single source. `if (gameRunning) -> Start Match controls;
  else -> Play VALORANT`. No independent booleans. `state.playPending` is
  only a short-lived optimistic lock cleared as soon as the snapshot
  reports `launch.active` / running / failed.

Tests:

- `python -m pytest -q` -> 68 passed (2 pre-existing FastAPI deprecation
  warnings). `test_match_history_is_unified_between_entry_points` rewritten
  for the grid row + all-three-entry-points + no dead implementations;
  `test_live_match_controls_markup` updated for the retired header PLAY,
  the removed warning copy, and `[hidden]` beating the button display.
- `python -m compileall -q app.py backend tests` passed.
- `build.bat` -> PyInstaller bundle + `dist_installer/VortexSetup.exe`
  (ProductVersion 5.5.38); built app `GET /api/app-version` ->
  `{"version":"5.5.38"}`.
- Live CDP verification on the source app (screenshots retained in the
  session scratchpad): match rows wide + narrow, and the closed-game
  dashboard.

Limitations:

- The Dashboard "Player Stats -> Match History" grid was verified by code
  (same `matchCardHtml` call) and by the shared component's screenshots;
  a live run needs VALORANT open, which was not available. The
  player-profile lookup returned no rows here (needs a Riot session) but
  is confirmed to use `matchCardHtml`, not the deleted `.detail-history-row`.

## 2026-09-01 — Codex — Riot transient login popup recovery

Changed:

- Added UI Automation tree detection for Riot's transient login modal by requiring its `Unable to load` or sign-in failure copy together with a `Sign out` button. Combined text-node matching handles UIA message splits and avoids reacting to unrelated Riot dialogs or normal signed-in state.
- Added a bounded recovery monitor after credential submission. It logs the detection, invokes `Sign out`, waits for the modal and session teardown to clear, waits three seconds, confirms the login form is ready, and reuses the existing verified credential-fill flow for the same account.
- Limited the flow to three total attempts (initial submission plus two retries). Persistent failure ends with `Riot login temporarily unavailable after 3 attempts.`; the existing batch checker then retains that account and continues to the next one.
- Kept all UI Automation calls on the login worker thread and made success confirmation require an exact active Riot username match.

Files:

- `backend/client_launcher.py`
- `tests/test_login_flow.py`
- `AI_CHANGES.md`, `AI_TASKS.md`

New APIs/contracts: none. The existing HTTP/login-progress boundary is unchanged.

Tests:

- `python -m pytest -q` → 74 passed (2 pre-existing FastAPI deprecation warnings).
- `python -m pytest -q tests/test_login_flow.py` → 10 passed.
- `python -m py_compile backend/client_launcher.py` and `git diff --check` passed.

## 2026-09-01 - Codex - Failed-attempt cleanup and legacy-ranked treatment

Changed:

- Made terminal login stages the shared cleanup boundary: success, known errors, validation failures, timeouts, popup recovery failures, and worker exceptions release the active attempt and make the next action available.
- Detects Riot client-side unsupported-special-character validation, records a non-sensitive validation log, and ends the attempt immediately. Submission monitoring now turns an unconfirmed result into a retryable terminal error instead of leaving the attempt active.
- Routed single Check Account through the same bounded login waiter used by batch checks; batch finalization also releases any leftover active login after cancellation or an exception.
- Added non-sensitive lifecycle logging for attempt mode/account, validation detection, cleanup start/completion, and next-attempt availability.
- Made `is_legacy_ranked_eligible` the frontend source for the legacy badge, category filter, and card class. Eligibility fields now participate in silent-refresh signatures, so a confirmed check repaints immediately. The white glow explicitly wins over favorite/active accent styling.

Files:

- `backend/client_launcher.py`, `backend/server.py`
- `frontend/app.js`, `frontend/styles.css`
- `tests/test_login_flow.py`, `tests/test_batch_account_check.py`, `tests/test_settings_and_ui.py`
- `AI_CHANGES.md`, `AI_TASKS.md`

New APIs/contracts: none. Existing login-progress and account eligibility response fields are unchanged.

Tests:

- `python -m pytest -q` -> 79 passed (2 FastAPI deprecation warnings).
- `python -m pytest tests/test_login_flow.py tests/test_batch_account_check.py tests/test_settings_and_ui.py -q` -> 24 passed.
- `python -m compileall -q backend` and `git diff --check` passed.

No version bump, installer build, GitHub push, tag, or release was created.

## 2026-09-02 - Codex - Recent-match role badge positioning

Changed:

- Fixed the shared recent-match row's CSS specificity conflict: the generic avatar-image rule was resizing the role image to the full 40px avatar size.
- Scoped the portrait sizing to non-role images and positioned the role icon as a consistent 15px lower-right badge with an opaque background, subtle border, and shadow. The badge can extend beyond the avatar edge without clipping while the portrait remains circular.

Files:

- `frontend/styles.css`
- `tests/test_settings_and_ui.py`, `AI_CHANGES.md`, `AI_TASKS.md`

New APIs/contracts: none. Match-row markup/data, detail fields, and responsive grid columns are unchanged.

Tests:

- `python -m pytest tests/test_settings_and_ui.py -q` -> 7 passed (2 FastAPI deprecation warnings).
- `python -m pytest -q` -> 79 passed (2 FastAPI deprecation warnings).
- `git diff --check` passed.
