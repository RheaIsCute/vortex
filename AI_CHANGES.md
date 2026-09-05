# Shared AI Change Log

Append a new section for each completed task. Keep entries factual and concise.

## 2026-09-05 — Codex — v5.5.45 packaging recovery and release gates

Repaired the unpublished v5.5.45 candidate without changing the live
`version.json` rollback (still 5.5.44) or the installed user database.

**Diagnosis.** Comparing the PYZ archives disproved the exe-size theory: the
9 MB candidate already contained all 14 Vortex backend modules, all FastAPI,
Starlette, Pydantic and Uvicorn modules, plus the three `uiautomation` Python
modules. Most of the ~8 MB in the known-good exe was unrelated packages from
its build environment (pytest/Pygments/NumPy/Pillow/Rich/Trio). The genuine
UIA packaging gap was its two `uiautomation/bin/UIAutomationClient_*.dll`
files. More importantly, the new frozen gate reproduced the backend failure:
Uvicorn opened its localhost socket, but the Windows Proactor loop's accept
path failed with `WinError 64`, leaving every version probe timed out. A prior
run had passed, confirming the failure was intermittent.

**Runtime repair.** `app.py` now backs missing windowed stdout/stderr with the
persistent startup log before third-party imports, catches/logs the complete
server-thread traceback, and requires a successful `/api/app-version` response
before creating WebView2. A failed backend therefore produces a native error
instead of cached HTML showing empty state. The background Uvicorn server uses
`SelectorEventLoop` on Windows, avoiding the reproduced Proactor accept
failure. A frozen-only smoke path also initializes UIAutomationCore/comtypes
and verifies both UIA helper DLLs.

**Build/release repair.** Runtime and PyInstaller versions are exactly pinned;
Uvicorn's standard protocol dependencies and dynamic modules are collected;
UIA package data/binaries are explicit. The spec emits an unprivileged console
`VortexSmoke.exe` from the exact same Analysis/PYZ as the elevated production
exe; it is run three times against isolated app data and is not shipped. The
final Inno artifact supports `/VORTEXBUILDSMOKE`, which CRC-checks/extracts the
payload to scratch without killing Vortex, creating shortcuts, or registering
an uninstaller. Inno now writes off-path; only a verified artifact is moved to
`dist_installer`, preventing readers/uploaders from seeing a partial file.

**Validation.** 126 tests pass (two existing FastAPI lifespan deprecation
warnings); `compileall`, `node --check frontend/app.js`, and `git diff --check`
pass. The final clean build embedded the required elevation manifest, produced
3,829 `_internal` files, passed three consecutive frozen API/UIA launches, and
passed the exact installer payload integrity/extraction check. The installed
5.5.44 process remained healthy with two accounts throughout. Nothing was
published or installed.

## 2026-09-05 — Incident: two failed v5.5.45 publish attempts, rolled back

The first `VortexSetup.exe` published for v5.5.45 failed Inno Setup's own
integrity check — `SetupLdr` aborted in 1.3s with "The setup files are
corrupted. Please obtain a new copy of the program." before Setup ever started.

**Cause.** Not a packaging fault: ISCC reported a successful compile and packed
all 3806 files, and `dist\Vortex` was verified complete. The output file was
corrupted in place — a recompile from the identical staged bundle produced a
byte-identical *length* (252,542,690) that passes the integrity check, so the
first compile's bytes were bad while its size was right. Defender real-time
protection is off on this machine and there were no detections, and the file had
no alternate data streams, so AV was not involved.

**Why it reached users.** The release process bumped `version.json`, published
the release and uploaded the asset without ever running the installer. Nothing
in `build.bat`'s (otherwise thorough) gauntlet — file counts, C-extension spot
checks, elevation-manifest verification — validates the *compiled installer*,
only the PyInstaller bundle that goes into it.

**Rollback.** `version.json` was pointed back at 5.5.44 and pushed first, then
the v5.5.45 release was set back to draft — that order matters, because drafting
first would have left `version.json` advertising 5.5.45 with a 404 download.
jsdelivr was purged (`purge.jsdelivr.net`) because an edge node kept serving the
stale 5.5.45 manifest for a few minutes after the push.

