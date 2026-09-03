# Shared AI Change Log

Append a new section for each completed task. Keep entries factual and concise.

## 2026-09-03 — Release v5.5.43

Published the Account Manager workspace redesign (status strip + roster rows,
see "Claude — Account Manager workspace redesign" below) as v5.5.43.
`backend/version.py`, `version.json`, `installer/vortex_setup.iss` bumped
5.5.42 → 5.5.43. 99 tests pass (`pytest -q tests` — 8/8 in
`test_settings_and_ui.py` including the new `test_roster_workspace_layout`);
`python -m compileall -q backend tests app.py` and `node --check
frontend/app.js` both clean. No installer build was run in this environment
(Inno Setup not present) — GitHub Actions / a local build with Inno Setup
installed still needs to produce and attach `VortexSetup.exe` to the release
for the in-app updater to pick it up.

## 2026-09-03 — Codex — Repository structure documentation

Added `docs/REPO_STRUCTURE.md`, a current-state repository map based on the
refreshed Graphify graph and direct source-tree inspection. No runtime behavior
was changed.

## 2026-09-03 — Release v5.5.42

Published the accumulated completed work as v5.5.42: the external-only
filesystem + runtime audits (opt-in `VORTEX_AUDIT_FS` / `VORTEX_AUDIT_RUNTIME`
logging, `backend/path_safety.py`, `backend/runtime_audit.py`), the Enable Live
Match Features authority contract (`live_hud_enabled` authoritative, scoped
startup cleanup/restore), the frontend performance/smoothness pass, and the
frontend UI/UX redesign below. `backend/version.py`, `version.json`,
`installer/vortex_setup.iss` bumped 5.5.41 → 5.5.42. 98 tests pass;
`python -m PyInstaller build_exe.spec` produces a complete `dist/Vortex` bundle
(installer step needs Inno Setup, which was not present in this environment).

## 2026-09-02 — Claude — Frontend UI/UX redesign (design-system consolidation)

Visual/UI layer only. No backend behaviour, no `app.js` data/polling/state logic,
no `live_overlay.*`, no Live Match lifecycle. Branch `ui/redesign-design-system`.

### Audit (Graphify + 3 Explore agents + headless-Chrome/CDP screenshots)

Graphify built this session (`graphify-out/`, scoped to 52 code/doc files, assets
excluded). Frontend is one `app.js` (5.9k L) + `styles.css` (8.6k L) + `index.html`
(1k L) served raw (no bundler). Findings that drove the work:

- `styles.css` had a good token base (surfaces, strokes, radii, shadows, motion,
  a 6-theme accent ramp) undermined by: **no spacing scale** (427 hardcoded px),
  **no type scale** (29 font sizes with half-px steps), **6 undefined CSS tokens**
  (`--stroke`, `--accent`, `--text`, `--font-sans`, `--border`, `--tier-color`)
  referenced across 22 sites in the match-detail modal subtree (rendered with
  browser-default borders/text as a result), ~13 one-off accent glows, ~18
  white-alpha + ~14 black-alpha ad-hoc values, `.modal-card`/`.dash-panel`
  byte-identical, ~20 pill/chip classes, 5 parallel stat-card impls, ~5
  PLAY-button styles, a bolt-on "Section 11 — UI/UX POLISH PASS", 10 responsive
  breakpoints in 3 disconnected passes.
- Dead code: the entire "Active Session Bar" feature (`renderSessionBar` +
  `#session-bar` never in the DOM + 8 null `DOM.session*` bindings + orphan
  `.session-bar*` CSS), plus `matchTeamScore()` and `openTrackerUrl()`
  (definition-only, no callers).
- `matchCardHtml(m,i,source)` confirmed the single shared match row — untouched.
- `tests/test_settings_and_ui.py` asserts on markup as text (substring +
  `str.split()` on CSS rule headers); every asserted id / class / string / rule
  header was preserved.

### Changes

**Design tokens (`styles.css` §1, additive):**
- Spacing scale `--sp-0..12` (2–60px), type scale `--fs-2xs..2xl` +
  `--lh-tight/normal`, `--radius-2xs: 4px`, neutral alpha steps `--wa-1..4` /
  `--ba-1..4`, modal-width scale `--modal-w-sm/md/lg/xl`, and a fixed
  accent-independent `--brand-grad`.

**The 6 undefined tokens (`styles.css` `body` accent block):** defined as aliases
(`--stroke`→`--stroke-2`, `--accent`→`--a`, `--text`→`--text-main`,
`--font-sans`→`--font-main`, `--border`→`--stroke-2`). The whole match-detail /
scoreboard / profile-grid subtree now resolves like the rest of the app.
`--tier-color` left as-is (already set inline by `profileStatsHtml`, every use
site already has a `var(--tier-color, var(--accent))` fallback).

