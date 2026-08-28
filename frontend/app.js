/**
 * Vortex Valorant Account Manager - Frontend Controller
 * Handles UI state, filtering, official rank icons, peak rank badges, match history drawer,
 * batch .TXT combo importer (username:password), live status badges (Playable/Banned/Suspended),
 * and automated full-roster account checker ("Check Accounts").
 */

// Global State
const state = {
    accounts: [],
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
    highlightId: null
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

    // Settings Modal
    modalSettings: document.getElementById("modal-settings"),
    modalSettingsClose: document.getElementById("modal-settings-close"),
    btnCancelSettings: document.getElementById("btn-cancel-settings"),
    btnSaveSettings: document.getElementById("btn-save-settings"),
    settingsClientPath: document.getElementById("settings-client-path"),
    settingsApiKey: document.getElementById("settings-api-key"),
    btnAutoDetectClient: document.getElementById("btn-auto-detect-client"),
    settingsAppVersion: document.getElementById("settings-app-version"),
    btnCheckUpdate: document.getElementById("btn-check-update"),
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

    // Live Match Dashboard
    modalDashboard: document.getElementById("modal-dashboard"),
    modalDashboardClose: document.getElementById("modal-dashboard-close"),
    dashRiotId: document.getElementById("dash-riot-id"),
    dashIdentitySub: document.getElementById("dash-identity-sub"),
    dashRankImg: document.getElementById("dash-rank-img"),
    dashLevel: document.getElementById("dash-level"),
    dashStateChip: document.getElementById("dash-state-chip"),
    dashStateLabel: document.getElementById("dash-state-label"),
    dashScoreboard: document.getElementById("dash-scoreboard"),
    dashScoreAlly: document.getElementById("dash-score-ally"),
    dashScoreEnemy: document.getElementById("dash-score-enemy"),
    dashRoundChip: document.getElementById("dash-round-chip"),
    dashMapName: document.getElementById("dash-map-name"),
    dashModeName: document.getElementById("dash-mode-name"),
    dashMapArt: document.getElementById("dash-map-art"),
    dashPregameBanner: document.getElementById("dash-pregame-banner"),
    dashPregameText: document.getElementById("dash-pregame-text"),
    dashPregameTimer: document.getElementById("dash-pregame-timer"),
    dashIdle: document.getElementById("dash-idle"),
    dashIdleTitle: document.getElementById("dash-idle-title"),
    dashIdleText: document.getElementById("dash-idle-text"),
    dashTeams: document.getElementById("dash-teams"),
    dashTeamEnemyWrap: document.getElementById("dash-team-enemy-wrap"),
    dashRosterAlly: document.getElementById("dash-roster-ally"),
    dashRosterEnemy: document.getElementById("dash-roster-enemy"),
    dashModeGrid: document.getElementById("dash-mode-grid"),
    dashQueueStatus: document.getElementById("dash-queue-status"),
    btnStartRanked: document.getElementById("btn-start-ranked"),
    btnQueueStart: document.getElementById("btn-queue-start"),
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
    startContinuousSync();
    startLiveSessionPolling();
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

function startContinuousSync() {
    setInterval(async () => {
        try {
            const res = await fetch("/api/sync-active-account");
            const data = await res.json();
            if (data.synced) {
                fetchAccounts();
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
    }, 4500);
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
    } else if (manual) {
        showToast("You're on the latest version!", "success");
        if (DOM.updateStatusText) DOM.updateStatusText.textContent = "You're on the latest version.";
    }
}

async function installPendingUpdate() {
    if (!state.pendingUpdate) return;

    if (DOM.btnInstallUpdate) {
        DOM.btnInstallUpdate.disabled = true;
        DOM.btnInstallUpdate.innerHTML = `<i class="fa-solid fa-spinner rotating"></i> Downloading...`;
    }

    try {
        const res = await fetch("/api/download-and-install-update", { method: "POST" });
        const data = await res.json();
        if (!data.success) {
            showToast(data.message || "Update failed. Please try again.", "error");
            if (DOM.btnInstallUpdate) {
                DOM.btnInstallUpdate.disabled = false;
                DOM.btnInstallUpdate.innerHTML = "Install Update";
            }
            return;
        }
        // The installer is downloaded and Explorer is open with it selected.
        // The user runs it themselves - the app doesn't launch it, since some
        // AV software blocks app-spawned installers.
        showToast(data.message || "Update downloaded - run VortexSetup to install.", "success");
        if (DOM.updateBannerText) {
            DOM.updateBannerText.textContent = "Downloaded! Close Vortex, then run VortexSetup (opened in Explorer).";
        }
        if (DOM.btnInstallUpdate) {
            DOM.btnInstallUpdate.disabled = false;
            DOM.btnInstallUpdate.innerHTML = `<i class="fa-solid fa-folder-open"></i> Show File`;
        }
    } catch (err) {
        showToast("Couldn't download the update. Check your connection.", "error");
        if (DOM.btnInstallUpdate) {
            DOM.btnInstallUpdate.disabled = false;
            DOM.btnInstallUpdate.innerHTML = "Install Update";
        }
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
            refreshAccountStats(state.activeMatchAccId).then(() => {
                openMatchesModal(state.activeMatchAccId);
            });
        }
    });

    DOM.btnOpenSettings.addEventListener("click", openSettingsModal);
    DOM.modalSettingsClose.addEventListener("click", () => closeModal(DOM.modalSettings));
    DOM.btnCancelSettings.addEventListener("click", () => closeModal(DOM.modalSettings));
    DOM.btnSaveSettings.addEventListener("click", saveSettings);
    DOM.btnAutoDetectClient.addEventListener("click", autoDetectClientPath);
    if (DOM.btnCheckUpdate) DOM.btnCheckUpdate.addEventListener("click", () => checkForUpdate(true));
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
        closeModal(DOM.modalLaunch);
        stopLaunchPolling();
        showToast("Login continues in the background", "info");
        // Backend login worker keeps running; refresh once it's had time to finish.
        setTimeout(() => { fetchAccounts(); fetchStatsSummary(); }, 8000);
    });

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
            closeAllModals();
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