**Second attempt.** Recompiled, integrity-probed the artifact (`/VERYSILENT
/SUPPRESSMSGBOXES /DIR=<scratch> /LOG=<log>`; a written Setup log means SetupLdr
validated the payload), replaced the release asset, downloaded the published
asset back and confirmed `SHA256 A8EC9177…` matches the locally verified build,
and then re-published and re-advertised. That installer was structurally valid,
but its packaged backend did not answer; v5.5.45 was unpublished again and the
manifest returned to 5.5.44.

The durable startup, frozen-application, and side-effect-free installer gates
are implemented in the packaging-recovery entry above.

## 2026-09-05 — Release v5.5.45

Published the frontend density/accent pass below together with the
elevated-login and credential-entry work that was already sitting uncommitted
in the tree, as v5.5.45. `backend/version.py` and `installer/vortex_setup.iss`
bumped 5.5.44 → 5.5.45 in commit `0802719`; `version.json` was deliberately
held back to a separate commit.

That ordering matters: `updater.check_for_update()` consults the GitHub release
API *and* the `version.json` mirrors on `master` and takes whichever advertises
the highest version, so pushing `version.json` at 5.5.45 before the release
existed would have made every running client offer an update whose
`download_url` 404s. The release was created as a draft, the asset uploaded, the
draft published, `releases/latest/download/VortexSetup.exe` confirmed to resolve
(HTTP 200), and only then was `version.json` bumped.

Toolchain had to be installed first: this machine had no Python, Git or Inno
Setup, and `winget` (v1.2.10691) crashes with an access violation, so Python
3.12.10, Git 2.55.0 and Inno Setup 6.7.3 were installed from direct vendor
downloads. 121 tests pass; `compileall` and `node --check frontend/app.js` clean.

`build.bat` produced `dist/Vortex/` (3805 files under `_internal/`, elevation
manifest verified) and a 240.8MB `VortexSetup.exe` — smaller than v5.5.44's
275MB purely because of newer dependency wheels; the bundled asset counts were
checked against the source tree and match exactly, allowing for the deliberate
`assets/valorant-api/weapons/` prefix exclusion and the ten excluded map files
in `build_exe.spec`.

## 2026-09-05 — Claude — Density, accent discipline and layout-defect pass

Frontend presentation only. No endpoint, contract, polling, filtering or
Live-Match lifecycle behaviour changed; `buildAccountView()`'s filtering and
eligibility logic is untouched.

**Reclaiming the first screen.** At 1440x900 the header, a full-width status
band, the toolbar and the hero card took 487px before the first account row —
four of eleven rows were visible. The four status totals moved into the toolbar
as one segmented filter control (they are a filter, and a band of their own cost
~53px for four numbers), and the hero card's centre column now puts the win-rate
trend and the credentials on one row instead of stacking three full-width bands.
Hero 295px → 211px; first roster row 583px → 430px, so seven rows are visible.

**Roster column alignment.** Each row is its own grid, so the
`max-content`/`auto` tracks were measured per row and the chip, winrate and
action columns were visibly ragged down the list. All tracks are now fixed
lengths or `fr` of the same free space. The state rail is also always 2px and
only changes colour — flagged rows used a 2px left border against 1px elsewhere,
which shifted their whole content box 1px right.

