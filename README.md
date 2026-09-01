# Vortex | Valorant Account Manager

A tactical, purple and obsidian-black desktop account manager and rank tracker for Valorant players.

![Vortex Desktop App](https://img.shields.io/badge/Vortex-Valorant%20Manager-purple?style=for-the-badge&logo=riotgames)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python)
![FastAPI & WebView](https://img.shields.io/badge/Engine-FastAPI%20%2B%20WebView2-8a2be2?style=for-the-badge)

---

## Features

- **Purple and Obsidian Tactical Theme**: Frosted glass cards, glowing accents, and clean vector icons.
- **Native Windows Desktop Window**: Standalone desktop app powered by Edge WebView2.
- **One-Click Valorant Launch**: Auto-detects Riot Client path and copies credentials to clipboard for fast logins.
- **Live Valorant Rank Tracking**: Tracks Rank (Iron to Radiant), Division, RR, Level, and Matches.
- **Single & Batch Sync**: Refresh individual accounts or sync all accounts at once.
- **Instant Search & Filters**: Search across accounts (`Ctrl + K`) with region filters (NA, EU, AP, KR, BR, LATAM) and category filters (Main, Smurf, Alt).
- **Live Match Dashboard**: Opens for whichever account is signed in - tracks the running match round by round (score, map, mode, both team rosters with agents and ranks), starts a ranked match in one click, switches game mode, and can insta-lock an agent the moment agent select opens.
- **Live Match Features**: one default-off switch in Settings turns on live match tracking and the in-game aim HUD; Vortex enables the required telemetry providers (Overwolf/Vortex Telemetry, with the Valorant Tracker log as an internal fallback) automatically. Account management and the Riot dashboard work without it; see [the telemetry setup guide](overwolf/vortex-telemetry/README.md).
- **Play Button & Session Detection**: The app detects which account is logged into the Riot Client right now, badges that card as live, and turns its button into PLAY to launch VALORANT straight into it.
- **Per-Account Check**: A "Check Account" button on anything Riot hasn't confirmed yet - logs in once, verifies the username and password work, and pulls the real Riot ID, region, level, rank and ban status.
- **Dual View Modes**: Grid View and Spreadsheet Table View.
- **Safe Local Storage**: Stored in `database.sqlite` with full JSON Export and Import capabilities.

---

## Quick Start

### 1. Run the App
Install dependencies once, then double-click `run_app.bat` or run:

```powershell
pip install -r requirements.txt
python app.py
```

### 2. Browser Mode (Optional)
```powershell
python app.py --browser
```

## Project Structure

```text
app.py                 Desktop entry point
backend/               FastAPI API, storage, Riot integration, live-match services
frontend/              Static application UI, overlay, and shipped assets
tests/                 Automated tests
installer/             Inno Setup installer definition
overwolf/              Optional Vortex Telemetry companion
docs/                  Architecture, development, and build documentation
build.bat              Windows packaging entry point
```

## Development

```powershell
python -m pytest -q
.\build.bat
```

Vortex uses local SQLite storage. In a source checkout it is the ignored `database.sqlite` file; packaged builds use `%LOCALAPPDATA%\\Vortex`. Do not commit account data, logs, backups, build output, or secrets.

For programmatic combo pastes, `POST /api/import-raw` accepts `{ "text": "USER:PASSWORD\\n..." }`. The first colon separates the username; blank/comment lines are ignored, malformed rows are reported, and duplicate detection/storage match the normal TXT import path. Account responses expose `competitive_queue_eligible` and derived `ranked_capable` / `is_legacy_ranked_eligible` when Riot provides a real queue-eligibility signal.

For architecture, development workflow, and release details, see [Architecture](docs/ARCHITECTURE.md), [Development](docs/DEVELOPMENT.md), and [Build & Release](docs/BUILD.md). Agents collaborating on the repository should begin with [AI_CONTEXT.md](AI_CONTEXT.md) and [AI_RULES.md](AI_RULES.md).
