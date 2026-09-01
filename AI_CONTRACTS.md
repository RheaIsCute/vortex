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

## Settings-to-game configuration bridge

Owner: `backend/game_config.py`

Purpose: Apply supported stored settings to local VALORANT configuration files.

Input: Settings values and the configured local game path.

Output: Apply/status results.

Stability: Path- and game-version-sensitive. UNDEFINED / NEEDS DESIGN for any new settings schema shared outside the existing API.
