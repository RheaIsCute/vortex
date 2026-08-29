/**
 * Vortex Valorant Account Manager - Frontend Controller
 * Handles UI state, filtering, official rank icons, peak rank badges, match history drawer,
 * batch .TXT combo importer (username:password), live status badges (Playable/Banned/Suspended),
 * and automated full-roster account checker ("Check Accounts").
 */

// Global State
const state = {
    accounts: [],
    bannedAccounts: [],
    settings: {},
    stats: {},
    currentRegion: "ALL",
    currentTag: "ALL",
    currentSort: "level",
    searchQuery: "",
    viewMode: "grid",
    isSyncingAll: false,
    isCheckingAccounts: false,
    activeLaunchAcc: null,
    activeMatchAccId: null,

    // Live session / dashboard
    live: null,
    activeAccountId: null,
    dashboardOpen: false,
    agents: [],
    modes: [],
    instalock: {},
    selectedAgentId: null,
    highlightId: null,

    // Dashboard view
    dashTab: "match",
    pendingQueueId: null,   // mode picked here, before the client confirms it
    playPending: false,     // guards PLAY against a second click
    queueStartedAt: 0,
    playerStats: null
};

// Fallback tier mapping
const TIER_ICONS = {
    RADIANT: { icon: "fa-solid fa-sun", colorClass: "rank-radiant", label: "Radiant" },
    IMMORTAL: { icon: "fa-solid fa-skull", colorClass: "rank-immortal", label: "Immortal" },
    ASCENDANT: { icon: "fa-solid fa-gem", colorClass: "rank-ascendant", label: "Ascendant" },
    DIAMOND: { icon: "fa-solid fa-diamond", colorClass: "rank-diamond", label: "Diamond" },
    PLATINUM: { icon: "fa-solid fa-shield", colorClass: "rank-platinum", label: "Platinum" },
    GOLD: { icon: "fa-solid fa-medal", colorClass: "rank-gold", label: "Gold" },
    SILVER: { icon: "fa-solid fa-circle", colorClass: "rank-silver", label: "Silver" },
    BRONZE: { icon: "fa-solid fa-shield-cat", colorClass: "rank-bronze", label: "Bronze" },
    IRON: { icon: "fa-solid fa-cube", colorClass: "rank-iron", label: "Iron" },
    UNRANKED: { icon: "fa-solid fa-circle-question", colorClass: "rank-unranked", label: "Unranked" }
};

const TIER_BASE_URL = "https://media.valorant-api.com/competitivetiers/03621f52-342b-cf4e-4f86-9350a49c6d04";
const DEFAULT_TIER_ICON = `${TIER_BASE_URL}/0/largeicon.png`;

// Mirrors TIER_INDEX_MAP in backend/scraper.py so a stored peak rank can
// still show its official emblem when peak_rank_icon_url is blank (older
// accounts synced before the icon URL was saved).
const TIER_INDEX_MAP = {
    "UNRANKED": 0,
    "IRON 1": 3, "IRON 2": 4, "IRON 3": 5,
    "BRONZE 1": 6, "BRONZE 2": 7, "BRONZE 3": 8,
    "SILVER 1": 9, "SILVER 2": 10, "SILVER 3": 11,
    "GOLD 1": 12, "GOLD 2": 13, "GOLD 3": 14,
    "PLATINUM 1": 15, "PLATINUM 2": 16, "PLATINUM 3": 17,
    "DIAMOND 1": 18, "DIAMOND 2": 19, "DIAMOND 3": 20,
    "ASCENDANT 1": 21, "ASCENDANT 2": 22, "ASCENDANT 3": 23,
    "IMMORTAL 1": 24, "IMMORTAL 2": 25, "IMMORTAL 3": 26,
    "RADIANT": 27
};

function getRankIconUrl(tier, division) {
    const tierUpper = (tier || "").toUpperCase().trim();
    if (!tierUpper) return "";
    const div = (division || "").toString().trim();
    const key = (tierUpper === "UNRANKED" || tierUpper === "RADIANT" || !div)
        ? tierUpper
        : `${tierUpper} ${div}`;
    let idx = TIER_INDEX_MAP[key];
    if (idx === undefined) idx = TIER_INDEX_MAP[`${tierUpper} 1`];
    if (idx === undefined) return "";
    return `${TIER_BASE_URL}/${idx}/largeicon.png`;
}

// DOM Elements
const DOM = {
    statTotal: document.getElementById("stat-total"),
    statMains: document.getElementById("stat-mains"),
    statRanked: document.getElementById("stat-ranked"),
    statUnrated: document.getElementById("stat-unrated"),

    searchInput: document.getElementById("search-input"),
    searchClear: document.getElementById("search-clear"),
    regionFilter: document.getElementById("region-filter"),
    tagFilter: document.getElementById("tag-filter"),
    sortFilter: document.getElementById("sort-filter"),
    viewGridBtn: document.getElementById("view-grid-btn"),
    viewTableBtn: document.getElementById("view-table-btn"),
    accountsGrid: document.getElementById("accounts-grid"),
    accountsTableWrapper: document.getElementById("accounts-table-wrapper"),
    accountsTableBody: document.getElementById("accounts-table-body"),
    emptyState: document.getElementById("empty-state"),
    skeletonGrid: document.getElementById("skeleton-grid"),
    resultCount: document.getElementById("result-count"),
    viewSwitcher: document.getElementById("view-switcher"),
    appHeader: document.getElementById("app-header"),
    scrollTopBtn: document.getElementById("scroll-top-btn"),

    btnCheckAllAccounts: document.getElementById("btn-check-all-accounts"),
    checkAllIcon: document.getElementById("check-all-icon"),
    btnAddAccount: document.getElementById("btn-add-account"),
    btnEmptyAdd: document.getElementById("btn-empty-add"),
    btnEmptyImport: document.getElementById("btn-empty-import"),
    btnImportCombo: document.getElementById("btn-import-combo"),
    btnSyncAll: document.getElementById("btn-sync-all"),
    syncAllIcon: document.getElementById("sync-all-icon"),
    btnKillClient: document.getElementById("btn-kill-client"),
    syncProgressBar: document.getElementById("sync-progress-bar"),
    syncProgressFill: document.getElementById("sync-progress-fill"),
    syncProgressText: document.getElementById("sync-progress-text"),
    btnBackupRestore: document.getElementById("btn-backup-restore"),
    btnOpenSettings: document.getElementById("btn-open-settings"),

    // Banned Accounts
    btnOpenBanned: document.getElementById("btn-open-banned"),
    bannedCountBadge: document.getElementById("banned-count-badge"),
    modalBanned: document.getElementById("modal-banned"),
    modalBannedClose: document.getElementById("modal-banned-close"),
    bannedListContainer: document.getElementById("banned-list-container"),
    bannedEmptyState: document.getElementById("banned-empty-state"),

    // Batch Import Combo Modal (Drag & Drop)
    modalImportCombo: document.getElementById("modal-import-combo"),
    modalImportComboClose: document.getElementById("modal-import-combo-close"),
    btnCancelCombo: document.getElementById("btn-cancel-combo"),
    comboDropzone: document.getElementById("combo-dropzone"),
    fileComboInput: document.getElementById("file-combo-input"),
    comboTextInput: document.getElementById("combo-text-input"),
    comboCountPreview: document.getElementById("combo-count-preview"),
    btnDoComboImport: document.getElementById("btn-do-combo-import"),

    // Clean Add/Edit Account Modal
    modalAccount: document.getElementById("modal-account"),
    modalAccountTitle: document.getElementById("modal-account-title"),
    modalAccountIcon: document.getElementById("modal-account-icon"),
    modalAccountClose: document.getElementById("modal-account-close"),
    btnCancelAccount: document.getElementById("btn-cancel-account"),
    formAccount: document.getElementById("form-account"),
    formAccountId: document.getElementById("form-account-id"),
    formUsername: document.getElementById("form-username"),
    formPassword: document.getElementById("form-password"),
    btnToggleFormPassword: document.getElementById("btn-toggle-form-password"),
    formTag: document.getElementById("form-tag"),
    formNotes: document.getElementById("form-notes"),
    formFavorite: document.getElementById("form-favorite"),

    // Matches Modal
    modalMatches: document.getElementById("modal-matches"),
    modalMatchesClose: document.getElementById("modal-matches-close"),
    matchModalRankImg: document.getElementById("match-modal-rank-img"),
    matchModalRiotId: document.getElementById("match-modal-riot-id"),
    matchModalSub: document.getElementById("match-modal-sub"),
    matchMetaCurrent: document.getElementById("match-meta-current"),
    matchMetaPeak: document.getElementById("match-meta-peak"),
    matchMetaPeakImg: document.getElementById("match-meta-peak-img"),
    matchMetaWinrate: document.getElementById("match-meta-winrate"),
    matchesListContainer: document.getElementById("matches-list-container"),
    btnRefreshMatches: document.getElementById("btn-refresh-matches"),
    playerLookupForm: document.getElementById("player-lookup-form"),
    playerLookupInput: document.getElementById("player-lookup-input"),
    modalMatchDetail: document.getElementById("modal-match-detail"),
    modalMatchDetailClose: document.getElementById("modal-match-detail-close"),
    detailModalTitle: document.getElementById("detail-modal-title"),
    detailModalSub: document.getElementById("detail-modal-sub"),
    matchDetailContent: document.getElementById("match-detail-content"),

    // Settings Modal
    modalSettings: document.getElementById("modal-settings"),
    modalSettingsClose: document.getElementById("modal-settings-close"),
    btnCancelSettings: document.getElementById("btn-cancel-settings"),
    btnSaveSettings: document.getElementById("btn-save-settings"),
    settingsClientPath: document.getElementById("settings-client-path"),
    settingsApiKey: document.getElementById("settings-api-key"),
    btnAutoDetectClient: document.getElementById("btn-auto-detect-client"),
    settingsAppVersion: document.getElementById("settings-app-version"),
    appVersionBadge: document.getElementById("app-version-badge"),
    btnCheckUpdate: document.getElementById("btn-check-update"),
    settingsLogPath: document.getElementById("settings-log-path"),
    btnOpenLog: document.getElementById("btn-open-log"),
    settingsForceBorderless: document.getElementById("settings-force-borderless"),
    settingsStaySignedIn: document.getElementById("settings-stay-signed-in"),
    settingsAutoLaunch: document.getElementById("settings-auto-launch"),
    settingsOverlayEnabled: document.getElementById("settings-overlay-enabled"),
    settingsOverlayHotkey: document.getElementById("settings-overlay-hotkey"),
    overlayHotkeyHelp: document.getElementById("overlay-hotkey-help"),
    btnBorderlessAll: document.getElementById("btn-borderless-all"),
    settingsProfileAccount: document.getElementById("settings-profile-account"),
    settingsProfileAutoapply: document.getElementById("settings-profile-autoapply"),
    settingsCopyTarget: document.getElementById("settings-copy-target"),
    btnCopySettingsNow: document.getElementById("btn-copy-settings-now"),
    btnCopySettingsAll: document.getElementById("btn-copy-settings-all"),
    presetSummary: document.getElementById("preset-summary"),
    presetWhen: document.getElementById("preset-when"),
    presetLog: document.getElementById("preset-log"),
    presetLogTitle: document.getElementById("preset-log-title"),
    presetLogBody: document.getElementById("preset-log-body"),
    presetLogClose: document.getElementById("preset-log-close"),
    btnPresetCapture: document.getElementById("btn-preset-capture"),
    btnPresetApply: document.getElementById("btn-preset-apply"),
    btnPresetApplyAll: document.getElementById("btn-preset-apply-all"),
    settingsProfileStatus: document.getElementById("settings-profile-status"),
    updateStatusText: document.getElementById("update-status-text"),
    themePicker: document.getElementById("theme-picker"),

    // Update Banner
    updateBanner: document.getElementById("update-banner"),
    updateBannerText: document.getElementById("update-banner-text"),
    btnInstallUpdate: document.getElementById("btn-install-update"),
    btnDismissUpdate: document.getElementById("btn-dismiss-update"),

    // Backup Modal
    modalBackup: document.getElementById("modal-backup"),
    modalBackupClose: document.getElementById("modal-backup-close"),
    btnDoExport: document.getElementById("btn-do-export"),
    btnTriggerImport: document.getElementById("btn-trigger-import"),
    fileImportInput: document.getElementById("file-import-input"),

    // Quick Launch Modal
    modalLaunch: document.getElementById("modal-launch"),
    btnCloseLaunch: document.getElementById("btn-close-launch"),
    btnRetryLaunch: document.getElementById("btn-retry-launch"),
    launchStatusPill: document.getElementById("launch-status-pill"),
    launchBgHint: document.getElementById("launch-bg-hint"),
    launchUserVal: document.getElementById("launch-user-val"),
    launchPassVal: document.getElementById("launch-pass-val"),
    btnCopyLaunchUser: document.getElementById("btn-copy-launch-user"),
    btnCopyLaunchPass: document.getElementById("btn-copy-launch-pass"),

    // Active Session Bar
    sessionBar: document.getElementById("session-bar"),
    sessionName: document.getElementById("session-name"),
    sessionMeta: document.getElementById("session-meta"),
    sessionRankImg: document.getElementById("session-rank-img"),
    sessionStateChip: document.getElementById("session-state-chip"),
    btnSessionPlay: document.getElementById("btn-session-play"),
    sessionPlayLabel: document.getElementById("session-play-label"),
    btnOpenDashboard: document.getElementById("btn-open-dashboard"),

    // Live Dashboard view
    headerActions: document.getElementById("header-actions"),
    accountsView: document.getElementById("accounts-view"),
    btnToggleDashboard: document.getElementById("btn-toggle-dashboard"),
    dashView: document.getElementById("dash-view"),
    dashClose: document.getElementById("dash-close"),
    btnDashPlay: document.getElementById("btn-dash-play"),
    dashPlayLabel: document.getElementById("dash-play-label"),
    dashTabs: document.getElementById("dash-tabs"),
    dashTabGlide: document.getElementById("dash-tab-glide"),
    dashStatsBody: document.getElementById("dash-stats-body"),
    dashInventoryBody: document.getElementById("dash-inventory-body"),
    dashQueueBanner: document.getElementById("dash-queue-banner"),
    dashQueueBannerSub: document.getElementById("dash-queue-banner-sub"),
    dashQueueClock: document.getElementById("dash-queue-clock"),
    dashCtaTitle: document.getElementById("dash-cta-title"),
    dashCtaSub: document.getElementById("dash-cta-sub"),
    dashCtaIcon: document.getElementById("dash-cta-icon"),
    instalockLabel: document.getElementById("instalock-label"),
    dashRiotId: document.getElementById("dash-riot-id"),
    dashIdentitySub: document.getElementById("dash-identity-sub"),
    dashRankImg: document.getElementById("dash-rank-img"),
    dashLevel: document.getElementById("dash-level"),
    dashStateChip: document.getElementById("dash-state-chip"),
    dashStateLabel: document.getElementById("dash-state-label"),
    dashHero: document.getElementById("dash-hero"),
    dashHeroChips: document.getElementById("dash-hero-chips"),
    dashScoreAlly: document.getElementById("dash-score-ally"),
    dashScoreEnemy: document.getElementById("dash-score-enemy"),
    dashScoreDiff: document.getElementById("dash-score-diff"),
    dashScoreTarget: document.getElementById("dash-score-target"),
    dashRoundStrip: document.getElementById("dash-round-strip"),
    dashMe: document.getElementById("dash-me"),
    dashRecap: document.getElementById("dash-recap"),
    dashMapName: document.getElementById("dash-map-name"),
    dashModeName: document.getElementById("dash-mode-name"),
    dashMapArt: document.getElementById("dash-map-art"),
    dashPregameBanner: document.getElementById("dash-pregame-banner"),
    dashPregameText: document.getElementById("dash-pregame-text"),
    dashPregameTimer: document.getElementById("dash-pregame-timer"),
    dashIdle: document.getElementById("dash-idle"),
    dashIdleTitle: document.getElementById("dash-idle-title"),
    dashIdleText: document.getElementById("dash-idle-text"),
    dashDuoBanner: document.getElementById("dash-duo-banner"),
    dashTeams: document.getElementById("dash-teams"),
    dashTeamEnemyWrap: document.getElementById("dash-team-enemy-wrap"),
    dashRosterAlly: document.getElementById("dash-roster-ally"),
    dashRosterEnemy: document.getElementById("dash-roster-enemy"),
    dashModeGrid: document.getElementById("dash-mode-grid"),
    dashQueueStatus: document.getElementById("dash-queue-status"),
    btnStartRanked: document.getElementById("btn-start-ranked"),
    btnQueueStop: document.getElementById("btn-queue-stop"),
    dashAgentGrid: document.getElementById("dash-agent-grid"),
    dashAgentSearch: document.getElementById("dash-agent-search"),
    btnInstalockToggle: document.getElementById("btn-instalock-toggle"),
    btnLockNow: document.getElementById("btn-lock-now"),
    dashInstalockPill: document.getElementById("dash-instalock-pill"),
    dashInstalockStatus: document.getElementById("dash-instalock-status"),

    // Add/Edit validation + secondary save
    formValidation: document.getElementById("form-validation"),
    btnSaveAndCheck: document.getElementById("btn-save-and-check"),

    toastContainer: document.getElementById("toast-container")
};

document.addEventListener("DOMContentLoaded", () => {
    initEventListeners();
    initUiEnhancements();
    loadSettings();
    fetchStatsSummary();
    fetchAccounts();
    fetchBannedAccounts(true);
    startContinuousSync();
    startLiveSessionPolling();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    updateEffectsPausedState();
    loadAppVersion();
    checkForUpdate(false);

    // Re-check for updates every 6h for long-running sessions.
    setInterval(() => checkForUpdate(false), 6 * 60 * 60 * 1000);

    // Pick up the backend's periodic full roster refresh (rank/level/history
    // updates and ghost-account repairs) without needing a manual sync.
    setInterval(() => {
        fetchAccounts();
        fetchStatsSummary();
        fetchBannedAccounts();
    }, 5 * 60 * 1000);
});

const ACTIVE_SYNC_INTERVAL = 15000;
const ACTIVE_SYNC_RECHECK_WHILE_MATCHING = 5000;
const ACTIVE_SYNC_RECHECK_WHILE_HIDDEN = 30000;

function startContinuousSync() {
    scheduleContinuousSync(2500);
}

function isLiveMatchActive() {
    const phase = state.live && state.live.match && state.live.match.phase;
    const loopState = state.live && state.live.state;
    return phase === "agent_select" || phase === "in_match" ||
        loopState === "PREGAME" || loopState === "INGAME";
}

function continuousSyncDelay() {
    if (document.hidden) return ACTIVE_SYNC_RECHECK_WHILE_HIDDEN;
    if (isLiveMatchActive()) return ACTIVE_SYNC_RECHECK_WHILE_MATCHING;
    return state.live && state.live.valorant_running
        ? ACTIVE_SYNC_INTERVAL
        : ACTIVE_SYNC_INTERVAL + 5000;
}

function scheduleContinuousSync(delay = continuousSyncDelay()) {
    clearTimeout(state._continuousSyncTimer);
    state._continuousSyncTimer = setTimeout(runContinuousSync, delay);
}

async function runContinuousSync() {
    // The live snapshot already owns the fast path during a match. Re-running
    // active-account discovery here would duplicate Riot/SQLite work at the
    // exact moment the live dashboard needs the backend most.
    if (document.hidden || isLiveMatchActive()) {
        scheduleContinuousSync();
        return;
    }

    // A visibility change can reschedule this function while an earlier call
    // is still resolving. Keep the work single-flight just like live polling.
    if (state._continuousSyncPromise) {
        scheduleContinuousSync();
        return state._continuousSyncPromise;
    }

    const task = (async () => {
        try {
            const res = await fetch("/api/sync-active-account");
            const data = await res.json();
            if (data.synced) {
                fetchAccounts(true);
                fetchStatsSummary();
                if (data.moved_to_banned) {
                    showToast(`${data.display_name || 'Account'} is banned/suspended - moved to Banned Accounts.`, "warning");
                    fetchBannedAccounts();
                } else if (data.restored_from_banned) {
                    showToast(`${data.display_name || 'Account'} is playable again - restored to active accounts.`, "success");
                    fetchBannedAccounts();
                }
            }
        } catch (err) {
            // Ignore background sync errors
        }
    })();

    state._continuousSyncPromise = task;
    try {
        await task;
    } finally {
        if (state._continuousSyncPromise === task) state._continuousSyncPromise = null;
        scheduleContinuousSync();
    }
}

function updateEffectsPausedState() {
    const shouldPause = document.hidden || !!(state.live && state.live.valorant_running);
    document.body.classList.toggle("effects-paused", shouldPause);
    document.body.classList.toggle("game-running", !!(state.live && state.live.valorant_running));
}

function handleVisibilityChange() {
    updateEffectsPausedState();

    // Becoming visible should feel immediate. Going into the background keeps
    // lightweight timers alive only so state recovers cleanly on restore.
    scheduleLivePoll(document.hidden ? getLivePollDelay() : 0);
    scheduleContinuousSync(document.hidden ? continuousSyncDelay() : 750);
}

// ==========================================================================
// AUTO-UPDATE
// ==========================================================================

async function loadAppVersion() {
    try {
        const res = await fetch("/api/app-version");
        const data = await res.json();
        state.appVersion = data.version || "";
        if (DOM.settingsAppVersion && state.appVersion) {
            DOM.settingsAppVersion.value = `v${state.appVersion}`;
        }
        if (DOM.appVersionBadge && state.appVersion) {
            DOM.appVersionBadge.textContent = `v${state.appVersion}`;
        }
    } catch (err) {
        // Non-critical
    }
}

async function checkForUpdate(manual) {
    if (manual && DOM.updateStatusText) {
        DOM.updateStatusText.textContent = "Checking for updates...";
    }

    let data;
    try {
        const res = await fetch("/api/check-update");
        data = await res.json();
    } catch (err) {
        if (manual) {
            showToast("Couldn't reach the update server. Check your connection.", "error");
            if (DOM.updateStatusText) DOM.updateStatusText.textContent = "Updates are hosted at asarii.xyz.";
        }
        return;
    }

    if (data.available) {
        state.pendingUpdate = data;
        if (DOM.updateBannerText) {
            DOM.updateBannerText.textContent = `Version ${data.latest_version} is available (you have v${data.current_version}).`;
        }
        if (DOM.updateBanner) DOM.updateBanner.style.display = "flex";
        // Surface it on every detection (startup included), but only toast
        // once per session for the same version so the periodic re-check
        // doesn't nag.
        if (manual || state._notifiedUpdateVersion !== data.latest_version) {
            showToast(`Update available: v${data.latest_version}`, "info");
            state._notifiedUpdateVersion = data.latest_version;
        }
        if (DOM.updateStatusText) {
            DOM.updateStatusText.textContent = `v${data.latest_version} is available.`;
        }
        // The packaged desktop app owns its updater. Browser mode should only
        // advertise the release and never try to download an installer.
        if (!manual) scheduleDesktopAutoUpdate();
    } else if (manual) {
        showToast("You're on the latest version!", "success");
        if (DOM.updateStatusText) DOM.updateStatusText.textContent = "You're on the latest version.";
    }
}

let autoUpdateTimer = null;
function scheduleDesktopAutoUpdate() {
    if (autoUpdateTimer !== null || !state.pendingUpdate) return;
    const start = () => {
        if (autoUpdateTimer !== null || !state.pendingUpdate) return;
        if (!(window.pywebview && window.pywebview.api)) return;
        autoUpdateTimer = setTimeout(() => {
            autoUpdateTimer = null;
            installPendingUpdate();
        }, 1200);
    };
    start();
    if (!(window.pywebview && window.pywebview.api)) {
        window.addEventListener("pywebviewready", start, { once: true });
    }
}

async function installPendingUpdate() {
    if (!state.pendingUpdate) return;

    if (DOM.btnInstallUpdate) {
        DOM.btnInstallUpdate.disabled = true;
        DOM.btnInstallUpdate.innerHTML = `<i class="fa-solid fa-spinner rotating"></i> Updating...`;
    }

    if (DOM.updateBannerText) {
        DOM.updateBannerText.textContent = `Downloading v${state.pendingUpdate.latest_version} & restarting Vortex...`;
    }

    try {
        const res = await fetch("/api/download-and-install-update", { method: "POST" });
        const data = await res.json();
        if (!data.success) {
            showToast(data.message || "Update failed. Please try again.", "error");
            if (DOM.btnInstallUpdate) {
                DOM.btnInstallUpdate.disabled = false;
                DOM.btnInstallUpdate.innerHTML = "Update Now";
            }
            return;
        }

        if (data.relaunching) {
            showToast("Update downloaded! Restarting Vortex...", "success");
            if (DOM.updateBannerText) {
                DOM.updateBannerText.innerHTML = `<i class="fa-solid fa-arrows-rotate rotating"></i> Restarting Vortex with update v${state.pendingUpdate.latest_version}...`;
            }
            if (DOM.btnInstallUpdate) {
                DOM.btnInstallUpdate.innerHTML = `<i class="fa-solid fa-arrows-rotate rotating"></i> Restarting...`;
            }
        } else {
            // The background updater couldn't arm itself, so Vortex stays open
            // and the installer has been revealed in Explorer instead. Put the
            // banner and button back into a state the user can act on.
            showToast(data.message || "Update downloaded - run the installer to finish.", "warning");
            if (DOM.updateBannerText) {
                DOM.updateBannerText.innerHTML =
                    `<i class="fa-solid fa-triangle-exclamation"></i> v${state.pendingUpdate.latest_version} downloaded - run the installer that just opened to finish updating.`;
            }
            if (DOM.btnInstallUpdate) {
                DOM.btnInstallUpdate.disabled = false;
                DOM.btnInstallUpdate.innerHTML = "Try Again";
            }
        }
    } catch (err) {
        showToast("Applying update and restarting...", "success");
    }
}