async function fetchAccounts() {
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
        state.accounts = data.accounts || [];

        if (tagParam === "FAVORITES") {
            state.accounts = state.accounts.filter(a => a.favorite);
        }

        renderAccounts();
    } catch (err) {
        if (DOM.skeletonGrid) DOM.skeletonGrid.style.display = "none";
        showToast("Failed to load accounts", "error");
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

async function fetchBannedAccounts() {
    if (!DOM.bannedListContainer) return;
    try {
        const res = await fetch("/api/banned-accounts");
        const data = await res.json();
        renderBannedAccounts(data.accounts || []);
    } catch (err) {
        showToast("Failed to load banned accounts", "error");
    }
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
            ${icon}
            <span class="peak-emblem-text">Peak: ${escapeHtml(label)}</span>
        </span>
    `;
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

function renderAccounts() {
    if (DOM.skeletonGrid) DOM.skeletonGrid.style.display = "none";

    // Entrance animations only replay when the visible set actually changed —
    // the background sync re-renders every few seconds and would otherwise
    // restart them mid-hover.
    const signature = state.accounts.map(a => a.id).join(",") + "|" + state.viewMode;
    const isNewSet = signature !== state._renderSignature;
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
        displayName: acc.display_name || acc.username
    };
}

function renderGridView() {
    DOM.accountsGrid.innerHTML = state.accounts.map((acc, i) => {
        const v = buildAccountView(acc);
        const peakBadge = buildPeakBadge(acc);

        return `
            <div class="account-card ${acc.favorite ? 'is-favorite' : ''} ${v.cardFlags}" data-id="${acc.id}" style="--i:${Math.min(i, 24)}">
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
                        <div class="winrate-bar-fill ${v.wrClass}" data-width="${v.winrate}"></div>
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
                        <button class="btn btn-icon btn-sm" id="btn-refresh-${acc.id}" onclick="refreshAccountStats(${acc.id})" title="Sync Stats with Riot Servers">
                            <i class="fa-solid fa-arrows-rotate"></i>
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

    animateWinrateBars(DOM.accountsGrid);
}

function renderTableView() {
    DOM.accountsTableBody.innerHTML = state.accounts.map((acc, i) => {
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
                        <button class="btn btn-icon btn-sm" onclick="refreshAccountStats(${acc.id})" title="Sync Stats"><i class="fa-solid fa-arrows-rotate"></i></button>
                        <button class="btn btn-icon btn-sm" onclick="openEditModal(${acc.id})" title="Edit Account"><i class="fa-solid fa-pen"></i></button>
                        <button class="btn btn-icon btn-sm is-danger" onclick="deleteAccount(${acc.id})" title="Delete Account"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}

/** Meters start at 0 and grow on the next frame so the fill always animates. */
function animateWinrateBars(root) {
    const bars = root.querySelectorAll(".winrate-bar-fill[data-width]");
    requestAnimationFrame(() => {
        bars.forEach(bar => {
            bar.style.width = `${bar.dataset.width}%`;
        });
    });
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
            <div class="match-card ${outcomeClass}" style="--i:${i}">
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
            </div>
        `;
    }).join("");
}

// ==========================================================================
// CLEAN ADD ACCOUNT MODAL
// ==========================================================================

function openAccountModal(acc = null) {
    DOM.formAccount.reset();
    DOM.formPassword.type = "password";
    DOM.btnToggleFormPassword.innerHTML = '<i class="fa-regular fa-eye"></i>';

    if (acc) {
        DOM.modalAccountTitle.textContent = "Edit Valorant Account";
        DOM.modalAccountIcon.className = "fa-solid fa-user-pen";
        DOM.formAccountId.value = acc.id;
        DOM.formUsername.value = acc.username || "";
        DOM.formPassword.value = acc.password || "";
        DOM.formTag.value = acc.tag || "";
        DOM.formNotes.value = acc.notes || "";
        DOM.formFavorite.checked = !!acc.favorite;
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
    const acc = state.accounts.find(a => a.id === id);
    if (acc) openAccountModal(acc);
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

    const dupe = state.accounts.find(a =>
        a.username.trim().toLowerCase() === username.toLowerCase() &&
        String(a.id) !== String(DOM.formAccountId.value)
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

    try {
        let res;
        if (isEdit) {
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
            } else {
                showToast(
                    isEdit
                        ? `Updated ${creds.username}`
                        : `Added ${creds.username} - check it to confirm the login works.`,
                    "success"
                );
            }

            closeModal(DOM.modalAccount);
            await fetchAccounts();
            fetchStatsSummary();

            // Point straight at the row that just changed, so it's obvious
            // which account this was.
            if (savedId && !data.moved_to_banned) {
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
    const acc = state.accounts.find(a => a.id === id);
    const name = acc ? (acc.display_name || acc.username) : "this account";
    if (!confirm(`Delete ${name}?`)) return;

    try {
        const res = await fetch(`/api/accounts/${id}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("Account deleted", "info");
            fetchAccounts();
            fetchStatsSummary();
        }
    } catch (err) {
        showToast("Failed to delete account", "error");
    }
}

async function toggleFavorite(id) {
    try {
        const res = await fetch(`/api/accounts/${id}/toggle-favorite`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            const acc = state.accounts.find(a => a.id === id);
            if (acc) acc.favorite = data.account.favorite;
            fetchAccounts();
        }
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

                if (!settleTimer) {
                    settleTimer = setTimeout(() => {
                        fetchAccounts();
                        fetchStatsSummary();
                        pollLiveSession();
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

async function launchAccount(id) {
    const acc = state.accounts.find(a => a.id === id);
    if (!acc) return;

    state.activeLaunchAcc = acc;
    DOM.launchUserVal.textContent = acc.username;
    setLaunchModalTitle("Logging In to Riot Client");
    renderLaunchProgress({ stage: "opening", message: "Starting…" });
    openModal(DOM.modalLaunch);

    // Fire the login (backend spawns its own worker thread and returns fast).
    fetch(`/api/accounts/${id}/launch`, { method: "POST" })
        .then(r => r.json())
        .then(data => {
            if (!data.success) showToast(data.message || "Could not start login", "info");
        })
        .catch(() => showToast("Failed to open Riot Client", "error"));

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

function openSettingsModal() {
    DOM.settingsClientPath.value = state.settings.riot_client_path || "";
    DOM.settingsApiKey.value = state.settings.riot_api_key || "";
    if (DOM.settingsAppVersion) {
        DOM.settingsAppVersion.value = state.appVersion ? `v${state.appVersion}` : "Loading...";
    }
    openModal(DOM.modalSettings);
}

async function saveSettings() {
    const payload = {
        settings: {
            riot_client_path: DOM.settingsClientPath.value.trim(),
            riot_api_key: DOM.settingsApiKey.value.trim()
        }
    };

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
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
    state.dashboardOpen = false;
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

// The snapshot costs a handful of Riot requests, so it's only polled hard
// while the dashboard is actually on screen.
const LIVE_POLL_IDLE = 5000;
const LIVE_POLL_ACTIVE = 1600;

function startLiveSessionPolling() {
    const tick = async () => {
        try {
            await pollLiveSession();
        } catch (err) {
            // Never let one bad frame stop the loop.
        }
        clearTimeout(state._livePollTimer);
        state._livePollTimer = setTimeout(tick, state.dashboardOpen ? LIVE_POLL_ACTIVE : LIVE_POLL_IDLE);
    };
    tick();
}

async function pollLiveSession() {
    let live;
    try {
        const res = await fetch("/api/live/session");
        live = await res.json();
    } catch (err) {
        return;
    }

    const previousId = state.activeAccountId;
    state.live = live;
    state.activeAccountId = live.available ? live.account_id : null;

    renderSessionBar(live);
    if (state.dashboardOpen) {
        renderDashboard(live);
        refreshInstalockStatus();
    }

    // Re-render only when the active card actually moved, so the badge and
    // the PLAY button appear without restarting animations every poll.
    if (previousId !== state.activeAccountId) renderAccounts();
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

    if (DOM.btnSessionPlay) {
        DOM.btnSessionPlay.disabled = !!live.valorant_running;
        DOM.sessionPlayLabel.textContent = live.valorant_running ? "Running" : "Play";
    }
}

async function playAccount(id) {
    const acc = state.accounts.find(a => a.id === id);
    if (!acc) return;

    const isActive = state.activeAccountId === id;
    if (!isActive) {
        // Switching accounts means a full Riot Client login first - show the
        // same progress modal the LOGIN button uses.
        state.activeLaunchAcc = acc;
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
        if (data.success && !data.switched) {
            setTimeout(pollLiveSession, 2500);
        }
    } catch (err) {
        showToast("Failed to start VALORANT", "error");
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
            pollLiveSession();
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
// LIVE MATCH DASHBOARD
// ==========================================================================

async function openDashboard() {
    state.dashboardOpen = true;
    openModal(DOM.modalDashboard);

    if (!state.agents.length) await loadLiveAgents();
    renderModeGrid();
    renderAgentGrid();
    refreshInstalockStatus();

    if (state.live) renderDashboard(state.live);
    pollLiveSession();
}

function closeDashboard() {
    state.dashboardOpen = false;
    closeModal(DOM.modalDashboard);
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

function renderDashboard(live) {
    if (!DOM.modalDashboard) return;

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

    DOM.dashScoreboard.style.display = inMatch ? "block" : "none";
    DOM.dashPregameBanner.style.display = inPregame ? "flex" : "none";
    DOM.dashTeams.style.display = match ? "grid" : "none";
    DOM.dashIdle.style.display = match ? "none" : "flex";

    if (!match) {
        DOM.dashIdleTitle.textContent = live.available
            ? (live.valorant_running ? "No live match" : "VALORANT isn't running")
            : "No Riot Client session";
        DOM.dashIdleText.textContent = live.message ||
            "Start a match from the panel on the right and this tracks it round by round.";
    }

    if (inMatch) {
        DOM.dashScoreAlly.textContent = match.score.ally;
        DOM.dashScoreEnemy.textContent = match.score.enemy;
        DOM.dashRoundChip.textContent = `Round ${match.round}`;
        DOM.dashMapName.textContent = match.map.name || "Unknown map";
        DOM.dashModeName.textContent = match.mode || live.queue_label || "";
        DOM.dashMapArt.style.backgroundImage = match.map.splash ? `url("${match.map.splash}")` : "none";
    }

    if (inPregame) {
        DOM.dashPregameText.textContent =
            `Agent select · ${match.map.name || "Unknown map"} · ${match.mode || live.queue_label || ""}`;
        DOM.dashPregameTimer.textContent = match.time_remaining > 0
            ? `${Math.ceil(match.time_remaining)}s`
            : "--";
    }

    if (match) {
        renderRoster(DOM.dashRosterAlly, match.team);
        renderRoster(DOM.dashRosterEnemy, match.enemy);
        DOM.dashTeamEnemyWrap.style.display = (match.enemy && match.enemy.length) ? "block" : "none";
    }

    // -- queue controls ------------------------------------------------
    const inQueue = !!(live.party && live.party.in_queue);
    const canControl = !!live.valorant_running;

    DOM.dashQueueStatus.textContent = inQueue
        ? `Searching for a ${live.queue_label || "match"}…`
        : `Mode: ${live.queue_label || "not set"}`;
    DOM.dashQueueStatus.classList.toggle("is-searching", inQueue);

    DOM.btnStartRanked.disabled = !canControl || inQueue;
    DOM.btnQueueStart.disabled = !canControl || inQueue;
    DOM.btnQueueStop.disabled = !canControl || !inQueue;

    DOM.dashModeGrid.querySelectorAll(".dash-mode-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.queue === live.queue_id);
        b.disabled = !canControl;
    });

    DOM.btnLockNow.disabled = !inPregame || !state.selectedAgentId;
}

function renderRoster(el, players) {
    if (!el) return;

    if (!players || !players.length) {
        el.innerHTML = '<p class="dash-roster-empty">No players yet.</p>';
        return;
    }

    el.innerHTML = players.map(p => `
        <div class="dash-player ${p.is_self ? "is-self" : ""} ${p.locked ? "is-locked" : ""}">
            ${p.agent_icon
                ? `<img src="${p.agent_icon}" class="dash-player-agent" alt="${escapeHtml(p.agent)}" onerror="this.style.visibility='hidden';">`
                : `<span class="dash-player-agent is-empty"><i class="fa-solid fa-user"></i></span>`}
            <div class="dash-player-info">
                <span class="dash-player-name">${escapeHtml(p.name || (p.is_self ? "You" : "Hidden"))}</span>
                <span class="dash-player-sub">
                    ${escapeHtml(p.agent || "Picking…")}${p.level ? ` · LV ${p.level}` : ""}
                </span>
            </div>
            ${p.tier ? `<img src="${p.tier_icon}" class="dash-player-rank" alt="${escapeHtml(p.tier_label)}" title="${escapeHtml(p.tier_label)}" onerror="this.style.display='none';">` : ""}
        </div>
    `).join("");
}

// -- queue & mode control ------------------------------------------------

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
    try {
        const res = await fetch("/api/live/mode", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ queue_id: queueId })
        });
        const data = await res.json();
        showToast(data.message || (data.success ? "Mode changed" : "Couldn't change mode"),
                  data.success ? "success" : "error");
        if (data.success) pollLiveSession();
    } catch (err) {
        showToast("Couldn't reach the game client", "error");
    }
}

async function startQueue(queueId) {
    try {
        const res = await fetch("/api/live/queue/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ queue_id: queueId || null })
        });
        const data = await res.json();
        showToast(data.message || (data.success ? "Queue started" : "Couldn't start the queue"),
                  data.success ? "success" : "error");
        if (data.success) pollLiveSession();
    } catch (err) {
        showToast("Couldn't reach the game client", "error");
    }
}

async function stopQueue() {
    try {
        const res = await fetch("/api/live/queue/stop", { method: "POST" });
        const data = await res.json();
        showToast(data.message || "Left the queue", data.success ? "info" : "error");
        if (data.success) pollLiveSession();
    } catch (err) {
        showToast("Couldn't reach the game client", "error");
    }
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
        DOM.btnInstalockToggle.innerHTML = armed
            ? `<i class="fa-solid fa-power-off"></i> Turn Off (${escapeHtml(lock.agent_name || "armed")})`
            : `<i class="fa-solid fa-bolt"></i> Arm Insta-Lock${agent ? ` · ${escapeHtml(agent.name)}` : ""}`;
    }

    if (DOM.dashInstalockPill) {
        DOM.dashInstalockPill.textContent = armed ? (lock.status === "locked" ? "Locked" : "Armed") : "Off";
        DOM.dashInstalockPill.className = `dash-instalock-pill ${armed ? "is-armed" : ""}`;
    }

    if (DOM.dashInstalockStatus) {
        DOM.dashInstalockStatus.textContent = lock.message || "";
        DOM.dashInstalockStatus.className =
            `dash-instalock-status ${lock.status === "failed" ? "is-error" : (lock.status === "locked" ? "is-ok" : "")}`;
    }

    const inPregame = !!(state.live && state.live.match && state.live.match.phase === "agent_select");
    if (DOM.btnLockNow) DOM.btnLockNow.disabled = !inPregame || !state.selectedAgentId;
}

async function refreshInstalockStatus() {
    try {
        const res = await fetch("/api/live/instalock");
        state.instalock = await res.json();
        if (state.instalock.enabled && state.instalock.agent_id && !state.selectedAgentId) {
            state.selectedAgentId = state.instalock.agent_id;
            renderAgentGrid();
        }
    } catch (err) {
        state.instalock = {};
    }
    updateInstalockControls();
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
        pollLiveSession();
    } catch (err) {
        showToast("Couldn't reach the game client", "error");
    }
}

function initLiveEventListeners() {
    if (DOM.btnSessionPlay) {
        DOM.btnSessionPlay.addEventListener("click", () => {
            if (state.activeAccountId) playAccount(state.activeAccountId);
            else showToast("No matching account found for this session.", "info");
        });
    }

    if (DOM.btnOpenDashboard) DOM.btnOpenDashboard.addEventListener("click", openDashboard);
    if (DOM.modalDashboardClose) DOM.modalDashboardClose.addEventListener("click", closeDashboard);

    if (DOM.btnStartRanked) DOM.btnStartRanked.addEventListener("click", () => startQueue("competitive"));
    if (DOM.btnQueueStart) DOM.btnQueueStart.addEventListener("click", () => startQueue(null));
    if (DOM.btnQueueStop) DOM.btnQueueStop.addEventListener("click", stopQueue);

    if (DOM.btnInstalockToggle) DOM.btnInstalockToggle.addEventListener("click", toggleInstalock);
    if (DOM.btnLockNow) DOM.btnLockNow.addEventListener("click", lockAgentNow);
    if (DOM.dashAgentSearch) DOM.dashAgentSearch.addEventListener("input", renderAgentGrid);

    // The dashboard has its own teardown, so route Escape/backdrop through it.
    if (DOM.modalDashboard) {
        DOM.modalDashboard.addEventListener("mousedown", (e) => {
            if (e.target === DOM.modalDashboard) closeDashboard();
        });
    }
}
