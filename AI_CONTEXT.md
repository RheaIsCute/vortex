# Vortex: AI Context

## Purpose

Vortex is a Windows desktop VALORANT account manager. It stores account credentials locally, launches and verifies Riot Client sessions, shows account/rank data, manages game settings, and optionally provides live-match telemetry and an aim HUD.

## Architecture

```text
app.py (PyWebView desktop host)
  -> backend/server.py (FastAPI API and static frontend host)
       -> backend/* (storage, Riot integration, automation, live-match services)
       -> frontend/* (HTML/CSS/JavaScript UI)
```

## Directory map

- `app.py` — desktop entry point; starts Uvicorn and the native WebView window.
- `backend/` — application services. `server.py` is the API boundary; `database.py` owns SQLite; `client_launcher.py` owns Riot Client automation; `valorant_client.py` owns local Valorant APIs; `live_combat.py` and `overwolf.py` own optional live telemetry.
- `frontend/` — static UI served by FastAPI. `index.html` is the main application, `app.js` owns client state/UI behavior, and `live_overlay.*` is the HUD.
- `frontend/assets/` — shipped UI art and cached Valorant content. Preserve paths: PyInstaller bundles this directory.
- `tests/` — backend and UI-contract tests.
- `installer/` — Inno Setup installer source.
- `overwolf/vortex-telemetry/` — standalone companion telemetry extension.
- `docs/` — deeper developer documentation.
- Root build files — `build.bat`, `build_exe.spec`, `version.json`, launch helpers, and the Windows manifest. They remain at root because build, update, and packaging code references these paths directly.

## Key flows

### Account lifecycle

Accounts are created/imported through FastAPI, stored by `Database`, checked with Riot/Valorant client information, categorized, and shown by the frontend. Packaged builds store SQLite data in `%LOCALAPPDATA%\\Vortex`; source runs use the ignored root `database.sqlite`. Automatic snapshots live beside the database in `backups/`.

### Riot login and client data

`ClientLauncher` automates Riot Client sign-in and exposes login progress. Once a session exists, `ValorantLiveClient` reads local authenticated client endpoints. It must remain read-only unless an explicit feature requires otherwise. `StatScraper` enriches accounts from public/stat sources.

### UI and settings

The browser UI communicates only through the FastAPI API. Persistent settings are string values in SQLite and are accessed through `Database`. Vortex does **not** read or write VALORANT/Riot configuration files; `game_config.py` only cleans up Vortex-owned data left by a removed preset feature. All Vortex file writes/deletes on computed paths route through `backend/path_safety.py`, which rejects any Riot/VALORANT/Vanguard location.

### Live match

Live tracking is opt-in. `LiveCombatTracker` combines tracker logs and telemetry. `overwolf.py` manages the optional Overwolf companion; the web overlay is `frontend/live_overlay.*`. The Aim HUD is a **separate Vortex-owned pywebview window** (click-through `WS_EX_TRANSPARENT`, topmost), positioned over VALORANT by window handle — not injected, no graphics hook, no memory read.

### External-only guarantee

Vortex interacts with Riot Client / VALORANT **externally only**: read-only local/PVP APIs, the authenticated game endpoints the client itself calls, OS window/input automation (UIA + pyautogui), and process start/stop via `taskkill`/`Popen`. It never opens a process handle with more than `PROCESS_QUERY_LIMITED_INFORMATION`, never reads/writes another process's memory, never injects code or hooks, and never loads a driver. Set `VORTEX_AUDIT_RUNTIME=1` for a forensic log of every such operation (`backend/runtime_audit.py`).

### Build, install, update

`build.bat` invokes PyInstaller using `build_exe.spec`, stages the distribution, and compiles `installer/vortex_setup.iss`. `updater.py` reads root `version.json`, downloads a release installer, and coordinates shutdown safely. Do not move these files without updating all three systems.

## Fragile areas

- Frozen builds use `sys._MEIPASS` for bundled files but `%LOCALAPPDATA%\\Vortex` for writable data.
- Riot Client UI automation is timing- and locale-sensitive; preserve its logging and progress contract.
- The installer/updater handoff deliberately handles locked WebView2 and Overwolf processes.
- `frontend/assets/valorant-api/` is shipped runtime data, not disposable build output.

## Terminology

- **Riot Client**: sign-in launcher; **VALORANT local client**: authenticated game APIs.
- **Ranked capable**: account that can enter competitive queue, based on level or confirmed client eligibility.
- **Live Match Features**: opt-in telemetry, dashboard, and aim HUD.