function initEventListeners() {
    // Debounced so typing stays smooth instead of firing a request per keystroke.
    let searchTimer = null;
    DOM.searchInput.addEventListener("input", (e) => {
        state.searchQuery = e.target.value.trim();
        DOM.searchClear.style.display = state.searchQuery ? "flex" : "none";
        clearTimeout(searchTimer);
        searchTimer = setTimeout(fetchAccounts, 160);
    });

    DOM.searchClear.addEventListener("click", () => {
        DOM.searchInput.value = "";
        state.searchQuery = "";
        DOM.searchClear.style.display = "none";
        DOM.searchInput.focus();
        fetchAccounts();
    });

    if (DOM.regionFilter) {
        DOM.regionFilter.addEventListener("change", (e) => {
            state.currentRegion = e.target.value;
            fetchAccounts();
        });
    }

    DOM.tagFilter.addEventListener("change", (e) => {
        state.currentTag = e.target.value;
        fetchAccounts();
    });

    DOM.sortFilter.addEventListener("change", (e) => {
        state.currentSort = e.target.value;
        fetchAccounts();
    });

    DOM.viewGridBtn.addEventListener("click", () => setViewMode("grid"));
    DOM.viewTableBtn.addEventListener("click", () => setViewMode("table"));

    // Check All Accounts
    if (DOM.btnCheckAllAccounts) {
        DOM.btnCheckAllAccounts.addEventListener("click", handleCheckAllAccounts);
    }

    DOM.btnAddAccount.addEventListener("click", () => openAccountModal());
    DOM.btnEmptyAdd.addEventListener("click", () => openAccountModal());

    // Batch Import Combo & Drag and Drop
    if (DOM.btnImportCombo) DOM.btnImportCombo.addEventListener("click", () => openModal(DOM.modalImportCombo));
    if (DOM.btnEmptyImport) DOM.btnEmptyImport.addEventListener("click", () => openModal(DOM.modalImportCombo));
    if (DOM.modalImportComboClose) DOM.modalImportComboClose.addEventListener("click", () => closeModal(DOM.modalImportCombo));
    if (DOM.btnCancelCombo) DOM.btnCancelCombo.addEventListener("click", () => closeModal(DOM.modalImportCombo));

    if (DOM.comboDropzone) {
        DOM.comboDropzone.addEventListener("click", () => DOM.fileComboInput.click());

        DOM.comboDropzone.addEventListener("dragover", (e) => {
            e.preventDefault();
            e.stopPropagation();
            DOM.comboDropzone.classList.add("dragover");
        });

        DOM.comboDropzone.addEventListener("dragleave", (e) => {
            e.preventDefault();
            e.stopPropagation();
            DOM.comboDropzone.classList.remove("dragover");
        });

        DOM.comboDropzone.addEventListener("drop", (e) => {
            e.preventDefault();
            e.stopPropagation();
            DOM.comboDropzone.classList.remove("dragover");
            
            const files = e.dataTransfer.files;
            if (files && files.length > 0) {
                readComboFile(files[0]);
            }
        });
    }

    if (DOM.fileComboInput) {
        DOM.fileComboInput.addEventListener("change", (e) => {
            if (e.target.files && e.target.files.length > 0) {
                readComboFile(e.target.files[0]);
            }
        });
    }

    if (DOM.comboTextInput) {
        DOM.comboTextInput.addEventListener("input", updateComboPreviewCount);
    }

    if (DOM.btnDoComboImport) {
        DOM.btnDoComboImport.addEventListener("click", handleBatchTextImport);
    }

    DOM.modalAccountClose.addEventListener("click", () => closeModal(DOM.modalAccount));
    DOM.btnCancelAccount.addEventListener("click", () => closeModal(DOM.modalAccount));
    DOM.formAccount.addEventListener("submit", handleAccountSubmit);
    if (DOM.btnSaveAndCheck) {
        DOM.btnSaveAndCheck.addEventListener("click", (e) => handleAccountSubmit(e, true));
    }

    DOM.btnToggleFormPassword.addEventListener("click", () => {
        const type = DOM.formPassword.type === "password" ? "text" : "password";
        DOM.formPassword.type = type;
        DOM.btnToggleFormPassword.innerHTML = type === "password" 
            ? '<i class="fa-regular fa-eye"></i>' 
            : '<i class="fa-regular fa-eye-slash"></i>';
    });

    DOM.btnSyncAll.addEventListener("click", handleSyncAll);

    if (DOM.btnKillClient) {
        DOM.btnKillClient.addEventListener("click", async () => {
            try {
                await fetch("/api/kill-client", { method: "POST" });
                showToast("Riot Client force closed", "info");
            } catch (e) {
                showToast("Failed to close Riot Client", "error");
            }
        });
    }

    // Matches Modal
    DOM.modalMatchesClose.addEventListener("click", () => closeModal(DOM.modalMatches));
    DOM.btnRefreshMatches.addEventListener("click", () => {
        if (state.activeMatchAccId) {
            openMatchesModal(state.activeMatchAccId);
        }
    });
    if (DOM.playerLookupForm) DOM.playerLookupForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const riotId = DOM.playerLookupInput.value.trim();
        if (!riotId) return;
        await openPlayerProfile(riotId);
    });
    if (DOM.modalMatchDetailClose) DOM.modalMatchDetailClose.addEventListener("click", () => closeModal(DOM.modalMatchDetail));

    DOM.btnOpenSettings.addEventListener("click", openSettingsModal);
    DOM.modalSettingsClose.addEventListener("click", () => closeModal(DOM.modalSettings));
    DOM.btnCancelSettings.addEventListener("click", () => closeModal(DOM.modalSettings));
    DOM.btnSaveSettings.addEventListener("click", saveSettings);
    DOM.btnAutoDetectClient.addEventListener("click", autoDetectClientPath);
    if (DOM.btnCheckUpdate) DOM.btnCheckUpdate.addEventListener("click", () => checkForUpdate(true));
    if (DOM.btnOpenLog) DOM.btnOpenLog.addEventListener("click", openLoginLog);
    if (DOM.btnCopySettingsNow) DOM.btnCopySettingsNow.addEventListener("click", copySettingsNow);
    if (DOM.btnCopySettingsAll) DOM.btnCopySettingsAll.addEventListener("click", copySettingsToAll);
    if (DOM.btnBorderlessAll) DOM.btnBorderlessAll.addEventListener("click", applyBorderlessToAll);
    if (DOM.settingsOverlayHotkey) DOM.settingsOverlayHotkey.addEventListener("input", renderOverlayHotkeyValidity);
    if (DOM.btnPresetCapture) DOM.btnPresetCapture.addEventListener("click", capturePreset);
    if (DOM.btnPresetApply) DOM.btnPresetApply.addEventListener("click", applyPresetToCurrent);
    if (DOM.btnPresetApplyAll) DOM.btnPresetApplyAll.addEventListener("click", applyPresetToAll);
    if (DOM.presetLogClose) DOM.presetLogClose.addEventListener("click", () => {
        DOM.presetLog.style.display = "none";
    });
    // Picking a different profile changes what a copy would carry, so the
    // description under the picker has to follow the selection.
    if (DOM.settingsProfileAccount) {
        DOM.settingsProfileAccount.addEventListener("change", onProfileAccountChange);
    }
    if (DOM.btnInstallUpdate) DOM.btnInstallUpdate.addEventListener("click", installPendingUpdate);
    if (DOM.btnDismissUpdate) DOM.btnDismissUpdate.addEventListener("click", () => {
        if (DOM.updateBanner) DOM.updateBanner.style.display = "none";
    });
    if (DOM.themePicker) {
        DOM.themePicker.querySelectorAll(".theme-swatch").forEach(el => {
            el.addEventListener("click", () => selectTheme(el.dataset.theme));
        });
    }

    DOM.btnBackupRestore.addEventListener("click", () => openModal(DOM.modalBackup));
    DOM.modalBackupClose.addEventListener("click", () => closeModal(DOM.modalBackup));
    DOM.btnDoExport.addEventListener("click", handleExportBackup);
    DOM.btnTriggerImport.addEventListener("click", () => DOM.fileImportInput.click());
    DOM.fileImportInput.addEventListener("change", handleImportBackup);

    if (DOM.btnOpenBanned) DOM.btnOpenBanned.addEventListener("click", () => {
        openModal(DOM.modalBanned);
        fetchBannedAccounts();
    });
    if (DOM.modalBannedClose) DOM.modalBannedClose.addEventListener("click", () => closeModal(DOM.modalBanned));

    DOM.btnCloseLaunch.addEventListener("click", () => {
        const stillRunning = !!state._launchPoll;
        closeModal(DOM.modalLaunch);
        stopLaunchPolling();
        if (stillRunning) {
            showToast("Login continues in the background", "info");
            // Backend login worker keeps running; refresh once it's had time to finish.
            setTimeout(() => { fetchAccounts(); fetchStatsSummary(); }, 8000);
        }
    });

    if (DOM.btnRetryLaunch) {
        DOM.btnRetryLaunch.addEventListener("click", () => {
            if (typeof state._launchRetry === "function") state._launchRetry();
        });
    }

    if (DOM.btnCopyLaunchUser) {
        DOM.btnCopyLaunchUser.addEventListener("click", () => {
            if (state.activeLaunchAcc) {
                copyText(state.activeLaunchAcc.username, "Username copied");
            }
        });
    }

    if (DOM.btnCopyLaunchPass) {
        DOM.btnCopyLaunchPass.addEventListener("click", () => {
            if (state.activeLaunchAcc) {
                copyText(state.activeLaunchAcc.password, "Password copied");
            }
        });
    }

    initLiveEventListeners();

    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            DOM.searchInput.focus();
            DOM.searchInput.select();
        }
        if (e.key === "Escape") {
            // A modal sits on top of the dashboard, so it closes first.
            const openModalEl = document.querySelector(".modal-overlay.active");
            if (openModalEl) closeAllModals();
            else if (state.dashboardOpen) closeDashboard();
        }
    });
}

function readComboFile(file) {
    const reader = new FileReader();
    reader.onload = (event) => {
        DOM.comboTextInput.value = event.target.result;
        updateComboPreviewCount();
        showToast(`Loaded ${file.name}`, "info");
    };
    reader.readAsText(file);
}

function updateComboPreviewCount() {
    if (!DOM.comboTextInput || !DOM.comboCountPreview) return;
    const lines = DOM.comboTextInput.value.split("\n");
    let validCount = 0;
    for (const l of lines) {
        const trimmed = l.trim();
        if (trimmed && !trimmed.startsWith("#") && !trimmed.startsWith("//")) {
            if (trimmed.includes(":") || trimmed.includes("|") || trimmed.includes(",")) {
                validCount++;
            }
        }
    }
    DOM.comboCountPreview.innerHTML = `Parsed: <strong>${validCount}</strong> accounts ready`;
}

async function handleBatchTextImport() {
    const rawText = DOM.comboTextInput.value.trim();
    if (!rawText) {
        showToast("Please paste accounts or drop a .txt file", "error");
        return;
    }

    const btn = DOM.btnDoComboImport;
    btn.innerHTML = '<i class="fa-solid fa-spinner rotating"></i> Importing...';

    try {
        const res = await fetch("/api/import-text", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: rawText })
        });
        const data = await res.json();
        if (data.success) {
            showToast(buildImportMessage(data), data.imported_count > 0 ? "success" : "info");
            DOM.comboTextInput.value = "";
            updateComboPreviewCount();
            closeModal(DOM.modalImportCombo);
            fetchAccounts();
            fetchStatsSummary();
        } else {
            showToast("Failed to import accounts", "error");
        }
    } catch (err) {
        showToast("Import communication error", "error");
    } finally {
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Import Accounts';
    }
}

// ==========================================================================
// CHECK ACCOUNTS (SEQUENTIAL SCANNER)
// ==========================================================================

async function handleCheckAllAccounts() {
    if (state.isCheckingAccounts) {
        try {
            await fetch("/api/accounts/cancel-check", { method: "POST" });
            showToast("Stopping account check...", "info");
        } catch (e) {}
        return;
    }

    state.isCheckingAccounts = true;
    DOM.checkAllIcon.classList.add("rotating");
    DOM.syncProgressBar.style.display = "block";
    DOM.syncProgressFill.style.width = "10%";
    DOM.syncProgressText.textContent = "Starting account verification...";

    try {
        const res = await fetch("/api/accounts/check-all", { method: "POST" });
        const startData = await res.json();

        if (!startData.success && startData.message) {
            showToast(startData.message, "info");
        }

        // Poll progress until complete
        const pollInterval = setInterval(async () => {
            try {
                const statusRes = await fetch("/api/accounts/check-status");
                const progress = await statusRes.json();

                if (progress.running) {
                    const pct = Math.max(10, Math.round((progress.current / Math.max(progress.total, 1)) * 100));
                    DOM.syncProgressFill.style.width = `${pct}%`;
                    DOM.syncProgressText.textContent = progress.message || `Checking accounts (${progress.current}/${progress.total})...`;
                    fetchAccounts();
                    fetchStatsSummary();
                } else {
                    clearInterval(pollInterval);
                    DOM.syncProgressFill.style.width = "100%";
                    DOM.syncProgressText.textContent = progress.message || "All accounts verified!";
                    DOM.checkAllIcon.classList.remove("rotating");
                    state.isCheckingAccounts = false;
                    showToast(progress.message || "Account check completed!", "success");

                    setTimeout(() => {
                        DOM.syncProgressBar.style.display = "none";
                        DOM.syncProgressFill.style.width = "0%";
                    }, 2500);

                    fetchAccounts();
                    fetchStatsSummary();
                    fetchBannedAccounts();
                }
            } catch (err) {
                // Ignore poll error
            }
        }, 1500);

    } catch (err) {
        showToast("Failed to start account verification", "error");
        DOM.checkAllIcon.classList.remove("rotating");
        DOM.syncProgressBar.style.display = "none";
        state.isCheckingAccounts = false;
    }
}

// ==========================================================================
// DATA & API
// ==========================================================================

/**
 * Fingerprint of everything a card/row actually draws.
 *
 * Stringifying the whole payload was both expensive (it drags along every
 * account's stored match history) and unstable - the background sync rewrites
 * last_updated every few seconds, so the fingerprint changed on every tick and
 * the roster was rebuilt anyway. Timestamps are bucketed to the minute, which
 * is the finest granularity formatTimeAgo can actually show.
 */
function accountsSignature(list) {
    const minute = (iso) => {
        if (!iso) return "";
        const t = Date.parse(iso);
        return isNaN(t) ? "" : Math.floor(t / 60000);
    };

    return list.map(a => [
        a.id, a.username, a.display_name, a.region, a.tag, a.notes,
        a.rank_tier, a.rank_division, a.lp, a.level, a.winrate, a.games_played,
        a.rank_icon_url, a.peak_rank_tier, a.peak_rank_division,
        a.peak_rank_icon_url, a.peak_rank_season, a.status, a.favorite,
        a.needs_check, minute(a.last_login)
    ].join("")).join("")
        + "|" + state.activeAccountId + "|" + state.viewMode;
}

async function fetchAccounts(silent = false) {
    try {
        let tagParam = state.currentTag;
        let url = `/api/accounts?search=${encodeURIComponent(state.searchQuery)}&region=${encodeURIComponent(state.currentRegion)}&sort_by=${encodeURIComponent(state.currentSort)}`;
        
        if (tagParam === "FAVORITES") {
            url += "&favorite=true";
        } else if (tagParam === "BANNED") {
            url += "&status=BANNED";
        } else if (tagParam === "PLAYABLE") {
            url += "&status=PLAYABLE";
        } else if (tagParam !== "ALL") {
            url += `&tag=${encodeURIComponent(tagParam)}`;
        }

        const res = await fetch(url);
        const data = await res.json();
        let newAccounts = data.accounts || [];

        if (tagParam === "FAVORITES") {
            newAccounts = newAccounts.filter(a => a.favorite);
        }

        // Avoid unnecessary DOM rebuilds if data hasn't changed
        const signature = accountsSignature(newAccounts);
        if (silent && state._lastAccountsSignature === signature) {
            return;
        }
        state._lastAccountsSignature = signature;
        state.accounts = newAccounts;

        renderAccounts(silent);
    } catch (err) {
        if (DOM.skeletonGrid) DOM.skeletonGrid.style.display = "none";
        if (!silent) showToast("Failed to load accounts", "error");
    }
}

async function fetchStatsSummary() {
    try {
        const res = await fetch("/api/stats-summary");
        const data = await res.json();
        state.stats = data;

        setStatValue(DOM.statTotal, data.total_accounts || 0);
        setStatValue(DOM.statMains, data.main_accounts || 0);
        setStatValue(DOM.statRanked, data.ranked_accounts || 0);
        setStatValue(DOM.statUnrated, data.unrated_accounts || 0);

        if (DOM.bannedCountBadge) {
            const bannedCount = data.banned_accounts || 0;
            DOM.bannedCountBadge.textContent = bannedCount;
            DOM.bannedCountBadge.style.display = bannedCount > 0 ? "flex" : "none";
        }
    } catch (err) {
        console.error("Failed to load stats summary", err);
    }
}

// ==========================================================================
// BANNED ACCOUNTS
// ==========================================================================

async function fetchBannedAccounts(silent = false) {
    try {
        const res = await fetch("/api/banned-accounts");
        const data = await res.json();
        // Cached in state because the "currently logged in" card has to be
        // able to edit/delete a banned account without the Banned modal ever
        // having been opened.
        state.bannedAccounts = data.accounts || [];
        if (DOM.bannedListContainer) renderBannedAccounts(state.bannedAccounts);
    } catch (err) {
        if (!silent) showToast("Failed to load banned accounts", "error");
    }
}

/** The banned-store record for an id, if that's where the account lives. */
function findBannedAccount(id) {
    const numId = Number(id);
    return (state.bannedAccounts || []).find(a => Number(a.id) === numId) || null;
}

/**
 * Resolves an id against both stores. The hero card can be showing an account
 * that got flagged and moved to the banned store mid-session, and every action
 * on it (edit, delete, restore) has to follow it there.
 */
function resolveAccount(id) {
    const numId = Number(id);
    const active = state.accounts.find(a => Number(a.id) === numId);
    if (active) return { acc: active, banned: false };
    const banned = findBannedAccount(numId);
    if (banned) return { acc: banned, banned: true };
    return { acc: null, banned: false };
}

function renderBannedAccounts(accounts) {
    const rows = DOM.bannedListContainer.querySelectorAll(".banned-row");
    rows.forEach(r => r.remove());

    if (DOM.bannedEmptyState) {
        DOM.bannedEmptyState.style.display = accounts.length === 0 ? "block" : "none";
    }

    accounts.forEach(acc => {
        const row = document.createElement("div");
        row.className = "banned-row";
        const statusLabel = (acc.status || "BANNED").toUpperCase();
        row.innerHTML = `
            <div class="banned-row-info">
                <div class="banned-row-title">
                    <i class="fa-solid fa-ban text-red"></i>
                    ${escapeHtml(acc.display_name || acc.username)}
                    <span class="badge-status badge-${statusLabel === "SUSPENDED" ? "suspended" : "banned"}">${statusLabel}</span>
                </div>
                <div class="banned-row-meta">${escapeHtml(acc.username)} &middot; ${escapeHtml(acc.region || "NA")}</div>
            </div>
            <div class="banned-row-actions">
                <button class="btn btn-secondary btn-sm btn-recheck-banned" data-id="${acc.id}" title="Recheck this account's status">
                    <i class="fa-solid fa-arrows-rotate"></i> Recheck
                </button>
                <button class="btn btn-icon btn-delete-banned" data-id="${acc.id}" title="Permanently delete">
                    <i class="fa-solid fa-trash"></i>
                </button>
            </div>
        `;
        DOM.bannedListContainer.appendChild(row);
    });

    DOM.bannedListContainer.querySelectorAll(".btn-recheck-banned").forEach(btn => {
        btn.addEventListener("click", () => recheckBannedAccount(btn.dataset.id, btn));
    });
    DOM.bannedListContainer.querySelectorAll(".btn-delete-banned").forEach(btn => {
        btn.addEventListener("click", () => deleteBannedAccount(btn.dataset.id));
    });
}

async function recheckBannedAccount(id, btnEl) {
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = `<i class="fa-solid fa-spinner rotating"></i> Checking...`;
    }
    try {
        const res = await fetch(`/api/banned-accounts/${id}/recheck`, { method: "POST" });
        const data = await res.json();
        showToast(data.message || "Recheck complete", data.still_banned === false ? "success" : "info");
        await fetchBannedAccounts();
        await fetchStatsSummary();
        if (data.still_banned === false) {
            await fetchAccounts();
        }
    } catch (err) {
        showToast("Failed to recheck account", "error");
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.innerHTML = `<i class="fa-solid fa-arrows-rotate"></i> Recheck`;
        }
    }
}

async function deleteBannedAccount(id) {
    try {
        await fetch(`/api/banned-accounts/${id}`, { method: "DELETE" });
        showToast("Banned account deleted permanently", "info");
        await fetchBannedAccounts();
        await fetchStatsSummary();
    } catch (err) {
        showToast("Failed to delete banned account", "error");
    }
}

async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        state.settings = await res.json();
    } catch (err) {
        console.error("Failed to load settings", err);
    }
    applyTheme(state.settings.theme || "blue");
}

// ==========================================================================
// THEME
// ==========================================================================

const VALID_THEMES = ["blue", "purple", "emerald", "crimson", "amber", "cyan"];

function applyTheme(themeName) {
    const theme = VALID_THEMES.includes(themeName) ? themeName : "blue";
    document.body.className = document.body.className
        .split(/\s+/)
        .filter(c => !c.startsWith("theme-"))
        .concat(`theme-${theme}`)
        .join(" ")
        .trim();

    if (DOM.themePicker) {
        DOM.themePicker.querySelectorAll(".theme-swatch").forEach(opt => {
            opt.classList.toggle("active", opt.dataset.theme === theme);
        });
    }
}

async function selectTheme(themeName) {
    applyTheme(themeName);
    state.settings.theme = themeName;
    try {
        await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ settings: { theme: themeName } })
        });
    } catch (err) {
        // Non-critical - the theme still applied locally this session.
    }
}

// ==========================================================================
// ACCOUNT RENDERING & BADGES
// ==========================================================================

function buildImportMessage(data) {
    const imported = data.imported_count || 0;
    const dupes = data.skipped_existing || 0;
    const banned = data.skipped_banned || 0;

    const skips = [];
    if (dupes) skips.push(`${dupes} already added`);
    if (banned) skips.push(`${banned} banned`);

    if (imported === 0 && skips.length) {
        return `No new accounts — skipped ${skips.join(" and ")}.`;
    }
    if (skips.length) {
        return `Imported ${imported} — skipped ${skips.join(" and ")}.`;
    }
    return `Imported ${imported} account${imported === 1 ? "" : "s"} successfully!`;
}

function buildPeakBadge(acc) {
    if (!acc.peak_rank_tier) return "";

    const label = `${acc.peak_rank_tier} ${acc.peak_rank_division || ""}`.trim();
    // Prefer the icon URL the sync saved; fall back to deriving it from the
    // tier so accounts synced before that field existed still show an emblem.
    const iconUrl = acc.peak_rank_icon_url || getRankIconUrl(acc.peak_rank_tier, acc.peak_rank_division);
    const season = acc.peak_rank_season ? ` (${acc.peak_rank_season})` : "";

    const icon = iconUrl
        ? `<img src="${iconUrl}" class="peak-emblem-icon" alt="${escapeHtml(label)}" onerror="this.style.display='none';">`
        : `<i class="fa-solid fa-trophy text-gold"></i>`;

    return `
        <span class="peak-emblem-badge" title="All-Time Peak Rank: ${escapeHtml(label)}${escapeHtml(season)}">
            <span class="peak-emblem-text">Peak: ${escapeHtml(label)}</span>
            ${icon}
        </span>
    `;
}

function getAccountCombatStats(acc) {
    const matches = Array.isArray(acc.match_history) ? acc.match_history : [];
    if (!matches || matches.length === 0) {
        return {
            winrate: Number(acc.winrate) || 0,
            games: acc.games_played || 0,
            kd: "0.0",
            kda: "0.0",
            hs: 0,
            avgKills: "0.0"
        };
    }

    let kills = 0, deaths = 0, assists = 0;
    let totalHsPct = 0, hsCount = 0;

    for (const m of matches) {
        kills += Number(m.kills) || 0;
        deaths += Number(m.deaths) || 0;
        assists += Number(m.assists) || 0;
        if (m.hs_pct !== undefined && m.hs_pct !== null && !isNaN(m.hs_pct)) {
            totalHsPct += Number(m.hs_pct);
            hsCount++;
        }
    }

    const n = matches.length;
    const kd = deaths > 0 ? (kills / deaths).toFixed(2) : (kills > 0 ? kills.toFixed(2) : "0.0");
    const kda = deaths > 0 ? ((kills + assists) / deaths).toFixed(2) : ((kills + assists) > 0 ? (kills + assists).toFixed(2) : "0.0");
    const avgHs = hsCount > 0 ? Math.round(totalHsPct / hsCount) : 0;
    const avgKills = n > 0 ? (kills / n).toFixed(1) : "0.0";

    return {
        winrate: Number(acc.winrate) || 0,
        games: acc.games_played || n,
        kd,
        kda,
        hs: avgHs,
        avgKills
    };
}

function getStatusBadge(status) {
    const s = (status || "PLAYABLE").toUpperCase();
    if (s === "BANNED") {
        return '<span class="badge-status badge-banned"><i class="fa-solid fa-ban"></i> BANNED</span>';
    } else if (s === "SUSPENDED") {
        return '<span class="badge-status badge-suspended"><i class="fa-solid fa-triangle-exclamation"></i> SUSPENDED</span>';
    } else if (s === "UNVERIFIED") {
        return '<span class="badge-status badge-unverified">Unverified</span>';
    } else {
        return '<span class="badge-status badge-playable"><i class="fa-solid fa-circle-check"></i> Playable</span>';
    }
}

function renderAccounts(silent = false) {
    if (DOM.skeletonGrid) DOM.skeletonGrid.style.display = "none";

    // Entrance animations only replay when the visible set actually changed —
    // the background sync re-renders silently and shouldn't restart animations.
    const signature = state.accounts.map(a => a.id).join(",") + "|" + state.viewMode;
    const isNewSet = !silent && (signature !== state._renderSignature);
    state._renderSignature = signature;

    if (DOM.resultCount) {
        const n = state.accounts.length;
        DOM.resultCount.innerHTML = `<strong>${n}</strong> shown`;
    }

    if (state.accounts.length === 0) {
        DOM.accountsGrid.style.display = "none";
        DOM.accountsGrid.innerHTML = "";
        DOM.accountsTableWrapper.style.display = "none";
        DOM.accountsTableBody.innerHTML = "";
        DOM.emptyState.style.display = "flex";
        return;
    }

    DOM.emptyState.style.display = "none";

    if (state.viewMode === "grid") {
        DOM.accountsGrid.style.display = "grid";
        DOM.accountsTableWrapper.style.display = "none";
        // Clear the hidden view so its markup can't duplicate element ids.
        DOM.accountsTableBody.innerHTML = "";
        renderGridView();
        DOM.accountsGrid.classList.toggle("animate-in", isNewSet);
    } else {
        DOM.accountsGrid.style.display = "none";
        DOM.accountsGrid.innerHTML = "";
        DOM.accountsTableWrapper.style.display = "block";
        renderTableView();
        DOM.accountsTableBody.classList.toggle("animate-in", isNewSet);
    }
}