**Shared primitives (`styles.css` new "5.9 SHARED PRIMITIVES" subsection):**
- `.surface` / `--raised` / `--flush` (card/panel box).
- `.chip` + `.chip--accent/ok/warn/danger/info/neutral/frost` (the shared pill).
- `.btn-cta` (the shared PLAY-style button; hover = `filter: brightness()` +
  shadow step, no `translateY`).
- `.state-block` + `.state-block__icon/__title/__hint` + `.state-block--error` and
  `.spinner` (+ `spin` keyframe) — the shared loading/empty/error block.
- One global `:where(...):focus-visible { box-shadow: var(--ring) }` (0-specificity;
  existing per-element focus rules still win where they exist).
- `body.modal-open { overflow: hidden; scrollbar-gutter: stable; }` (scroll-lock
  that does not shift the page).

**`stateBlock()` helper (`app.js`, near `escapeHtml`):** replaced all 7 hand-rolled
`.no-matches-msg` divs (match-history modal load/error/empty, player-lookup
load/error/empty, match-detail scoreboard fallback). `.no-matches-msg` CSS
deleted. Also removed a stray inline `var(--accent-purple)`.

**`credRows(acc)` helper (`app.js`):** the identical user/pass `.cred-row` pair
from the grid card and the hero card is now one helper (~44 lines de-duplicated);
`.credentials-box` / `.hero-creds-box` wrappers unchanged.

**Modal accessibility (`app.js` `openModal`/`closeModal`):** save + restore focus
on close, Tab focus-trap inside the sheet while open (WeakMap of handlers),
body scroll-lock. `closeAllModals` already routed through `closeModal`. Focus
lands on the sheet container (`tabindex=-1`), not the close button. Global ESC
handler and `initOverlayDismiss` backdrop-close unchanged.

**Modal sizing/spacing (`styles.css` §7):** `.modal-card` / `.modal-small` /
`.modal-large` / `.modal-matches-card` / `.modal-import-card` / `.modal-detail-card`
widths → the `--modal-w-*` scale (matches modal 860→780; import 640→580).
`.modal-header` / `.modal-close` / `.modal-form` / `.modal-footer` / overlay
backdrop → `--sp-*` / `--ba-4` / `--fs-*`. Selectors and the `::before` accent
seam kept verbatim.

**Settings grouping (`index.html` + `styles.css`):** the 7 flat `.form-group`s are
now 6 labelled `<section class="settings-section">` blocks (Appearance / General /
Updates / Live Match / Post-Game / Launch & Login) + the existing `<details>`
Advanced. Only `<section>`/`<h3 class="settings-section-title">` wrappers added —
every `#settings-*` id, `data-theme` swatch, `.form-group`/`.switch-row`/
`.field-help`, and the asserted labels ("Post-Game Actions", "Launch &amp; Login",
"Advanced / Developer Settings") kept verbatim. `openSettingsModal()` unchanged.

**Purple default (`index.html`, `app.js`, `backend/database.py`):**
`body class="theme-blue"` → `"theme-purple"`; `applyTheme` fallback + `VALID_THEMES`
order → purple first; theme-picker swatch order → Violet first; DB `theme`
default `"blue"` → `"purple"` (one string; `theme` is a free string in the
settings contract — **no AI_CONTRACTS change**). Existing users' saved choice is
respected. `.brand-wordmark` gradient pinned to a purple ramp (`#fff → #c9a2ff →
#fff`) so the wordmark stays purple-forward under any accent. `--brand-grad`
token added for logo/boot alignment.

**Legacy-ranked treatment (`styles.css` §11.3):** the loud triple white
`box-shadow` bloom (`0 0 30px …`) → a quiet frost ring (`inset 0 0 0 1px
var(--wa-2)` + `var(--wa-4)` border); when the card is also active/favourited the
accent `--glow-sm` layers on top instead of two blooms fighting. `.badge-legacy`
→ `--wa-*` tokens. **`.account-card.is-legacy-ranked.is-favorite` selector kept
verbatim** (asserted). The authoritative `isLegacyRankedEligible(acc)` flag and
its consumers are untouched.

**Card-badge / stat-pill consolidation (`styles.css` §4/§6):** `.badge-region`,
`.badge-tag`, `.badge-status`, `.badge-live` and `.stat-pill` now share the
`.chip` box shape (`--radius-full`, `--sp-*` padding, `--fs-2xs`, `--stroke-2`),
keeping only their own colours. Section 11 header renamed from "UI/UX POLISH PASS"
to "COMPONENT DETAILS".

**Dead code removed:**
- `renderSessionBar()` (fn + its sole call site) + 8 null `DOM.session*` bindings
  + the `#btn-session-play`/`#btn-open-dashboard` guarded listeners + orphan
  `.session-bar*` / `session-bar-in` / `.session-live-dot` CSS + its
  reduced-motion entry. `.session-state-chip` **kept** (used by the hero card and
  the dashboard).
