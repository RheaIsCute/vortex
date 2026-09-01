# Development

## Prerequisites

- Windows with Python 3.11+ recommended.
- VALORANT/Riot Client only for flows that interact with the real client.
- Inno Setup only for installer builds.

## Setup and run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

`run_app.bat` and `Launch_Vortex.vbs` are Windows launch helpers. The app listens on a loopback port near 8765 and opens a native WebView.

## Tests

```powershell
python -m pytest -q
python -m compileall -q backend tests app.py
```

Tests are primarily unit and contract tests. Tests that import browser test clients may require their optional HTTP client dependency.

## Debugging

- Login automation logs to `login_debug.log` in a source run and to the Vortex local-data directory for packaged runs.
- Check the FastAPI endpoint response before changing UI behavior.
- Treat unavailable Riot/VALORANT client data as an expected condition, not proof that an account is invalid.

## Parallel work

Use separate branches/worktrees for parallel agents. Claim files in `AI_TASKS.md`, read `AI_CONTEXT.md` and `AI_CONTRACTS.md`, and append completed work to `AI_CHANGES.md`.