/** Shared per-account view model used by both the grid and table renderers. */
function buildAccountView(acc) {
    const tier = (acc.rank_tier || "UNRANKED").toUpperCase();
    const rankInfo = TIER_ICONS[tier] || TIER_ICONS.UNRANKED;
    const effectiveTag = acc.tag && !['Smurf', 'Ranked', 'Unrated', ''].includes(acc.tag)
        ? acc.tag
        : (acc.level >= 20 ? 'Ranked' : 'Unrated');
    const winrate = Number(acc.winrate) || 0;

    // The signed-in account gets a live badge and a PLAY button instead of
    // LOGIN; anything Riot hasn't confirmed yet gets a Check Account button.
    const isActive = state.activeAccountId === acc.id;
    const needsCheck = acc.needs_check === true;
    const isHighlighted = state.highlightId === acc.id;

    const lastLoginFormatted = isActive
        ? '<span class="last-login-val is-active"><span class="live-dot-mini"></span> Active Now</span>'
        : (acc.last_login
            ? `<span class="last-login-val">${formatTimeAgo(acc.last_login)}</span>`
            : '<span class="last-login-val is-never">Never</span>');

    return {
        isActive,
        needsCheck,
        cardFlags: [isActive ? "is-active-session" : "", isHighlighted ? "is-highlighted" : ""]
            .filter(Boolean).join(" "),
        liveBadge: isActive
            ? '<span class="badge-live"><span class="live-dot"></span> LOGGED IN</span>'
            : "",
        tier,
        rankInfo,
        rankTitle: formatRankTitle(acc),
        rankIconSrc: acc.rank_icon_url || DEFAULT_TIER_ICON,
        peakIconSrc: acc.peak_rank_icon_url || getRankIconUrl(acc.peak_rank_tier, acc.peak_rank_division),
        effectiveTag,
        tagClass: getTagBadgeClass(effectiveTag, acc.level),
        winrate,
        // Meter colour follows the value: red below 45%, amber to 55%, accent above.
        wrClass: winrate >= 55 ? "wr-high" : (winrate >= 45 ? "wr-mid" : "wr-low"),
        tierClass: `tier-${tier.toLowerCase()}`,
        statusBadge: getStatusBadge(acc.status),
        displayName: acc.display_name || acc.username,
        lastLoginFormatted
    };
}

function renderHeroAccountCard(acc, isBanned = false, isUnsaved = false) {
    const v = buildAccountView(acc);
    const peakBadge = buildPeakBadge(acc);
    const combat = getAccountCombatStats(acc);
    const isValRunning = state.live && state.live.valorant_running;
    const sessionInfo = sessionStateInfo(state.live);

    // A flagged account keeps its card - it's still the signed-in session -
    // but the actions change: there's nothing to play, and the useful moves
    // are correcting the record, putting it back, or deleting it.
    const bannedLabel = ((acc.status || "BANNED").toUpperCase() === "SUSPENDED")
        ? "SUSPENDED" : "BANNED";

    return `
        <div class="account-card account-card-hero is-active-session ${isBanned ? 'is-banned-session' : ''} ${acc.favorite ? 'is-favorite' : ''} ${v.cardFlags}" data-id="${acc.id}">
            <div class="hero-ambient-glow"></div>

            <!-- Hero Top Header -->
            <div class="hero-header">
                <div class="hero-header-left">
                    <span class="badge-live-hero ${isBanned ? 'is-banned' : ''}" title="Currently signed in to Riot Client">
                        <span class="live-dot-hero"></span>
                        <span class="live-label-hero">${isBanned ? `LOGGED IN &middot; ${bannedLabel}` : 'CURRENTLY LOGGED IN'}</span>
                    </span>
                    <span class="badge-region">${escapeHtml(acc.region || 'NA')}</span>
                    <span class="badge-tag ${v.tagClass}">${escapeHtml(v.effectiveTag)}</span>
                    ${v.statusBadge}
                    <span class="session-state-chip ${sessionInfo.cls}">${isValRunning ? sessionInfo.label : "Riot Session Active"}</span>
                    <span class="hero-last-login"><i class="fa-regular fa-clock"></i> Last Login: <strong>Active Now</strong></span>
                </div>
                <div class="hero-header-right">
                    ${(isBanned || isUnsaved) ? "" : `
                    <button class="card-favorite-btn ${acc.favorite ? 'active' : ''}" onclick="toggleFavorite(${acc.id})" title="Pin Account">
                        <i class="fa-${acc.favorite ? 'solid' : 'regular'} fa-star"></i>
                    </button>
                    `}
                </div>
            </div>

            <!-- Hero Body -->
            <div class="hero-body">
                <!-- Hero Left: Massive Emblem & Identity -->
                <div class="hero-identity-col">
                    <div class="hero-emblem-wrap ${v.tierClass}" title="Current Rank: ${v.rankTitle}">
                        <img src="${v.rankIconSrc}" alt="${v.rankTitle}" class="hero-emblem-img" onerror="this.onerror=null; this.src='${DEFAULT_TIER_ICON}';">
                        <span class="hero-level-chip">LV ${acc.level || "-"}</span>
                    </div>
                    <div class="hero-name-block">
                        <div class="hero-summoner-row">
                            <h2 class="hero-summoner-name" title="${escapeHtml(v.displayName)}">${escapeHtml(v.displayName)}</h2>
                            ${acc.display_name ? `
                                <button class="btn-mini-copy hero-copy-btn" onclick="copyText('${escapeHtml(acc.display_name)}', 'Riot ID copied')" title="Copy Riot ID">
                                    <i class="fa-regular fa-copy"></i>
                                </button>
                            ` : ''}
                        </div>
                        <div class="hero-rank-row">
                            <span class="hero-rank-tier ${v.rankInfo.colorClass}">${v.rankTitle}</span>
                            ${peakBadge}
                        </div>
                    </div>
                </div>

                <!-- Hero Center: Stats, Winrate & Credentials -->
                <div class="hero-stats-col">
                    <div class="hero-stats-panel">
                        <div class="hero-stat-card">
                            <span class="hero-stat-label">WIN RATE</span>
                            <span class="hero-stat-value ${v.wrClass}">${v.winrate}%</span>
                        </div>
                        <div class="hero-stat-card">
                            <span class="hero-stat-label">AVG KDA</span>
                            <span class="hero-stat-value text-accent">${combat.kda} <small class="stat-unit">KDA</small></span>
                        </div>
                        <div class="hero-stat-card">
                            <span class="hero-stat-label">HEADSHOT</span>
                            <span class="hero-stat-value text-cyan">${combat.hs}%</span>
                        </div>
                        <div class="hero-stat-card">
                            <span class="hero-stat-label">MATCHES</span>
                            <span class="hero-stat-value">${acc.games_played || combat.games || 0}</span>
                        </div>
                    </div>

                    <div class="hero-winrate-track">
                        <div class="winrate-bar-fill ${v.wrClass}" style="width: ${v.winrate}%;"></div>
                    </div>

                    <div class="hero-creds-box">
                        <div class="cred-row">
                            <span class="cred-label"><i class="fa-solid fa-user"></i> User</span>
                            <span class="cred-val-wrap">
                                <span class="cred-text">${escapeHtml(acc.username)}</span>
                                <button class="btn-mini-copy" onclick="copyText('${escapeHtml(acc.username)}', 'Username copied')" title="Copy Username">
                                    <i class="fa-regular fa-copy"></i>
                                </button>
                            </span>
                        </div>
                        <div class="cred-row">
                            <span class="cred-label"><i class="fa-solid fa-key"></i> Pass</span>
                            <span class="cred-val-wrap">
                                <span class="masked" id="pass-mask-${acc.id}">••••••••</span>
                                <button class="btn-mini-copy" onclick="togglePasswordVisibility(${acc.id}, '${escapeHtml(acc.password)}')" title="Toggle View">
                                    <i class="fa-regular fa-eye" id="eye-icon-${acc.id}"></i>
                                </button>
                                <button class="btn-mini-copy" onclick="copyText('${escapeHtml(acc.password)}', 'Password copied')" title="Copy Password">
                                    <i class="fa-regular fa-copy"></i>
                                </button>
                            </span>
                        </div>
                    </div>

                    ${acc.notes ? `<div class="hero-notes" title="${escapeHtml(acc.notes)}"><i class="fa-solid fa-note-sticky"></i> ${escapeHtml(acc.notes)}</div>` : ''}
                </div>

                <!-- Hero Right: Launch & Actions -->
                <div class="hero-actions-col">
                    ${isUnsaved ? `
                    <div class="hero-banned-notice">
                        <i class="fa-solid fa-circle-info"></i>
                        <div class="hero-banned-text">
                            <span class="hero-banned-title">This session isn't in your accounts</span>
                            <span class="hero-banned-sub">${isBanned
                                ? "Riot reports it as " + bannedLabel + ", so it wasn't added automatically."
                                : "Add it to store the credentials and track it."}</span>
                        </div>
                    </div>
                    <button class="btn-hero-play is-restore" onclick="openAccountModal()" title="Add this account">
                        <div class="hero-play-text-wrap">
                            <span class="hero-play-title">ADD TO MY ACCOUNTS</span>
                            <span class="hero-play-sub">Store this login</span>
                        </div>
                    </button>
                    ` : isBanned ? `
                    <div class="hero-banned-notice">
                        <i class="fa-solid fa-ban"></i>
                        <div class="hero-banned-text">
                            <span class="hero-banned-title">Riot reports this account as ${bannedLabel}</span>
                            <span class="hero-banned-sub">It's kept in Banned Accounts. You can still fix its details, put it back, or delete it.</span>
                        </div>
                    </div>
                    <button class="btn-hero-play is-restore" onclick="restoreBannedAccount(${acc.id})" title="Move this account back to your main roster">
                        <div class="hero-play-text-wrap">
                            <span class="hero-play-title">MOVE BACK TO ACCOUNTS</span>
                            <span class="hero-play-sub">Undo the banned flag</span>
                        </div>
                    </button>
                    ` : `
                    <button class="btn-hero-play ${isValRunning ? 'is-running' : ''}" onclick="playAccount(${acc.id})" title="Launch VALORANT on this account">
                        <div class="hero-play-text-wrap">
                            <span class="hero-play-title">${isValRunning ? 'VALORANT RUNNING' : 'PLAY VALORANT'}</span>
                            <span class="hero-play-sub">${isValRunning ? 'Client Active' : 'Launch Game Client'}</span>
                        </div>
                    </button>
                    `}

                    <div class="hero-aux-actions">
                        ${isUnsaved ? "" : isBanned ? `
                        <button class="btn btn-secondary hero-action-btn" onclick="recheckBannedAccount(${acc.id})" title="Log in again and re-check this account's status">
                            <i class="fa-solid fa-arrows-rotate"></i>
                            <span>Recheck</span>
                        </button>
                        ` : `
                        <button class="btn btn-secondary hero-action-btn" onclick="openMatchesModal(${acc.id})" title="View Match History & Details">
                            <i class="fa-solid fa-clock-rotate-left"></i>
                            <span>Matches (${acc.games_played || 0})</span>
                        </button>
                        <button class="btn btn-primary hero-action-btn hero-dashboard-btn" onclick="openDashboard()" title="Open Live Match Dashboard">
                            <i class="fa-solid fa-gauge-high"></i>
                            <span>Dashboard</span>
                        </button>
                        `}
                        ${isUnsaved ? "" : `
                        <button class="btn btn-secondary hero-action-btn" onclick="openEditModal(${acc.id})" title="Edit Account">
                            <i class="fa-solid fa-pen"></i>
                            <span>Edit</span>
                        </button>
                        <button class="btn btn-icon hero-delete-btn is-danger" onclick="deleteAccount(${acc.id})" title="Delete Account">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                        `}
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderGridView() {
    let activeAcc = state.activeAccountId ? state.accounts.find(a => a.id === state.activeAccountId) : null;
    if (!activeAcc && state.live && state.live.available && state.live.username) {
        activeAcc = state.accounts.find(a => 
            (a.username && a.username.toLowerCase() === state.live.username.toLowerCase()) ||
            (a.display_name && state.live.display_name && a.display_name.toLowerCase() === state.live.display_name.toLowerCase())
        );
    }

    // The signed-in account may be one that got flagged and moved to the
    // banned store. It still owns the hero card, but it has to be rendered
    // from its real banned-store record - otherwise the card is built from a
    // synthetic stand-in with id 0, and every button on it silently no-ops.
    let activeIsBanned = false;
    if (!activeAcc && state.live && state.live.available) {
        const bannedId = state.live.banned_account_id;
        const bannedAcc = bannedId
            ? findBannedAccount(bannedId)
            : (state.live.username
                ? (state.bannedAccounts || []).find(a =>
                    (a.username || "").toLowerCase() === state.live.username.toLowerCase())
                : null);
        if (bannedAcc) {
            activeAcc = bannedAcc;
            activeIsBanned = true;
        }
    }

    if (!activeAcc && state.live && state.live.available && state.live.username) {
        activeAcc = {
            id: state.live.account_id || 0,
            username: state.live.username,
            display_name: state.live.display_name || state.live.username,
            region: state.live.region || "NA",
            level: state.live.level || 0,
            rank_tier: (state.live.rank_label || "UNRANKED").split(" ")[0].toUpperCase(),
            rank_division: (state.live.rank_label || "").split(" ")[1] || "",
            lp: 0,
            rank_icon_url: state.live.rank_icon_url || DEFAULT_TIER_ICON,
            tag: "Active Session",
            status: state.live.status || "PLAYABLE",
            games_played: 0,
            winrate: 0
        };
    }

    const regularAccounts = activeAcc && activeAcc.id
        ? state.accounts.filter(a => a.id !== activeAcc.id && (a.username || '').toLowerCase() !== (activeAcc.username || '').toLowerCase())
        : state.accounts;

    let html = "";
    if (activeAcc) {
        // id 0 means this session has no stored record at all (it was deleted,
        // or Riot reports it banned so it was never auto-added). The card still
        // shows the session, but with actions that can actually do something.
        html += renderHeroAccountCard(activeAcc, activeIsBanned, !activeAcc.id);
    }

    html += regularAccounts.map((acc, i) => {
        const v = buildAccountView(acc);
        const peakBadge = buildPeakBadge(acc);
        const animIndex = (activeAcc ? 1 : 0) + i;

        return `
            <div class="account-card ${acc.favorite ? 'is-favorite' : ''} ${v.cardFlags}" data-id="${acc.id}" style="--i:${Math.min(animIndex, 24)}">
                <!-- Header -->
                <div class="card-header">
                    <div class="card-badges">
                        <span class="badge-region">${escapeHtml(acc.region || 'NA')}</span>
                        <span class="badge-tag ${v.tagClass}">${escapeHtml(v.effectiveTag)}</span>
                        ${v.statusBadge}
                        ${v.liveBadge}
                    </div>
                    <button class="card-favorite-btn ${acc.favorite ? 'active' : ''}" onclick="toggleFavorite(${acc.id})" title="Pin Account">
                        <i class="fa-${acc.favorite ? 'solid' : 'regular'} fa-star"></i>
                    </button>
                </div>

                <!-- Profile Info & Official Emblem -->
                <div class="card-profile">
                    <div class="rank-emblem-wrap ${v.tierClass}" title="Current Rank: ${v.rankTitle}">
                        <img src="${v.rankIconSrc}" alt="${v.rankTitle}" class="rank-emblem-img" onerror="this.onerror=null; this.src='${DEFAULT_TIER_ICON}';">
                        <span class="level-bubble">LV ${acc.level || "-"}</span>
                    </div>
                    <div class="profile-info">
                        <div class="summoner-name-row">
                            <span class="summoner-name" title="${escapeHtml(v.displayName)}">${escapeHtml(v.displayName)}</span>
                            ${acc.display_name ? `
                                <button class="btn-mini-copy" onclick="copyText('${escapeHtml(acc.display_name)}', 'Riot ID copied')" title="Copy Riot ID">
                                    <i class="fa-regular fa-copy"></i>
                                </button>
                            ` : ''}
                        </div>
                        <span class="rank-tier-title ${v.rankInfo.colorClass}">${v.rankTitle}</span>
                        ${peakBadge}
                        ${acc.notes ? `<p class="account-notes" title="${escapeHtml(acc.notes)}"><i class="fa-solid fa-note-sticky"></i> ${escapeHtml(acc.notes)}</p>` : ''}
                    </div>
                </div>

                <!-- Winrate & Matches -->
                <div class="card-stats-row">
                    <div class="winrate-meta">
                        <span>Winrate <strong>${v.winrate}%</strong></span>
                        <span>Matches <strong>${acc.games_played || 0}</strong></span>
                    </div>
                    <div class="winrate-bar-track">
                        <div class="winrate-bar-fill ${v.wrClass}" style="width: ${v.winrate}%;"></div>
                    </div>
                </div>

                <!-- Credentials (Masked) -->
                <div class="credentials-box">
                    <div class="cred-row">
                        <span class="cred-label"><i class="fa-solid fa-user"></i> User</span>
                        <span class="cred-val-wrap">
                            <span class="cred-text">${escapeHtml(acc.username)}</span>
                            <button class="btn-mini-copy" onclick="copyText('${escapeHtml(acc.username)}', 'Username copied')" title="Copy Username">
                                <i class="fa-regular fa-copy"></i>
                            </button>
                        </span>
                    </div>
                    <div class="cred-row">
                        <span class="cred-label"><i class="fa-solid fa-key"></i> Pass</span>
                        <span class="cred-val-wrap">
                            <span class="masked" id="pass-mask-${acc.id}">••••••••</span>
                            <button class="btn-mini-copy" onclick="togglePasswordVisibility(${acc.id}, '${escapeHtml(acc.password)}')" title="Toggle View">
                                <i class="fa-regular fa-eye" id="eye-icon-${acc.id}"></i>
                            </button>
                            <button class="btn-mini-copy" onclick="copyText('${escapeHtml(acc.password)}', 'Password copied')" title="Copy Password">
                                <i class="fa-regular fa-copy"></i>
                            </button>
                        </span>
                    </div>
                </div>

                <!-- Last Logged In -->
                <div class="card-last-login">
                    <span class="last-login-label"><i class="fa-regular fa-clock"></i> Last Logged In:</span>
                    ${v.lastLoginFormatted}
                </div>

                <!-- Verify prompt for accounts Riot hasn't confirmed yet -->
                ${v.needsCheck ? `
                    <button class="btn-check-card" id="btn-check-${acc.id}" onclick="checkAccount(${acc.id})" title="Log in once to confirm the username and password work, and pull the real Riot ID, level and rank">
                        <i class="fa-solid fa-shield-halved"></i>
                        <span class="check-card-label">Check Account</span>
                        <span class="check-card-hint">Not verified yet</span>
                    </button>
                ` : ''}

                <!-- Actions Footer -->
                <div class="card-actions">
                    ${v.isActive ? `
                        <button class="btn-launch-card is-play" onclick="playAccount(${acc.id})" title="Launch VALORANT on this account">
                            <i class="fa-solid fa-play"></i> PLAY
                        </button>
                    ` : `
                        <button class="btn-launch-card" onclick="launchAccount(${acc.id})" title="Auto-fill login into Riot Client">
                            <i class="fa-solid fa-arrow-right-to-bracket"></i> LOGIN
                        </button>
                    `}
                    <div class="card-btn-group">
                        ${v.isActive ? `
                            <button class="btn btn-icon btn-sm is-live" onclick="openDashboard()" title="Open the live match dashboard">
                                <i class="fa-solid fa-gauge-high"></i>
                            </button>
                        ` : ''}
                        <button class="btn btn-icon btn-sm" onclick="openMatchesModal(${acc.id})" title="View Match History & Live Rank Details">
                            <i class="fa-solid fa-clock-rotate-left"></i>
                        </button>
                        <button class="btn btn-icon btn-sm" onclick="openEditModal(${acc.id})" title="Edit Account">
                            <i class="fa-solid fa-pen"></i>
                        </button>
                        <button class="btn btn-icon btn-sm is-danger" onclick="deleteAccount(${acc.id})" title="Delete Account">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join("");

    DOM.accountsGrid.innerHTML = html;
}