- `matchTeamScore()`, `openTrackerUrl()` — definition-only, deleted.

**Card CSS tokenised** where touched (grid/gap/padding on `.account-card` and
`.accounts-grid`).

### Verification

- `python -m pytest -q` → **98 passed** (unchanged from the pre-change working
  tree; `tests/test_settings_and_ui.py` 7/7 green at every step).
- `python -m compileall -q backend app.py` clean; `node --check` on `app.js` /
  `boot.js` clean; `git diff --check` clean.
- Ran the source app (`uvicorn backend.server:app`) and drove headless Chrome via
  CDP (`Page.captureScreenshot`) — 42 screenshots per pass at 1280/1600/1920 px
  and 150 % DPI, covering the roster (grid/table/empty/skeleton/hero),
  filter popover, all 8 modals, settings (+ Advanced open), dashboard (idle),
  toasts, and all six accent themes. **Zero JS console errors** on every pass.
  Note: this app's live SQLite backend mutates between runs (active-session
  detection, background sync), so full-page pixel diffs are unreliable — each
  screenshot was reviewed directly. The match-detail modal, previously rendering
  with browser-default borders/text, now renders correctly.
- Re-ran Graphify (same 52-file scope). Diff vs the pre-change graph:
  `renderSessionBar`, `matchTeamScore`, `openTrackerUrl` **gone** from the node
  list; `stateBlock`, `credRows` present as leaf helpers (not hubs); god nodes
  unchanged (`showToast`, `initEventListeners`, `escapeHtml`, `fetchAccounts`);
  graph health 0 missing/self-loop edges; `app.js` still relates to
  `backend/server.py` only via the API boundary — **no new frontend→backend
  edges, no orphaned old modules, no duplicate replacement components** (one
  `matchCardHtml`, one `stateBlock`, one `.chip`, one `.surface`).

### Not done (deferred — lower visibility, higher regression risk / context cost)

- Full tokenisation sweep of the 4,400-line dashboard CSS (§10). The dashboard
  adopts the new tokens where its rules were touched; a complete pass is a
  follow-up.
- Physical fold of the (now-renamed) Section 11 sub-blocks into sections 4-7 —
  they already consume the shared tokens/primitives in place.
- Responsive-breakpoint consolidation (10 → 4). The duplicated `1280` / `1080`
  media blocks remain.
- Full 20-class `.chip` migration — the account-card badges + `.stat-pill` +
  `.badge-live` are done; the dashboard-internal chips are part of the deferred
  dashboard pass.

### Files

`frontend/styles.css`, `frontend/index.html`, `frontend/app.js`,
`backend/database.py` (one default string), `AI_CHANGES.md`, `AI_TASKS.md`.
Plan: `~/.claude/plans/before-making-any-changes-mossy-ember.md`.
Graphify outputs regenerated in `graphify-out/`.

## 2026-09-02 — Codex — Frontend performance / smoothness pass

- Audited the frontend hot paths with Graphify before and after the pass. The
  pre-edit graph had 1,175 nodes / 2,507 edges; the refreshed code-only graph
  has 1,186 nodes / 2,522 edges and still reports no import cycles. The updated
  query traces `openDashboard` → `runViewSlide` → `renderDashboard`, the live
  polling loop, account/filter rendering, modal history/profile flows, and the
  listener/timer owners.
- Fixed the forward-navigation asymmetry: the dashboard now gets its first
  animation frame before the expensive initial dashboard render, while close
  remains the reverse path. Added a stored animation fallback timer and
  height correction after the deferred render.
- Removed repeated DOM/listener churn by delegating banned-account, mode, and
  agent-grid clicks to stable containers. Added stale-response guards for
  account/filter, banned-account, match-history, and player-profile requests;
  modal close now aborts in-flight history/profile work.
- Made check-account, launch-progress, stats-summary, and player-stats work
  single-flight; refreshes now skip unchanged roster/banned/stats markup, and
  the account-check path no longer repaints the roster on every 1.5-second
  status tick. Launch follow-up timers now have explicit ownership and are
  cancelled on teardown.
- Reduced avoidable visual work without redesigning the UI: replaced the
  shared `transition: all`, stopped animating modal backdrop blur, removed blur
  from account-card entrance animation, shortened its stagger, and marked
  below-the-fold dynamic images `loading="lazy" decoding="async"`. Existing
  reduced-motion/effects-paused behavior and Overwolf/VAL Tracker lifecycle
  behavior were preserved.

Validation:

- `python -m pytest -q` — 98 passed (2 existing FastAPI deprecation warnings).
- `node --check frontend/app.js`, `python -m compileall -q app.py backend tests`,
  and `git diff --check` passed.