**Accent discipline.** LOGIN is every row's resting action; twenty accent
buttons stacked down the page out-shouted the one row that is actually different
(the signed-in account's PLAY). Row and table LOGIN buttons are now neutral and
take the accent on hover/focus. Region chips are neutral mono. The dashboard tab
pill and the hero launch button's halo were toned down, and the disabled
"Start a Match" slot drops the accent entirely — while a match is running it
carries a message, not an action.

**Removed non-information.** The `PLAYABLE` chip is gone from roster rows (the
default state of nearly every account, rendered in the strongest colour on the
row); `buildAccountView()` exposes `statusChip` for list views while the hero
card keeps the full `statusBadge`. The dashboard's premades panel now hides when
neither team has a stack instead of spending a band on "All Solo Queue / No
Stacks Detected". The match-history list states `K / D / A`, `KD` and `HS%` once
in a header row (`.matches-list-headed`) rather than on each of ten rows; the
shared row keeps its own captions for the dashboard and profile contexts, where
the grid drops columns responsively.

**Defects found while inspecting the rendered UI:**

- `.field-help code` was left grouped with the checkbox rule by an earlier edit,
  so inline `<code>` was a flex container — a block-level box that split
  one-line help text across three lines. Given its own rule.
- Below 1120px the header labels clipped mid-word ("Che", "Add", "Imp", "Syn"):
  the dashboard-mode collapse declares `.header-actions .btn > span` with equal
  specificity later in the file and was overriding the responsive
  `display: none`. The media query now uses the same technique with a leading
  `body` so it wins regardless of order.
- The roster row's `max-width: 1180px` grid declared six tracks, but the
  `max-width: 1320px` block already hides last-login, so only five cells
  survive; the actions landed in the 88px track meant for the hidden cell and
  the buttons spilled across the winrate. Each breakpoint now declares exactly
  as many tracks as it has cells (verified at 1600/1440/1300/1200/1120/1024/900).
- Table view needs ~1705px for thirteen columns, so at every realistic window it
  scrolled and the column that fell off the right edge was Actions. It is now
  pinned to the edge. That required row tints (`is-active-session`,
  `is-legacy-ranked`, `tr:hover`) to move from translucent `background` to
  `background-image`, so the pinned cell can keep an opaque `background-color`
  underneath — otherwise the columns it floats over showed straight through it.
  This also removed two `!important` declarations.
- Agent avatars in match rows sat on a near-black plate under agent art that is
  itself dark, so they read as empty discs; the plate is lighter and the image
  lifted. Also dropped a dead `overflow: hidden` that a later `overflow: visible`
  in the same rule already overrode.
- Filter-popover chip groups each ended in a short orphan row (5+2, 3+3+2,
  3+3+1). They are now a grid — three columns for region codes, two for the
  longer labels — and the selection tick is drawn transparent on every chip so
  choosing one no longer nudges its label sideways.
- Settings repeated each section's icon and title on the field label directly
  beneath it (six times). Removed, and the six 245x105 theme tiles became a row
  of swatches; the modal's scroll height went 1431px → 1198px.

**Settings section headings.** Removing the duplicated field labels dropped two
strings `tests/test_settings_and_ui.py` asserts on (`Post-Game Actions`,
`Launch & Login`). The section headings now carry those full names instead of
the shortened `Post-Game` / `Launch &amp; Login`, which satisfies the contract
and is the same intent — the name is stated once, on the heading, rather than
twice.

**Validation.** 121 tests pass (`python -m pytest -q`);
`python -m compileall -q backend tests app.py` and `node --check
frontend/app.js` are clean. Also verified by rendering the real frontend against
a Node mock of the API (shapes taken from `backend/server.py` and
`valorant_client.py`) in headless Chrome over CDP: roster, table, dashboard,
match history, settings, filters, import, banned and add-account, at
1600/1440/1300/1200/1120/1024/900px. Zero console errors and zero failed
requests in every pass; roster rows stay single-line (70px) with cells == tracks
and no horizontal page overflow at every width.

**Checkout correction.** The 2,233 absent paths were deliberate in-flight
cleanup/build-footprint deletions, not evidence of a damaged checkout. Restoring
the ten tests and Overwolf companion was useful for validation, but describing
all absent tracked files as accidental damage was incorrect.

## 2026-09-03 — Release v5.5.43

Published the Account Manager workspace redesign (status strip + roster rows,
see "Claude — Account Manager workspace redesign" below) as v5.5.43.
`backend/version.py`, `version.json`, `installer/vortex_setup.iss` bumped
5.5.42 → 5.5.43. 99 tests pass (`pytest -q tests` — 8/8 in
`test_settings_and_ui.py` including the new `test_roster_workspace_layout`);
`python -m compileall -q backend tests app.py` and `node --check
frontend/app.js` both clean.

Built and published the installer: `python -m PyInstaller build_exe.spec
--clean -y` produced `dist/Vortex/` (Vortex.exe + `_internal/`, ~374MB). Inno
Setup's compiler is a legacy 32-bit app that does not honor Windows'
`LongPathsEnabled`, so compiling directly from this repo's path (which nests
past the 260-char `MAX_PATH` under `_internal/numpy-2.5.2.dist-info/licenses/`)
failed with "system cannot find the path specified" even with long paths
enabled at the OS level. Fixed by staging `dist/Vortex/`,
`frontend/assets/logo.ico` and `installer/vortex_setup.iss` under a short
`C:\vxbuild\` path (mirroring the script's relative layout) and compiling
`ISCC.exe installer\vortex_setup.iss /DAppVersion=5.5.43` from there, which
produced `VortexSetup.exe` (288MB). Published to the `v5.5.43` GitHub release
via `gh release create v5.5.43 dist_installer/VortexSetup.exe`; verified
`releases/latest/download/VortexSetup.exe` (the URL `version.json` points at)
resolves with HTTP 200 and the correct byte size. `v5.5.42` was never tagged
as a release, so `v5.5.43` now cleanly supersedes `v5.5.41` as `latest`.

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
# 2026-09-03 - Codex - Reliable background batch account verification

Changed:

- Made Riot credential-field discovery resilient to accessible-name casing and
  nesting changes, using password/name/automation-id semantics with form-order
  fallback.
- Credential entry now tries UI Automation ValuePattern writes and UIA button
  invocation first, so Check Accounts can normally type and submit without
  bringing Riot Client to the foreground. The proven clipboard/keyboard path
  remains as a compatibility fallback.
- Added popup checks before username entry, between username/password, and
  before submission. Added event-driven login-stage wakeups to the batch waiter
  while retaining a short timed check for session changes outside Vortex.
- Batch Stop is now explicit on the main button and signals the active login
  worker before closing Riot Client; the UI waits for backend confirmation
  before allowing another scan.
- Added `%LOCALAPPDATA%\Vortex\global_banned_usernames.sqlite`, containing only
  normalized usernames and timestamps. Existing banned rows seed it; confirmed
  bans update it; imports and batch scans move/skip matches without logging in;
  confirmed playable restores remove the name.

Files:

- `backend/client_launcher.py`, `backend/server.py`, `backend/database.py`
- `frontend/app.js`
- `tests/test_login_flow.py`, `tests/test_batch_account_check.py`,
  `tests/test_account_import_and_eligibility.py`
- `AI_CONTRACTS.md`, `AI_CHANGES.md`, `AI_TASKS.md`

Validation:

- `python -m pytest -q` -> 104 passed (2 pre-existing FastAPI warnings).
- `python -m compileall -q app.py backend tests`, `node --check frontend/app.js`,
  and `git diff --check` passed.

No version bump, build, tag, push, or release was created.

## v5.5.44 release

- Bumped `backend/version.py`, `version.json`, and the Inno Setup default to
  `5.5.44`.
- Re-ran the full test suite: 104 passed.
- Built `dist/Vortex/Vortex.exe` and `dist_installer/VortexSetup.exe`.
- Verified installer ProductVersion `5.5.44`; SHA-256:
  `1C8BAA5D9C4A60CA2008E00EDFA6125F4FADD893045E8A43BD7389BACB4BC4ED`.

## 2026-09-05 - Codex - Offline packaged-asset deduplication

Changed:

- Replaced the broad `("frontend", "frontend")` PyInstaller data collection
  entry with `frontend_datas()`. It retains every frontend file except an
  explicit, audited exclusion list, preserving the existing onedir updater
  behavior.
- Omitted ten redundant cached map images from the frozen frontend. Four old
  map ids duplicated the retained Drift splash/list-image pair exactly; a
  second old id duplicated another retained splash/list-image pair exactly.
  `localGameAssetUrl()` now aliases those exact media URLs to the retained
  local files, so both normal and stale API responses remain offline-safe.
- Omitted `frontend/assets/logo-source.png` from the frozen frontend. It has
  no runtime reference; the required `logo.svg`, `logo.png`, and `logo.ico`
  remain bundled.

Measured static-asset footprint:

- Before: 489 files, 143,381,031 bytes.
- After (PyInstaller input): 478 files, 113,248,988 bytes.
- Reduction: 11 files, 30,132,043 bytes (28.74 MiB, 21.02%). Map aliases
  account for 29,845,450 bytes; the unused design-source image accounts for
  286,593 bytes.

Audit findings:

- The full Valorant cache is 142,832,069 bytes: maps 98,638,431 bytes, agents
  34,971,667 bytes, weapon-skin chromas 5,817,656 bytes, competitive tiers
  3,114,619 bytes, and weapons 289,696 bytes.
- Preserved all non-duplicate cached categories. `resolve_map()` can return
  dynamic map art for live-session responses, `/api/live/agents` returns
  dynamic agent art, tiers are used by account/history UI, and weapon/chroma
  art can be returned by loadout metadata. Removing those categories would
  introduce local 404s or a CDN fallback.
- All declared Python dependencies have direct imports in the source or are
  packaging/runtime dependencies; no safe dependency removal was found. The
  existing hidden imports remain justified by frozen multiprocessing, UIA,
  and pywebview startup requirements.
- No backend responsibility extraction was made: the only candidate modules
  overlap an active login/elevation task, and this change preserves every
  FastAPI, SQLite, updater, and external-only contract.

Validation:

- Executed the alias function in Node against all ten URLs; each resolves to
  its intended local retained path and its original/retained files have equal
  SHA-256 hashes.
- Confirmed every aliased source path is excluded by `build_exe.spec` and that
  unaliased Valorant URLs and non-Valorant URLs are unchanged.
- `node --check frontend/app.js`, `frontend/boot.js`, and
  `frontend/live_overlay.js` passed.

Environment limitations:

- This supplied checkout has no `dist/`, `dist_installer/`, `tests/`,
  `installer/`, or `.git` directory, and Python/PyInstaller are unavailable
  on PATH. Therefore total before/after bundle size, installer size, pytest,
  Python compile checks, `git diff --check`, frozen launch, and installer
  validation could not be run. No release or version change was made.

### Follow-up: weapon-media reference audit

- Audited `frontend/assets/valorant-api/weapons/` (18 files, 289,696 bytes)
  separately from `weaponskinchromas/` (71 files, 5,817,656 bytes).
- `get_weapon_data()` retains weapon ids only for display names; it never
  returns a cached weapon image URL. The Inventory markup renders `g.icon`,
  which is a skin-chroma URL, plus its tier icon. No frontend or backend path
  references the cached `weapons/` display or killstream images.
- Added the proven-unused `assets/valorant-api/weapons/` prefix to the
  PyInstaller frontend-data exclusions. Skin-chroma files remain packaged.
- Additional packaged reduction: 18 files, 289,696 bytes (282.91 KiB).
  Cumulative packaged static assets: 489 files / 143,381,031 bytes to 460
  files / 112,959,292 bytes, saving 30,421,739 bytes (29.01 MiB, 21.22%).
- Re-ran the Node asset contract: all ten map aliases still hash-match,
  all 71 skin files remain included, and all 18 weapon files are excluded.

## 2026-09-05 - Codex - Fast event-driven Riot login and mandatory elevation

Changed:

- Replaced the normal login path's fixed 1.4-second settle, two 120 ms
  post-`ValuePattern` waits, 250 ms pre-submit wait, and redundant window/form
  waits with immediate synchronous UIA writes and native button invocation.
  `ValuePattern` gets two bounded attempts before the existing foreground
  keyboard/clipboard compatibility path. Cancellation is checked before any
  fallback.
- Added a Riot-process-scoped WinEvent listener for create/show/hide/focus/state
  changes. Readiness follows check -> subscribe -> recheck -> event/adaptive
  40-250 ms fallback polling, with cleanup on every exit. Explicit 64-bit
  ctypes signatures prevent hook-handle truncation and leaked listeners.
- Cached only stable state: a validated Riot executable path and a PID-bound
  top-level HWND. Normal window reuse avoids desktop enumeration; destroyed or
  replaced windows invalidate the cache. Dynamic UIA objects remain per-mount.
- Consolidated username, password, submit, Stay signed in, popup, and validation
  discovery into one scoped Riot-window traversal. Popup plus validation result
  monitoring now shares one scan. Structure events and stale-object failures
  trigger fast reacquisition.
- Submit invokes an already-enabled button immediately, otherwise waits on the
  scoped listener with adaptive fallback for up to the existing bounded window.
  The Enter-key path remains the final compatibility fallback. Mid-entry popup,
  form-remount, progress, retry, and Stop behavior remain intact.
- Batch startup/reset now waits for actual process exit. Account transitions
  wait for the actual signed-out state, then retain a 250 ms rate-limit cooldown
  instead of a blind two seconds. The warm-login 200 ms teardown sleep was
  removed; login remains sequential. Banned/suspended and global-ban behavior
  was not changed.
- Added opt-in `VORTEX_LOGIN_TIMING=1` milestone diagnostics. They contain only
  milestone names and durations, never account identifiers, credential values
  or lengths, tokens, or payloads.
- Changed the application manifest to `requireAdministrator`, `uiAccess=false`.
  PyInstaller was initially observed overriding the XML back to `asInvoker`;
  `uac_admin=True`/`uac_uiaccess=False` now enforce the same contract in the
  spec. `tools/verify_executable_manifest.py` reads the final PE's RT_MANIFEST,
  and `build.bat` refuses to accept/package a mismatched executable.
- Source `app.py` now performs the elevation decision before DPI setup and
  before importing FastAPI, pywebview, Riot automation, or other integrations.
  A successful `runas` handoff exits the original process; denial/failure exits
  with an error; a sentinel prevents loops. Windows-native argument quoting
  preserves spaced paths/arguments and relaunch logging omits parameters.
- Installer-created shortcuts and post-install launch now target the elevated
  executable directly with `{app}` as working directory. The Vortex logo is
  unchanged and the onedir/updater architecture is preserved.

Measurements (deterministic fake UIA controls; no live credentials):

- Controls ready -> Login invoked, before (5 runs): best 1891.9 ms, median
  1892.0 ms, worst 1892.7 ms. After (9 runs): best 0.664 ms, median 0.843 ms,
  worst 2.204 ms.
- After breakdown: controls -> username 0.403/0.509/1.798 ms;
  username -> password 0.083/0.126/0.177 ms; password -> invoke
  0.162/0.224/0.276 ms (best/median/worst).
- State-ready account N -> account N+1 Login call, after (7 sequential mocked
  runs): 256.2/260.2/261.4 ms best/median/worst. The prior implementation had
  an unconditional 2000 ms transition floor before its other work.
- A live Riot process-start -> controls-ready measurement was not performed;
  detection now wakes from the scoped event immediately with a 40 ms initial
  polling fallback, while retaining the original generous overall timeout.

Validation:

- Present test suite: `python -m pytest tests -q` -> 51 passed, with two
  pre-existing FastAPI deprecation warnings. Added coverage for ready/delayed
  submit, check/subscription race, window recreation, popup during entry,
  stale reacquisition, native retry/fallback, cancellation, listener cleanup,
  PID-bound HWND reuse, sequential batch transitions, source handoff/denial,
  loop prevention, quoted arguments, and manifest/spec contracts.
- `python -m compileall -q app.py backend tests tools`, `node --check
  frontend/app.js`, and task-scoped `git diff --check` passed.
- `build.bat` produced the canonical 5.5.44 onedir bundle with 675 `_internal`
  files and all required native spot checks. The embedded PE resource was
  verified as `requireAdministrator`, `uiAccess=false`.
- From a real medium-integrity shell, launching the fresh executable displayed
  UAC and produced exactly one usable Vortex process. Its token was confirmed
  elevated; no unelevated Vortex duplicate remained. The test process and its
  WebView child tree were then closed.
- Existing installed Start/Desktop shortcuts were inspected and target
  `Vortex.exe` directly. Inno Setup was not installed, so a new installer and
  newly generated shortcut could not be built/visually tested. Windows desktop
  automation was unavailable, so Explorer's optional shield overlay was not
  visually observed. The existing installed 5.5.44 executable remains the old
  `asInvoker` build until a new installer is built/installed.
- The updater was source-audited: the one-directory layout and direct executable
  relaunch remain unchanged. No update was downloaded or installed. Eleven
  tracked baseline test modules were absent from the supplied checkout, so only
  the 51 locally present tests could be executed.

Files changed by this task:

- `app.py`, `backend/elevation.py`, `backend/client_launcher.py`,
  `backend/server.py`
- `vortex.manifest`, `build_exe.spec`, `build.bat`,
  `installer/vortex_setup.iss`, `tools/verify_executable_manifest.py`
- `tests/test_login_flow.py`, `tests/test_batch_account_check.py`,
  `tests/test_elevation.py`
- `AI_CONTRACTS.md`, `AI_CHANGES.md`, `AI_TASKS.md`

No public version bump, tag, push, installer publication, or release was made.