function renderTableView() {
    const activeAcc = state.activeAccountId ? state.accounts.find(a => a.id === state.activeAccountId) : null;
    const sorted = activeAcc
        ? [activeAcc, ...state.accounts.filter(a => a.id !== state.activeAccountId)]
        : state.accounts;

    DOM.accountsTableBody.innerHTML = sorted.map((acc, i) => {
        const v = buildAccountView(acc);

        return `
            <tr class="${v.cardFlags}" data-id="${acc.id}" style="--i:${Math.min(i, 30)}">
                <td class="text-center">
                    <button class="card-favorite-btn ${acc.favorite ? 'active' : ''}" onclick="toggleFavorite(${acc.id})" title="Pin Account">
                        <i class="fa-${acc.favorite ? 'solid' : 'regular'} fa-star"></i>
                    </button>
                </td>
                <td>${v.statusBadge}${v.liveBadge}</td>
                <td>
                    <div class="table-summoner">
                        <span class="table-name">${escapeHtml(v.displayName)}</span>
                        ${acc.display_name ? `<span class="table-sub">${escapeHtml(acc.username)}</span>` : ''}
                    </div>
                </td>
                <td>
                    <span class="table-cred">
                        ${escapeHtml(acc.username)}
                        <button class="btn-mini-copy" onclick="copyText('${escapeHtml(acc.username)}', 'Username copied')" title="Copy Username">
                            <i class="fa-regular fa-copy"></i>
                        </button>
                    </span>
                </td>
                <td>
                    <span class="table-cred">
                        <span class="masked" id="pass-mask-${acc.id}">••••••••</span>
                        <button class="btn-mini-copy" onclick="togglePasswordVisibility(${acc.id}, '${escapeHtml(acc.password)}')" title="Toggle View">
                            <i class="fa-regular fa-eye" id="eye-icon-${acc.id}"></i>
                        </button>
                        <button class="btn-mini-copy" onclick="copyText('${escapeHtml(acc.password)}', 'Password copied')" title="Copy Password">
                            <i class="fa-regular fa-copy"></i>
                        </button>
                    </span>
                </td>
                <td><span class="badge-region">${escapeHtml(acc.region || 'NA')}</span></td>
                <td>
                    <div class="table-rank-cell">
                        <img src="${v.rankIconSrc}" class="table-rank-icon" alt="${v.rankTitle}" onerror="this.onerror=null; this.src='${DEFAULT_TIER_ICON}';">
                        <span class="${v.rankInfo.colorClass}"><strong>${v.rankTitle}</strong></span>
                    </div>
                </td>
                <td>
                    ${acc.peak_rank_tier ? `
                        <div class="table-rank-cell">
                            ${v.peakIconSrc ? `<img src="${v.peakIconSrc}" class="table-rank-icon" alt="Peak" onerror="this.style.display='none';">` : '<i class="fa-solid fa-trophy text-gold"></i>'}
                            <span class="text-gold"><strong>${escapeHtml(acc.peak_rank_tier)} ${escapeHtml(acc.peak_rank_division || '')}</strong></span>
                        </div>
                    ` : '<span class="text-dim">---</span>'}
                </td>
                <td><span class="level-chip">LV ${acc.level || "-"}</span></td>
                <td>${v.winrate}% <span class="text-dim">(${acc.games_played || 0}G)</span></td>
                <td><span class="badge-tag ${v.tagClass}">${escapeHtml(v.effectiveTag)}</span></td>
                <td>${v.lastLoginFormatted}</td>
                <td>
                    <div class="table-actions">
                        ${v.isActive ? `
                            <button class="btn btn-play btn-sm" onclick="playAccount(${acc.id})" title="Launch VALORANT on this account">
                                <i class="fa-solid fa-play"></i> PLAY
                            </button>
                            <button class="btn btn-icon btn-sm is-live" onclick="openDashboard()" title="Live match dashboard"><i class="fa-solid fa-gauge-high"></i></button>
                        ` : `
                            <button class="btn btn-primary btn-sm" onclick="launchAccount(${acc.id})" title="Auto-fill login into Riot Client">
                                <i class="fa-solid fa-arrow-right-to-bracket"></i> LOGIN
                            </button>
                        `}
                        ${v.needsCheck ? `
                            <button class="btn btn-icon btn-sm is-warning" id="btn-check-${acc.id}" onclick="checkAccount(${acc.id})" title="Check Account - verify the credentials and pull live data"><i class="fa-solid fa-shield-halved"></i></button>
                        ` : ''}
                        <button class="btn btn-icon btn-sm" onclick="openMatchesModal(${acc.id})" title="Recent Matches"><i class="fa-solid fa-clock-rotate-left"></i></button>
                        <button class="btn btn-icon btn-sm" onclick="openEditModal(${acc.id})" title="Edit Account"><i class="fa-solid fa-pen"></i></button>
                        <button class="btn btn-icon btn-sm is-danger" onclick="deleteAccount(${acc.id})" title="Delete Account"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}

function setViewMode(mode) {
    state.viewMode = mode;
    DOM.viewGridBtn.classList.toggle("active", mode === "grid");
    DOM.viewTableBtn.classList.toggle("active", mode === "table");
    if (DOM.viewSwitcher) DOM.viewSwitcher.dataset.view = mode;
    renderAccounts();
}

function formatRankTitle(acc) {
    const tier = (acc.rank_tier || "UNRANKED").toUpperCase();
    if (tier === "UNRANKED") return "Unranked";
    let str = tier.charAt(0) + tier.slice(1).toLowerCase();
    if (acc.rank_division) str += ` ${acc.rank_division}`;
    if (acc.lp !== undefined && acc.lp !== null && acc.lp > 0) str += ` (${acc.lp} RR)`;
    return str;
}

function getTagBadgeClass(tag, level) {
    if (tag) {
        const lower = tag.toLowerCase();
        if (lower === "main") return "tag-main";
        if (lower === "alt") return "tag-alt";
        if (lower === "ranked") return "tag-ranked";
        if (lower === "unrated") return "tag-unrated";
    }
    if (level && level >= 20) return "tag-ranked";
    return "tag-unrated";
}

// ==========================================================================
// MATCH HISTORY MODAL
// ==========================================================================

async function openMatchesModal(id) {
    state.activeMatchAccId = id;
    const acc = state.accounts.find(a => a.id === id);
    if (!acc) return;

    DOM.matchModalRiotId.textContent = acc.display_name || acc.username;
    DOM.matchModalRankImg.src = acc.rank_icon_url || DEFAULT_TIER_ICON;
    DOM.matchMetaCurrent.textContent = formatRankTitle(acc);
    DOM.matchMetaPeak.textContent = acc.peak_rank_tier ? `${acc.peak_rank_tier} ${acc.peak_rank_division || ''}` : 'None';
    
    if (acc.peak_rank_icon_url && DOM.matchMetaPeakImg) {
        DOM.matchMetaPeakImg.src = acc.peak_rank_icon_url;
        DOM.matchMetaPeakImg.style.display = "inline-block";
    } else if (DOM.matchMetaPeakImg) {
        DOM.matchMetaPeakImg.style.display = "none";
    }

    DOM.matchMetaWinrate.textContent = `${acc.winrate || 0}%`;

    DOM.matchesListContainer.innerHTML = '<div class="no-matches-msg"><i class="fa-solid fa-spinner rotating"></i> Loading match history from Riot servers...</div>';
    openModal(DOM.modalMatches);

    try {
        const res = await fetch(`/api/accounts/${id}/matches`);
        const data = await res.json();
        const matches = data.matches || [];
        state.currentAccountMatches = matches;
        renderMatchHistoryList(matches);
    } catch (err) {
        DOM.matchesListContainer.innerHTML = '<div class="no-matches-msg">Failed to load match history.</div>';
    }
}

function renderMatchHistoryList(matches) {
    if (!matches || matches.length === 0) {
        DOM.matchesListContainer.innerHTML = `
            <div class="no-matches-msg">
                <i class="fa-solid fa-shield-halved" style="font-size: 28px; margin-bottom: 8px; color: var(--accent-purple);"></i>
                <p>No recent match data available for this account.</p>
                <p style="font-size: 12px; color: var(--text-dim);">Play a game or check if your Riot ID is correct.</p>
            </div>
        `;
        return;
    }

    DOM.matchesListContainer.innerHTML = matches.map((m, i) => {
        const outcome = (m.outcome || "VICTORY").toUpperCase();
        const outcomeClass = outcome === "VICTORY" ? "outcome-victory" : (outcome === "DEFEAT" ? "outcome-defeat" : "outcome-draw");
        const agentIcon = m.agent_icon || "https://media.valorant-api.com/agents";

        return `
            <button class="match-card ${outcomeClass}" style="--i:${i}" type="button" onclick="openMatchDetail(${i}, 'account')" title="Open full match details">
                <!-- Agent Section -->
                <div class="match-agent-section">
                    <img src="${agentIcon}" alt="${m.agent || 'Agent'}" class="match-agent-avatar" onerror="this.src='https://media.valorant-api.com/agents';">
                    <div class="match-agent-info">
                        <h4>${escapeHtml(m.agent || 'Agent')}</h4>
                        <span class="match-mode-label">${escapeHtml(m.mode || 'Competitive')}</span>
                    </div>
                </div>

                <!-- Map Section -->
                <div class="match-map-section">
                    <span class="match-map-name">${escapeHtml(m.map || 'Ascent')}</span>
                    <span class="match-date-label">${escapeHtml(m.game_date || 'Recent')}</span>
                </div>

                <!-- Score Section -->
                <div class="match-score-section">
                    <span class="match-outcome-badge">${outcome}</span>
                    <span class="match-rounds-score">${m.rounds_won || 0} : ${m.rounds_lost || 0}</span>
                </div>

                <!-- Stats Section -->
                <div class="match-stats-section">
                    <div class="stat-box">
                        <span class="stat-box-label">K / D / A</span>
                        <span class="stat-box-val">${m.kills || 0} / ${m.deaths || 0} / ${m.assists || 0}</span>
                    </div>
                    <div class="stat-box">
                        <span class="stat-box-label">KD Ratio</span>
                        <span class="stat-box-val" style="color: ${m.kdr >= 1.0 ? '#10b981' : '#ef4444'};">${m.kdr || 0}</span>
                    </div>
                    <div class="stat-box">
                        <span class="stat-box-label">Headshot</span>
                        <span class="stat-box-val">${m.hs_pct || 0}%</span>
                    </div>
                </div>
            </button>
        `;
    }).join("");
}

function profileStatsHtml(profile) {
    const current = [profile.rank_tier, profile.rank_division].filter(Boolean).join(" ") || "Unranked";
    const peak = [profile.peak_rank_tier, profile.peak_rank_division].filter(Boolean).join(" ") || "No recorded peak";
    const matches = profile.match_history || [];
    const combat = profile.combat || {};
    const combatAvailable = combat.matches_analyzed || combat.last5_games;
    return `
        <div class="profile-summary">
            <div><span>Current rank</span><strong>${escapeHtml(current)}${profile.lp ? ` · ${profile.lp} RR` : ""}</strong></div>
            <div><span>Peak rank</span><strong>${escapeHtml(peak)}</strong></div>
            <div><span>Level</span><strong>${profile.level || "—"}</strong></div>
            <div><span>Recent win rate</span><strong>${profile.winrate || 0}%</strong></div>
        </div>
        ${combatAvailable ? `<h4 class="detail-section-title"><i class="fa-solid fa-chart-simple"></i> Recent performance</h4>
        <div class="detail-stat-grid">
            <div><span>K/D ratio</span><strong>${combat.kd ?? 0}</strong></div>
            <div><span>K / D / A</span><strong>${combat.kills ?? 0} / ${combat.deaths ?? 0} / ${combat.assists ?? 0}</strong></div>
            <div><span>Headshots</span><strong>${combat.hs_pct ?? 0}%</strong></div>
            <div><span>ADR / ACS</span><strong>${combat.adr ?? 0} / ${combat.acs ?? 0}</strong></div>
        </div>` : ""}
        <h4 class="detail-section-title"><i class="fa-solid fa-clock-rotate-left"></i> Recent matches</h4>
        <div class="detail-history">${matches.length ? matches.map((m, i) => `
            <button type="button" class="detail-history-row ${m.outcome === "VICTORY" ? "is-win" : "is-loss"}" onclick="openMatchDetail(${i}, 'profile')">
                <span>${escapeHtml(m.outcome || "MATCH")}</span><strong>${escapeHtml(m.map || "Unknown map")}</strong>
                <small>${escapeHtml(m.agent || "Agent")} · ${m.kills || 0}/${m.deaths || 0}/${m.assists || 0}</small>
            </button>`).join("") : '<p class="no-matches-msg">No public recent-match data is available for this player.</p>'}</div>`;
}

async function openPlayerProfile(riotId, puuid = "") {
    if ((!riotId || !riotId.includes("#")) && !puuid) {
        showToast("This player has not resolved yet. Refresh the match and try again.", "warning");
        return;
    }
    DOM.detailModalTitle.textContent = riotId && riotId.includes("#") ? riotId : "Loading player…";
    DOM.detailModalSub.textContent = "Loading profile and match history…";
    DOM.matchDetailContent.innerHTML = '<div class="no-matches-msg"><i class="fa-solid fa-spinner rotating"></i> Looking up player data…</div>';
    openModal(DOM.modalMatchDetail);
    try {
        const response = await fetch("/api/players/lookup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ riot_id: riotId || "", puuid: puuid || "" })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Lookup failed");
        state.profileMatches = data.profile.match_history || [];
        DOM.detailModalTitle.textContent = data.riot_id;
        DOM.detailModalSub.textContent = data.identity_hidden
            ? "Identity hidden · live-session rank and combat data"
            : "Player profile · click a match for its full scoreboard";
        DOM.matchDetailContent.innerHTML = profileStatsHtml(data.profile);
    } catch (error) {
        DOM.detailModalSub.textContent = "Player lookup unavailable";
        DOM.matchDetailContent.innerHTML = `<div class="no-matches-msg">${escapeHtml(error.message || "Could not load this player.")}</div>`;
    }
}

function matchTeamScore(m, teamId, teamIndex) {
    const summary = (m.teams || []).find(t => String(t.team || "").toLowerCase() === String(teamId || "").toLowerCase());
    if (summary) return Number(summary.rounds_won || 0);
    const selfTeam = (m.roster || []).find(p => p.is_self)?.team;
    if (selfTeam && String(selfTeam).toLowerCase() === String(teamId).toLowerCase()) return Number(m.rounds_won || 0);
    if (selfTeam) return Number(m.rounds_lost || 0);
    return teamIndex === 0 ? Number(m.rounds_won || 0) : Number(m.rounds_lost || 0);
}

function matchTeamHtml(m, teamId, teamIndex) {
    const players = (m.roster || [])
        .filter(p => String(p.team || "Unassigned").toLowerCase() === String(teamId).toLowerCase())
        .sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
    const summary = (m.teams || []).find(t => String(t.team || "").toLowerCase() === String(teamId).toLowerCase());
    const rounds = matchTeamScore(m, teamId, teamIndex);
    const teamName = /blue/i.test(teamId) ? "Blue Team" : /red/i.test(teamId) ? "Red Team" : `${teamId || `Team ${teamIndex + 1}`}`;
    const result = summary ? (summary.won ? "WIN" : "LOSS") : "TEAM";
    return `
        <section class="detail-team ${summary?.won ? "is-winner" : ""}">
            <div class="detail-team-head">
                <span><i class="fa-solid fa-people-group"></i> ${escapeHtml(teamName)}</span>
                <strong>${rounds} rounds <em>${result}</em></strong>
            </div>
            <div class="detail-score-head"><span>Agent / Riot ID</span><span>K / D / A</span><span>ACS</span><span>Score</span><span>ADR</span><span>HS%</span></div>
            <div class="detail-score-body">${players.map(p => {
                const riotId = p.riot_id && p.riot_id.includes("#") ? p.riot_id : "Riot ID resolving…";
                const clickId = encodeURIComponent(p.riot_id || "");
                const clickPuuid = encodeURIComponent(p.puuid || "");
                return `<button type="button" class="detail-score-player ${p.is_self ? "is-self" : ""}" onclick="openPlayerProfile(decodeURIComponent('${clickId}'), decodeURIComponent('${clickPuuid}'))">
                    <span class="detail-score-identity">${p.agent_icon ? `<img src="${p.agent_icon}" alt="">` : '<i class="fa-solid fa-user"></i>'}<span><strong>${escapeHtml(riotId)}</strong><small>${escapeHtml(p.agent || "Agent")}</small></span></span>
                    <b>${p.kills || 0} / ${p.deaths || 0} / ${p.assists || 0}</b>
                    <b>${p.acs ?? 0}</b><b>${p.score ?? 0}</b><b>${p.adr ?? 0}</b><b>${p.hs_pct ?? 0}%</b>
                </button>`;
            }).join("")}</div>
        </section>`;
}

function openMatchDetail(index, source) {
    const matches = source === "account" ? state.currentAccountMatches : source === "profile" ? state.profileMatches : state.dashboardMatches;
    const m = matches && matches[index];
    if (!m) return;
    const outcome = (m.outcome || m.result || "Match").toUpperCase();
    const roster = m.roster || [];
    const teamIds = [...new Set([
        ...(m.teams || []).map(t => t.team).filter(Boolean),
        ...roster.map(p => p.team || "Unassigned")
    ])];
    DOM.detailModalTitle.textContent = `${m.map || "Unknown map"} · ${outcome}`;
    DOM.detailModalSub.textContent = `${m.mode || "Match"} · ${m.rounds_won ?? 0} : ${m.rounds_lost ?? 0} · ${m.game_date || "Recent"}`;
    DOM.matchDetailContent.innerHTML = `
        <div class="detail-stat-grid">
            <div><span>K / D / A</span><strong>${m.kills || 0} / ${m.deaths || 0} / ${m.assists || 0}</strong></div>
            <div><span>K/D ratio</span><strong>${m.kdr ?? m.kd ?? 0}</strong></div>
            <div><span>Headshots</span><strong>${m.hs_pct ?? m.hs ?? 0}%</strong></div>
            <div><span>${m.adr !== undefined ? "ADR" : "Score"}</span><strong>${m.adr ?? m.score ?? 0}</strong></div>
        </div>
        <h4 class="detail-section-title"><i class="fa-solid fa-table-list"></i> Full scoreboard <small>Click any player to view their profile and match history</small></h4>
        <div class="detail-scoreboard">${roster.length ? teamIds.map((team, i) => matchTeamHtml(m, team, i)).join("") : '<p class="no-matches-msg">Scoreboard data will appear after this history is refreshed.</p>'}</div>
        ${(m.round_results || []).length ? `<h4 class="detail-section-title"><i class="fa-solid fa-timeline"></i> Round results</h4>
        <div class="detail-rounds">${m.round_results.map(r => `<span class="${/blue/i.test(r.winner) ? "is-blue" : "is-red"}" title="${escapeHtml(r.result || "Round")}">${r.round}</span>`).join("")}</div>` : ""}`;
    openModal(DOM.modalMatchDetail);
}

// ==========================================================================
// CLEAN ADD ACCOUNT MODAL
// ==========================================================================

function openAccountModal(acc = null, isBanned = false) {
    DOM.formAccount.reset();
    DOM.formPassword.type = "password";
    DOM.btnToggleFormPassword.innerHTML = '<i class="fa-regular fa-eye"></i>';

    // Which store this record came from decides where the save goes - a
    // banned account is edited through the banned endpoint, not /api/accounts.
    state.editingBanned = !!(acc && isBanned);

    if (acc) {
        DOM.modalAccountTitle.textContent = "Edit Valorant Account";
        DOM.modalAccountIcon.className = "fa-solid fa-user-pen";
        DOM.formAccountId.value = acc.id;
        DOM.formUsername.value = acc.username || "";
        DOM.formPassword.value = acc.password || "";
        DOM.formTag.value = acc.tag || "";
        DOM.formNotes.value = acc.notes || "";
        DOM.formFavorite.checked = !!acc.favorite;
        if (isBanned) {
            DOM.modalAccountTitle.textContent = "Edit Banned Account";
            DOM.modalAccountIcon.className = "fa-solid fa-user-lock";
        }
    } else {
        DOM.modalAccountTitle.textContent = "Add Valorant Account";
        DOM.modalAccountIcon.className = "fa-solid fa-user-plus";
        DOM.formAccountId.value = "";
        DOM.formTag.value = "";
        DOM.formFavorite.checked = false;
    }

    openModal(DOM.modalAccount);
}

function openEditModal(id) {
    const { acc, banned } = resolveAccount(id);
    if (acc) {
        openAccountModal(acc, banned);
        return;
    }
    // The record may have been moved to the banned store since the last fetch
    // (that's exactly what happens the moment a login comes back flagged), so
    // refresh that store once before giving up rather than doing nothing.
    fetchBannedAccounts(true).then(() => {
        const again = resolveAccount(id);
        if (again.acc) openAccountModal(again.acc, again.banned);
        else showToast("That account is no longer stored.", "error");
    });
}

/**
 * Catches the entry mistakes that produce an account which can never log in -
 * a whole "user:pass" combo pasted into one box, an email instead of the Riot
 * username, a stray space, or a duplicate of something already stored.
 * Returns the cleaned credentials, or false after showing the reason.
 */
function validateAccountForm() {
    const showError = (msg) => {
        if (DOM.formValidation) {
            DOM.formValidation.style.display = "block";
            DOM.formValidation.innerHTML =
                `<i class="fa-solid fa-circle-exclamation"></i> ${escapeHtml(msg)}`;
        }
        return false;
    };

    if (DOM.formValidation) DOM.formValidation.style.display = "none";

    let username = DOM.formUsername.value.trim();
    let password = DOM.formPassword.value.trim();

    // A pasted combo lands entirely in the username box - split it instead of
    // saving a username that would never work.
    if (!password && /[:|]/.test(username)) {
        const parts = username.split(/[:|]/).map(s => s.trim()).filter(Boolean);
        if (parts.length >= 2) {
            username = parts[0];
            password = parts.slice(1).join(":");
            DOM.formUsername.value = username;
            DOM.formPassword.value = password;
        }
    }

    if (!username) return showError("Enter the Riot Client login username.");
    if (!password) return showError("Enter the account password.");
    if (/\s/.test(username)) return showError("Riot usernames don't contain spaces - remove the stray space.");
    if (username.includes("@")) {
        return showError("Use the Riot username, not the email address - the Riot Client login won't accept an email.");
    }

    const editingId = String(DOM.formAccountId.value);
    const pool = state.editingBanned ? (state.bannedAccounts || []) : state.accounts;
    const dupe = pool.find(a =>
        (a.username || "").trim().toLowerCase() === username.toLowerCase() &&
        String(a.id) !== editingId
    );
    if (dupe) return showError(`"${username}" is already in your accounts.`);

    return { username, password };
}

async function handleAccountSubmit(e, checkAfterSave = false) {
    e.preventDefault();
    const id = DOM.formAccountId.value;
    const isEdit = !!id;

    const creds = validateAccountForm();
    if (!creds) return;

    const payload = {
        username: creds.username,
        password: creds.password,
        tag: DOM.formTag.value,
        notes: DOM.formNotes.value.trim(),
        favorite: DOM.formFavorite.checked
    };

    const editingBanned = isEdit && state.editingBanned;

    try {
        let res;
        if (editingBanned) {
            res = await fetch(`/api/banned-accounts/${id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } else if (isEdit) {
            res = await fetch(`/api/accounts/${id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } else {
            res = await fetch("/api/accounts", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        }

        const data = await res.json();
        if (data.success) {
            const savedId = (data.account && data.account.id) || Number(id) || null;

            if (data.moved_to_banned) {
                showToast("Account is banned/suspended - moved to Banned Accounts.", "warning");
                fetchBannedAccounts();
            } else if (data.restored_from_banned) {
                showToast(`${creds.username} moved back to your accounts.`, "success");
            } else {
                showToast(
                    isEdit
                        ? `Updated ${creds.username}`
                        : `Added ${creds.username} - check it to confirm the login works.`,
                    "success"
                );
            }

            state.editingBanned = false;
            closeModal(DOM.modalAccount);
            await fetchAccounts();
            await fetchBannedAccounts(true);
            fetchStatsSummary();

            // Point straight at the row that just changed, so it's obvious
            // which account this was.
            const stillBanned = editingBanned && !data.restored_from_banned;
            if (savedId && !data.moved_to_banned && !stillBanned) {
                highlightAccount(savedId);
                if (checkAfterSave) checkAccount(savedId);
            }
        } else if (data.duplicate) {
            // Already stored (active or banned) - keep the modal open so the
            // entry isn't lost and the user can correct the username.
            showToast(data.message || "That account is already added.", "info");
        } else {
            showToast(data.message || "Failed to save account", "error");
        }
    } catch (err) {
        showToast("Server communication error", "error");
    }
}

async function deleteAccount(id) {
    const { acc, banned } = resolveAccount(id);
    const name = acc ? (acc.display_name || acc.username) : "this account";
    if (!confirm(`Delete ${name}?`)) return;

    const url = banned ? `/api/banned-accounts/${id}` : `/api/accounts/${id}`;
    try {
        const res = await fetch(url, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("Account deleted", "info");
            fetchAccounts();
            fetchBannedAccounts(true);
            fetchStatsSummary();
        }
    } catch (err) {
        showToast("Failed to delete account", "error");
    }
}

/** Puts a banned account back on the main roster without waiting on a recheck. */
async function restoreBannedAccount(id) {
    try {
        const res = await fetch(`/api/banned-accounts/${id}/restore`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Moved back to your accounts", "success");
            await fetchAccounts();
            await fetchBannedAccounts(true);
            fetchStatsSummary();
            scheduleLivePoll(0);
        } else {
            showToast(data.message || "Could not restore that account", "error");
        }
    } catch (err) {
        showToast("Could not restore that account", "error");
    }
}

function sortAccountsList(accounts, sortBy) {
    const tierRanks = {
        "RADIANT": 1, "IMMORTAL": 2, "ASCENDANT": 3, "DIAMOND": 4,
        "PLATINUM": 5, "GOLD": 6, "SILVER": 7, "BRONZE": 8, "IRON": 9, "UNRANKED": 10
    };
    return [...accounts].sort((a, b) => {
        const favA = a.favorite ? 1 : 0;
        const favB = b.favorite ? 1 : 0;
        if (favB !== favA) return favB - favA;

        if (sortBy === "rank") {
            const rA = tierRanks[(a.rank_tier || "UNRANKED").toUpperCase()] || 10;
            const rB = tierRanks[(b.rank_tier || "UNRANKED").toUpperCase()] || 10;
            if (rA !== rB) return rA - rB;
            return (b.lp || 0) - (a.lp || 0);
        } else if (sortBy === "winrate") {
            return (Number(b.winrate) || 0) - (Number(a.winrate) || 0);
        } else if (sortBy === "name") {
            return (a.username || "").localeCompare(b.username || "", undefined, { sensitivity: "base" });
        } else if (sortBy === "last_updated") {
            return (b.last_updated || "").localeCompare(a.last_updated || "");
        } else {
            return (b.level || 0) - (a.level || 0);
        }
    });
}

async function toggleFavorite(id) {
    const acc = state.accounts.find(a => a.id === id);
    if (!acc) return;

    const newFav = !acc.favorite;
    acc.favorite = newFav;

    // 1. Immediately toggle the button and class in the DOM
    const cards = document.querySelectorAll(`[data-id="${id}"]`);
    cards.forEach(card => {
        card.classList.toggle("is-favorite", newFav);
        const starBtn = card.querySelector(".card-favorite-btn");
        if (starBtn) {
            starBtn.classList.toggle("active", newFav);
            const icon = starBtn.querySelector("i");
            if (icon) {
                icon.className = `fa-${newFav ? 'solid' : 'regular'} fa-star`;
            }
        }
    });

    // 2. Re-sort the accounts list in memory
    state.accounts = sortAccountsList(state.accounts, state.currentSort);

    // 3. Move the DOM element directly without full section re-render
    if (state.currentTag === "FAVORITES" && !newFav) {
        cards.forEach(card => {
            card.style.transition = "opacity 0.25s ease, transform 0.25s ease";
            card.style.opacity = "0";
            card.style.transform = "scale(0.95)";
            setTimeout(() => card.remove(), 260);
        });
        state.accounts = state.accounts.filter(a => a.id !== id);
    } else {
        const activeAcc = state.activeAccountId ? state.accounts.find(a => a.id === state.activeAccountId) : null;
        const regularAccounts = activeAcc ? state.accounts.filter(a => a.id !== state.activeAccountId) : state.accounts;
        const newIndex = regularAccounts.findIndex(a => a.id === id);

        if (state.viewMode === "grid" && DOM.accountsGrid) {
            const cardEl = DOM.accountsGrid.querySelector(`.account-card[data-id="${id}"]:not(.account-card-hero)`);
            if (cardEl && newIndex !== -1) {
                const existingCards = Array.from(DOM.accountsGrid.querySelectorAll(`.account-card:not(.account-card-hero)`));
                const targetSibling = existingCards.filter(c => c !== cardEl)[newIndex];
                if (targetSibling) {
                    DOM.accountsGrid.insertBefore(cardEl, targetSibling);
                } else {
                    DOM.accountsGrid.appendChild(cardEl);
                }
            }
        } else if (state.viewMode === "table" && DOM.accountsTableBody) {
            const rowEl = DOM.accountsTableBody.querySelector(`tr[data-id="${id}"]`);
            if (rowEl && newIndex !== -1) {
                const existingRows = Array.from(DOM.accountsTableBody.querySelectorAll(`tr`));
                const targetSibling = existingRows.filter(r => r !== rowEl)[newIndex];
                if (targetSibling) {
                    DOM.accountsTableBody.insertBefore(rowEl, targetSibling);
                } else {
                    DOM.accountsTableBody.appendChild(rowEl);
                }
            }
        }
    }

    state._lastAccountsSignature = accountsSignature(state.accounts);

    try {
        await fetch(`/api/accounts/${id}/toggle-favorite`, { method: "POST" });
    } catch (err) {
        showToast("Failed to update pin", "error");
    }
}

// ==========================================================================
// STATS & AUTO-LOGIN
// ==========================================================================

async function refreshAccountStats(id) {
    const btn = document.getElementById(`btn-refresh-${id}`);
    if (btn) btn.querySelector("i").classList.add("rotating");

    try {
        const res = await fetch(`/api/accounts/${id}/refresh`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            if (data.moved_to_banned) {
                showToast(data.message || "Account is banned - moved to Banned Accounts", "warning");
                fetchBannedAccounts();
            } else {
                showToast("Level, Rank & Stats synced live", "success");
            }
            fetchAccounts();
            fetchStatsSummary();
        } else {
            showToast(data.message || "No stats found", "info");
        }
    } catch (err) {
        showToast("Error updating stats", "error");
    } finally {
        if (btn) btn.querySelector("i").classList.remove("rotating");
    }
}

async function handleSyncAll() {
    if (state.isSyncingAll) return;
    state.isSyncingAll = true;

    DOM.syncAllIcon.classList.add("rotating");
    DOM.syncProgressBar.style.display = "block";
    DOM.syncProgressFill.style.width = "45%";
    DOM.syncProgressText.textContent = "Connecting to Riot servers...";

    try {
        DOM.syncProgressFill.style.width = "80%";
        const res = await fetch("/api/accounts/refresh-all", { method: "POST" });
        const data = await res.json();

        DOM.syncProgressFill.style.width = "100%";
        DOM.syncProgressText.textContent = `Synced ${data.refreshed_count || 0} accounts`;

        showToast(`Synced ${data.refreshed_count || 0} accounts`, "success");
        fetchAccounts();
        fetchStatsSummary();
        fetchBannedAccounts();
    } catch (err) {
        showToast("Batch sync error", "error");
    } finally {
        setTimeout(() => {
            DOM.syncProgressBar.style.display = "none";
            DOM.syncProgressFill.style.width = "0%";
            DOM.syncAllIcon.classList.remove("rotating");
            state.isSyncingAll = false;
        }, 1500);
    }
}

const LAUNCH_STAGE_ORDER = ["opening", "signout", "waiting_window", "typing", "submitted"];

const LAUNCH_STATUS_LABEL = {
    done: "Ready",
    error: "Failed",
};

function renderLaunchProgress(prog) {
    const sub = document.getElementById("launch-modal-sub");
    const anim = document.getElementById("launch-anim");
    const icon = document.getElementById("launch-anim-icon");
    const steps = document.querySelectorAll("#launch-steps li");
    if (!sub || !anim) return;

    const stage = prog.stage || "opening";
    sub.textContent = prog.message || "Working…";

    anim.classList.toggle("is-done", stage === "done");
    anim.classList.toggle("is-error", stage === "error");
    if (icon) {
        icon.className = "launch-anim-icon fa-solid " + (
            stage === "done" ? "fa-check" :
            stage === "error" ? "fa-triangle-exclamation" :
            "fa-arrow-right-to-bracket"
        );
    }

    // Status pill: a plain-language "where are we" that doesn't require
    // reading the step list - Working / Ready / Failed.
    if (DOM.launchStatusPill) {
        DOM.launchStatusPill.textContent = LAUNCH_STATUS_LABEL[stage] || "Working";
        DOM.launchStatusPill.classList.toggle("is-done", stage === "done");
        DOM.launchStatusPill.classList.toggle("is-error", stage === "error");
    }

    // Retry only makes sense once something has actually failed.
    if (DOM.btnRetryLaunch) DOM.btnRetryLaunch.style.display = stage === "error" ? "inline-flex" : "none";
    if (DOM.btnCloseLaunch) {
        DOM.btnCloseLaunch.textContent = stage === "done" ? "Done" : (stage === "error" ? "Close" : "Run in background");
    }
    if (DOM.launchBgHint) {
        DOM.launchBgHint.style.display = (stage === "done" || stage === "error") ? "none" : "block";
    }

    const idx = LAUNCH_STAGE_ORDER.indexOf(stage);
    steps.forEach(li => {
        const sIdx = LAUNCH_STAGE_ORDER.indexOf(li.dataset.stage);
        li.classList.remove("active", "done");
        if (stage === "done") {
            li.classList.add("done");
        } else if (stage === "error") {
            if (idx >= 0 && sIdx < idx) li.classList.add("done");
        } else if (idx >= 0) {
            if (sIdx < idx) li.classList.add("done");
            else if (sIdx === idx) li.classList.add("active");
        }
    });
}

function stopLaunchPolling() {
    if (state._launchPoll) {
        clearInterval(state._launchPoll);
        state._launchPoll = null;
    }
}

/**
 * Drives the login progress animation from the backend's live stage feed.
 * Shared by LOGIN, PLAY (when it has to switch account first) and Check
 * Account, so all three show the same steps.
 */
function startLaunchPolling(options = {}) {
    stopLaunchPolling();
    let settleTimer = null;

    state._launchPoll = setInterval(async () => {
        try {
            const p = await (await fetch("/api/login-progress")).json();
            if (p.username && state.activeLaunchAcc &&
                p.username.toLowerCase() !== state.activeLaunchAcc.username.toLowerCase()) {
                return; // a different login took over
            }
            renderLaunchProgress(p);

            if (p.stage === "done" || p.stage === "error") {
                stopLaunchPolling();
                showToast(
                    p.message || (p.stage === "done" ? "Logged in" : "Login failed"),
                    p.stage === "done" ? "success" : "error"
                );

                // Riot's checkbox can't be read back, so the only honest signal
                // is whether it left a persisted login behind. Say so when it
                // didn't, rather than letting the next launch surprise the user
                // with a password prompt.
                if (p.stage === "done" && p.stay_signed_in === false) {
                    setTimeout(() => showToast(
                        "Signed in, but Riot didn't keep the session - you'll be asked for the password next time. " +
                        "Tick \"Stay signed in\" yourself on the next login, or turn the option off in Settings.",
                        "warning"
                    ), 900);
                }

                if (!settleTimer) {
                    settleTimer = setTimeout(() => {
                        fetchAccounts();
                        fetchStatsSummary();
                        scheduleLivePoll(0);
                    }, 1500);
                }

                // Signing in is exactly when the live dashboard becomes
                // useful, so it opens itself once the session is up.
                if (p.stage === "done" && options.openDashboardWhenDone) {
                    setTimeout(() => {
                        closeModal(DOM.modalLaunch);
                        openDashboard();
                    }, 1800);
                }
            }
        } catch (e) { /* keep polling */ }
    }, 700);
}

/** The launch modal is reused for login, play-switch and account checks. */
function setLaunchModalTitle(text) {
    const el = document.getElementById("launch-modal-title");
    if (el) el.textContent = text;
}

async function launchAccount(id, inPlace = false) {
    const acc = state.accounts.find(a => a.id === id);
    if (!acc) return;

    state.activeLaunchAcc = acc;
    // Retry goes back into the sign-in page that's already open rather than
    // restarting the client. Restarting closed the window the user was
    // watching and began the whole wait again, which is why retrying looked
    // like it never retried.
    state._launchRetry = () => launchAccount(id, true);
    DOM.launchUserVal.textContent = acc.username;
    setLaunchModalTitle("Logging In to Riot Client");
    renderLaunchProgress({
        stage: "opening",
        message: inPlace ? "Retrying in the open Riot Client…" : "Starting…"
    });
    openModal(DOM.modalLaunch);

    // Fire the login (backend spawns its own worker thread and returns fast).
    fetch(`/api/accounts/${id}/launch${inPlace ? "?in_place=true" : ""}`, { method: "POST" })
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                showToast(data.message || "Could not start login", "info");
                renderLaunchProgress({ stage: "error", message: data.message || "Could not start login." });
            }
        })
        .catch(() => {
            showToast("Failed to open Riot Client", "error");
            renderLaunchProgress({ stage: "error", message: "Failed to reach the app's backend." });
        });

    startLaunchPolling({ openDashboardWhenDone: true });

    // Safety: refresh account list a few seconds in regardless.
    setTimeout(() => { fetchAccounts(); fetchStatsSummary(); }, 6000);
}

function openTrackerUrl(displayName) {
    const clean = displayName.replace("#", "%23");
    const url = `https://tracker.gg/valorant/profile/riot/${clean}/overview`;
    window.open(url, "_blank");
}

// ==========================================================================
// SETTINGS & BACKUP
// ==========================================================================

/**
 * Same modifier+key grammar the backend's parse_hotkey() enforces
 * (backend/overlay_hotkey.py) - kept in sync by hand since it's a small,
 * stable rule set. Used only for instant feedback here; the backend is what
 * actually decides whether a combination can be registered.
 */
function validateOverlayHotkey(spec) {
    const trimmed = (spec || "").trim();
    if (!trimmed) return "Enter a key combination, e.g. CTRL+SHIFT+F8.";
    const parts = trimmed.toUpperCase().split(/[+\s]+/).filter(Boolean);
    const mods = new Set(["CTRL", "CONTROL", "SHIFT", "ALT", "WIN", "WINDOWS", "META", "SUPER"]);
    const named = new Set([
        "SPACE", "TAB", "ESC", "ESCAPE", "ENTER", "RETURN", "BACKSPACE",
        "INSERT", "DELETE", "DEL", "HOME", "END", "PAGEUP", "PAGEDOWN",
        "UP", "DOWN", "LEFT", "RIGHT", "PRINTSCREEN", "PAUSE"
    ]);
    for (let n = 1; n <= 24; n++) named.add(`F${n}`);

    let hasModifier = false, key = null;
    for (const part of parts) {
        if (mods.has(part)) { hasModifier = true; continue; }
        if (key !== null) return `"${part}" isn't a modifier and a key was already given.`;
        key = part;
    }
    if (key === null) return "Add a key after the modifiers, e.g. CTRL+SHIFT+F8.";
    if (!hasModifier) return "Add at least one modifier (CTRL, ALT, SHIFT or WIN) so this doesn't fire on plain typing.";
    if (!(named.has(key) || (key.length === 1 && /^[A-Z0-9]$/.test(key)))) {
        return `"${key}" isn't a key this can bind - use a letter, digit, or F1-F24.`;
    }
    return null;
}

function renderOverlayHotkeyValidity() {
    if (!DOM.settingsOverlayHotkey || !DOM.overlayHotkeyHelp) return;
    const problem = validateOverlayHotkey(DOM.settingsOverlayHotkey.value);
    DOM.settingsOverlayHotkey.classList.toggle("is-invalid", !!problem);
    DOM.overlayHotkeyHelp.textContent = problem ||
        "One or more of CTRL / ALT / SHIFT / WIN, plus a letter, digit, or F1-F24. Applies on next launch.";
    DOM.overlayHotkeyHelp.classList.toggle("is-error", !!problem);
    return !problem;
}

function openSettingsModal() {
    DOM.settingsClientPath.value = state.settings.riot_client_path || "";
    DOM.settingsApiKey.value = state.settings.riot_api_key || "";
    if (DOM.settingsOverlayEnabled) DOM.settingsOverlayEnabled.checked = (state.settings.overlay_enabled || "1") !== "0";
    if (DOM.settingsOverlayHotkey) DOM.settingsOverlayHotkey.value = state.settings.overlay_hotkey || "CTRL+SHIFT+F8";
    renderOverlayHotkeyValidity();
    if (DOM.settingsAppVersion) {
        DOM.settingsAppVersion.value = state.appVersion ? `v${state.appVersion}` : "Loading...";
    }
    loadLoginLogPath();
    loadGameConfigSettings();
    openModal(DOM.modalSettings);
}

// -- launch display mode + settings profile -------------------------------

async function loadGameConfigSettings() {
    if (DOM.settingsProfileStatus) DOM.settingsProfileStatus.textContent = "";
    try {
        const res = await fetch("/api/game-config/settings");
        const data = await res.json();
        state.gameConfig = data;

        if (DOM.settingsForceBorderless) DOM.settingsForceBorderless.checked = !!data.force_borderless;
        if (DOM.settingsStaySignedIn) DOM.settingsStaySignedIn.checked = !!data.stay_signed_in;
        if (DOM.settingsAutoLaunch) DOM.settingsAutoLaunch.checked = !!data.auto_launch_after_login;
        if (DOM.settingsProfileAutoapply) DOM.settingsProfileAutoapply.checked = !!data.autoapply;

        const accounts = data.accounts || [];
        const ready = accounts.filter(a => a.has_config);

        fillAccountSelect(DOM.settingsProfileAccount, accounts, data.profile_account_id,
            "No profile account selected");
        fillAccountSelect(DOM.settingsCopyTarget, accounts, null,
            "Copy to: whoever's signed in now");

        renderProfileStatus(data, accounts, ready);
    } catch (err) {
        state.gameConfig = null;
    }
    loadPreset();
}

/**
 * Spells out what the profile actually holds and how many accounts can take
 * a copy right now. Accounts become usable on their own: signing into one
 * with Vortex open records its Riot id, and playing one match on this PC
 * creates the settings folder a copy reads from and writes to.
 */
function renderProfileStatus(data, accounts, ready) {
    const el = DOM.settingsProfileStatus;
    if (!el) return;

    const bits = [];
    const detail = data.profile_detail;
    if (detail && detail.found) {
        const present = (detail.files || []).filter(f => f.present).map(f => f.label);
        bits.push(present.length
            ? `Profile carries: ${present.join(", ")}.`
            : "That profile account has no settings files on this PC yet.");
    }

    const unidentified = accounts.filter(a => !a.has_puuid).length;

    if (!accounts.length) {
        bits.push("No accounts stored yet.");
    } else if (!ready.length) {
        bits.push("No account has VALORANT settings on this PC yet. Sign into one with Vortex open, play a match, and it becomes usable here.");
    } else {
        bits.push(`${ready.length} of ${accounts.length} accounts can send or receive settings.`);
        if (unidentified) {
            bits.push(`${unidentified} still need to be signed into once with Vortex open so it can identify them - "Check Accounts" does all of them in one pass.`);
        }
    }

    el.textContent = bits.join(" ");
}

/**
 * Saves the newly picked profile and re-reads what it holds, so the summary
 * under the picker describes the account actually selected.
 */
async function onProfileAccountChange() {
    const id = parseInt(DOM.settingsProfileAccount?.value || "", 10) || 0;
    try {
        await fetch("/api/game-config/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ profile_account_id: id })
        });
    } catch (err) {
        // A failed save just means the summary stays as it was.
    }
    loadGameConfigSettings();
}

/** Forces windowed borderless on every account that has settings on this PC. */
async function applyBorderlessToAll() {
    const btn = DOM.btnBorderlessAll;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner rotating"></i> Applying...`;
    }
    try {
        const res = await fetch("/api/game-config/force-borderless", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ all_accounts: true })
        });
        const data = await res.json();
        showToast(data.message || (data.success ? "Applied." : "Couldn't apply."),
                  data.success ? "success" : "error");
    } catch (err) {
        showToast("Failed to reach the app's backend.", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> Set every account to borderless now`;
        }
    }
}

/** Copies the profile's whole setup onto every account that can take it. */
async function copySettingsToAll() {
    const profileId = parseInt(DOM.settingsProfileAccount?.value || "", 10);
    if (!profileId) {
        showToast("Pick a profile account to copy from first.", "info");
        return;
    }

    const cfg = state.gameConfig || {};
    const others = (cfg.accounts || []).filter(a => a.id !== profileId && a.has_config);
    const name = (cfg.accounts || []).find(a => a.id === profileId);
    const label = name ? name.display_name : "this account";

    if (!others.length) {
        showToast("No other account has settings on this PC yet, so there's nothing to copy onto.", "info");
        return;
    }
    if (!confirm(
        `Copy ${label}'s crosshair, sensitivity, HUD, keybinds and video settings onto ` +
        `${others.length} other account${others.length === 1 ? "" : "s"}?

` +
        `This overwrites their current settings and can't be undone.`)) {
        return;
    }

    const btn = DOM.btnCopySettingsAll;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner rotating"></i> Applying...`;
    }
    try {
        const res = await fetch("/api/game-config/copy-all", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source_account_id: profileId, gameplay: true, video: true })
        });
        const data = await res.json();
        showToast(data.message || (data.success ? "Applied." : "Couldn't apply settings."),
                  data.success ? "success" : "error");

        if (DOM.settingsProfileStatus) {
            const lines = [data.message || ""];
            if (data.applied && data.applied.length) {
                lines.push(`Applied to: ${data.applied.join(", ")}.`);
            }
            if (data.skipped && data.skipped.length) {
                lines.push("Skipped: " + data.skipped.map(sk => `${sk.name} (${sk.why})`).join(", ") + ".");
            }
            DOM.settingsProfileStatus.textContent = lines.filter(Boolean).join(" ");
        }
    } catch (err) {
        showToast("Failed to reach the app's backend.", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i class="fa-solid fa-users-gear"></i> Apply to All Accounts`;
        }
    }
}

/**
 * Fills a <select> with accounts.
 *
 * Options are never `disabled`. They used to be, for any account with no
 * local config detected - and since the app had no way to identify accounts
 * at all, that was every account, which made the whole dropdown unclickable
 * with no explanation. Accounts that aren't ready are now selectable and
 * labelled with the reason, and the copy action explains what to do instead
 * of the list silently refusing to respond.
 */
function fillAccountSelect(selectEl, accounts, selectedId, placeholder) {
    if (!selectEl) return;
    const opts = [`<option value="">${escapeHtml(placeholder)}</option>`];
    for (const acc of accounts) {
        const suffix = acc.has_config === false
            ? ` - ${acc.reason || "no settings on this PC yet"}`
            : "";
        opts.push(`<option value="${acc.id}" ${selectedId === acc.id ? "selected" : ""}>` +
                  `${escapeHtml(acc.display_name)}${escapeHtml(suffix)}</option>`);
    }
    selectEl.innerHTML = opts.join("");
}

async function copySettingsNow() {
    const profileId = parseInt(DOM.settingsProfileAccount?.value || "", 10);
    if (!profileId) {
        showToast("Pick a profile account to copy from first.", "info");
        return;
    }
    const targetId = parseInt(DOM.settingsCopyTarget?.value || "", 10) || null;

    if (DOM.btnCopySettingsNow) {
        DOM.btnCopySettingsNow.disabled = true;
        DOM.btnCopySettingsNow.innerHTML = `<i class="fa-solid fa-spinner rotating"></i> Copying...`;
    }
    try {
        const res = await fetch("/api/game-config/copy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source_account_id: profileId, target_account_id: targetId })
        });
        const data = await res.json();
        showToast(data.message || (data.success ? "Copied." : "Couldn't copy settings."),
                  data.success ? "success" : "error");
        if (DOM.settingsProfileStatus) DOM.settingsProfileStatus.textContent = data.message || "";
        if (data.success) loadGameConfigSettings();
    } catch (err) {
        showToast("Failed to reach the app's backend.", "error");
    } finally {
        if (DOM.btnCopySettingsNow) {
            DOM.btnCopySettingsNow.disabled = false;
            DOM.btnCopySettingsNow.innerHTML = `<i class="fa-solid fa-copy"></i> Copy Now`;
        }
    }
}

async function loadLoginLogPath() {
    if (!DOM.settingsLogPath) return;
    try {
        const res = await fetch("/api/login-log-path");
        const data = await res.json();
        DOM.settingsLogPath.value = data.path || "";
    } catch (err) {
        DOM.settingsLogPath.value = "";
    }
}

async function openLoginLog() {
    try {
        const res = await fetch("/api/open-login-log", { method: "POST" });
        const data = await res.json();
        if (!data.success) showToast(data.message || "Couldn't open the log", "info");
    } catch (err) {
        showToast("Couldn't open the log", "error");
    }
}

async function saveSettings() {
    if (DOM.settingsOverlayHotkey && !renderOverlayHotkeyValidity()) {
        showToast("Fix the Quick Panel shortcut before saving.", "error");
        return;
    }

    const payload = {
        settings: {
            riot_client_path: DOM.settingsClientPath.value.trim(),
            riot_api_key: DOM.settingsApiKey.value.trim(),
            overlay_enabled: DOM.settingsOverlayEnabled?.checked ? "1" : "0",
            overlay_hotkey: (DOM.settingsOverlayHotkey?.value || "CTRL+SHIFT+F8").trim().toUpperCase()
        }
    };

    const gameConfigPayload = {
        force_borderless: !!DOM.settingsForceBorderless?.checked,
        stay_signed_in: !!DOM.settingsStaySignedIn?.checked,
        auto_launch_after_login: !!DOM.settingsAutoLaunch?.checked,
        autoapply: !!DOM.settingsProfileAutoapply?.checked,
        profile_account_id: parseInt(DOM.settingsProfileAccount?.value || "", 10) || 0
    };

    try {
        const [res] = await Promise.all([
            fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            }),
            fetch("/api/game-config/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(gameConfigPayload)
            })
        ]);
        const data = await res.json();
        if (data.success) {
            state.settings = data.settings;
            showToast("Settings saved", "success");
            closeModal(DOM.modalSettings);
        }
    } catch (err) {
        showToast("Failed to save settings", "error");
    }
}

async function autoDetectClientPath() {
    try {
        const res = await fetch("/api/detect-client");
        const data = await res.json();
        if (data.found) {
            DOM.settingsClientPath.value = data.path;
            showToast("Riot Client path detected", "success");
        } else {
            showToast("Could not auto-detect path", "info");
        }
    } catch (err) {
        showToast("Detection error", "error");
    }
}

async function handleExportBackup() {
    try {
        const res = await fetch("/api/export");
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `valorant_accounts_backup_${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        showToast("Backup exported", "success");
        closeModal(DOM.modalBackup);
    } catch (err) {
        showToast("Failed to export", "error");
    }
}

async function handleImportBackup(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (event) => {
        try {
            const parsed = JSON.parse(event.target.result);
            const accountsList = Array.isArray(parsed) ? parsed : (parsed.accounts || []);

            if (accountsList.length === 0) {
                showToast("No accounts found in backup", "error");
                return;
            }

            const res = await fetch("/api/import", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ accounts: accountsList })
            });

            const data = await res.json();
            if (data.success) {
                showToast(buildImportMessage(data), data.imported_count > 0 ? "success" : "info");
                closeModal(DOM.modalBackup);
                fetchAccounts();
                fetchStatsSummary();
            }
        } catch (err) {
            showToast("Invalid JSON file", "error");
        }
    };
    reader.readAsText(file);
    DOM.fileImportInput.value = "";
}