- `build.bat` passed: `dist\Vortex\Vortex.exe` with 3,909 internal files and
  `dist_installer\VortexSetup.exe` were produced.
- Local smoke checks returned HTTP 200 for the app shell, frontend assets,
  settings, stats, accounts, and banned-account endpoints. The in-app browser
  runtime was unavailable (`No browser is available`), so no visual click/
  screenshot verification was possible in this environment.


## 2026-09-02 — Codex — Live Match authority completion

- Kept the existing `live_hud_enabled` database key as the one authoritative
  persisted **Live Match Features** state. The historic provider keys are now
  migration/compatibility mirrors; provider startup, telemetry, app startup,
  and the frontend no longer read them independently.
- Re-enable now restores only exact Run/RunOnce registrations that Vortex
  recorded removing. Metadata includes the matched command, registry type/view,
  and StartupApproved state where present. An entry that appeared after the
  off transition is treated as a user or installer change and is never
  overwritten; unsupported or failed restoration stays recorded for a later
  explicit re-enable attempt.
- The only discovered integration startup mechanism was the exact
  `HKCU\Run\Overwolf` value. Cleanup is intentionally limited to evidenced
  Run/RunOnce registrations (and the matching StartupApproved value), rather
  than removing speculative shortcuts or scheduled tasks.
- Regenerated the scoped backend lifecycle graph: 742 nodes, 1,654 extracted
  edges, 1,494 built directed edges. Source and graph inspection confirm the
  sole provider wake path is the enabled live snapshot; all Overwolf/Tracker
  launch and installer paths retain the process-local gate.

Validation:

- `python -m pytest -q` — 98 passed (2 existing FastAPI deprecation warnings).
- `python -m py_compile backend/database.py backend/server.py backend/overwolf.py app.py`
  and `node --check frontend/app.js` passed.
- `git diff --check` passed. Graph health reported no missing endpoints; its
  130 dangling static references are external/shared symbols outside the
  scoped `backend/` corpus, not lifecycle bypasses.

## 2026-09-02 — Claude — Deep runtime audit for VALORANT/Riot process interference

Audit method: traced actual execution, not string matches — every `ctypes`/`windll`
call, pywin32 use, COM/UIA path, `subprocess`/`Popen`, bundled binary, native
helper, third-party dependency, the Overwolf extension, and the frontend overlay.

Findings (evidence-backed — see the FINAL REPORT in the task thread for line refs):

- **No Vortex-owned code runs inside the VALORANT process.** No injection of any
  kind: no `CreateRemoteThread`/`NtCreateThreadEx`, no `SetWindowsHookEx`, no
  `AppInit_DLLs`, no proxy/IAT/inline hooks, no MinHook/EasyHook/Detours/Frida,
  no graphics/DirectX/overlay hook. `build_exe.spec` ships `binaries=[]` — zero
  custom native modules. `backend/native_autofill.cs` is **dead code**: never
  compiled, bundled, or referenced.
- **No process memory access.** No `ReadProcessMemory`/`WriteProcessMemory`,
  `Nt*VirtualMemory`, `VirtualAllocEx`, `MapViewOfFile`, section mapping, handle
  duplication, or shared-memory IPC anywhere. No `pymem`-style dependency.
