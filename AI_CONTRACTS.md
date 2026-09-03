# Cross-Module Contracts

Only documented, existing boundaries appear here. Add a contract before depending on a new shared API.

## Database account and settings service

Owner: `backend/database.py` (`Database`)

Purpose: Owns SQLite schema, account/banned-account lifecycle, imports, backups, and persistent settings.

Input: Account dictionaries, account IDs, import text, and string-keyed settings updates.

Output: Plain account/settings dictionaries and operation result dictionaries.

Stability: Core contract. Schema migrations must be non-destructive and preserve packaged-data paths.

Account import and eligibility metadata:

- `Database.import_accounts_from_raw(raw_text)` accepts one `USER:PASSWORD` row per line and returns created rows, duplicate counts, and malformed-line details. It shares the existing TXT import storage and identity checks.
- `/api/import-raw` is the UI-facing HTTP entry point for that method.
- Account responses may include `competitive_queue_eligible` (`true`, `false`, or `null`), `ranked_eligibility_source`, `is_legacy_ranked_eligible`, and `ranked_capable`. `null` means Riot did not provide a usable eligibility response and must not be interpreted as ineligible.

## HTTP application boundary

Owner: `backend/server.py` (FastAPI `app`)

Purpose: The only supported boundary between browser UI and backend services; also serves `frontend/` as static files.

Input: `/api/*` HTTP requests and Pydantic request models.

Output: JSON responses used by `frontend/app.js` and related UI files.

Stability: Treat endpoint and response-field changes as compatibility changes. Update frontend and tests together.

## Riot sign-in automation

Owner: `backend/client_launcher.py` (`ClientLauncher`)

Purpose: Locate, launch, sign into, and inspect the Riot Client while publishing login progress.

Input: Credentials, optional client path, and sign-in preferences.

Output: Login/result dictionaries and active-account metadata.

Stability: Timing-sensitive Windows contract. Keep credential handling local and never log credential values.

## Local VALORANT client integration

Owner: `backend/valorant_client.py` (`ValorantLiveClient`)

Purpose: Read authenticated local VALORANT session, party, queue, and player information.

Input: Local lockfile/session state and account identifiers.

Output: Parsed response dictionaries or unavailable/unknown values when the client cannot be queried.

Stability: Riot internal endpoints can change. Callers must handle unavailable data without treating it as a negative account state.

## Live-match telemetry

Owner: `backend/live_combat.py`, `backend/overwolf.py`, and `overwolf/vortex-telemetry/`

Purpose: Provide opt-in match state to the API and `frontend/live_overlay.*`.

Input: Tracker logs and local telemetry events.

Output: Live-combat state dictionaries with availability/source indicators.

Stability: Optional feature; account management must function when it is disabled or unavailable.

Live Match lifecycle:

- The existing persisted `live_hud_enabled` key is the sole authoritative
  value for the user-facing **Live Match Features** switch. Its legacy name is
  retained for existing databases; `overwolf_enabled` and
  `valorant_tracker_enabled` are compatibility mirrors and must not be read as
  independent lifecycle controls.
- `GET /api/settings` returns `live_hud_enabled`. `POST /api/settings` accepts
  it as string `"1"`/`"0"`, persists it before lifecycle work, and returns
  `{success: true, settings, live_match_cleanup?, live_match_startup_restore?}`.
  The transition work is asynchronous from the request handler's perspective;
  recoverable process/startup failures are reported in those optional result
  objects rather than failing the settings write.
- `backend/overwolf.py` owns the process/startup cleanup contract exposed by
  `disable_live_match_integration()`, the provider-launch gate exposed by
  `enable_live_match_integration()`, and restoration via
  `restore_startup_entries()`.
- Disable cleanup identifies VAL Tracker's `OverwolfBrowser.exe` by the exact
  Tracker app UID, closes Vortex Telemetry's matching Overwolf child, and only
  closes the shared Overwolf root when no unknown user Overwolf app is attached.
- The settings transition clears Vortex live-combat/session state and provider
  launch state; account/login and the separate autolock flow remain untouched.
- The observed Windows startup mechanism is an exact Overwolf/Tracker
  Run/RunOnce value (plus its matching HKCU StartupApproved value). Vortex
  deliberately does not alter speculative startup shortcuts or scheduled
  tasks. Removed Run entries carry Vortex-owned restore metadata in
  `live_match_startup_cleanup`; on re-enable, Vortex restores only those exact
  values and leaves an entry created later by the user or installer untouched.
- This is best-effort and least-privilege: inability to inspect, terminate, or
  edit an entry is logged and does not break account management.

## Legacy preset cleanup

Owner: `backend/game_config.py`

Purpose: One-time startup cleanup of Vortex-owned files left by a removed
settings-profile/preset feature. Vortex is external-only: it does **not** read
or write any VALORANT/Riot configuration file.

Input: None (paths are Vortex-owned, under `settings_preset/`).

Output: None.

Stability: Frozen. Do not add game-config writes here or anywhere else.

## Runtime forensic audit log

Owner: `backend/runtime_audit.py` (`record` + typed helpers)

Purpose: Opt-in observability for Vortex's sensitive OS operations. Enabled by
`VORTEX_AUDIT_RUNTIME=1`; writes `%LOCALAPPDATA%\Vortex\runtime_audit.log`.
Records process opens (with decoded access mask), process launches/terminations,
Riot API calls (method + path), window/input automation, child commands, and
provider actions. Never records secrets or payloads.

Input: Category + short non-secret description via the typed helpers
(`process_open`, `process_launch`, `process_terminate`, `riot_api`,
`window_automation`, `child_command`, `live_provider`).

Output: Log lines only. No return value, no control-flow effect.

Stability: Additive/observability contract. New code that opens a process
handle, launches or kills a process, calls a Riot API, or automates a foreign
window should call the matching helper. Disabled by default; must stay a no-op
when the env var is unset.

## Filesystem write/delete safety

Owner: `backend/path_safety.py` (`guard_path`, `safe_remove`)

Purpose: Single choke point for every Vortex write/delete on a computed path.
Normalizes/resolves the target and raises `ProtectedPathError` if it lands in a
Riot Games / VALORANT / Riot Vanguard location. With `VORTEX_AUDIT_FS=1` it
logs every guarded write/delete (path + operation, never contents).

Input: A filesystem path and an operation label.

Output: The normalized absolute path, or `ProtectedPathError`.

Stability: Core safety contract. New code that writes or deletes on a computed
path must call `guard_path` (or `safe_remove`) first.