// ==========================================================================
// UTILITIES
// ==========================================================================

async function copyText(text, toastMsg = "Copied to clipboard") {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            await fetch("/api/copy", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text })
            });
        }
        showToast(toastMsg, "success");
    } catch (err) {
        showToast("Failed to copy", "error");
    }
}

function togglePasswordVisibility(id, password) {
    const maskElem = document.getElementById(`pass-mask-${id}`);
    const iconElem = document.getElementById(`eye-icon-${id}`);
    if (!maskElem) return;

    if (maskElem.textContent === "••••••••") {
        maskElem.textContent = password;
        if (iconElem) iconElem.className = "fa-regular fa-eye-slash";
    } else {
        maskElem.textContent = "••••••••";
        if (iconElem) iconElem.className = "fa-regular fa-eye";
    }
}

function openModal(el) {
    if (el) el.classList.add("active");
}

function closeModal(el) {
    if (el) el.classList.remove("active");
}

function closeAllModals() {
    document.querySelectorAll(".modal-overlay").forEach(m => m.classList.remove("active"));
}

const TOAST_ICONS = {
    success: "fa-check",
    error: "fa-xmark",
    warning: "fa-triangle-exclamation",
    info: "fa-info"
};

function showToast(msg, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    const icon = TOAST_ICONS[type] || TOAST_ICONS.info;

    toast.innerHTML = `
        <span class="toast-icon"><i class="fa-solid ${icon}"></i></span>
        <span class="toast-msg">${escapeHtml(msg)}</span>
        <span class="toast-timer"></span>
    `;
    DOM.toastContainer.appendChild(toast);

    // Keep the stack readable — drop the oldest once more than four are up.
    while (DOM.toastContainer.children.length > 4) {
        DOM.toastContainer.firstElementChild.remove();
    }

    const dismiss = () => {
        if (toast.classList.contains("is-leaving")) return;
        toast.classList.add("is-leaving");
        setTimeout(() => toast.remove(), 320);
    };

    toast.addEventListener("click", dismiss);
    setTimeout(dismiss, 2800);
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatTimeAgo(isoString) {
    if (!isoString) return "Never";
    try {
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return "Never";
        const now = new Date();
        const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
        if (diffSec < 0 || diffSec < 60) return "Just now";
        const diffMin = Math.floor(diffSec / 60);
        if (diffMin < 60) return `${diffMin}m ago`;
        const diffHr = Math.floor(diffMin / 60);
        if (diffHr < 24) return `${diffHr}h ago`;
        const diffDays = Math.floor(diffHr / 24);
        if (diffDays === 1) return "Yesterday";
        if (diffDays < 7) return `${diffDays}d ago`;
        if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    } catch (e) {
        return "Never";
    }
}

// ==========================================================================
// UI ENHANCEMENT LAYER
// Purely presentational wiring: click ripples, cursor-tracked card lighting,
// scroll chrome, and overlay dismissal. Nothing here touches app data, so it
// can be disabled wholesale without affecting behaviour.
// ==========================================================================

const PREFERS_REDUCED_MOTION =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function initUiEnhancements() {
    initRipples();
    initCardSpotlight();
    initScrollChrome();
    initOverlayDismiss();
}

/** Material-style click ripple on every button, added at capture time so it
 *  also fires for buttons rendered later by the account renderers. */
function initRipples() {
    if (PREFERS_REDUCED_MOTION) return;

    document.addEventListener("pointerdown", (e) => {
        const target = e.target.closest(".btn, .btn-launch-card, .view-btn, .theme-swatch, .backup-card .btn");
        if (!target || target.disabled) return;

        const rect = target.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const ripple = document.createElement("span");
        ripple.className = "ripple";
        ripple.style.width = ripple.style.height = `${size}px`;
        ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
        ripple.style.top = `${e.clientY - rect.top - size / 2}px`;

        target.appendChild(ripple);
        setTimeout(() => ripple.remove(), 620);
    });
}

/** Feeds the hovered card's local cursor position to CSS as --mx / --my so the
 *  spotlight gradient follows the pointer. Throttled to one write per frame. */
function initCardSpotlight() {
    if (PREFERS_REDUCED_MOTION || !DOM.accountsGrid) return;

    let queued = false;
    let lastEvent = null;

    DOM.accountsGrid.addEventListener("pointermove", (e) => {
        if (document.body.classList.contains("effects-paused")) return;
        lastEvent = e;
        if (queued) return;
        queued = true;

        requestAnimationFrame(() => {
            queued = false;
            const card = lastEvent.target.closest(".account-card");
            if (!card) return;
            const rect = card.getBoundingClientRect();
            card.style.setProperty("--mx", `${lastEvent.clientX - rect.left}px`);
            card.style.setProperty("--my", `${lastEvent.clientY - rect.top}px`);
        });
    });
}

/** Condenses the sticky header and reveals the back-to-top button on scroll. */
function initScrollChrome() {
    let ticking = false;

    const update = () => {
        ticking = false;
        const y = window.scrollY;
        if (DOM.appHeader) DOM.appHeader.classList.toggle("is-stuck", y > 12);
        if (DOM.scrollTopBtn) DOM.scrollTopBtn.classList.toggle("visible", y > 400);
    };

    window.addEventListener("scroll", () => {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(update);
    }, { passive: true });

    if (DOM.scrollTopBtn) {
        DOM.scrollTopBtn.addEventListener("click", () => {
            window.scrollTo({ top: 0, behavior: PREFERS_REDUCED_MOTION ? "auto" : "smooth" });
        });
    }

    update();
}

/** Click the dimmed backdrop (never the sheet itself) to close a modal. */
function initOverlayDismiss() {
    document.querySelectorAll(".modal-overlay").forEach(overlay => {
        overlay.addEventListener("mousedown", (e) => {
            if (e.target !== overlay) return;
            // The launch modal owns extra teardown, so route it through its button.
            if (overlay === DOM.modalLaunch) {
                DOM.btnCloseLaunch.click();
            } else {
                closeModal(overlay);
            }
        });
    });
}

/** Writes a stat number, flashing it only when the value actually changed. */
function setStatValue(el, value) {
    if (!el) return;
    const next = String(value);
    if (el.textContent === next) return;

    el.textContent = next;
    if (PREFERS_REDUCED_MOTION) return;

    el.classList.remove("bump");
    // Force a reflow so the animation restarts on consecutive updates.
    void el.offsetWidth;
    el.classList.add("bump");
    setTimeout(() => el.classList.remove("bump"), 400);
}

// ==========================================================================
// LIVE SESSION - detects which account is signed in to the Riot Client
// ==========================================================================

const SESSION_STATES = {
    MENUS: { label: "In Menus", cls: "state-menus", icon: "fa-solid fa-house" },
    PREGAME: { label: "Agent Select", cls: "state-pregame", icon: "fa-solid fa-user-check" },
    INGAME: { label: "In Match", cls: "state-ingame", icon: "fa-solid fa-crosshairs" },
    OFFLINE: { label: "Game Closed", cls: "state-offline", icon: "fa-solid fa-power-off" }
};

// Live rounds and agent select are time-sensitive even if the app is behind
// VALORANT. Menus, closed clients and hidden idle windows can back off hard.
const LIVE_POLL_CRITICAL = 1100;
const LIVE_POLL_DASHBOARD = 1200;
const LIVE_POLL_MENUS = 3500;
const LIVE_POLL_SIGNED_IN = 7000;
const LIVE_POLL_IDLE = 10000;
const LIVE_POLL_HIDDEN = 15000;

function getLivePollDelay() {
    if (isLiveMatchActive()) return LIVE_POLL_CRITICAL;
    if (state.dashboardOpen && !document.hidden) return LIVE_POLL_DASHBOARD;
    if (document.hidden) return LIVE_POLL_HIDDEN;
    if (state.live && state.live.valorant_running) return LIVE_POLL_MENUS;
    if (state.live && state.live.available) return LIVE_POLL_SIGNED_IN;
    return LIVE_POLL_IDLE;
}

function scheduleLivePoll(delay = getLivePollDelay()) {
    clearTimeout(state._livePollTimer);
    state._livePollTimer = setTimeout(runLivePollTick, Math.max(0, delay));
}

async function runLivePollTick() {
    try {
        await pollLiveSession();
    } catch (err) {
        // Never let one bad frame stop the loop.
    } finally {
        scheduleLivePoll();
    }
}

function startLiveSessionPolling() {
    scheduleLivePoll(0);
}

function updateLiveHeroCardState(live) {
    const heroCard = document.querySelector(".account-card-hero");
    if (!heroCard) return;

    const isValRunning = !!(live && live.available && live.valorant_running);
    const sessionInfo = sessionStateInfo(live);

    const titleEl = heroCard.querySelector(".hero-play-title");
    const subEl = heroCard.querySelector(".hero-play-sub");
    if (titleEl) titleEl.textContent = isValRunning ? "VALORANT RUNNING" : "PLAY VALORANT";
    if (subEl) subEl.textContent = isValRunning ? "Client Active" : "Launch Game Client";

    const chipEl = heroCard.querySelector(".session-state-chip");
    if (chipEl) {
        chipEl.className = `session-state-chip ${sessionInfo.cls}`;
        chipEl.textContent = isValRunning ? sessionInfo.label : "Riot Session Active";
    }

    const playBtn = heroCard.querySelector(".btn-hero-play");
    if (playBtn) {
        playBtn.classList.toggle("is-running", isValRunning);
    }
}

async function pollLiveSession() {
    if (state._livePollPromise) return state._livePollPromise;

    const task = pollLiveSessionOnce();
    state._livePollPromise = task;
    try {
        return await task;
    } finally {
        if (state._livePollPromise === task) state._livePollPromise = null;
    }
}

async function pollLiveSessionOnce() {
    let live;
    try {
        const res = await fetch("/api/live/session");
        live = await res.json();
    } catch (err) {
        return;
    }

    const previousId = state.activeAccountId;
    const hadHero = !!document.querySelector(".account-card-hero");
    state.live = live;
    state.activeAccountId = live.available ? live.account_id : null;
    updateEffectsPausedState();

    if (live.available && live.account_id && !state.accounts.some(a => a.id === live.account_id)) {
        await fetchAccounts(false);
    }

    // A signed-in account that's been flagged lives in the banned store, so
    // the hero card can only be built once that store is loaded.
    const wasBanned = state._liveBanned === true;
    const nowBanned = !!(live.available && live.account_banned);
    state._liveBanned = nowBanned;
    if (nowBanned && !findBannedAccount(live.banned_account_id)) {
        await fetchBannedAccounts(true);
    }

    renderSessionBar(live);
    updateLiveHeroCardState(live);

    if (state.dashboardOpen) {
        renderDashboard(live);
        refreshInstalockStatus();
    }

    // A finished match is the moment the profile is actually out of date -
    // but rebuilding it costs a round of Riot requests plus a match-details
    // fetch per game, so a closed dashboard just drops the cache and lets the
    // next open pay for it.
    if (state._wasInMatch && !live.match) {
        if (state.dashboardOpen) refreshPlayerStats(true);
        else state._statsDirty = true;
    }
    state._wasInMatch = !!live.match;

    // Re-render when the active card moved, when the hero card needs to
    // appear, or when the signed-in account crossed the banned line in either
    // direction (both change which card is rendered and what it can do).
    if (previousId !== state.activeAccountId || (live.available && !hadHero) || wasBanned !== nowBanned) {
        renderAccounts();
    }

    return live;
}

function sessionStateInfo(live) {
    if (!live || !live.available) return SESSION_STATES.OFFLINE;
    if (!live.valorant_running) return SESSION_STATES.OFFLINE;
    return SESSION_STATES[live.state] || SESSION_STATES.MENUS;
}

function renderSessionBar(live) {
    if (!DOM.sessionBar) return;

    if (!live || !live.available) {
        DOM.sessionBar.style.display = "none";
        return;
    }

    DOM.sessionBar.style.display = "flex";
    DOM.sessionName.textContent = live.display_name || live.username || "Signed in";

    const bits = [];
    if (live.level) bits.push(`Level ${live.level}`);
    if (live.rank_label) bits.push(live.rank_label);
    if (live.region) bits.push(live.region);
    if (live.party && live.party.size > 1) bits.push(`Party of ${live.party.size}`);
    DOM.sessionMeta.textContent = bits.join(" · ") || "Signed in to Riot Client";

    if (DOM.sessionRankImg) {
        if (live.rank_icon_url) {
            DOM.sessionRankImg.src = live.rank_icon_url;
            DOM.sessionRankImg.style.display = "block";
        } else {
            DOM.sessionRankImg.style.display = "none";
        }
    }

    const info = sessionStateInfo(live);
    if (DOM.sessionStateChip) {
        DOM.sessionStateChip.className = `session-state-chip ${info.cls}`;
        DOM.sessionStateChip.textContent = live.valorant_running ? info.label : "VALORANT closed";
    }

    // The Play buttons are driven together by renderPlayButton, which also
    // knows about a launch that's still in flight.
    renderPlayButton(live);
}

async function playAccount(id) {
    const acc = state.accounts.find(a => a.id === id);
    if (!acc) return;

    const isActive = state.activeAccountId === id;
    if (!isActive) {
        // Switching accounts means a full Riot Client login first - show the
        // same progress modal the LOGIN button uses.
        state.activeLaunchAcc = acc;
        state._launchRetry = () => playAccount(id);
        DOM.launchUserVal.textContent = acc.username;
        setLaunchModalTitle("Switching Account & Starting VALORANT");
        renderLaunchProgress({ stage: "opening", message: "Opening Riot Client…" });
        openModal(DOM.modalLaunch);
        startLaunchPolling({ openDashboardWhenDone: true });
    }

    try {
        const res = await fetch(`/api/accounts/${id}/play`, { method: "POST" });
        const data = await res.json();
        showToast(data.message || (data.success ? "Starting VALORANT…" : "Couldn't start VALORANT"),
                  data.success ? "success" : "error");
        if (data.success) {
            openDashboard();
            if (!data.switched) {
                scheduleLivePoll(1200);
            }
        } else if (!data.success && !isActive) {
            stopLaunchPolling();
            renderLaunchProgress({ stage: "error", message: data.message || "Couldn't start VALORANT." });
        }
    } catch (err) {
        showToast("Failed to start VALORANT", "error");
        if (!isActive) {
            stopLaunchPolling();
            renderLaunchProgress({ stage: "error", message: "Failed to reach the app's backend." });
        }
    }
}

// ==========================================================================
// SINGLE ACCOUNT CHECK
// ==========================================================================

async function checkAccount(id) {
    const acc = state.accounts.find(a => a.id === id);
    if (!acc) return;

    if (state.isCheckingAccounts) {
        showToast("A full roster check is already running.", "info");
        return;
    }

    state.activeLaunchAcc = acc;
    state._launchRetry = () => checkAccount(id);
    DOM.launchUserVal.textContent = acc.username;
    setLaunchModalTitle("Checking Account");
    renderLaunchProgress({ stage: "opening", message: "Verifying these credentials with Riot…" });
    openModal(DOM.modalLaunch);
    startLaunchPolling();

    const btn = document.getElementById(`btn-check-${id}`);
    if (btn) {
        btn.disabled = true;
        btn.classList.add("is-checking");
    }

    try {
        const res = await fetch(`/api/accounts/${id}/check`, { method: "POST" });
        const data = await res.json();

        stopLaunchPolling();
        renderLaunchProgress({
            stage: data.verified ? "done" : "error",
            message: data.message || (data.verified ? "Verified" : "Couldn't verify")
        });

        showToast(data.message || "Check finished",
                  data.verified ? (data.moved_to_banned ? "warning" : "success") : "error");

        await fetchAccounts();
        fetchStatsSummary();
        if (data.moved_to_banned) fetchBannedAccounts();
        if (data.verified && !data.moved_to_banned) {
            highlightAccount(id);
            scheduleLivePoll(0);
        }
    } catch (err) {
        stopLaunchPolling();
        renderLaunchProgress({ stage: "error", message: "The check couldn't finish." });
        showToast("Account check failed", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.classList.remove("is-checking");
        }
    }
}

/** Flags a card so it stands out right after it's added or verified. */
function highlightAccount(id) {
    state.highlightId = id;
    renderAccounts();

    setTimeout(() => {
        const card = document.querySelector(`[data-id="${id}"]`);
        if (card) {
            card.scrollIntoView({
                behavior: PREFERS_REDUCED_MOTION ? "auto" : "smooth",
                block: "center"
            });
        }
    }, 80);

    clearTimeout(state._highlightTimer);
    state._highlightTimer = setTimeout(() => {
        state.highlightId = null;
        renderAccounts();
    }, 9000);
}

// ==========================================================================
// LIVE DASHBOARD
// The dashboard is a view rather than a modal: opening it collapses the
// roster and shrinks the account tools into an icon rail, and closing it
// puts everything back.
// ==========================================================================

async function openDashboard() {
    if (state.dashboardOpen) return;
    state.dashboardOpen = true;

    document.body.classList.add("dashboard-mode");
    if (DOM.dashView) {
        DOM.dashView.classList.add("is-open");
        DOM.dashView.setAttribute("aria-hidden", "false");
    }
    if (DOM.btnToggleDashboard) DOM.btnToggleDashboard.classList.add("is-active");

    if (!state.agents.length) await loadLiveAgents();
    renderModeGrid();
    renderAgentGrid();
    refreshInstalockStatus(true);
    moveTabGlide();

    if (state.live) renderDashboard(state.live);
    scheduleLivePoll(0);
    startQueueClock();

    // The roster collapses out from under the page, so anchor back to the
    // top rather than leaving the view stranded mid-document.
    window.scrollTo({ top: 0, behavior: PREFERS_REDUCED_MOTION ? "auto" : "smooth" });
}

function closeDashboard() {
    if (!state.dashboardOpen) return;
    state.dashboardOpen = false;

    document.body.classList.remove("dashboard-mode");
    if (DOM.dashView) {
        DOM.dashView.classList.remove("is-open");
        DOM.dashView.setAttribute("aria-hidden", "true");
    }
    if (DOM.btnToggleDashboard) DOM.btnToggleDashboard.classList.remove("is-active");

    stopQueueClock();
    clearTimeout(state._statsTimer);
}

function toggleDashboard() {
    if (state.dashboardOpen) closeDashboard();
    else openDashboard();
}

async function loadLiveAgents() {
    try {
        const res = await fetch("/api/live/agents");
        const data = await res.json();
        state.agents = data.agents || [];
        state.modes = data.modes || [];
    } catch (err) {
        state.agents = [];
        state.modes = [];
    }
}

// -- tabs ----------------------------------------------------------------
// (handled below)

// -- tabs ----------------------------------------------------------------

function switchDashTab(tab) {
    state.dashTab = tab;

    document.querySelectorAll(".dash-tab").forEach(b => {
        b.classList.toggle("active", b.dataset.tab === tab);
    });
    document.querySelectorAll(".dash-tab-panel").forEach(p => {
        p.classList.toggle("is-active", p.dataset.panel === tab);
    });

    moveTabGlide();

    if (tab === "stats" || tab === "inventory") refreshPlayerStats();
}

/** Slides the pill under the active tab. */
function moveTabGlide() {
    if (!DOM.dashTabGlide || !DOM.dashTabs) return;
    const active = DOM.dashTabs.querySelector(".dash-tab.active");
    if (!active) return;

    DOM.dashTabGlide.style.width = `${active.offsetWidth}px`;
    DOM.dashTabGlide.style.transform = `translateX(${active.offsetLeft - 4}px)`;
}

// -- dashboard rendering --------------------------------------------------

function dashboardSectionChanged(key, value) {
    if (!state._dashboardRenderSignatures) {
        state._dashboardRenderSignatures = Object.create(null);
    }

    let signature;
    try {
        signature = JSON.stringify(value);
        if (signature === undefined) signature = String(value);
    } catch (err) {
        // Live payloads are plain JSON today. If that ever changes, rendering
        // is safer than leaving a section stale.
        signature = `${Date.now()}-${Math.random()}`;
    }

    if (state._dashboardRenderSignatures[key] === signature) return false;
    state._dashboardRenderSignatures[key] = signature;
    return true;
}

function renderDashboard(live) {
    if (!DOM.dashView) return;

    // -- identity ------------------------------------------------------
    DOM.dashRiotId.textContent = live.display_name || live.username || "Not signed in";
    DOM.dashLevel.textContent = live.level ? `LV ${live.level}` : "LV -";

    if (live.rank_icon_url) {
        DOM.dashRankImg.src = live.rank_icon_url;
        DOM.dashRankImg.style.display = "block";
    } else {
        DOM.dashRankImg.style.display = "none";
    }

    const subBits = [];
    if (live.rank_label) subBits.push(live.rank_label);
    if (live.region) subBits.push(live.region);
    if (live.party && live.party.size) subBits.push(`Party ${live.party.size}/${live.party.max || 5}`);
    DOM.dashIdentitySub.textContent = subBits.join(" · ") || "Signed in to Riot Client";

    const info = sessionStateInfo(live);
    DOM.dashStateChip.className = `dash-state-chip ${info.cls}`;
    DOM.dashStateLabel.textContent = live.available
        ? (live.valorant_running ? info.label : "VALORANT closed")
        : "No session";

    // -- live match ----------------------------------------------------
    const match = live.match;
    const inPregame = !!match && match.phase === "agent_select";
    const inMatch = !!match && match.phase === "in_match";
    const inQueue = !!(live.party && live.party.in_queue);

    DOM.dashHero.style.display = inMatch ? "block" : "none";
    DOM.dashPregameBanner.style.display = inPregame ? "flex" : "none";
    DOM.dashQueueBanner.style.display = (inQueue && !match) ? "flex" : "none";
    DOM.dashTeams.style.display = match ? "grid" : "none";
    DOM.dashIdle.style.display = (match || inQueue) ? "none" : "flex";

    if (!match && !inQueue) {
        DOM.dashIdleTitle.textContent = live.available
            ? (live.valorant_running ? "No live match" : "VALORANT isn't running")
            : "No Riot Client session";
        DOM.dashIdleText.textContent = live.message ||
            "Start a match from the panel on the right and this tracks it round by round.";
    }

    if (inMatch) renderMatchHero(match, live);
    renderMeCard(match);
    renderRecap(live, !!match);

    if (inPregame) {
        const startSide = match.starting_side || "Defender";
        const sideIcon = startSide === "Defender" ? "fa-shield-halved" : "fa-crosshairs";
        const sideCls = startSide === "Defender" ? "side-defender" : "side-attacker";
        const sideText = startSide === "Defender" ? "Starting Defense" : "Starting Attack";

        if (dashboardSectionChanged("pregame-banner", {
            map: match.map && match.map.name,
            mode: match.mode || live.queue_label || "",
            startSide
        })) {
            DOM.dashPregameText.innerHTML = `
                <span>Agent select &middot; <strong>${escapeHtml(match.map.name || "Unknown map")}</strong> &middot; ${escapeHtml(match.mode || live.queue_label || "")}</span>
                <span class="dash-side-pill ${sideCls}"><i class="fa-solid ${sideIcon}"></i> ${sideText}</span>
            `;
        }
    }

    // Sync independent smooth timers
    syncPregameTimer(match, inPregame);
    syncQueueTimer(live, inQueue);

    if (match) {
        renderDuoBanner(match);
        renderRoster(DOM.dashRosterAlly, match.team);
        renderRoster(DOM.dashRosterEnemy, match.enemy);
        DOM.dashTeamEnemyWrap.style.display = (match.enemy && match.enemy.length) ? "block" : "none";

        const allySide = match.current_side || match.side || match.starting_side || "Defender";
        const enemySide = allySide === "Defender" ? "Attacker" : "Defender";
        renderTeamTitle(".dash-team-ally", "fa-user-group", "Your Team", allySide, match.team);
        renderTeamTitle(".dash-team-enemy", "fa-crosshairs", "Enemy Team", enemySide, match.enemy);
    } else {
        renderDuoBanner(null);
    }

    if (inQueue && DOM.dashQueueBannerSub) {
        DOM.dashQueueBannerSub.textContent = live.queue_label || "Searching for a match";
    }

    renderQueueControls(live);
    renderPlayButton(live);
    updateInstalockControls();
}

// -- INDEPENDENT SMOOTH TIMERS --------------------------------------------
let _queueTimerInterval = null;
let _pregameTimerInterval = null;

function syncQueueTimer(live, inQueue) {
    if (!inQueue) {
        state.queueStartedAt = 0;
        if (_queueTimerInterval) {
            clearInterval(_queueTimerInterval);
            _queueTimerInterval = null;
        }
        return;
    }

    const backendElapsed = (live && live.queue_elapsed) || 0;
    const targetStart = Date.now() - backendElapsed * 1000;

    // Only resync start timestamp if uninitialized or drifted by > 2.5s
    if (!state.queueStartedAt || Math.abs(state.queueStartedAt - targetStart) > 2500) {
        state.queueStartedAt = targetStart;
    }

    if (!_queueTimerInterval) {
        updateQueueClockDisplay();
        _queueTimerInterval = setInterval(updateQueueClockDisplay, 500);
    }
}

function updateQueueClockDisplay() {
    if (!state.queueStartedAt || !DOM.dashQueueClock) return;
    const elapsed = Math.max(0, Math.floor((Date.now() - state.queueStartedAt) / 1000));
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    DOM.dashQueueClock.textContent = `${m}:${s < 10 ? "0" : ""}${s}`;
}

function syncPregameTimer(match, inPregame) {
    if (!inPregame || !match || !(match.time_remaining > 0)) {
        state.pregameEndsAt = 0;
        if (_pregameTimerInterval) {
            clearInterval(_pregameTimerInterval);
            _pregameTimerInterval = null;
        }
        if (DOM.dashPregameTimer) DOM.dashPregameTimer.textContent = "--";
        return;
    }

    const targetEnd = Date.now() + Math.ceil(match.time_remaining) * 1000;

    // Only resync target end if uninitialized or drifted by > 2s
    if (!state.pregameEndsAt || Math.abs(state.pregameEndsAt - targetEnd) > 2000) {
        state.pregameEndsAt = targetEnd;
    }

    if (!_pregameTimerInterval) {
        updatePregameClockDisplay();
        _pregameTimerInterval = setInterval(updatePregameClockDisplay, 250);
    }
}

function updatePregameClockDisplay() {
    if (!state.pregameEndsAt || !DOM.dashPregameTimer) return;
    const rem = Math.max(0, Math.ceil((state.pregameEndsAt - Date.now()) / 1000));
    DOM.dashPregameTimer.textContent = rem > 0 ? `${rem}s` : "0s";
}

function stopQueueClock() {
    state.queueStartedAt = 0;
    if (_queueTimerInterval) {
        clearInterval(_queueTimerInterval);
        _queueTimerInterval = null;
    }
    state.pregameEndsAt = 0;
    if (_pregameTimerInterval) {
        clearInterval(_pregameTimerInterval);
        _pregameTimerInterval = null;
    }
}

// -- match hero, personal line, rosters -----------------------------------

const DEFAULT_UNRANKED_ICON =
    "https://media.valorant-api.com/competitivetiers/03621f52-342b-cf4e-4f86-9350a49c6d04/0/largeicon.png";

function sideMeta(side) {
    return side === "Defender"
        ? { cls: "side-defender", icon: "fa-shield-halved", label: "Defense" }
        : { cls: "side-attacker", icon: "fa-crosshairs", label: "Attack" };
}

/** Rounds won/lost, the round-by-round ledger, and where the match stands. */
function renderMatchHero(match, live) {
    if (!dashboardSectionChanged("match-hero", {
        matchId: match.match_id,
        map: match.map,
        mode: match.mode,
        progress: match.progress,
        score: match.score,
        round: match.round,
        currentSide: match.current_side,
        side: match.side,
        startingSide: match.starting_side,
        queueLabel: live.queue_label
    })) return;

    const p = match.progress || {};
    const won = p.rounds_won != null ? p.rounds_won : match.score.ally;
    const lost = p.rounds_lost != null ? p.rounds_lost : match.score.enemy;
    const side = sideMeta(p.current_side || match.current_side || match.side || "Defender");

    DOM.dashScoreAlly.textContent = won;
    DOM.dashScoreEnemy.textContent = lost;
    DOM.dashMapName.textContent = match.map.name || "Unknown map";
    DOM.dashModeName.textContent = match.mode || live.queue_label || "";
    DOM.dashMapArt.style.backgroundImage = match.map.splash ? `url("${match.map.splash}")` : "none";

    const diff = won - lost;
    DOM.dashScoreDiff.textContent = diff === 0 ? "TIED" : (diff > 0 ? `+${diff}` : `${diff}`);
    DOM.dashScoreDiff.className = `dash-score-diff ${diff > 0 ? "is-ahead" : diff < 0 ? "is-behind" : ""}`;

    const target = p.rounds_to_win || 0;
    if (target) {
        const need = Math.max(0, target - won);
        const survive = Math.max(0, target - lost);
        DOM.dashScoreTarget.innerHTML = need === 0
            ? "match won"
            : `<strong>${need}</strong> to win &middot; <strong>${survive}</strong> to lose`;
    } else {
        DOM.dashScoreTarget.textContent = "";
    }

    // Chips: round number, half, side, and whatever the score is screaming.
    const chips = [];
    chips.push(`<span class="dash-chip is-round">Round ${p.round_number || match.round}</span>`);
    if (p.half) chips.push(`<span class="dash-chip">${escapeHtml(p.half)}</span>`);
    chips.push(`<span class="dash-chip ${side.cls}"><i class="fa-solid ${side.icon}"></i> ${side.label}</span>`);
    if (p.match_point) chips.push(`<span class="dash-chip is-hot"><i class="fa-solid fa-fire"></i> Match Point</span>`);
    else if (p.elim_point) chips.push(`<span class="dash-chip is-cold"><i class="fa-solid fa-triangle-exclamation"></i> Elim Point</span>`);
    if (p.streak && p.streak.count >= 2) {
        chips.push(`<span class="dash-chip ${p.streak.won ? "is-win" : "is-loss"}">
            <i class="fa-solid ${p.streak.won ? "fa-arrow-trend-up" : "fa-arrow-trend-down"}"></i>
            ${p.streak.count} ${p.streak.won ? "won" : "lost"} in a row</span>`);
    }
    DOM.dashHeroChips.innerHTML = chips.join("");

    // Round ledger. Rounds that finished before the dashboard was watching
    // can't be placed in order, so they render muted rather than pretending.
    const history = p.history || [];
    DOM.dashRoundStrip.innerHTML = history.length
        ? history.map(r => {
            const label = r.known
                ? `Round ${r.n}: ${r.won ? "won" : "lost"}${r.side ? ` on ${r.side.toLowerCase()}` : ""}`
                : "Played before tracking started";
            return `<span class="dash-pip ${r.won ? "is-won" : "is-lost"}${r.known ? "" : " is-unknown"}" title="${escapeHtml(label)}"></span>`;
          }).join("")
        : `<span class="dash-strip-empty">Round 1 in progress</span>`;
}

/** Renders a dedicated banner summarizing detected parties and stacks for both teams. */
function renderDuoBanner(match) {
    if (!DOM.dashDuoBanner) return;
    if (!match) {
        if (!dashboardSectionChanged("duo-banner", null)) return;
        DOM.dashDuoBanner.style.display = "none";
        return;
    }

    const stacks = match.stacks || { ally: [], enemy: [] };
    const allyStacks = stacks.ally || [];
    const enemyStacks = stacks.enemy || [];
    const hasEnemy = (match.enemy && match.enemy.length > 0);

    if (!dashboardSectionChanged("duo-banner", {
        matchId: match.match_id,
        allyStacks,
        enemyStacks,
        hasEnemy
    })) return;

    const allyHtml = allyStacks.length > 0
        ? allyStacks.map(s => `
            <div class="dash-duo-tag is-ally ${s.confirmed ? "is-confirmed" : ""}">
                <i class="fa-solid ${s.confirmed ? "fa-user-group" : "fa-link"}"></i>
                <span class="dash-duo-tag-type">${escapeHtml(s.tag)}</span>
                <span class="dash-duo-tag-names">${escapeHtml(s.names.join(" + "))}</span>
                ${s.confirmed ? `<span class="dash-duo-badge is-confirmed">YOUR PARTY</span>` : `<span class="dash-duo-badge is-detected">PREMADE</span>`}
            </div>`).join("")
        : `<div class="dash-duo-tag is-solo"><i class="fa-solid fa-user"></i> <span>All Solo Queue</span></div>`;

    const enemyHtml = hasEnemy
        ? (enemyStacks.length > 0
            ? enemyStacks.map(s => `
                <div class="dash-duo-tag is-enemy">
                    <i class="fa-solid fa-link"></i>
                    <span class="dash-duo-tag-type">${escapeHtml(s.tag)}</span>
                    <span class="dash-duo-tag-names">${escapeHtml(s.names.join(" + "))}</span>
                    <span class="dash-duo-badge is-detected">PREMADE</span>
                </div>`).join("")
            : `<div class="dash-duo-tag is-solo"><i class="fa-solid fa-user"></i> <span>No Stacks Detected</span></div>`)
        : "";

    DOM.dashDuoBanner.style.display = "flex";
    DOM.dashDuoBanner.innerHTML = `
        <div class="dash-duo-section">
            <div class="dash-duo-title"><i class="fa-solid fa-shield-halved"></i> Ally Premades</div>
            <div class="dash-duo-list">${allyHtml}</div>
        </div>
        ${hasEnemy ? `
        <div class="dash-duo-section">
            <div class="dash-duo-title is-enemy"><i class="fa-solid fa-skull"></i> Enemy Premades</div>
            <div class="dash-duo-list">${enemyHtml}</div>
        </div>` : ""}
    `;
}

/**
 * The "you, right now" panel.
 *
 * Two strictly separated blocks, because conflating them is what made the old
 * panel look live without being live:
 *
 *  - CURRENT MATCH: this match only. The round line (score, round win rate,
 *    attack/defense split, streak) is live on every poll. The combat line
 *    (K/D/A, HS%, ADR, ACS) is only filled in from a real read of this match -
 *    when Riot hasn't published it yet the tiles show "--" and say so, rather
 *    than borrowing an average from previous games.
 *  - LAST 5 MATCHES: the rolling average, always labelled as the average.
 */
function renderMeCard(match) {
    const me = match && match.me;
    if (!dashboardSectionChanged("me-card", {
        phase: match && match.phase,
        me: me || null
    })) return;

    if (!me) {
        DOM.dashMe.style.display = "none";
        return;
    }
    DOM.dashMe.style.display = "block";

    const cur = me.current || {};
    const recent = me.recent || {};
    const hasCombat = !!cur.available;
    const inMatch = match.phase === "in_match";
    const liveEventsOnly = cur.source === "game_log";

    const num = (v, digits) => (v === null || v === undefined)
        ? "--"
        : (digits ? Number(v).toFixed(digits) : String(v));
    const pct = v => (v === null || v === undefined) ? "--" : v + "%";
    const goodBad = (v, threshold) =>
        (v === null || v === undefined) ? "is-pending" : (v >= threshold ? "is-good" : "is-bad");

    // -- current match: combat line -------------------------------------
    const combatTiles = [
        { k: "K / D / A", v: cur.kda_line || "--", c: hasCombat ? "is-kda" : "is-pending" },
        { k: "K/D", v: num(cur.kd, 2), c: goodBad(cur.kd, 1) },
        { k: liveEventsOnly ? "HS Kills" : "Headshot %", v: liveEventsOnly ? pct(cur.headshot_kill_pct) : pct(cur.hs_pct), c: hasCombat ? "is-hs" : "is-pending" },
        { k: "ADR", v: num(cur.adr), c: hasCombat ? "is-adr" : "is-pending" },
        { k: "ACS", v: num(cur.acs), c: hasCombat ? "is-acs" : "is-pending" }
    ];

    // -- current match: round line (live on every poll) -------------------
    const atk = cur.attack_record || { won: 0, played: 0 };
    const def = cur.defense_record || { won: 0, played: 0 };
    const streak = cur.streak || { count: 0, won: false };

    const roundTiles = [
        {
            k: "Rounds",
            v: (cur.rounds_won || 0) + " - " + (cur.rounds_lost || 0),
            c: (cur.rounds_won || 0) >= (cur.rounds_lost || 0) ? "is-good" : "is-bad"
        },
        {
            k: "Round Win %",
            v: cur.rounds_played ? cur.round_winrate + "%" : "--",
            c: goodBad(cur.rounds_played ? cur.round_winrate : null, 50)
        },
        { k: "On Attack", v: atk.played ? atk.won + "/" + atk.played : "--", c: "is-atk" },
        { k: "On Defense", v: def.played ? def.won + "/" + def.played : "--", c: "is-def" },
        {
            k: "Streak",
            v: streak.count >= 2 ? streak.count + " " + (streak.won ? "W" : "L") : "--",
            c: streak.count >= 2 ? (streak.won ? "is-good" : "is-bad") : "is-pending"
        }
    ];

    // -- last 5 matches (the average, named as the average) ---------------
    const recentTiles = [
        { k: "Avg K/D", v: num(recent.kd, 2), c: goodBad(recent.kd, 1) },
        { k: "Avg HS%", v: pct(recent.hs_pct), c: "is-hs" },
        { k: "Avg ADR", v: num(recent.adr), c: "is-adr" },
        { k: "Win Rate", v: pct(recent.winrate), c: goodBad(recent.winrate, 50) }
    ];

    const tileHtml = tiles => tiles.map(t =>
        '<div class="dash-me-tile ' + t.c + '">' +
            '<span class="dash-me-tile-v">' + escapeHtml(String(t.v)) + '</span>' +
            '<span class="dash-me-tile-k">' + t.k + '</span>' +
        '</div>').join("");

    const formPips = (me.last5_form && me.last5_form.length > 0)
        ? '<div class="dash-me-form-row">' +
              me.last5_form.map(f =>
                  '<span class="dash-form-pip is-' + f.toLowerCase() + '">' + f + '</span>').join("") +
              '<span class="dash-me-form-sub">' +
                  (me.last5_wins || 0) + 'W ' + (me.last5_losses || 0) + 'L &middot; ' +
                  (me.winrate_last5 != null ? me.winrate_last5 : 0) + '% WR</span>' +
          '</div>'
        : "";

    const shots = cur.shots || 0;
    const share = n => shots ? Math.round((n / shots) * 100) : 0;

    const agentHtml = me.agent_icon
        ? '<img src="' + me.agent_icon + '" class="dash-me-agent" alt="' +
          escapeHtml(me.agent || "") + '" onerror="this.style.visibility=\'hidden\';">'
        : '<span class="dash-me-agent is-empty"><i class="fa-solid fa-user"></i></span>';

    const rankHtml = me.tier_icon
        ? '<img src="' + me.tier_icon + '" class="dash-me-rank" alt="" onerror="this.style.display=\'none\';">'
        : "";

    const pendingHtml = liveEventsOnly ?
        '<div class="dash-me-pending is-live-feed">' +
            '<i class="fa-solid fa-satellite-dish"></i>' +
            '<span>Live event feed: K/D updates the moment events reach your local game log. “HS Kills” is headshot kills per kill; Riot still supplies exact shot accuracy, ADR and ACS when available.</span>' +
        '</div>' : (hasCombat ? "" :
        '<div class="dash-me-pending">' +
            '<i class="fa-solid fa-hourglass-half"></i>' +
            '<span>' + escapeHtml(cur.reason || "Waiting on Riot for this match's combat stats.") +
            ' Rounds, sides and streak above are live now; K/D/A, HS%, ADR and ACS fill in the moment Riot publishes them.</span>' +
        '</div>');

    const hitHtml = (hasCombat && shots)
        ? '<div class="dash-hs-bar" title="' + cur.headshots + ' head &middot; ' + cur.bodyshots +
              ' body &middot; ' + cur.legshots + ' leg">' +
              '<span class="dash-hs-seg is-head" style="width:' + share(cur.headshots) + '%"></span>' +
              '<span class="dash-hs-seg is-body" style="width:' + share(cur.bodyshots) + '%"></span>' +
              '<span class="dash-hs-seg is-leg" style="width:' + share(cur.legshots) + '%"></span>' +
          '</div>' +
          '<div class="dash-hs-legend">' +
              '<span><i class="dot is-head"></i> Head ' + share(cur.headshots) + '%</span>' +
              '<span><i class="dot is-body"></i> Body ' + share(cur.bodyshots) + '%</span>' +
              '<span><i class="dot is-leg"></i> Leg ' + share(cur.legshots) + '%</span>' +
              (cur.damage
                  ? '<span class="dash-hs-dmg">' + cur.damage.toLocaleString() +
                    ' dmg over ' + (cur.rounds_played || 0) + ' rounds</span>'
                  : "") +
          '</div>'
        : "";

    const roundChip = inMatch
        ? '<span class="dash-me-round-chip">Round ' + (cur.round_number || 1) + '</span>'
        : "";

    DOM.dashMe.innerHTML =
        '<div class="dash-me-head">' +
            agentHtml +
            '<div class="dash-me-id">' +
                '<span class="dash-me-title">' + escapeHtml(me.agent || "Your agent") + '</span>' +
                '<span class="dash-me-sub">' +
                    escapeHtml(me.tier_label || "Unranked") +
                    (me.rr ? ' &middot; ' + me.rr + ' RR' : "") +
                '</span>' +
            '</div>' +
            rankHtml +
        '</div>' +

        '<div class="dash-me-section">' +
            '<div class="dash-me-section-head">' +
                '<span class="dash-me-section-title">' +
                    '<i class="fa-solid fa-circle-dot"></i> Current Match' +
                '</span>' +
                roundChip +
            '</div>' +
            '<div class="dash-me-tiles">' + tileHtml(roundTiles) + '</div>' +
            '<div class="dash-me-tiles is-combat">' + tileHtml(combatTiles) + '</div>' +
            pendingHtml +
            hitHtml +
        '</div>' +

        '<div class="dash-me-section is-recent">' +
            '<div class="dash-me-section-head">' +
                '<span class="dash-me-section-title">' +
                    '<i class="fa-solid fa-clock-rotate-left"></i> Last 5 Matches' +
                '</span>' +
                '<span class="dash-me-section-note">average, not this match</span>' +
            '</div>' +
            formPips +
            '<div class="dash-me-tiles">' + tileHtml(recentTiles) + '</div>' +
        '</div>';
}


/** Between matches: how the last one went, and how the session is going. */
function renderRecap(live, hasMatch) {
    const last = live.last_match;
    const session = live.session || {};
    if (!dashboardSectionChanged("recap", { last, session, hasMatch })) return;

    if (hasMatch || (!last && !(session.matches > 0))) {
        DOM.dashRecap.style.display = "none";
        return;
    }
    DOM.dashRecap.style.display = "grid";

    const lastHtml = last ? `
        <div class="dash-recap-card is-${(last.result || "").toLowerCase()}">
            <div class="dash-recap-head">
                <span class="dash-recap-label">Last Match</span>
                <span class="dash-recap-result">${escapeHtml(last.result || "")}</span>
            </div>
            <div class="dash-recap-score">${last.rounds_won} <span>-</span> ${last.rounds_lost}</div>
            <div class="dash-recap-sub">
                ${last.agent_icon ? `<img src="${last.agent_icon}" alt="" onerror="this.style.display='none';">` : ""}
                ${escapeHtml(last.map || "")} · ${escapeHtml(last.mode || "")}
            </div>
            <div class="dash-recap-stats">
                <span><strong>${last.kda}</strong> KDA</span>
                <span><strong>${last.hs_pct}%</strong> HS</span>
                <span><strong>${last.adr}</strong> ADR</span>
                <span><strong>${last.acs}</strong> ACS</span>
            </div>
        </div>` : "";

    const sessionHtml = session.matches > 0 ? `
        <div class="dash-recap-card is-session">
            <div class="dash-recap-head">
                <span class="dash-recap-label">This Session</span>
                <span class="dash-recap-result">${session.wins}W ${session.losses}L</span>
            </div>
            <div class="dash-recap-form">
                ${(session.form || []).map(r =>
                    `<span class="dash-form-pip is-${(r || "").toLowerCase()}">${(r || "?")[0]}</span>`
                ).join("")}
            </div>
            <div class="dash-recap-stats">
                <span><strong>${session.kills}/${session.deaths}/${session.assists}</strong></span>
                <span><strong>${session.kd}</strong> KD</span>
                <span><strong>${session.hs_pct}%</strong> HS</span>
                <span><strong>${session.adr}</strong> ADR</span>
            </div>
        </div>` : "";

    DOM.dashRecap.innerHTML = lastHtml + sessionHtml;
}

/** Team heading with its side and a count of the premades on it. */
function renderTeamTitle(selector, icon, text, side, players) {
    const el = document.querySelector(selector);
    if (!el) return;
    const meta = sideMeta(side);
    const groups = new Set((players || []).map(p => p.party_group).filter(Boolean));
    if (!dashboardSectionChanged(`team-title:${selector}`, {
        icon, text, side, groups: Array.from(groups).sort()
    })) return;

    el.innerHTML = `
        <i class="fa-solid ${icon}"></i> ${text}
        <span class="dash-side-pill ${meta.cls}"><i class="fa-solid ${meta.icon}"></i> ${side}</span>
        ${groups.size ? `<span class="dash-party-count" title="${groups.size} stack${groups.size > 1 ? "s" : ""} queued together on this team">
            <i class="fa-solid fa-link"></i> ${groups.size} ${groups.size === 1 ? "Stack" : "Stacks"}</span>` : ""}
    `;
}

function renderRoster(el, players) {
    if (!el) return;

    if (!dashboardSectionChanged(`roster:${el.id || "unknown"}`, players || [])) return;

    if (!players || !players.length) {
        el.innerHTML = '<p class="dash-roster-empty">No players yet.</p>';
        return;
    }

    el.innerHTML = players.map(p => {
        const tierIcon = p.tier_icon || DEFAULT_UNRANKED_ICON;
        const tierLabel = p.tier_label || "Unranked";
        const hasRank = (p.tier && p.tier > 0);
        const hasPeak = (p.peak_tier && p.peak_tier > 0 && p.peak_tier !== p.tier);

        // Premades: your own party is confirmed by Riot, everyone else is
        // inferred from party ids & co-occurrences across recent matches.
        const group = p.party_group || 0;
        const tag = p.party_tag || (p.party_size === 2 ? "DUO" : (p.party_size === 3 ? "TRIO" : (p.party_size > 3 ? `${p.party_size}-STACK` : "")));
        const partnerText = (p.party_partners && p.party_partners.length > 0)
            ? p.party_partners.join(", ")
            : "";

        const partyChip = group ? `
            <span class="dash-party-chip pg-${((group - 1) % 5) + 1} ${p.party_confirmed ? "is-confirmed" : ""}"
                  title="${p.party_confirmed
                      ? `In your party (${tag}) with: ${escapeHtml(partnerText || 'you')}`
                      : `Queued (${tag}) with: ${escapeHtml(partnerText || 'teammates')} (matched in recent games)`}">
                <i class="fa-solid ${p.party_confirmed ? "fa-user-group" : "fa-link"}"></i> ${tag}
            </span>` : "";

        const stat = (cls, icon, value, title) => `
            <span class="dash-player-stat-pill ${cls}" title="${escapeHtml(title)}">
                <i class="fa-solid ${icon}"></i> ${escapeHtml(String(value))}
            </span>`;

        const wrValue = (p.winrate_last5 !== undefined && p.winrate_last5 !== null)
            ? `${p.winrate_last5}% WR`
            : `${p.winrate || 0}% WR`;
        const wrTitle = (p.last5_games && p.last5_games > 0)
            ? `Winrate across last ${p.last5_games} matches (${p.last5_wins}W ${p.last5_losses}L)`
            : `${p.wins || 0} wins from ${p.games || 0} ranked games`;

        const formPips = (p.last5_form && p.last5_form.length > 0)
            ? `<div class="dash-player-form-pips" title="Recent form: ${p.last5_form.join(' ')}">
                 ${p.last5_form.map(f => `<span class="dash-form-mini-pip is-${f.toLowerCase()}">${f}</span>`).join('')}
               </div>`
            : "";

        return `
            <button type="button" class="dash-player ${p.is_self ? "is-self" : ""} ${p.locked ? "is-locked" : ""} ${group ? `has-party pg-${((group - 1) % 5) + 1}` : ""}" onclick="openPlayerProfile(decodeURIComponent('${encodeURIComponent(p.name || "")}'))" title="Check this player's match history">
                <div class="dash-player-lead">
                    ${p.agent_icon
                        ? `<img src="${p.agent_icon}" class="dash-player-agent" alt="${escapeHtml(p.agent)}" onerror="this.style.visibility='hidden';">`
                        : `<span class="dash-player-agent is-empty"><i class="fa-solid fa-user"></i></span>`}
                    ${p.locked ? `<span class="dash-player-locked" title="Locked in"><i class="fa-solid fa-lock"></i></span>` : ""}
                </div>

                <div class="dash-player-info">
                    <div class="dash-player-name-row">
                        <span class="dash-player-name">${escapeHtml(p.name || (p.is_self ? "You" : (p.incognito ? "Hidden" : "Resolving…")))}</span>
                        ${p.is_self ? `<span class="dash-self-tag">YOU</span>` : ""}
                        ${partyChip}
                    </div>
                    <div class="dash-player-sub">
                        <span>${escapeHtml(p.agent || "Picking…")}</span>
                        ${p.level ? `<span class="dash-player-lvl">LV ${p.level}</span>` : ""}
                        ${hasPeak ? `<span class="dash-player-peak" title="Peak rank">
                            <img src="${p.peak_tier_icon || DEFAULT_UNRANKED_ICON}" alt="" onerror="this.style.display='none';">
                            ${escapeHtml(p.peak_tier_label || "")}</span>` : ""}
                    </div>
                    <div class="dash-player-stats-row">
                        ${stat("is-kd", "fa-crosshairs", p.kd > 0 ? `${p.kd} KD` : "-- KD", "Recent matches K/D")}
                        ${stat("is-hs", "fa-bullseye", p.hs_pct > 0 ? `${p.hs_pct}% HS` : "-- HS", "Recent matches Headshot accuracy")}
                        ${stat("is-adr", "fa-burst", p.adr > 0 ? `${p.adr} ADR` : "-- ADR", "Average damage per round")}
                        ${stat("is-wr", "fa-chart-simple", wrValue, wrTitle)}
                        ${formPips}
                    </div>
                </div>

                <div class="dash-player-rank" title="${escapeHtml(tierLabel)}${p.rr ? ` (${p.rr} RR)` : ""}">
                    <img src="${tierIcon}" alt="${escapeHtml(tierLabel)}" onerror="this.src='${DEFAULT_UNRANKED_ICON}';">
                    <span class="dash-player-rr">${hasRank && p.rr ? `${p.rr} RR` : (hasRank ? "" : "Unranked")}</span>
                </div>
            </button>
        `;
    }).join("");
}

// -- PLAY -----------------------------------------------------------------

/**
 * One click only. The button re-opens when the game is confirmed running
 * (nothing left to do), when the launch is confirmed failed, or when the
 * game disappears again - never while a launch is still in flight.
 */
function renderPlayButton(live) {
    const launch = (live && live.launch) || {};
    const running = !!(live && live.valorant_running);
    const launching = !!launch.active || (state.playPending && !running);

    // The optimistic lock is dropped as soon as the backend owns the state.
    if (state.playPending && (launch.active || running || launch.stage === "failed")) {
        state.playPending = false;
    }

    let label = "PLAY";
    let icon = "fa-solid fa-play";
    let disabled = false;
    let cls = "btn-dash-play";
    let title = "Force-start VALORANT for this account";

    if (!live || !live.available) {
        label = "NO SESSION";
        disabled = true;
        title = "Sign in to an account first.";
    } else if (running) {
        label = "RUNNING";
        icon = "fa-solid fa-circle-check";
        disabled = true;
        cls += " is-running";
        title = "VALORANT is already running.";
    } else if (launching) {
        label = "STARTING…";
        icon = "fa-solid fa-circle-notch";
        disabled = true;
        cls += " is-launching";
        title = launch.message || "Starting VALORANT…";
    } else if (launch.stage === "failed") {
        label = "RETRY";
        icon = "fa-solid fa-rotate-right";
        title = launch.message || "VALORANT didn't start - try again.";
    }

    if (DOM.btnDashPlay) {
        DOM.btnDashPlay.className = cls;
        DOM.btnDashPlay.disabled = disabled;
        DOM.btnDashPlay.title = title;
        const iconEl = DOM.btnDashPlay.querySelector("i");
        if (iconEl) iconEl.className = icon;
        if (DOM.dashPlayLabel) DOM.dashPlayLabel.textContent = label;
    }

    if (DOM.btnSessionPlay) {
        DOM.btnSessionPlay.disabled = disabled;
        if (DOM.sessionPlayLabel) {
            DOM.sessionPlayLabel.textContent = running ? "Running" : (launching ? "Starting…" : "Play");
        }
    }
}

async function forceLaunchValorant() {
    if (state.playPending) return;
    state.playPending = true;
    renderPlayButton(state.live);

    try {
        const res = await fetch("/api/live/launch", { method: "POST" });
        const data = await res.json();
        showToast(data.message || "Starting VALORANT…", data.success ? "success" : "error");

        if (!data.success) state.playPending = false;
        if (data.launch) state.live = { ...(state.live || {}), launch: data.launch };
        renderPlayButton(state.live);
    } catch (err) {
        state.playPending = false;
        showToast("Couldn't reach the app's backend", "error");
        renderPlayButton(state.live);
    }

    // The backend confirms the process itself; this just gets the first
    // update on screen quickly.
    scheduleLivePoll(1500);
}

// -- queue & mode control ------------------------------------------------

/** Queue the dashboard will start: the pending pick, else what the client has. */
function activeQueueId(live) {
    return state.pendingQueueId || (live && live.queue_id) || "competitive";
}

function modeById(queueId) {
    return (state.modes || []).find(m => m.id === queueId) || null;
}

function renderQueueControls(live) {
    const inQueue = !!(live.party && live.party.in_queue);
    const inMatch = !!live.match;
    const canControl = !!live.valorant_running;

    const queueId = activeQueueId(live);
    const mode = modeById(queueId);
    const modeName = mode ? mode.name : (live.queue_label || "Competitive");

    // The client caught up with the pending pick - stop overriding it.
    if (state.pendingQueueId && live.queue_id === state.pendingQueueId) {
        state.pendingQueueId = null;
    }

    // -- CTA -----------------------------------------------------------
    if (DOM.dashCtaIcon) DOM.dashCtaIcon.className = mode ? mode.icon : "fa-solid fa-trophy";

    let ctaTitle = `Start ${modeName} Match`;
    let ctaSub = `Queues up for ${modeName}`;

    if (!canControl) {
        ctaTitle = "VALORANT isn't running";
        ctaSub = "Press PLAY to start the game first";
    } else if (inMatch) {
        ctaTitle = live.match.phase === "agent_select" ? "In agent select" : "You're in a match";
        ctaSub = "Finish or leave it before queueing again";
    } else if (inQueue) {
        ctaTitle = "Matchmaking (In Queue)";
        ctaSub = `Searching for ${live.queue_label || modeName}`;
    }

    if (DOM.dashCtaTitle) DOM.dashCtaTitle.textContent = ctaTitle;
    if (DOM.dashCtaSub) DOM.dashCtaSub.textContent = ctaSub;

    DOM.btnStartRanked.disabled = !canControl || inQueue || inMatch;
    DOM.btnStartRanked.classList.toggle("is-queued", inQueue);

    DOM.btnQueueStop.disabled = !canControl || !inQueue;
    DOM.btnQueueStop.style.display = inQueue ? "flex" : "none";

    // -- status line ---------------------------------------------------
    if (inQueue) {
        DOM.dashQueueStatus.textContent =
            `Matchmaking (In Queue) · ${live.queue_label || modeName} · ${formatClock(live.queue_elapsed || 0)}`;
    } else if (inMatch) {
        DOM.dashQueueStatus.textContent = `In a ${live.match.mode || modeName} match`;
    } else {
        DOM.dashQueueStatus.textContent = `Mode: ${modeName}`;
    }
    DOM.dashQueueStatus.classList.toggle("is-searching", inQueue);

    DOM.dashModeGrid.querySelectorAll(".dash-mode-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.queue === queueId);
        b.disabled = !canControl || inQueue || inMatch;
    });
}