- **Process handles: the only `OpenProcess` calls request `PROCESS_QUERY_LIMITED_INFORMATION`
  (0x1000)** — `backend/elevation.py:_process_elevation` (read Riot Client's
  elevation token) and `backend/client_launcher.py:is_valorant_foreground` (read
  the foreground window's image name). Process *existence* checks use
  `CreateToolhelp32Snapshot` (name enumeration, no handle). No QUESTIONABLE or
  INVASIVE access mask (`VM_READ/WRITE/OPERATION`, `CREATE_THREAD`,
  `DUP_HANDLE`, `SUSPEND_RESUME`, `ALL_ACCESS`) is requested anywhere.
- **No driver or service interaction.** No `DeviceIoControl`, no `\\.\` device
  opens, no `OpenSCManager`/`CreateService`/`StartService`, no `sc.exe`, no
  `.sys` handling, no vulnerable-driver library. Vanguard (`vgc.exe`,
  `vgtray.exe`, `vgk.sys`, `vgc.sys`) is **never referenced** except as a
  protected path `backend/path_safety.py` refuses to write to.
- **Process termination** is OS-level `taskkill /F /IM` on VALORANT + Riot
  Client only (`client_launcher.kill_valorant`, `force_kill_riot_client`),
  during account-switch teardown — plus Riot's own local
  `DELETE /rso-auth/v1/session` for sign-out. Overwolf/VAL Tracker cleanup uses
  `taskkill /PID` on Overwolf PIDs only. Vanguard is never touched.
- **Live Match / Aim HUD is a separate Vortex-owned pywebview desktop window**
  (`app.py` `_make_live_hud_controller`): `WS_EX_TRANSPARENT` click-through,
  `WS_EX_TOOLWINDOW`, `HWND_TOPMOST`, positioned over VALORANT via
  `SetWindowPos`, shown/hidden from `is_valorant_foreground()`. The code
  explicitly rejects `WS_EX_LAYERED`. No injection, no graphics hook, no memory
  read — the textbook external-overlay architecture.
- **Overwolf / VAL Tracker**: Vortex `Popen`s `OverwolfLauncher.exe -overwolfsilent`
  and the vendors' own silent installers (downloaded to `%TEMP%`). It installs
  no Vortex plugin into VALORANT and modifies no Overwolf config. The bundled
  `overwolf/vortex-telemetry/` extension declares `permissions: ["GameInfo","Web"]`
  only (not `Extensions`), has no overlay/in-game window
  (`start_window: background`), and only *reads* Overwolf's Game Events Provider
  stream, POSTing normalized events to `127.0.0.1:8765+`. Whether Overwolf's GEP
  attaches to VALORANT is **Overwolf's** behaviour, not Vortex's. Disabling Live
  Match Features stops every provider launch and cleans up
  (`overwolf.disable_live_match_integration`).
- **Riot local/remote APIs** are the lockfile-authenticated Riot Client REST API
  (`127.0.0.1:<port>`, self-signed cert) and the authenticated PVP endpoints
  (`glz-*.a.pvp.net`, `pd.*.a.pvp.net`) — the same endpoints the game client
  calls. Most are GET. State-changing calls: `PUT name-service/v2/players`
  (name lookup), `POST parties/.../queue|matchmaking/join|leave`,
  `POST pregame/.../select|lock/<agent>`, `POST product-launcher .../launch`,
  `DELETE rso-auth/v1/session`. All are official matchmaking/session actions,
  not file/memory/process operations.
- **Registry**: reads only (`winreg.OpenKey` + `QueryValueEx`/`EnumValue`) to
  locate the Riot Client and (Overwolf cleanup) to enumerate `Run`/`RunOnce`.
  The only registry *writes* are `DeleteValue` on HKCU/HKLM `Run` entries that
  match Overwolf/VAL Tracker exactly (`overwolf._cleanup_registry_startup`) —
  never any Riot/Vanguard key.

Answers to the task's direct questions (all evidence-backed, none from assumption):

- Does any Vortex-owned code execute inside VALORANT? **No.**
- Does Vortex write to VALORANT memory? **No** (no memory API is called at all).
- Does Vortex obtain write/operation/thread rights to VALORANT? **No** — only
  `PROCESS_QUERY_LIMITED_INFORMATION`.
- Does Vortex modify Riot/VALORANT/Vanguard files? **No** (confirmed static +
  runtime: every such path is opened `"r"`).
- Does Vortex load drivers? **No.**
- Does Vortex indirectly cause a Vortex-owned component to inject? **No** — the
  only bundled companion (Vortex Telemetry) is a background Overwolf GEP reader.
- Does Live Match / Overwolf introduce a separate injected component? Not from
  Vortex. Overwolf's own GEP runtime is third-party; Vortex neither ships nor
  configures an injected piece.

Changed (this task adds observability only — no behaviour change, nothing removed):

- Added `backend/runtime_audit.py`: opt-in (`VORTEX_AUDIT_RUNTIME=1`) forensic
  log at `%LOCALAPPDATA%\Vortex\runtime_audit.log` (or `<repo>\runtime_audit.log`
  from source). Records `process.open` (with decoded access mask, flags
  `INVASIVE` bits), `process.launch`, `process.terminate`, `riot.api`
  (method + path), `window.automation`, `child.command`, `file.outside`,
  `live.provider`. Never logs passwords, tokens, Authorization/Basic-auth, or
  bodies (with a scrub backstop for query strings and `//user:pass@`).
- Wired it into: `elevation._process_elevation` + `relaunch_elevated`;
  `client_launcher` `is_valorant_foreground`, `kill_valorant`,
  `force_kill_riot_client`, `api_sign_out`, both Riot Client `Popen` launches,
  `auto_fill_credentials`, `focus_window`; `valorant_client` `_remote` (non-GET),
  `_spawn`, `_launch_via_client_api`; `overwolf` `ensure_running`, `_taskkill`,
  both provider installers; `server._spawn_detached`; `updater` background spawn.

Files:

- `backend/runtime_audit.py` (new), `backend/elevation.py`,
  `backend/client_launcher.py`, `backend/valorant_client.py`,
  `backend/overwolf.py`, `backend/server.py`, `backend/updater.py`
- `tests/test_runtime_audit.py` (new), `AI_CONTEXT.md`, `AI_CONTRACTS.md`,
  `AI_CHANGES.md`, `AI_TASKS.md`

Tests/build:

- `python -m pytest -q` → 94 passed (2 pre-existing FastAPI deprecation
  warnings). Was 91; +3 runtime-audit tests.
- `python -m compileall -q app.py backend tests` and `git diff --check` passed.
- Manual smoke: `VORTEX_AUDIT_RUNTIME=1` produces the expected audit lines and
  correctly flags a synthetic `PROCESS_VM_WRITE` open as `INVASIVE`; secrets in
  a URL are scrubbed to `<redacted>`.
- Full app build (`build.bat`) not run this task (no code path affecting the
  bundle changed; `binaries=[]` unchanged).

Recommended removals (optional — all inert today):

- `backend/native_autofill.cs` — dead C# mouse/keyboard autofill helper, never
  built or referenced. Safe to delete outright; the Python UIA + pyautogui path
  is the live implementation.

Still needs manual review / not code-determinable here:

- Overwolf's GEP runtime and the VAL Tracker app are third-party closed-source;
  whether *they* attach to or read VALORANT is outside this repo. The isolation
  lever is "Live Match Features off", which this audit confirms stops all Vortex
  provider launches and cleans up.
- A/B runtime test (Vortex fully closed vs running vs Live Match on) — procedure
  documented in the FINAL REPORT; not executed here (no live VALORANT session).

## 2026-09-02 — Codex — Enable Live Match Features lifecycle

Changed:

- Made the existing merged Live Match Features setting control Vortex live
  runtime state and the Overwolf integration. Turning it off clears live
  combat/session caches, blocks provider and installer launches, stops matching
  external processes immediately, and runs the same cleanup once at Vortex
  startup when the persisted setting is off. Account/login and autolock flows
  remain separate.
- Identifies the observed VAL Tracker runtime as `OverwolfBrowser.exe` with
  the exact app UID
  `ipmlnnogholfmdmenfijjifldcpjoecappfccceh`. The observed shared process set
  is `Overwolf.exe`, `OverwolfBrowser.exe`, `OverwolfHelper.exe`, and
  `OverwolfHelper64.exe`; the known `OverwolfLauncher.exe` identity is also
  supported. Vortex-owned in-flight installers named
  `OverwolfSetup-vortex.exe` and `ValorantTrackerSetup-vortex.exe` are also
  targeted. Shutdown requests graceful tree termination, waits, then uses
  `/F` only for remaining matching PIDs, with failures logged.
- Startup cleanup is scoped to matching Overwolf/Tracker entries in HKCU/HKLM
  `Run` and `RunOnce`, the matching HKCU `StartupApproved\Run` value, exact
  startup-folder shortcut names, and clearly matching scheduled tasks. The
  current machine had only `HKCU\...\Run\Overwolf`; no separate VAL Tracker
  Windows startup entry or scheduled task was found. Removed/disabled entry
  identity is stored as non-secret `live_match_startup_cleanup` metadata.
- A shared Overwolf root is left running when an unknown user Overwolf app is
  attached, while exact Tracker/Vortex-owned browser processes can still be
  stopped. Re-enabling only re-arms on-demand behavior and does not recreate
  startup registrations. The UI keeps one simple switch and explains the
  external cleanup.

Files:

- `backend/overwolf.py`, `backend/server.py`, `frontend/index.html`
- `tests/test_overwolf_lifecycle.py`, `tests/test_settings_and_ui.py`
- `AI_CONTRACTS.md`, `AI_TASKS.md`, `AI_CHANGES.md`

Tests/build:

- `python -m pytest -q` — 91 passed; 2 existing FastAPI deprecation warnings.
- `python -m compileall -q app.py backend tests`, `node --check
  frontend/app.js`, and `git diff --check` passed.
- Standard `build.bat` reached PyInstaller but could not replace the locked
  existing `dist\Vortex` bundle because the running Vortex process holds its
  files. The same PyInstaller spec built a fresh 3,868-file bundle in `%TEMP%`,
  and Inno Setup successfully compiled `dist_installer\VortexSetup.exe` from
  that verified bundle.

Limitations:

- Overwolf's observed `AutoLaunchInstalledApps` setting is global to Overwolf;
  it was not modified because changing it would affect unrelated Overwolf
  apps. Therefore this implementation removes Windows startup registrations
  and prevents Vortex from re-launching the integration, but cannot safely
  control Overwolf's own per-game autolaunch behavior for the Tracker when an
  unrelated Overwolf app keeps the shared root alive.
- Verification did not invoke the destructive off action on the live machine;
  the observed Overwolf/Tracker processes were intentionally left running.

## 2026-09-02 — Claude — External-only audit + path-safety guardrails

Audit result:

- Full workspace searched for Riot Client / VALORANT / Vanguard file or process tampering: install dirs, executables, DLLs, configs, manifests, pak/assets, registry keys, process memory, DLL injection, remote threads, hooks, handle manipulation, drivers, symlinks/junctions. Also Python, PowerShell, batch, VBS, installer, updater, bundled `.cs`, and the Overwolf extension.
- **No Riot/VALORANT/Vanguard file is modified, replaced, patched, deleted, renamed, or created anywhere.** No `WriteProcessMemory` / `CreateRemoteThread` / `NtWriteVirtualMemory` / DLL injection / code caves / inline hooks exist. The only `OpenProcess` calls (`elevation.py`, `client_launcher.py`) use `PROCESS_QUERY_LIMITED_INFORMATION` — read-only token/name checks. No registry writes exist.
- Riot interaction is entirely external: reads the Riot Client lockfile and `RiotGamesPrivateSettings.yaml` (`"r"` only), calls the Riot Client's own localhost REST API (`GET`/`DELETE /player-session`, product-launcher PLAY endpoint), reads `ShooterGame.log` / `RiotClientInstalls.json` / product settings, UI Automation + `native_autofill.cs` mouse/keyboard input on the Riot Client window, `subprocess.Popen` to start `RiotClientServices.exe`, and process/window detection via `tasklist` / toolhelp snapshot.
- `game_config.py` was already reduced (in a prior task) to deleting Vortex-owned `settings_preset/` leftovers; the `AI_CONTEXT.md` / `AI_CONTRACTS.md` "settings-to-game configuration bridge" wording was stale and is now corrected.
- `server.py` post-VALORANT-close launcher runs a **user-configured** program path (default points at a user-supplied `Desktop\Private\ldr.novgk.exe` if present). Vortex only `Popen`s it — never creates or modifies it. No change made; noted for manual review.
- Installer (`vortex_setup.iss`) writes only to `{app}` and kills only Vortex/Overwolf/WebView2 processes. Updater writes only to `%TEMP%` and delegates install to the Inno installer. Neither touches Riot paths.

Changed:

- Added `backend/path_safety.py`: `guard_path(path, op)` normalizes + fully resolves a target and raises `ProtectedPathError` if it lands in a Riot Games / VALORANT / Riot Vanguard location (install trees, `%LOCALAPPDATA%\Riot Games`, `%LOCALAPPDATA%\VALORANT`, `Riot Vanguard`, `vgk.sys` / `vgc.sys`). `safe_remove(path)` is `os.remove` behind the same guard. Opt-in audit logging of every guarded write/delete via `VORTEX_AUDIT_FS=1` (logs path + operation only, never contents).
- Wired the guard into every computed write/delete site: updater installer download (`updater.py`), Overwolf + Valorant Tracker installer downloads (`overwolf.py`), SQLite backup write and snapshot pruning (`database.py`), legacy preset cleanup (`game_config.py`). Fixed-constant `%TEMP%` handshake files were left as-is (not computed from external input).
- `game_config.py` legacy cleanup now uses `safe_remove`; docstring clarified.

Files:

- `backend/path_safety.py` (new), `backend/game_config.py`, `backend/updater.py`, `backend/overwolf.py`, `backend/database.py`
- `tests/test_path_safety.py` (new), `AI_CONTEXT.md`, `AI_CONTRACTS.md`, `AI_TASKS.md`, `AI_CHANGES.md`

Tests/build:

- `python -m pytest -q` → 83 passed (2 pre-existing FastAPI deprecation warnings). Was 79; +4 new path-safety tests.
- `python -m compileall -q app.py backend tests` and `git diff --check` passed.

Integration notes:

- No endpoint, contract, or account/login/updater/installer behavior change. `guard_path` is a no-op for all existing paths (all Vortex-owned). New write/delete code on computed paths must call `guard_path` / `safe_remove` first (see the "Filesystem write/delete safety" contract).
- App-level `saveBackup` (user-picked Save-As dialog for the user's own backup JSON) is intentionally not guarded — it is explicit user file selection, not a computed Vortex write.

Still needs manual review:

- The user-configured "run a program when VALORANT closes" feature and its `ldr.novgk.exe` default: Vortex's code is a plain process launch, but the external tool itself (user-supplied, not in this repo) is outside audit scope.

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

## 2026-09-01 - Codex - Publish v5.5.41 role-badge fix

Changed:

- Bumped `backend/version.py`, `version.json`, and `installer/vortex_setup.iss` from 5.5.40 to 5.5.41.
- Built and published the installer containing the recent-match role-badge fix.

Release:

- GitHub release: https://github.com/RheaIsCute/vortex/releases/tag/v5.5.41
- Installer: `VortexSetup.exe`, 277,253,898 bytes.
- SHA-256: `0451C4F8CFB32F5065BA3AEF1E2DA6521B001514DFE025F50EB7B373D37578ED`.
- Bundle contained 3,868 `_internal` files.

Tests:

- `python -m pytest -q` -> 79 passed (2 FastAPI deprecation warnings).
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

## 2026-09-03 — Claude — Account Manager workspace redesign (roster rows)

Frontend layout restructuring of the desktop workspace. No backend change; the
UI still talks to the same `/api/*` endpoints with the same payloads.

### Audit (Graphify + source cross-check)

Reused the existing `graphify-out/` graph, then verified against source:

- One render path — `fetchAccounts()` → `renderAccounts()` →
  `renderGridView()` / `renderTableView()`, both consuming the shared
  `buildAccountView(acc)` view model. `buildAccountView` was left untouched, so
  filtering, sorting, ranked-eligibility and status logic are unchanged.
- 198 ids in `index.html`, 194 referenced from `app.js`. Only
  `settings-log-path` binds to an element that does not exist — pre-existing and
  required absent by `test_frontend_settings_and_search_markup`.
- 23 CSS classes were defined but referenced nowhere in
  `index.html` / `app.js` / `live_overlay.*` / `boot.*`. `tier-*`, `theme-*`,
  `toast-*` and `chip--*` are built dynamically in JS and were kept.

### Changes

**Layout hierarchy (`index.html`)** — the workspace now reads in three levels:
a **status strip** (roster totals), the **active-session hero card**, then the
**roster rows**. The four stat pills moved out of the sticky header into that
strip, leaving the header as brand + actions only.

**Status strip** — `#status-strip` with four `.status-tile` buttons. Each tile
is also a one-click account-type filter: it writes the same `state.currentTag`
the Filters popover owns, then calls the normal `fetchAccounts()`, so the strip,
the popover, the "N shown" count and the filter badge can never disagree.
`initStatusStrip()` binds it; `syncStatusStrip()` is called from the existing
`syncFilterIndicators()` so the mirror runs on every filter change. The
`stat-total` / `stat-mains` / `stat-ranked` / `stat-unrated` ids are preserved,
so `fetchStatsSummary()` is unchanged.

**Roster rows (`renderGridView`)** — the ~344px card wall was replaced by one
dense row per account: pin, rank emblem + level, identity (name, rank title,
peak badge, note), region/type/status chips, winrate figure, last-checked, and
the actions cluster. `.accounts-grid` is now a flex column and each
`.roster-row` is its own fixed-column grid. The per-card cursor spotlight,
accent capline and hover lift were dropped — at 20 rows they read as noise.

**Credentials on demand** — the always-visible masked credential rows are gone
from the resting layout. Each row has a key toggle that opens a
`.roster-creds` drawer rendered from the existing shared `credRows(acc)` helper.
`.roster-creds[hidden] { display: none }` is required because a bare
`display: flex` otherwise beats the `hidden` attribute.

**Dead code removed** — 40+ orphaned rules: the retired grid-card internals
(`.card-header`, `.card-badges`, `.card-profile`, `.card-stats-row`,
`.card-actions`, `.card-btn-group`, `.card-last-login`, `.winrate-meta`,
`.winrate-bar-track`, `.winrate-bar-fill`, `.level-bubble`, `.rank-tier-title`,
`.summoner-name-row`, `.profile-info`, `.btn-launch-card`, `.btn-check-card`,
`.skeleton-card`), the moved `.stats-overview` pills, and long-dead leftovers
(`.combo-dupe`, `.custom-select-wrapper`, `.search-kbd`, `.flex-2`, `.pg-1..5`,
`.rank-text`, `.text-green`, `.hero-winrate-track`, `.account-card.is-busy`).
Fixed a latent bug found while cutting: a dangling `.rank-tier-title,` selector
had been left attached to `.peak-emblem-badge`. The ripple delegation in
`app.js` was repointed from `.btn-launch-card` to `.roster-act`.

### Verification

- `python -m compileall -q backend tests app.py` — clean.
- `node --check frontend/app.js` — clean; `styles.css` braces balanced.
- `pytest -q tests/test_settings_and_ui.py` — 8 passed (7 existing + 1 new
  `test_roster_workspace_layout`). Full suite: **99 passed**.
- Rendered live in headless Chrome over CDP against the real backend and a
  17-account database: 17 rows, status strip filter 17 → 9 with the count and
  filter badge following, credential drawer opening only its own row, match
  history rendering `matchCardHtml` rows, table view 17 rows, import / banned /
  settings modals all opening, and no horizontal overflow at 1280px or 1040px.
  **Zero console errors or warnings** in every pass.
- Graphify `update` rebuilt the graph (1301 nodes); `toggleRosterCreds`,
  `initStatusStrip` and `syncStatusStrip` are present and connected, with no
  new frontend→backend edges.

Not changed: `backend/*`, `frontend/assets/*`, `live_overlay.*`, `boot.*`,
installer and root build files. The hero/active-session card, the shared
`matchCardHtml` row, the Live Match lifecycle and the table view keep their
existing contracts.

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
