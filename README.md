# Vortex | Valorant Account Manager

A tactical, purple and obsidian-black desktop account manager and rank tracker for Valorant players.

![Vortex Desktop App](https://img.shields.io/badge/Vortex-Valorant%20Manager-purple?style=for-the-badge&logo=riotgames)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python)
![FastAPI & WebView](https://img.shields.io/badge/Engine-FastAPI%20%2B%20WebView2-8a2be2?style=for-the-badge)

---

## Features

### Application

- **Desktop application.** Runs as a standalone Windows app. The Python backend (FastAPI + Uvicorn) starts on a local port bound to `127.0.0.1`, and the interface is rendered in a native window using Edge WebView2 (pywebview). It is not reachable from other machines. `python app.py --browser` opens the same interface in the default web browser instead of the desktop window.
- **Interface.** Dark theme with a choice of six accent colors (Blue, Violet, Emerald, Crimson, Amber, Cyan). The selected accent is saved automatically and applied on the next start. Uses Font Awesome icons and web fonts loaded from CDNs.
- **Per-monitor DPI awareness.** The process sets per-monitor DPI awareness at startup so text stays sharp when the window moves between displays with different scaling.
- **Automatic updates.** On start and on demand (Settings → Check for Updates), the app reads a `version.json` manifest from the project repository (via jsDelivr and GitHub Raw) and compares it to the running version. If a newer version exists it shows a banner and can download the installer and run it silently, closing and relaunching the app. A silent install that fails or cannot be verified falls back to running the installer visibly. Requires an internet connection; any failure is treated as "no update".

### Account storage

- **Local SQLite database.** Accounts are stored in `database.sqlite` (in `%LOCALAPPDATA%\Vortex\` for the packaged build, or the project folder when run from source). Each record holds username, password, region, Riot ID, category tag, notes, current rank, peak rank, level, recent win rate, recent match history, account status, PUUID, and login/update timestamps. Schema migrations run automatically on start.
- **JSON export and import.** Export writes every active account to a JSON file. Import reads such a file back; accounts already present in the roster or the banned list are skipped, not duplicated.
- **Text and combo-list import.** Paste or drop a `.txt`/`.csv` file with one account per line. Recognised separators are `:`, `,`, `|`, and tab. Recognised field orders are `username:password`, `username:password:region`, `username:password:tag`, and `username:password:RiotID#TAG`. Lines starting with `#` or `//` are ignored. Duplicates (against the roster, the banned list, or earlier lines in the same paste) are skipped. Imported accounts start with status `UNVERIFIED` until checked.
- **Category tags.** Each account has a category: `Main`, `Alt`, `Ranked`, or `Unrated`. When left on "Auto", an account is tagged `Ranked` if its level is 20 or higher and `Unrated` otherwise. Legacy `Smurf` and auto-assigned `Main` tags are migrated to `Ranked`/`Unrated` on start.
- **Pinned accounts.** Any account can be pinned. Pinned accounts sort to the top of every list and view.

### Roster view

- **Two layouts.** A card grid and a table. The table shows status, Riot ID, username, password, region, current rank, peak rank, level, win rate, category, and last login in columns.
- **Search.** A search box (focused with `Ctrl + K`) matches against username, Riot ID, and notes.
- **Filters.** Filter by region (NA, EU, AP, KR, BR, LATAM), and by category or state (All, Pinned only, Playable only, Ranked, Unrated, Main, Alt).
- **Sorting.** Sort by last used, level, pinned first, rank, win rate, name, or last updated. Pinned accounts always come first.
- **Copy buttons.** Each account card and row has buttons to copy the Riot ID, username, and password to the clipboard, and to reveal or hide the password.
- **Header counters.** The header shows totals for all accounts, Main accounts, Ranked accounts (level 20+), and Unrated accounts (below level 20).

### Rank and stat sync

- **Data source.** Rank and match data for a Riot ID (`Name#TAG`) is fetched over the web from the HenrikDev VALORANT API using an API key (a default key is bundled; a personal key can be set in Settings).
- **What is retrieved.** Account level and player card, current rank tier and division and RR, all-time peak rank and the season it was reached, recent win rate, and the last 10 matches (map, mode, result, score, agent, K/D/A, headshot percentage, and a compact roster for each match).
- **Sync one account.** The refresh button on an account re-fetches its stats. If that account is the one currently signed in to the Riot Client, its rank, level, and status are read directly from Riot's own local API instead.
- **Sync all accounts.** "Sync All" refreshes every account with a known Riot ID in parallel.
- **Automatic background sync.** Every 30 minutes the app runs a full roster sync in the background. It also repairs accounts whose status became blank so they reappear in listings.
- **Active-session sync.** While the app is open it polls the Riot Client every few seconds. When the signed-in account matches a stored account, that account's rank, level, region, status, and last-login time are updated. This is also how an account switch is detected.
- **Protected fields.** A failed or partial fetch will not overwrite a previously stored peak rank, match history, level, win rate, or PUUID with an empty value.

### Login and launch

- **Automated Riot Client login.** Vortex closes VALORANT if it is running, signs the current Riot session out through the Riot Client's local API, and enters the stored username and password into the Riot Client sign-in form. It prefers UI Automation to locate and fill the fields and verify what was typed, retrying if the sign-in page reloads mid-entry; if UI Automation is unavailable it falls back to a timed keyboard-and-clipboard sequence. If the page keeps resetting it restarts the Riot Client once and tries again. Progress is shown step by step, with a watchdog that reports an error if any step stalls. Every attempt is written to `login_debug.log` (openable from Settings).
- **"Stay signed in".** When enabled (default), the automated login ticks Riot's own "Stay signed in" checkbox so relaunching the Riot Client does not ask for the password again. After login the app checks whether Riot actually persisted the session and records the result.
- **Play.** "Play" on an account starts VALORANT for it. If that account is already the signed-in session, the game starts immediately; otherwise the account is logged in first and the game starts once the login completes. Banned or suspended accounts are not launched.
- **Session detection.** The app detects which account is signed in to the Riot Client, marks that account's card as the live session, and changes its button to "PLAY".
- **Auto-launch after login (optional, off by default).** When enabled, a plain login also starts VALORANT once it completes, so login behaves like Play.
- **Riot Client detection.** The Riot Client path is found by checking common install locations and the Windows registry. It can be set manually in Settings.
- **Force-close Riot Client.** A header button ends all Riot Client processes.

### Account verification

- **Check one account.** "Check Account" logs the account in, confirms the credentials work, and reads the real Riot ID, region, level, current rank, peak rank, and ban status from Riot's servers, then fetches its recent match history. The account is left signed in, so it flows straight into Play or the dashboard. Only offered for accounts Riot has not already confirmed.
- **Check all accounts.** "Check Accounts" logs into every unverified account in turn, with pauses between accounts to avoid Riot rate limits and a Riot Client restart every four accounts. Already-verified accounts are skipped. Accounts whose login fails are removed; accounts found banned or suspended are moved to the banned list. Progress is shown and the run can be cancelled.

### Banned accounts

- **Separate list.** Accounts detected as banned or suspended are moved to a separate banned list rather than deleted. Their credentials, last known rank, and match history are kept. The header shows a count.
- **Editing and restoring.** A banned account can be edited. Setting its status back to something playable moves it back to the main roster. It can also be restored directly, or rechecked (logged in again to confirm whether the ban is still in place). Permanent deletion is a separate, explicit action.

### Live match dashboard

- **Scope.** Opens for whichever account is currently signed in to the Riot Client. Requires VALORANT to be running for match data; identity and rank are shown as soon as the Riot Client session is detected. Polls about once a second, with a short shared cache so multiple widgets do not each trigger Riot requests.
- **Live match.** Shows the current map, mode, and side, the round-by-round score, and a running round ledger. The ledger is built by watching the score change while the dashboard is open; a match joined late is seeded from the current score with the unknown rounds marked as such. Also shows match point / elimination point, current half or overtime, and the current win/loss streak.
- **Team rosters.** Both teams, with each player's agent, level, current rank and RR, peak rank, overall and last-5 win rate, and K/D and headshot figures. Players hidden by streamer mode are shown as hidden.
- **Party detection.** Your own party is read directly from Riot. Other players' parties are inferred from shared party IDs and recent-match party partners, and shown as DUO / TRIO / n-STACK.
- **Your line.** A separate card for the signed-in player showing agent and rank for the current match, this match's live K/D/A and headshot rate when a live source is available (see Live combat data), and, always labelled as such, the rolling last-5-match averages.
- **Last match and session.** Between games, the scoreline of the match that just finished (retried for a few seconds until Riot publishes it) and a running tally for every match played since the app started.
- **Queue and mode control.** Switch the party's queue without starting matchmaking, or start matchmaking (optionally switching queue first — this is what the one-click "Start Competitive Match" button does). Leave the queue. Supported modes: Competitive, Unrated, Swiftplay, Spike Rush, Deathmatch, Team Deathmatch, Escalation, Replication.
- **Insta-lock.** Arm an agent to be selected and locked automatically the moment agent select opens. A background watcher waits for agent select, then runs a select → settle → lock sequence. "Lock Now" does the same immediately while agent select is open. All of this uses Riot's local pregame API; it does not send input to the game.
- **Player Stats tab.** A profile view for the signed-in account: rank and RR, peak rank, win/loss form and streak, combat averages, top agents, recent matches, and the skin collection. Served from a background-refreshed cache, so it appears immediately.
- **Inventory tab.** The equipped weapon skins, plus counts and the Valorant Points value of the owned skin collection, and counts of owned agents, buddies, sprays, cards, and titles.
- **Force-start VALORANT.** A dashboard button that starts VALORANT for the current session without switching accounts.

### Quick Panel overlay

- **What it is.** A small, always-on-top window (not drawn over the game) for switching accounts without opening the full app. It is a normal desktop window that floats above other windows.
- **Global shortcut.** Shown and hidden with a system-wide hotkey (default `SHIFT+5`, configurable in Settings). The hotkey is registered with the OS; if another application already owns that combination, registration fails and is logged rather than retried. The Quick Panel can be disabled entirely; changes take effect on the next start.
- **Contents.** Lists the stored accounts with search and All / Favorites / Ranked / Unranked filters, shows the current Riot session and game state, and has a set of ready-to-import crosshair profile codes to copy. Switching to an account logs it in and, unless turned off, starts VALORANT afterwards; switching away from a running game requires confirmation.

### Live Aim HUD

- **What it is (optional, off by default).** A small click-through, non-activating window in the top-right corner showing the current match's live K/D/A, headshot rate, and a round-by-round aim trace.
- **Behaviour.** Only visible while VALORANT owns the foreground and a match (agent select or in-game) is running. Outside that it fades out and the window is hidden, so nothing is left on screen in the menus or when alt-tabbed. It never sends input to VALORANT.
- **Data.** Requires a live combat source (see below) for exact current-game numbers.

### Live combat data

- **Purpose.** Riot's local API exposes the live roster but not the live scoreboard, and match details are not published until a match ends. Live K/D/A, headshot-kill rate, per-round hit reports, and the kill feed come from Overwolf's VALORANT Game Events Provider. There is no game-memory access, input injection, or screen scraping.
- **Two providers.**
  - **Vortex Telemetry** — a background-only Overwolf companion app that posts normalised events straight to the local backend. It has no in-game window and does not require VALORANT Tracker. It is side-loaded manually; see [its setup guide](overwolf/vortex-telemetry/README.md).
  - **VALORANT Tracker** — if the Overwolf VALORANT Tracker app is already installed, Vortex reads the GEP updates it writes to its own log files.
- **Overwolf management (optional, on by default).** When enabled, Vortex finds an existing Overwolf install (registry, then common paths), installs it silently if missing, and starts it minimised to the tray the same way Overwolf's own startup entry does. Install is attempted at most once per run.
- **Other players.** Other players' kills and deaths in a live match are reconstructed from the kill feed by name and are best-effort: they miss kills that happened before Overwolf attached and cannot attribute assists.

### Local game settings

- **Scope.** Riot does not sync crosshair, sensitivity, keybinds, or video settings — they live in per-account files under `%LOCALAPPDATA%\VALORANT\Saved\Config\`, created the first time that account reaches the VALORANT main menu on this PC. Every operation here is best-effort and reports clearly when an account has no settings folder yet.
- **Force windowed borderless.** Sets the display mode to windowed borderless for one account, for the current session, or for every account with settings on this PC. On launch this is applied only once the game has reached the menus, because VALORANT rewrites its video config from memory at startup and an earlier write would be undone.
- **Copy settings between accounts.** Copy the crosshair/sensitivity/HUD file, the keybinds file, and/or the video settings file from one stored account to another, or from one account to every other account with settings on this PC. Both source and target must have played on this PC at least once.
- **Settings preset.** Capture the signed-in account's settings into Vortex's own storage (the PUUID comes from the live session, so an account Vortex has never identified can still be the source). Apply the saved preset to one account or to every account, on demand or automatically right before each launch. After a capture or apply, the interface shows concrete values read back from the files (crosshair profile name, sensitivity, keybind count, display mode, resolution) rather than just a success message.

### After VALORANT closes (optional, off by default)

- Watches for VALORANT closing and, on that transition, starts a chosen program once. The program is launched fully detached, from its own directory, with the Vortex install directory removed from its `PATH` so it cannot hold Vortex's files open during an update. The path defaults to `Desktop\Private\ldr.novgk.exe` for the current user.

---

## Quick Start

### 1. Run the App
Double-click `run_app.bat` or run in terminal:
```bash
python app.py
```

### 2. Browser Mode (Optional)
```bash
python app.py --browser
```