function renderModeGrid() {
    if (!DOM.dashModeGrid) return;

    DOM.dashModeGrid.innerHTML = (state.modes || []).map(m => `
        <button class="dash-mode-btn" data-queue="${escapeHtml(m.id)}" title="Switch to ${escapeHtml(m.name)}">
            <i class="${escapeHtml(m.icon)}"></i>
            <span>${escapeHtml(m.name)}</span>
        </button>
    `).join("");

    DOM.dashModeGrid.querySelectorAll(".dash-mode-btn").forEach(btn => {
        btn.addEventListener("click", () => changeMode(btn.dataset.queue));
    });
}

async function changeMode(queueId) {
    // Reflect the pick immediately - the CTA is the thing people watch to
    // confirm the mode took.
    state.pendingQueueId = queueId;
    if (state.live) renderQueueControls(state.live);

    try {
        const res = await fetch("/api/live/mode", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ queue_id: queueId })
        });
        const data = await res.json();
        if (!data.success) {
            state.pendingQueueId = null;
            showToast(data.message || "Couldn't change mode", "error");
        }
        scheduleLivePoll(0);
    } catch (err) {
        state.pendingQueueId = null;
        showToast("Couldn't reach the game client", "error");
    }
}

async function startQueue(queueId) {
    const target = queueId || activeQueueId(state.live);
    try {
        const res = await fetch("/api/live/queue/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ queue_id: target || null })
        });
        const data = await res.json();
        showToast(data.message || (data.success ? "Matchmaking started" : "Couldn't start the queue"),
                  data.success ? "success" : "error");
        if (data.success) {
            state.queueStartedAt = Date.now();
            startQueueClock();
        }
        scheduleLivePoll(0);
    } catch (err) {
        showToast("Couldn't reach the game client", "error");
    }
}

async function stopQueue() {
    try {
        const res = await fetch("/api/live/queue/stop", { method: "POST" });
        const data = await res.json();
        showToast(data.message || "Left the queue", data.success ? "info" : "error");
        if (data.success) state.queueStartedAt = 0;
        scheduleLivePoll(0);
    } catch (err) {
        showToast("Couldn't reach the game client", "error");
    }
}

// -- queue clock ----------------------------------------------------------

function formatClock(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function renderQueueClock() {
    if (!DOM.dashQueueClock) return;
    const elapsed = state.queueStartedAt ? (Date.now() - state.queueStartedAt) / 1000 : 0;
    DOM.dashQueueClock.textContent = formatClock(elapsed);
}

// Ticks locally so the timer counts every second instead of jumping with
// the poll interval.
function startQueueClock() {
    stopQueueClock();
    state._queueTimer = setInterval(renderQueueClock, 1000);
}

function stopQueueClock() {
    clearInterval(state._queueTimer);
    state._queueTimer = null;
}

// -- insta-lock ----------------------------------------------------------

function renderAgentGrid() {
    if (!DOM.dashAgentGrid) return;

    const query = (DOM.dashAgentSearch ? DOM.dashAgentSearch.value : "").trim().toLowerCase();
    const agents = state.agents.filter(a => !query || a.name.toLowerCase().includes(query));

    if (!agents.length) {
        DOM.dashAgentGrid.innerHTML = `<p class="dash-roster-empty">${
            state.agents.length ? "No agents match that search." : "Agent list unavailable - check your connection."
        }</p>`;
        return;
    }

    DOM.dashAgentGrid.innerHTML = agents.map(a => `
        <button class="dash-agent-btn ${a.id === state.selectedAgentId ? "active" : ""}"
                data-agent="${escapeHtml(a.id)}" title="${escapeHtml(a.name)}${a.role ? " · " + escapeHtml(a.role) : ""}">
            <img src="${a.icon}" alt="${escapeHtml(a.name)}" onerror="this.style.visibility='hidden';">
            <span>${escapeHtml(a.name)}</span>
        </button>
    `).join("");

    DOM.dashAgentGrid.querySelectorAll(".dash-agent-btn").forEach(btn => {
        btn.addEventListener("click", () => selectAgent(btn.dataset.agent));
    });
}

function selectAgent(agentId) {
    state.selectedAgentId = state.selectedAgentId === agentId ? null : agentId;
    renderAgentGrid();
    updateInstalockControls();
}

function updateInstalockControls() {
    const lock = state.instalock || {};
    const armed = !!lock.enabled;
    const agent = state.agents.find(a => a.id === state.selectedAgentId);

    if (DOM.btnInstalockToggle) {
        DOM.btnInstalockToggle.disabled = !armed && !state.selectedAgentId;
        DOM.btnInstalockToggle.classList.toggle("is-armed", armed);
        DOM.btnInstalockToggle.title = armed
            ? `Insta-lock is on for ${lock.agent_name || "your agent"} - click to turn it off`
            : "Locks your agent the moment agent select opens";
        if (DOM.instalockLabel) {
            DOM.instalockLabel.textContent = armed
                ? `INSTALOCK · ${(lock.agent_name || "ON").toUpperCase()}`
                : "INSTALOCK";
        }
    }

    if (DOM.dashInstalockPill) {
        const locked = lock.status === "locked";
        DOM.dashInstalockPill.textContent = armed ? (locked ? "LOCKED" : "ON") : "OFF";
        DOM.dashInstalockPill.className =
            `dash-instalock-pill ${armed ? "is-armed" : ""} ${locked ? "is-locked" : ""}`;
    }

    if (DOM.dashInstalockStatus) {
        DOM.dashInstalockStatus.textContent = lock.message ||
            (state.selectedAgentId && !armed
                ? `${agent ? agent.name : "Agent"} ready - press INSTALOCK to turn it on.`
                : "");
        DOM.dashInstalockStatus.className =
            `dash-instalock-status ${lock.status === "failed" ? "is-error" : (lock.status === "locked" ? "is-ok" : "")}`;
    }

    const inPregame = !!(state.live && state.live.match && state.live.match.phase === "agent_select");
    if (DOM.btnLockNow) DOM.btnLockNow.disabled = !inPregame || !state.selectedAgentId;
}

const INSTALOCK_REFRESH_PREGAME = 1500;
const INSTALOCK_REFRESH_NORMAL = 5000;

async function refreshInstalockStatus(force = false) {
    const now = Date.now();
    const phase = state.live && state.live.match && state.live.match.phase;
    const minAge = phase === "agent_select"
        ? INSTALOCK_REFRESH_PREGAME
        : INSTALOCK_REFRESH_NORMAL;

    if (!force && state._instalockCheckedAt && now - state._instalockCheckedAt < minAge) {
        return state.instalock;
    }
    if (state._instalockPromise) return state._instalockPromise;

    // Count attempts as well as successes so a temporarily unavailable local
    // endpoint cannot turn the live loop into an error-request storm.
    state._instalockCheckedAt = now;
    const task = (async () => {
        try {
            const res = await fetch("/api/live/instalock");
            state.instalock = await res.json();
            state._instalockCheckedAt = Date.now();
            if (state.instalock.enabled && state.instalock.agent_id && !state.selectedAgentId) {
                state.selectedAgentId = state.instalock.agent_id;
                renderAgentGrid();
            }
        } catch (err) {
            state.instalock = {};
        }
        updateInstalockControls();
        return state.instalock;
    })();

    state._instalockPromise = task;
    try {
        return await task;
    } finally {
        if (state._instalockPromise === task) state._instalockPromise = null;
    }
}

async function toggleInstalock() {
    const armed = !!(state.instalock && state.instalock.enabled);
    const payload = armed
        ? { enabled: false }
        : { enabled: true, agent_id: state.selectedAgentId };

    if (!armed && !state.selectedAgentId) {
        showToast("Pick an agent first.", "info");
        return;
    }

    try {
        const res = await fetch("/api/live/instalock", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        state.instalock = data.instalock || {};
        showToast(data.message || "Insta-lock updated", data.success ? "success" : "error");
        updateInstalockControls();
    } catch (err) {
        showToast("Couldn't update insta-lock", "error");
    }
}

async function lockAgentNow() {
    if (!state.selectedAgentId) return;
    try {
        const res = await fetch("/api/live/lock-now", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent_id: state.selectedAgentId })
        });
        const data = await res.json();
        showToast(data.message || "Lock attempted", data.success ? "success" : "error");
        scheduleLivePoll(0);
    } catch (err) {
        showToast("Couldn't reach the game client", "error");
    }
}

// ==========================================================================
// PLAYER STATS & INVENTORY
// ==========================================================================

const STATS_REFRESH = 30000;

async function refreshPlayerStats(force = false) {
    clearTimeout(state._statsTimer);

    if (state._statsDirty) {
        force = true;
        state._statsDirty = false;
    }

    try {
        const res = await fetch(`/api/live/stats${force ? "?force=true" : ""}`);
        state.playerStats = await res.json();
    } catch (err) {
        state.playerStats = { available: false, message: "Couldn't reach the app's backend." };
    }

    renderPlayerStats();
    renderInventory();

    // Keep polling while a stats tab is on screen - the first response is
    // usually still building in the background.
    if (state.dashboardOpen && (state.dashTab === "stats" || state.dashTab === "inventory")) {
        const wait = state.playerStats && state.playerStats.loading ? 3000 : STATS_REFRESH;
        state._statsTimer = setTimeout(() => refreshPlayerStats(), wait);
    }
}

function statsPlaceholder(stats) {
    if (stats && stats.loading) {
        return `<div class="dash-stats-empty">
            <i class="fa-solid fa-circle-notch fa-spin"></i>
            <span>Reading your profile from Riot…</span>
        </div>`;
    }
    return `<div class="dash-stats-empty">
        <i class="fa-solid fa-chart-simple"></i>
        <span>${escapeHtml((stats && stats.message) || "Start VALORANT to load your live profile.")}</span>
    </div>`;
}

function renderPlayerStats() {
    if (!DOM.dashStatsBody) return;
    const s = state.playerStats;

    if (!s || !s.available) {
        DOM.dashStatsBody.innerHTML = statsPlaceholder(s);
        return;
    }

    const rank = s.rank || {};
    const peak = s.peak || {};
    const combat = s.combat || {};
    const lifetime = s.lifetime || {};
    const act = s.act || {};

    const rrPct = Math.max(0, Math.min(100, rank.rr || 0));
    const streakCls = s.streak_type === "Win" ? "is-win" : "is-loss";

    DOM.dashStatsBody.innerHTML = `
        <div class="stat-hero">
            <div class="stat-hero-rank">
                <img src="${rank.icon || DEFAULT_TIER_ICON}" alt="${escapeHtml(rank.label || "Unranked")}"
                     onerror="this.style.visibility='hidden';">
                <div class="stat-hero-label">
                    <strong>${escapeHtml(rank.label || "Unranked")}</strong>
                    <span>${rank.leaderboard ? `Leaderboard #${rank.leaderboard}` : (act.label || "Current act")}</span>
                </div>
            </div>

            <div class="stat-rr">
                <div class="stat-rr-top">
                    <span>Rank Rating</span>
                    <b>${rank.rr || 0} RR</b>
                </div>
                <div class="stat-rr-track"><div class="stat-rr-fill" style="width:${rrPct}%"></div></div>
                <div class="stat-rr-top">
                    <span>${act.label || "This act"}</span>
                    <b>${act.wins || 0}W · ${act.losses || 0}L</b>
                </div>
            </div>

            <div class="stat-hero-peak">
                <img src="${peak.icon || DEFAULT_TIER_ICON}" alt="Peak rank" onerror="this.style.display='none';">
                <div>
                    <small>Peak</small>
                    <b>${escapeHtml(peak.label || "Unranked")}${peak.season ? ` · ${escapeHtml(peak.season)}` : ""}</b>
                </div>
            </div>
        </div>

        <div class="stat-tiles">
            ${statTile("Winrate", `${act.winrate || 0}%`,
                       `${act.games || 0} ranked games`, winrateClass(act.winrate))}
            ${statTile("Headshot %", `${combat.hs || 0}%`,
                       `Last ${combat.matches || 0} matches`, "is-accent")}
            ${statTile("K/D", combat.kd || 0, `KDA ${combat.kda || 0}`, combat.kd >= 1 ? "is-ok" : "is-bad")}
            ${statTile("ACS", combat.acs || 0, "Avg combat score", "is-gold")}
            ${statTile("Avg K/D/A", `${combat.avg_kills || 0}/${combat.avg_deaths || 0}/${combat.avg_assists || 0}`,
                       "Per match", "")}
            ${statTile("Lifetime", `${lifetime.winrate || 0}%`,
                       `${lifetime.wins || 0}W · ${lifetime.losses || 0}L`, winrateClass(lifetime.winrate))}
        </div>

        <div class="stat-block">
            <h5 class="stat-block-title">
                <i class="fa-solid fa-wave-square"></i> Recent Form
                ${s.streak ? `<span class="stat-streak ${streakCls}">
                    <i class="fa-solid ${s.streak_type === "Win" ? "fa-fire" : "fa-arrow-trend-down"}"></i>
                    ${s.streak} ${s.streak_type === "Win" ? "win" : "loss"} streak
                </span>` : `<span class="stat-block-note">${s.recent_wins || 0}W · ${s.recent_losses || 0}L in the last ${(s.form || []).length}</span>`}
            </h5>
            <div class="stat-form">
                ${(s.form || []).map((f, i) => `
                    <span class="form-pip ${f.result === "Win" ? "is-win" : f.result === "Loss" ? "is-loss" : "is-draw"}"
                          style="animation-delay:${i * 40}ms"
                          title="${escapeHtml(f.map || "")} · ${f.rr > 0 ? "+" : ""}${f.rr} RR">
                        ${f.result === "Win" ? "W" : f.result === "Loss" ? "L" : "D"}
                    </span>
                `).join("") || '<span class="dash-roster-empty">No ranked games yet.</span>'}
            </div>
            ${renderSparkline(s.rr_history || [])}
        </div>

        ${(s.top_agents || []).length ? `
        <div class="stat-block">
            <h5 class="stat-block-title"><i class="fa-solid fa-user-ninja"></i> Top Agents
                <span class="stat-block-note">Last ${combat.matches || 0} matches</span>
            </h5>
            <div class="stat-agents">
                ${s.top_agents.map(a => `
                    <div class="stat-agent-row">
                        <img src="${a.icon}" alt="${escapeHtml(a.name)}" onerror="this.style.visibility='hidden';">
                        <div class="stat-agent-meta">
                            <strong>${escapeHtml(a.name)}</strong>
                            <div class="stat-agent-bar"><span style="width:${a.winrate}%"></span></div>
                        </div>
                        <div class="stat-agent-nums">
                            <span>${a.winrate}% WR</span>
                            <small>${a.matches} played · ${a.kd} K/D</small>
                        </div>
                    </div>
                `).join("")}
            </div>
        </div>` : ""}

        ${(s.recent || []).length ? `
        <div class="stat-block">
            <h5 class="stat-block-title"><i class="fa-solid fa-clock-rotate-left"></i> Match History & Performance</h5>
            <div class="stat-matches">
                ${s.recent.map((m, i) => {
                    const isWin = m.result === "Win";
                    const isLoss = m.result === "Loss";
                    const outcomeText = isWin ? "VICTORY" : (isLoss ? "DEFEAT" : "DRAW");
                    const scoreText = m.placement ? `#${m.placement}` : `${m.rounds_won} – ${m.rounds_lost}`;
                    return `
                    <button type="button" class="stat-match ${isWin ? "is-win" : (isLoss ? "is-loss" : "")}" onclick="openMatchDetail(${i}, 'dashboard')" title="Open full match details">
                        <span class="stat-match-flag"></span>
                        <div class="stat-match-agent-wrap">
                            <img src="${m.agent_icon}" alt="${escapeHtml(m.agent)}" class="stat-match-agent-img" onerror="this.style.visibility='hidden';">
                        </div>
                        <div class="stat-match-meta">
                            <div class="stat-match-title-row">
                                <span class="stat-match-outcome ${isWin ? 'is-win' : (isLoss ? 'is-loss' : '')}">${outcomeText}</span>
                                <strong class="stat-match-map">${escapeHtml(m.map || "Unknown")}</strong>
                                <span class="stat-match-score-pill">${scoreText}</span>
                                ${m.surrendered ? `<span class="stat-match-surrender-pill" title="Match concluded early via surrender"><i class="fa-solid fa-flag"></i> Surrender</span>` : ""}
                            </div>
                            <div class="stat-match-details-row">
                                <span class="stat-match-mode">${escapeHtml(m.mode || "Competitive")}</span>
                                <span class="stat-match-metric is-hs" title="Match Headshot Accuracy"><i class="fa-solid fa-bullseye"></i> ${m.hs || 0}% HS</span>
                                <span class="stat-match-metric is-adr" title="Average Damage per Round"><i class="fa-solid fa-fire-flame-curved"></i> ${m.adr || 0} ADR</span>
                                <span class="stat-match-metric is-acs" title="Average Combat Score"><i class="fa-solid fa-bolt"></i> ${m.acs || 0} ACS</span>
                            </div>
                        </div>
                        <div class="stat-match-kda-wrap">
                            <div class="stat-match-kda-numbers">
                                <span class="stat-kda-score">${m.kills} <small>/</small> ${m.deaths} <small>/</small> ${m.assists}</span>
                            </div>
                            <div class="stat-match-kd-pill ${m.kd >= 1 ? 'is-positive' : 'is-negative'}">
                                ${m.kd} K/D
                            </div>
                        </div>
                    </button>
                `}).join("")}
            </div>
        </div>` : ""}
    `;
    state.dashboardMatches = s.recent || [];
}

function winrateClass(wr) {
    if (!wr) return "";
    return wr >= 50 ? "is-ok" : "is-bad";
}

function statTile(label, value, sub, cls) {
    return `<div class="stat-tile">
        <span class="stat-tile-label">${escapeHtml(label)}</span>
        <span class="stat-tile-value ${cls || ""}">${escapeHtml(String(value))}</span>
        <span class="stat-tile-sub">${escapeHtml(sub || "")}</span>
    </div>`;
}

/** RR over the last games, drawn as a self-scaling sparkline. */
function renderSparkline(points) {
    if (!points || points.length < 2) return "";

    const w = 100, h = 30;
    const min = Math.min(...points);
    const max = Math.max(...points);
    const span = Math.max(max - min, 1);

    const coords = points.map((p, i) => {
        const x = (i / (points.length - 1)) * w;
        const y = h - ((p - min) / span) * (h - 4) - 2;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
    });

    return `<svg class="stat-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
        <defs>
            <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="var(--a-soft)" stop-opacity="0.4"/>
                <stop offset="100%" stop-color="var(--a-soft)" stop-opacity="0"/>
            </linearGradient>
        </defs>
        <polygon class="stat-spark-area" points="0,${h} ${coords.join(" ")} ${w},${h}"/>
        <polyline class="stat-spark-line" points="${coords.join(" ")}"/>
    </svg>`;
}

function renderInventory() {
    if (!DOM.dashInventoryBody) return;
    const s = state.playerStats;

    if (!s || !s.available || !s.inventory) {
        DOM.dashInventoryBody.innerHTML = statsPlaceholder(s);
        return;
    }

    const inv = s.inventory;
    const pct = inv.skins_total ? Math.round((inv.skins_owned / inv.skins_total) * 100) : 0;

    DOM.dashInventoryBody.innerHTML = `
        <div class="stat-tiles inv-collection">
            ${statTile("Skins Owned", inv.skins_owned || 0, `${pct}% of ${inv.skins_total || 0}`, "is-gold")}
            ${statTile("Collection Value", `${(inv.value_vp || 0).toLocaleString()}`, "VP spent on skins", "is-accent")}
            ${statTile("Agents", inv.agents_owned || 0, "Unlocked", "")}
            ${statTile("Buddies", inv.buddies || 0, "Gun charms", "")}
            ${statTile("Sprays", inv.sprays || 0, "Owned", "")}
            ${statTile("Player Cards", inv.cards || 0, "Owned", "")}
        </div>

        <div class="stat-block">
            <h5 class="stat-block-title">
                <i class="fa-solid fa-gun"></i> Equipped Loadout
                <span class="stat-block-note">${(inv.loadout || []).length} weapons</span>
            </h5>
            ${(inv.loadout || []).length ? `
            <div class="inv-loadout">
                ${inv.loadout.map(g => `
                    <div class="inv-skin" style="--skin-tint:${g.tier_color ? g.tier_color + "33" : "transparent"}">
                        <div class="inv-skin-top">
                            <span class="inv-skin-weapon">${escapeHtml(g.weapon)}</span>
                            ${g.tier_icon ? `<img class="inv-skin-tier" src="${g.tier_icon}" alt="${escapeHtml(g.tier)}" title="${escapeHtml(g.tier)}" onerror="this.style.display='none';">` : ""}
                        </div>
                        <span class="inv-skin-name ${g.is_default ? "is-default" : ""}">${escapeHtml(g.skin)}</span>
                        ${g.icon ? `<img class="inv-skin-art" src="${g.icon}" alt="" onerror="this.style.display='none';">` : ""}
                    </div>
                `).join("")}
            </div>` : '<p class="dash-roster-empty">Loadout unavailable - open VALORANT to the menus.</p>'}
        </div>
    `;
}

// ==========================================================================

function initLiveEventListeners() {
    if (DOM.btnSessionPlay) {
        DOM.btnSessionPlay.addEventListener("click", () => {
            if (state.activeAccountId) playAccount(state.activeAccountId);
            else forceLaunchValorant();
        });
    }

    if (DOM.btnOpenDashboard) DOM.btnOpenDashboard.addEventListener("click", openDashboard);
    if (DOM.btnToggleDashboard) DOM.btnToggleDashboard.addEventListener("click", toggleDashboard);
    if (DOM.dashClose) DOM.dashClose.addEventListener("click", closeDashboard);
    if (DOM.btnDashPlay) DOM.btnDashPlay.addEventListener("click", forceLaunchValorant);

    if (DOM.dashTabs) {
        DOM.dashTabs.querySelectorAll(".dash-tab").forEach(btn => {
            btn.addEventListener("click", () => switchDashTab(btn.dataset.tab));
        });
    }

    if (DOM.btnStartRanked) DOM.btnStartRanked.addEventListener("click", () => startQueue(null));
    if (DOM.btnQueueStop) DOM.btnQueueStop.addEventListener("click", stopQueue);

    if (DOM.btnInstalockToggle) DOM.btnInstalockToggle.addEventListener("click", toggleInstalock);
    if (DOM.btnLockNow) DOM.btnLockNow.addEventListener("click", lockAgentNow);
    if (DOM.dashAgentSearch) DOM.dashAgentSearch.addEventListener("input", renderAgentGrid);

    // The glide pill is measured from layout, so it has to re-settle when the
    // panel changes width.
    window.addEventListener("resize", () => {
        if (state.dashboardOpen) moveTabGlide();
    });
}

// ==========================================================================
// SETTINGS PRESET
//
// The preset is captured from whichever account is signed in right now, not
// from a stored account. That's the whole point: most accounts have real
// settings sitting on this PC but no puuid stored, so they can't be picked
// from a list - but the live Riot Client always knows who is signed in.
//
// Every action reports exactly what it moved, so "it copied" can be checked
// against real values rather than taken on trust.
// ==========================================================================

/** Loads the saved preset and renders its summary. */
async function loadPreset() {
    if (!DOM.presetSummary) return;
    try {
        const res = await fetch("/api/game-config/preset");
        state.preset = await res.json();
    } catch (err) {
        state.preset = null;
    }
    renderPresetSummary();
}

function renderPresetSummary() {
    if (!DOM.presetSummary) return;
    const p = state.preset;

    if (!p || !p.exists) {
        DOM.presetSummary.innerHTML =
            '<span class="preset-empty">Nothing saved yet. Sign into the account whose settings you want, ' +
            'then press <strong>Save Current Account As Preset</strong>.</span>';
        if (DOM.presetWhen) DOM.presetWhen.textContent = "";
        return;
    }

    const d = p.details || {};
    const meta = p.meta || {};
    if (DOM.presetWhen) {
        DOM.presetWhen.textContent = meta.captured_at
            ? `from ${meta.label || "an account"} · ${formatPresetDate(meta.captured_at)}`
            : (meta.label ? `from ${meta.label}` : "");
    }

    const rows = [
        ["Crosshair profile", d.crosshair_profile],
        ["Sensitivity", d.sensitivity],
        ["Scoped sensitivity", d.scoped_sensitivity],
        ["Keybinds", d.keybind_count != null ? `${d.keybind_count} bound` : ""],
        ["Display mode", d.display_mode],
        ["Resolution", d.resolution]
    ].filter(r => r[1] !== undefined && r[1] !== null && String(r[1]).trim() !== "");

    const fileRows = (p.files || []).map(f =>
        `<li class="${f.present ? "is-present" : "is-missing"}">
            <i class="fa-solid ${f.present ? "fa-circle-check" : "fa-circle-xmark"}"></i>
            <span class="preset-file-label">${escapeHtml(f.label)}</span>
            <span class="preset-file-meta">${f.present ? formatBytes(f.size) : "not captured"}</span>
         </li>`).join("");

    DOM.presetSummary.innerHTML =
        `<ul class="preset-files">${fileRows}</ul>` +
        (rows.length
            ? `<div class="preset-values">${rows.map(([k, v]) =>
                `<div class="preset-value"><span>${escapeHtml(k)}</span><strong>${escapeHtml(String(v))}</strong></div>`
              ).join("")}</div>`
            : "");
}

function formatPresetDate(iso) {
    try {
        const d = new Date(iso);
        return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    } catch (e) {
        return iso;
    }
}

function formatBytes(n) {
    if (!n) return "0 B";
    return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`;
}

/** Shows the result panel: what moved, what didn't, and the values that landed. */
function showPresetLog(title, data, ok) {
    if (!DOM.presetLog) return;
    DOM.presetLog.style.display = "block";
    DOM.presetLog.classList.toggle("is-error", !ok);
    DOM.presetLogTitle.innerHTML =
        `<i class="fa-solid ${ok ? "fa-clipboard-check" : "fa-triangle-exclamation"}"></i> ${escapeHtml(title)}`;

    const parts = [];
    if (data.message) parts.push(`<p class="preset-log-msg">${escapeHtml(data.message)}</p>`);

    // Per-file outcome, for a capture or a single-account load.
    if (data.files && data.files.length) {
        parts.push(`<div class="preset-log-section">Files</div><ul class="preset-files">` +
            data.files.map(f =>
                `<li class="${f.present ? "is-present" : "is-missing"}">
                    <i class="fa-solid ${f.present ? "fa-circle-check" : "fa-circle-xmark"}"></i>
                    <span class="preset-file-label">${escapeHtml(f.label)}</span>
                    <span class="preset-file-meta">${f.present ? formatBytes(f.size) : "not found"}</span>
                 </li>`).join("") + `</ul>`);
    }

    if (data.details && Object.keys(data.details).length) {
        const labels = {
            crosshair_profile: "Crosshair profile",
            sensitivity: "Sensitivity",
            scoped_sensitivity: "Scoped sensitivity",
            settings_lines: "Settings entries",
            keybind_count: "Keybinds",
            agent_keybinds: "Per-agent keybinds",
            display_mode: "Display mode",
            resolution: "Resolution"
        };
        const rows = Object.entries(data.details)
            .filter(([, v]) => v !== "" && v !== null && v !== undefined)
            .map(([k, v]) =>
                `<div class="preset-value"><span>${escapeHtml(labels[k] || k)}</span><strong>${escapeHtml(String(v))}</strong></div>`);
        if (rows.length) {
            parts.push(`<div class="preset-log-section">Values now stored</div>
                        <div class="preset-values">${rows.join("")}</div>`);
        }
    }

    // Per-account outcome, for a load-onto-all.
    if (data.applied && data.applied.length && typeof data.applied[0] === "object") {
        parts.push(`<div class="preset-log-section">Applied to ${data.applied.length}</div>
            <ul class="preset-accounts">` + data.applied.map(a =>
                `<li class="is-present"><i class="fa-solid fa-circle-check"></i>
                    <span>${escapeHtml(a.name)}</span>
                    <span class="preset-file-meta">${escapeHtml((a.files || []).length + " files")}</span></li>`
            ).join("") + `</ul>`);
    }

    if (data.skipped && data.skipped.length) {
        parts.push(`<div class="preset-log-section">Skipped ${data.skipped.length}</div>
            <ul class="preset-accounts">` + data.skipped.map(sk =>
                `<li class="is-missing"><i class="fa-solid fa-circle-minus"></i>
                    <span>${escapeHtml(sk.name)}</span>
                    <span class="preset-file-meta">${escapeHtml(sk.why || "")}</span></li>`
            ).join("") + `</ul>`);
    }

    if (data.failed && data.failed.length) {
        parts.push(`<div class="preset-log-section">Couldn't write</div>
            <ul class="preset-accounts">` + data.failed.map(f =>
                `<li class="is-missing"><i class="fa-solid fa-circle-xmark"></i><span>${escapeHtml(String(f))}</span></li>`
            ).join("") + `</ul>`);
    }

    DOM.presetLogBody.innerHTML = parts.join("");
}

async function presetRequest(btn, url, body, busyLabel, title) {
    const original = btn ? btn.innerHTML : "";
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner rotating"></i> ${busyLabel}`;
    }
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        showPresetLog(title, data, !!data.success);
        showToast(data.message || (data.success ? "Done." : "Didn't work."),
                  data.success ? "success" : "error");
        if (data.success) {
            loadPreset();
            loadGameConfigSettings();
        }
        return data;
    } catch (err) {
        showToast("Failed to reach the app's backend.", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = original;
        }
    }
}

function capturePreset() {
    return presetRequest(
        DOM.btnPresetCapture, "/api/game-config/preset/capture", {},
        "Saving...", "Saved from the signed-in account"
    );
}

function applyPresetToCurrent() {
    return presetRequest(
        DOM.btnPresetApply, "/api/game-config/preset/apply", {},
        "Loading...", "Loaded onto the signed-in account"
    );
}

async function applyPresetToAll() {
    const n = ((state.gameConfig || {}).accounts || []).filter(a => a.has_puuid).length;
    if (!confirm(
        `Load the saved preset onto every account Vortex has identified (${n} right now)?\n\n` +
        `This overwrites their crosshair, sensitivity, keybinds and video settings and can't be undone.`)) {
        return;
    }
    return presetRequest(
        DOM.btnPresetApplyAll, "/api/game-config/preset/apply", { all_accounts: true },
        "Loading...", "Loaded onto all accounts"
    );
}
