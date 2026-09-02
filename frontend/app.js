/**
 * Vortex Valorant Account Manager - Frontend Controller
 * Handles UI state, filtering, official rank icons, peak rank badges, match history drawer,
 * batch .TXT combo importer (username:password), live status badges (Playable/Banned/Suspended),
 * and automated full-roster account checker ("Check Accounts").
 */

// Game assets are mirrored locally at release time so rank/agent/weapon art
// stays sharp and the dashboard does not depend on a tiny remote fallback.
const LOCAL_GAME_ASSET_ROOT = "/static/assets/valorant-api/";
function localGameAssetUrl(value) {
    if (typeof value !== "string") return value;
    return value.replace(/^https:\/\/media\.valorant-api\.com\//i, LOCAL_GAME_ASSET_ROOT);
}

function localizeGameAssets(value) {
    if (typeof value === "string") return localGameAssetUrl(value);
    if (Array.isArray(value)) return value.map(localizeGameAssets);
    if (value && typeof value === "object") {
        Object.keys(value).forEach(key => { value[key] = localizeGameAssets(value[key]); });
    }
    return value;
}

// Every dashboard API response passes through this once, covering new asset
// fields without requiring each future card/template to remember the helper.
const nativeFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const nativeJson = response.json.bind(response);
    response.json = async () => localizeGameAssets(await nativeJson());
    return response;
};

// Global State
const state = {
    accounts: [],
    bannedAccounts: [],
    settings: {},
    stats: {},
    currentRegion: "ALL",
    currentTag: "ALL",
    currentSort: "recent",
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

const TIER_BASE_URL = `${LOCAL_GAME_ASSET_ROOT}competitivetiers/03621f52-342b-cf4e-4f86-9350a49c6d04`;
const DEFAULT_TIER_ICON = `${TIER_BASE_URL}/0/largeicon.png`;

// Mirrors TIER_INDEX_MAP in backend/scraper.py so a stored peak rank can
// still show its official emblem when peak_rank_icon_url is blank (older
// accounts synced before the icon URL was saved).
const TIER_INDEX_MAP = {
    "UNRANKED": 0, "UNRATED": 0,
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

/**
 * Built-in Valorant Asset Registry & Resolvers
 * Maps names, UUIDs, roles, map splashes, and high-res competitive tier icons directly to local assets.
 */
const ValorantAssets = {
    agents: {
        "jett": { id: "add6443a-41bd-e414-f6ad-e58d267f4e95", name: "Jett", role: "Duelist", roleId: "dbe8757e-9e92-4ed4-b39f-9dfc589691d4" },
        "reyna": { id: "a3bfb853-43b2-7238-a4f1-ad90e9e46bcc", name: "Reyna", role: "Duelist", roleId: "dbe8757e-9e92-4ed4-b39f-9dfc589691d4" },
        "raze": { id: "f94c3b30-42be-e959-889c-5aa313dba261", name: "Raze", role: "Duelist", roleId: "dbe8757e-9e92-4ed4-b39f-9dfc589691d4" },
        "phoenix": { id: "eb93336a-449b-9c1b-0a54-a891f7921d69", name: "Phoenix", role: "Duelist", roleId: "dbe8757e-9e92-4ed4-b39f-9dfc589691d4" },
        "yoru": { id: "7f94d92c-4234-0a36-9646-3a87eb8b5c89", name: "Yoru", role: "Duelist", roleId: "dbe8757e-9e92-4ed4-b39f-9dfc589691d4" },
        "neon": { id: "bb2a4828-46eb-8cd1-e765-15848195d751", name: "Neon", role: "Duelist", roleId: "dbe8757e-9e92-4ed4-b39f-9dfc589691d4" },
        "iso": { id: "0e38b510-41a8-5780-5e8f-568b2a4f2d6c", name: "Iso", role: "Duelist", roleId: "dbe8757e-9e92-4ed4-b39f-9dfc589691d4" },
        "sova": { id: "320b2a48-4d9b-a075-30f1-1f93a9b638fa", name: "Sova", role: "Initiator", roleId: "1b47567f-8f7b-444b-aae3-b0c634622d10" },
        "breach": { id: "5f8d3a7f-467b-97f3-062c-13acf203c006", name: "Breach", role: "Initiator", roleId: "1b47567f-8f7b-444b-aae3-b0c634622d10" },
        "skye": { id: "6f2a04ca-43e0-be17-7f36-b3908627744d", name: "Skye", role: "Initiator", roleId: "1b47567f-8f7b-444b-aae3-b0c634622d10" },
        "kay/o": { id: "601dbbe7-43ce-be57-2a40-4abd24953621", name: "KAY/O", role: "Initiator", roleId: "1b47567f-8f7b-444b-aae3-b0c634622d10" },
        "kayo": { id: "601dbbe7-43ce-be57-2a40-4abd24953621", name: "KAY/O", role: "Initiator", roleId: "1b47567f-8f7b-444b-aae3-b0c634622d10" },
        "fade": { id: "dade69b4-4f5a-8528-247b-219e5a1facd6", name: "Fade", role: "Initiator", roleId: "1b47567f-8f7b-444b-aae3-b0c634622d10" },
        "gekko": { id: "e370fa57-4757-3604-3648-499e1f642d3f", name: "Gekko", role: "Initiator", roleId: "1b47567f-8f7b-444b-aae3-b0c634622d10" },
        "tejo": { id: "df1cb487-4902-002e-5c17-d28e83e78588", name: "Tejo", role: "Initiator", roleId: "1b47567f-8f7b-444b-aae3-b0c634622d10" },
        "brimstone": { id: "9f0d8ba9-4140-b941-57d3-a7ad57c6b417", name: "Brimstone", role: "Controller", roleId: "4ee40330-ecdd-4f2f-98a8-eb1243428373" },
        "omen": { id: "8e253930-4c05-31dd-1b6c-968525494517", name: "Omen", role: "Controller", roleId: "4ee40330-ecdd-4f2f-98a8-eb1243428373" },
        "viper": { id: "707eab51-4836-f488-046a-cda6bf494859", name: "Viper", role: "Controller", roleId: "4ee40330-ecdd-4f2f-98a8-eb1243428373" },
        "astra": { id: "41fb69c1-4189-7b37-f117-bcaf1e96f1bf", name: "Astra", role: "Controller", roleId: "4ee40330-ecdd-4f2f-98a8-eb1243428373" },
        "harbor": { id: "95b78ed7-4637-86d9-7e41-71ba8c293152", name: "Harbor", role: "Controller", roleId: "4ee40330-ecdd-4f2f-98a8-eb1243428373" },
        "clove": { id: "1dbf2edd-4729-0984-3115-daa5eed44993", name: "Clove", role: "Controller", roleId: "4ee40330-ecdd-4f2f-98a8-eb1243428373" },
        "killjoy": { id: "1e58de9c-4950-5125-93e9-a0aee9f98746", name: "Killjoy", role: "Sentinel", roleId: "5fc02f99-4091-4486-a531-98459a3e95e9" },
        "cypher": { id: "117ed9e3-49f3-6512-3ccf-0cada7e3823b", name: "Cypher", role: "Sentinel", roleId: "5fc02f99-4091-4486-a531-98459a3e95e9" },
        "sage": { id: "569fdd95-4d10-43ab-ca70-79becc718b46", name: "Sage", role: "Sentinel", roleId: "5fc02f99-4091-4486-a531-98459a3e95e9" },
        "chamber": { id: "22697a3d-45bf-8dd7-4fec-84a9e28c69d7", name: "Chamber", role: "Sentinel", roleId: "5fc02f99-4091-4486-a531-98459a3e95e9" },
        "deadlock": { id: "cc8b64c8-4b25-4ff9-6e7f-37b4da43d235", name: "Deadlock", role: "Sentinel", roleId: "5fc02f99-4091-4486-a531-98459a3e95e9" },
        "vyse": { id: "b444168c-4e35-8076-db47-ef9bf368f384", name: "Vyse", role: "Sentinel", roleId: "5fc02f99-4091-4486-a531-98459a3e95e9" }
    },
    maps: {
        "ascent": { id: "7eaecc1b-4337-bbf6-6ab9-04b8f06b3319", name: "Ascent" },
        "split": { id: "d960549e-485c-e861-8d71-aa9d1aed12a2", name: "Split" },
        "bind": { id: "2c9d57ec-4431-9c5e-2939-8f9ef6dd5cba", name: "Bind" },
        "haven": { id: "2bee0dc9-4ffe-519b-1cbd-7fbe763a6047", name: "Haven" },
        "icebox": { id: "e2ad5c54-4114-a870-9641-8ea21279579a", name: "Icebox" },
        "breeze": { id: "2fb9a4fd-47b8-4e7d-a969-74b4046ebd53", name: "Breeze" },
        "fracture": { id: "b529448b-4d60-346e-e89e-00a4c527a405", name: "Fracture" },
        "pearl": { id: "fd267378-4d1d-484f-ff52-77821ed10dc2", name: "Pearl" },
        "lotus": { id: "2fe4ed3a-450a-948b-6d6b-e89a78e680a9", name: "Lotus" },
        "sunset": { id: "92584fbe-486a-b1b2-9faa-39b0f486b498", name: "Sunset" },
        "abyss": { id: "224b0a95-48b9-f703-1bd8-67aca101a61f", name: "Abyss" },
        "district": { id: "690b3ed2-4dff-945b-8223-6da834e30d24", name: "District", isTdm: true },
        "kasbah": { id: "12452a9d-48c3-0b02-e7eb-0381c3520404", name: "Kasbah", isTdm: true },
        "piazza": { id: "de28aa9b-4cbe-1003-320e-6cb3ec309557", name: "Piazza", isTdm: true },
        "drift": { id: "1c7555fc-4bc6-3b98-9674-789d47ef6c50", name: "Drift", isTdm: true },
        "glitch": { id: "1c18ab1f-420d-0d8b-71d0-77ad3c439115", name: "Glitch", isTdm: true },
        "skirmish a": { id: "12452a9d-48c3-0b02-e7eb-0381c3520404", name: "Kasbah", isTdm: true },
        "skirmish b": { id: "690b3ed2-4dff-945b-8223-6da834e30d24", name: "District", isTdm: true },
        "skirmish d": { id: "de28aa9b-4cbe-1003-320e-6cb3ec309557", name: "Piazza", isTdm: true },
        "skirmish e": { id: "1c7555fc-4bc6-3b98-9674-789d47ef6c50", name: "Drift", isTdm: true },
        "the range": { id: "ee613ee9-28b7-4beb-9666-08db13bb2244", name: "The Range" },
        "range": { id: "ee613ee9-28b7-4beb-9666-08db13bb2244", name: "The Range" }
    },
    // A neutral placeholder for a player whose agent hasn't resolved. Callers
    // check `unresolved` so they don't print a misleading name/role (e.g.
    // "Miks · Agent") or a real agent's portrait for an unknown pick.
    _unknownAgent() {
        return { name: "Unknown agent", role: "", unresolved: true, icon: "", portrait: "", roleIcon: "" };
    },
    getAgent(nameOrId) {
        if (!nameOrId) return this._unknownAgent();
        const key = String(nameOrId).toLowerCase().trim();
        let entry = this.agents[key];
        if (!entry) {
            entry = Object.values(this.agents).find(a => a.id.toLowerCase() === key || a.name.toLowerCase() === key);
        }
        if (entry) {
            return {
                name: entry.name,
                role: entry.role,
                icon: `${LOCAL_GAME_ASSET_ROOT}agents/${entry.id}/displayicon.png`,
                portrait: `${LOCAL_GAME_ASSET_ROOT}agents/${entry.id}/fullportrait.png`,
                roleIcon: entry.roleId ? `${LOCAL_GAME_ASSET_ROOT}agents/roles/${entry.roleId}/displayicon.png` : ""
            };
        }
        if (typeof nameOrId === "string" && (nameOrId.startsWith("http") || nameOrId.startsWith("/"))) {
            return { name: "Agent", icon: localGameAssetUrl(nameOrId), portrait: "", role: "", roleIcon: "" };
        }
        return this._unknownAgent();
    },
    getMap(nameOrId) {
        if (!nameOrId) {
            return {
                name: "Ascent",
                displayName: "Ascent",
                splash: `${LOCAL_GAME_ASSET_ROOT}maps/7eaecc1b-4337-bbf6-6ab9-04b8f06b3319/splash.png`,
                icon: `${LOCAL_GAME_ASSET_ROOT}maps/7eaecc1b-4337-bbf6-6ab9-04b8f06b3319/listviewicon.png`,
                miniIcon: `${LOCAL_GAME_ASSET_ROOT}maps/7eaecc1b-4337-bbf6-6ab9-04b8f06b3319/displayicon.png`,
                isTdm: false
            };
        }
        const key = String(nameOrId).toLowerCase().trim();
        let entry = this.maps[key];
        if (!entry) {
            entry = Object.values(this.maps).find(m => m.id.toLowerCase() === key || m.name.toLowerCase() === key);
        }
        if (!entry) {
            for (const [k, val] of Object.entries(this.maps)) {
                if (key.includes(k) || k.includes(key)) {
                    entry = val;
                    break;
                }
            }
        }
        if (entry) {
            return {
                name: entry.name,
                displayName: entry.isTdm ? `${entry.name} (TDM)` : entry.name,
                splash: `${LOCAL_GAME_ASSET_ROOT}maps/${entry.id}/splash.png`,
                icon: `${LOCAL_GAME_ASSET_ROOT}maps/${entry.id}/listviewicon.png`,
                miniIcon: `${LOCAL_GAME_ASSET_ROOT}maps/${entry.id}/displayicon.png`,
                isTdm: !!entry.isTdm
            };
        }
        return {
            name: nameOrId,
            displayName: nameOrId,
            splash: `${LOCAL_GAME_ASSET_ROOT}maps/7eaecc1b-4337-bbf6-6ab9-04b8f06b3319/splash.png`,
            icon: `${LOCAL_GAME_ASSET_ROOT}maps/7eaecc1b-4337-bbf6-6ab9-04b8f06b3319/listviewicon.png`,
            miniIcon: "",
            isTdm: false
        };
    },
    getRank(tier, division) {
        const tierUpper = (tier || "UNRANKED").toUpperCase().trim();
        const div = (division || "").toString().trim();
        let key = (tierUpper === "UNRANKED" || tierUpper === "UNRATED" || tierUpper === "RADIANT" || !div)
            ? (tierUpper === "UNRATED" ? "UNRANKED" : tierUpper)
            : `${tierUpper} ${div}`;
        let idx = TIER_INDEX_MAP[key];
        if (idx === undefined) idx = TIER_INDEX_MAP[`${tierUpper} 1`];
        if (idx === undefined) idx = 0;

        let label = tierUpper.charAt(0) + tierUpper.slice(1).toLowerCase();
        if (tierUpper === "UNRANKED" || tierUpper === "UNRATED") label = "Unrated";
        else if (tierUpper === "RADIANT") label = "Radiant";
        else if (div) label += ` ${div}`;

        const rankStyles = {
            "IRON": { color: "#94a3b8", glow: "rgba(148,163,184,0.4)", gradient: "linear-gradient(135deg, #475569, #94a3b8)" },
            "BRONZE": { color: "#b45309", glow: "rgba(180,83,9,0.45)", gradient: "linear-gradient(135deg, #78350f, #d97706)" },
            "SILVER": { color: "#cbd5e1", glow: "rgba(203,213,225,0.45)", gradient: "linear-gradient(135deg, #64748b, #cbd5e1)" },
            "GOLD": { color: "#eab308", glow: "rgba(234,179,8,0.5)", gradient: "linear-gradient(135deg, #ca8a04, #fde047)" },
            "PLATINUM": { color: "#06b6d4", glow: "rgba(6,182,212,0.5)", gradient: "linear-gradient(135deg, #0891b2, #67e8f9)" },
            "DIAMOND": { color: "#c084fc", glow: "rgba(192,132,252,0.5)", gradient: "linear-gradient(135deg, #9333ea, #e879f9)" },
            "ASCENDANT": { color: "#10b981", glow: "rgba(16,185,129,0.5)", gradient: "linear-gradient(135deg, #059669, #34d399)" },
            "IMMORTAL": { color: "#f43f5e", glow: "rgba(244,63,94,0.55)", gradient: "linear-gradient(135deg, #e11d48, #fb7185)" },
            "RADIANT": { color: "#fde047", glow: "rgba(253,224,71,0.65)", gradient: "linear-gradient(135deg, #eab308, #fffbeb)" },
            "UNRANKED": { color: "#64748b", glow: "rgba(100,116,139,0.3)", gradient: "linear-gradient(135deg, #334155, #64748b)" },
            "UNRATED": { color: "#64748b", glow: "rgba(100,116,139,0.3)", gradient: "linear-gradient(135deg, #334155, #64748b)" }
        };
        const style = rankStyles[tierUpper] || rankStyles["UNRANKED"];

        return {
            tierIndex: idx,
            tierName: label,
            tierKey: tierUpper,
            icon: `${TIER_BASE_URL}/${idx}/largeicon.png`,
            color: style.color,
            glow: style.glow,
            gradient: style.gradient
        };
    }
};

function getRankIconUrl(tier, division) {
    return ValorantAssets.getRank(tier, division).icon;
}

// DOM Elements
const DOM = {
    statTotal: document.getElementById("stat-total"),
    statMains: document.getElementById("stat-mains"),
    statRanked: document.getElementById("stat-ranked"),
    statUnrated: document.getElementById("stat-unrated"),

    searchInput: document.getElementById("search-input"),
    searchClear: document.getElementById("search-clear"),
    filterControl: document.getElementById("filter-control"),
    btnFilters: document.getElementById("btn-filters"),
    filterPopover: document.getElementById("filter-popover"),
    filterCount: document.getElementById("filter-count"),
    filterActiveSummary: document.getElementById("filter-active-summary"),
    btnResetFilters: document.getElementById("btn-reset-filters"),
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
    comboInvalidPreview: document.getElementById("combo-invalid-preview"),
    comboResult: document.getElementById("combo-result"),
    comboResDetected: document.getElementById("combo-res-detected"),
    comboResImported: document.getElementById("combo-res-imported"),
    comboResDupes: document.getElementById("combo-res-dupes"),
    comboResInvalid: document.getElementById("combo-res-invalid"),
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
    settingsStaySignedIn: document.getElementById("settings-stay-signed-in"),
    settingsAutoLaunch: document.getElementById("settings-auto-launch"),
    settingsLiveMatchEnabled: document.getElementById("settings-live-match-enabled"),
    settingsPostValorantEnabled: document.getElementById("settings-post-valorant-enabled"),
    settingsPostValorantPath: document.getElementById("settings-post-valorant-path"),
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
    btnElevateLaunch: document.getElementById("btn-elevate-launch"),
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
    viewSwap: document.getElementById("view-swap"),
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
    btnSidePlay: document.getElementById("btn-side-play"),
    sidePlayIcon: document.getElementById("side-play-icon"),
    sidePlayTitle: document.getElementById("side-play-title"),
    sidePlaySub: document.getElementById("side-play-sub"),
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

function signalBootReady() {
    try {
        if (window.__vortexBoot && window.__vortexBoot.ready) window.__vortexBoot.ready();
        else window.__vortexBootReady = true;  // boot.js not parsed yet - it checks this flag
    } catch (_) {}
}

function bootStatus(text) {
    try {
        if (window.__vortexBoot && window.__vortexBoot.status) window.__vortexBoot.status(text);
    } catch (_) {}
}

document.addEventListener("DOMContentLoaded", () => {
    initEventListeners();
    initUiEnhancements();

    // Drive the boot screen: reveal the app once the first real data is in
    // (settings, the stats bar, and the account roster). Everything else can
    // keep loading behind the app. A 7s failsafe in boot.js covers a hang.
    bootStatus("Loading your library");
    Promise.allSettled([
        loadSettings(),
        fetchStatsSummary(),
        fetchAccounts(),
    ]).then(() => {
        bootStatus("Almost there");
        signalBootReady();
    });

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
        if (document.hidden) return;
        fetchAccounts();
        fetchStatsSummary();
        fetchBannedAccounts();
    }, 5 * 60 * 1000);
});

const ACTIVE_SYNC_INTERVAL = 60000;
const ACTIVE_SYNC_RECHECK_WHILE_MATCHING = 30000;
const ACTIVE_SYNC_RECHECK_WHILE_HIDDEN = 2 * 60 * 1000;

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
    return ACTIVE_SYNC_INTERVAL;
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
            if (DOM.updateStatusText) DOM.updateStatusText.textContent = "Updates are delivered through GitHub releases.";
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

    initFilterPopover();

    DOM.viewGridBtn.addEventListener("click", () => setViewMode("grid"));
    DOM.viewTableBtn.addEventListener("click", () => setViewMode("table"));

    // Check All Accounts
    if (DOM.btnCheckAllAccounts) {
        DOM.btnCheckAllAccounts.addEventListener("click", handleCheckAllAccounts);
    }

    DOM.btnAddAccount.addEventListener("click", () => openAccountModal());
    DOM.btnEmptyAdd.addEventListener("click", () => openAccountModal());

    // Batch Import Combo & Drag and Drop
    if (DOM.btnImportCombo) DOM.btnImportCombo.addEventListener("click", openComboModal);
    if (DOM.btnEmptyImport) DOM.btnEmptyImport.addEventListener("click", openComboModal);
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
        DOM.comboTextInput.addEventListener("input", () => {
            resetComboResult();
            updateComboPreviewCount();
        });
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

    if (DOM.btnElevateLaunch) {
        DOM.btnElevateLaunch.addEventListener("click", relaunchVortexElevated);
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
        if (e.key === "Escape") {
            // The filter popover is the lightest layer, so it yields first.
            if (DOM.filterPopover && DOM.filterPopover.classList.contains("is-open")) {
                closeFilterPopover();
                return;
            }
            // A modal sits on top of the dashboard, so it closes first.
            const openModalEl = document.querySelector(".modal-overlay.active");
            if (openModalEl) closeAllModals();
            else if (state.dashboardOpen) closeDashboard();
        }
    });
}

function openComboModal() {
    resetComboResult();
    if (DOM.comboTextInput) DOM.comboTextInput.value = "";
    updateComboPreviewCount();
    openModal(DOM.modalImportCombo);
    if (DOM.comboTextInput) setTimeout(() => DOM.comboTextInput.focus(), 60);
}

function resetComboResult() {
    if (DOM.comboResult) DOM.comboResult.hidden = true;
    if (DOM.btnCancelCombo) DOM.btnCancelCombo.textContent = "Cancel";
}

function readComboFile(file) {
    const reader = new FileReader();
    reader.onload = (event) => {
        DOM.comboTextInput.value = event.target.result;
        resetComboResult();
        updateComboPreviewCount();
        showToast(`Loaded ${file.name}`, "info");
    };
    reader.readAsText(file);
}

// Client-side mirror of database.import_from_text's line rules — used only to
// preview what will happen. A line "counts" if it has a separator with a
// non-empty value on each side.
function parseComboLines(text) {
    let valid = 0, invalid = 0;
    for (const raw of (text || "").split("\n")) {
        const line = raw.trim();
        if (!line || line.startsWith("#") || line.startsWith("//")) continue;
        const sep = [":", "|", ",", "\t"].find(s => line.includes(s));
        const parts = sep ? line.split(sep).map(p => p.trim()) : [];
        if (parts.length >= 2 && parts[0] && parts[1]) valid++;
        else invalid++;
    }
    return { valid, invalid };
}

function updateComboPreviewCount() {
    if (!DOM.comboTextInput || !DOM.comboCountPreview) return;
    const { valid, invalid } = parseComboLines(DOM.comboTextInput.value);
    DOM.comboCountPreview.innerHTML = `<strong>${valid}</strong> detected`;
    if (DOM.comboInvalidPreview) {
        DOM.comboInvalidPreview.hidden = invalid === 0;
        DOM.comboInvalidPreview.innerHTML = `<strong>${invalid}</strong> line${invalid === 1 ? "" : "s"} need <code>user:pass</code>`;
    }
}

async function handleBatchTextImport() {
    const rawText = DOM.comboTextInput.value.trim();
    if (!rawText) {
        showToast("Paste some accounts, or drop a .txt / .csv file", "error");
        return;
    }

    const preview = parseComboLines(rawText);
    const btn = DOM.btnDoComboImport;
    const originalLabel = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner rotating"></i> Importing...';

    try {
        const res = await fetch("/api/import-text", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: rawText })
        });
        const data = await res.json();
        if (data.success) {
            const imported = data.imported_count || 0;
            const dupes = data.skipped_existing || 0;
            const rejected = (data.skipped_banned || 0) + preview.invalid;

            // Show the breakdown in the modal rather than only a fleeting toast.
            if (DOM.comboResult) {
                DOM.comboResDetected.textContent = preview.valid;
                DOM.comboResImported.textContent = imported;
                DOM.comboResDupes.textContent = dupes;
                DOM.comboResInvalid.textContent = rejected;
                DOM.comboResult.hidden = false;
            }
            if (DOM.btnCancelCombo) DOM.btnCancelCombo.textContent = "Done";

            showToast(buildImportMessage(data), imported > 0 ? "success" : "info");
            DOM.comboTextInput.value = "";           // never keep plaintext around
            updateComboPreviewCount();
            fetchAccounts();
            fetchStatsSummary();
        } else {
            showToast("Failed to import accounts", "error");
        }
    } catch (err) {
        showToast("Import communication error", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalLabel;
    }
}

// ==========================================================================
// CHECK ACCOUNTS (SEQUENTIAL SCANNER)
// ==========================================================================

// Single place that puts the Check Accounts button and progress bar back to
// rest. Called on completion, on error, on cancel, and by a watchdog - the
// spinner used to get stuck forever if the poll loop died or the backend
// never reported running:false.
function stopCheckAccountsUi(hideBar = true) {
    state.isCheckingAccounts = false;
    if (state._checkPoll) { clearInterval(state._checkPoll); state._checkPoll = null; }
    if (state._checkPollDeadline) { clearTimeout(state._checkPollDeadline); state._checkPollDeadline = null; }
    if (DOM.btnCheckAllAccounts) {
        DOM.btnCheckAllAccounts.classList.remove("is-checking");
        DOM.btnCheckAllAccounts.removeAttribute("aria-busy");
    }
    if (DOM.checkAllIcon) {
        DOM.checkAllIcon.className = "fa-solid fa-list-check";
    }
    if (hideBar && DOM.syncProgressBar) {
        DOM.syncProgressBar.style.display = "none";
        if (DOM.syncProgressFill) DOM.syncProgressFill.style.width = "0%";
    }
}

async function handleCheckAllAccounts() {
    if (state.isCheckingAccounts) {
        try {
            await fetch("/api/accounts/cancel-check", { method: "POST" });
            showToast("Stopping account check...", "info");
        } catch (e) {}
        // Don't wait on the poll loop to notice - release the button now.
        stopCheckAccountsUi(true);
        return;
    }

    state.isCheckingAccounts = true;
    if (DOM.btnCheckAllAccounts) {
        DOM.btnCheckAllAccounts.classList.add("is-checking");
        DOM.btnCheckAllAccounts.setAttribute("aria-busy", "true");
    }
    if (DOM.checkAllIcon) {
        DOM.checkAllIcon.className = "fa-solid fa-spinner rotating";
    }
    DOM.syncProgressBar.style.display = "block";
    DOM.syncProgressFill.style.width = "10%";
    DOM.syncProgressText.textContent = "Starting account verification...";

    // Watchdog: if the poll loop hasn't seen progress in 3 minutes (a hung
    // backend task, a dropped connection), stop spinning and let the user retry.
    let lastCurrent = -1;
    const armWatchdog = () => {
        if (state._checkPollDeadline) clearTimeout(state._checkPollDeadline);
        state._checkPollDeadline = setTimeout(() => {
            showToast("Account check stopped responding - stopping. You can run it again.", "error");
            DOM.syncProgressText.textContent = "Account check stopped responding.";
            stopCheckAccountsUi(true);
        }, 180000);
    };

    try {
        const res = await fetch("/api/accounts/check-all", { method: "POST" });
        const startData = await res.json();

        if (!startData.success) {
            if (startData.message) showToast(startData.message, "info");
            stopCheckAccountsUi(true);
            return;
        }
        // Nothing to check: don't sit on a spinner.
        if (startData.to_check_count === 0) {
            if (startData.message) showToast(startData.message, "info");
            stopCheckAccountsUi(true);
            return;
        }

        armWatchdog();

        // Poll progress until complete
        state._checkPoll = setInterval(async () => {
            try {
                const statusRes = await fetch("/api/accounts/check-status");
                const progress = await statusRes.json();

                if (progress.current !== lastCurrent) { lastCurrent = progress.current; armWatchdog(); }

                if (progress.running) {
                    const pct = Math.max(10, Math.round((progress.current / Math.max(progress.total, 1)) * 100));
                    DOM.syncProgressFill.style.width = `${pct}%`;
                    DOM.syncProgressText.textContent = progress.message || `Checking accounts (${progress.current}/${progress.total})...`;
                    fetchAccounts();
                    fetchStatsSummary();
                } else {
                    DOM.syncProgressFill.style.width = "100%";
                    DOM.syncProgressText.textContent = progress.message || "All accounts verified!";
                    stopCheckAccountsUi(false);
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
                // Ignore a single poll error; the watchdog covers a sustained one.
            }
        }, 1500);

    } catch (err) {
        showToast("Failed to start account verification", "error");
        stopCheckAccountsUi(true);
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
        a.needs_check, a.competitive_queue_eligible,
        a.is_legacy_ranked_eligible, a.ranked_capable, a.ranked_eligibility_source,
        minute(a.last_login)
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
        } else if (tagParam !== "ALL" && tagParam !== "LEGACY_RANKED") {
            url += `&tag=${encodeURIComponent(tagParam)}`;
        }

        const res = await fetch(url);
        const data = await res.json();
        let newAccounts = data.accounts || [];

        if (tagParam === "FAVORITES") {
            newAccounts = newAccounts.filter(a => a.favorite);
        } else if (tagParam === "LEGACY_RANKED") {
            // Backend-derived flag: below the level gate but Competitive-eligible.
            newAccounts = newAccounts.filter(isLegacyRankedEligible);
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

// Brief, interruptible cross-fade of the accent-driven colours when the user
// picks a new theme. Only runs on an explicit switch — the initial applyTheme()
// on load stays instant. Repeated rapid switches just keep extending the timer.
let _accentAnimTimer = null;
function runAccentTransition() {
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
    document.body.classList.add("accent-anim");
    clearTimeout(_accentAnimTimer);
    _accentAnimTimer = setTimeout(() => {
        document.body.classList.remove("accent-anim");
    }, 320);
}

async function selectTheme(themeName) {
    if (themeName === state.settings.theme) return;
    runAccentTransition();
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
// FILTERS POPOVER
// --------------------------------------------------------------------------
// One "Filters" button opens a compact popover holding Region / Account Type /
// Sort By. The radios drive the same state.current* values the old three
// dropdowns did, so fetchAccounts() and every downstream consumer are
// unchanged. "LEGACY_RANKED" is the one account-type value handled client-side.
// ==========================================================================

const FILTER_DEFAULTS = { region: "ALL", tag: "ALL", sort: "recent" };

function initFilterPopover() {
    if (!DOM.btnFilters || !DOM.filterPopover) return;

    DOM.btnFilters.addEventListener("click", (e) => {
        e.stopPropagation();
        DOM.filterPopover.classList.contains("is-open") ? closeFilterPopover() : openFilterPopover();
    });

    DOM.filterPopover.addEventListener("change", (e) => {
        const input = e.target.closest("input[type=radio]");
        if (!input) return;
        const group = input.closest(".filter-options");
        if (group) {
            group.querySelectorAll(".filter-chip").forEach(chip =>
                chip.classList.toggle("is-selected", chip.contains(input) && input.checked));
        }
        const kind = group && group.dataset.filter;
        if (kind === "region") state.currentRegion = input.value;
        else if (kind === "tag") state.currentTag = input.value;
        else if (kind === "sort") state.currentSort = input.value;
        syncFilterIndicators();
        fetchAccounts();
    });

    if (DOM.btnResetFilters) {
        DOM.btnResetFilters.addEventListener("click", () => {
            state.currentRegion = FILTER_DEFAULTS.region;
            state.currentTag = FILTER_DEFAULTS.tag;
            state.currentSort = FILTER_DEFAULTS.sort;
            applyFilterStateToInputs();
            syncFilterIndicators();
            fetchAccounts();
        });
    }

    // Outside-click closes it; clicks inside the popover or on the button don't.
    document.addEventListener("click", (e) => {
        if (!DOM.filterPopover.classList.contains("is-open")) return;
        if (DOM.filterControl && DOM.filterControl.contains(e.target)) return;
        closeFilterPopover();
    });

    applyFilterStateToInputs();
    syncFilterIndicators();
}

function openFilterPopover() {
    DOM.filterPopover.classList.add("is-open");
    DOM.btnFilters.classList.add("is-open");
    DOM.btnFilters.setAttribute("aria-expanded", "true");
}

function closeFilterPopover() {
    DOM.filterPopover.classList.remove("is-open");
    DOM.btnFilters.classList.remove("is-open");
    DOM.btnFilters.setAttribute("aria-expanded", "false");
}

function applyFilterStateToInputs() {
    const map = {
        "flt-region": state.currentRegion,
        "flt-tag": state.currentTag,
        "flt-sort": state.currentSort,
    };
    Object.entries(map).forEach(([name, value]) => {
        DOM.filterPopover.querySelectorAll(`input[name="${name}"]`).forEach(input => {
            const on = input.value === value;
            input.checked = on;
            const chip = input.closest(".filter-chip");
            if (chip) chip.classList.toggle("is-selected", on);
        });
    });
}

function activeFilterCount() {
    let n = 0;
    if (state.currentRegion !== FILTER_DEFAULTS.region) n++;
    if (state.currentTag !== FILTER_DEFAULTS.tag) n++;
    if (state.currentSort !== FILTER_DEFAULTS.sort) n++;
    return n;
}

function syncFilterIndicators() {
    const n = activeFilterCount();
    if (DOM.filterCount) {
        DOM.filterCount.textContent = n;
        DOM.filterCount.hidden = n === 0;
    }
    if (DOM.btnFilters) DOM.btnFilters.classList.toggle("has-active", n > 0);
    if (DOM.btnResetFilters) DOM.btnResetFilters.disabled = n === 0;
    if (DOM.filterActiveSummary) {
        DOM.filterActiveSummary.textContent = n === 0
            ? "No filters"
            : `${n} active filter${n === 1 ? "" : "s"}`;
    }
}

// ==========================================================================
// ACCOUNT RENDERING & BADGES
// ==========================================================================

function buildImportMessage(data) {
    const imported = data.imported_count || 0;
    const repaired = data.repaired_passwords || 0;
    const dupes = data.skipped_existing || 0;
    const banned = data.skipped_banned || 0;

    const skips = [];
    if (dupes) skips.push(`${dupes} already added`);
    if (banned) skips.push(`${banned} banned`);

    if (repaired) {
        return `Imported ${imported}; restored ${repaired} missing password${repaired === 1 ? "" : "s"}.`;
    }
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

// Cumulative win-rate sparkline for the hero card: the running win% after
// each match, oldest -> newest. Falls back to a flat line at the stored
// winrate when there's no per-match history to trend.
function buildWinrateGraph(acc, v) {
    const W = 460, H = 46, PAD = 4;
    const matches = Array.isArray(acc.match_history) ? acc.match_history.slice() : [];
    // match_history is newest-first from the scraper; plot oldest -> newest.
    matches.reverse();
    const rated = matches.filter(m => {
        const o = (m.outcome || "").toUpperCase();
        return o === "VICTORY" || o === "DEFEAT" || o === "DRAW";
    });

    let series;
    if (rated.length >= 2) {
        let wins = 0;
        series = rated.map((m, i) => {
            const o = (m.outcome || "").toUpperCase();
            if (o === "VICTORY") wins += 1;
            else if (o === "DRAW") wins += 0.5;
            return wins / (i + 1) * 100;
        });
    } else {
        series = [v.winrate, v.winrate];
    }

    const stepX = series.length > 1 ? (W - PAD * 2) / (series.length - 1) : 0;
    const pt = (val, i) => {
        const x = series.length === 1 ? W / 2 : PAD + i * stepX;
        const y = H - PAD - Math.max(0, Math.min(100, val)) / 100 * (H - PAD * 2);
        return [Number(x.toFixed(1)), Number(y.toFixed(1))];
    };
    const pts = series.map(pt);
    const line = pts.map(p => p.join(",")).join(" ");
    const area = `${pts[0][0]},${H - PAD} ${line} ${pts[pts.length - 1][0]},${H - PAD}`;
    const last = pts[pts.length - 1];
    const mid = H - PAD - 0.5 * (H - PAD * 2); // the 50% reference line

    return `
        <div class="hero-winrate-graph" title="Cumulative win rate over the last ${rated.length || 0} matches">
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="wr-graph ${v.wrClass}">
                <line class="wr-graph-mid" x1="0" y1="${mid.toFixed(1)}" x2="${W}" y2="${mid.toFixed(1)}"></line>
                <polygon class="wr-graph-area" points="${area}"></polygon>
                <polyline class="wr-graph-line" points="${line}"></polyline>
                <circle class="wr-graph-dot" cx="${last[0]}" cy="${last[1]}" r="2.6"></circle>
            </svg>
        </div>`;
}

function getAccountCombatStats(acc) {
    const matches = Array.isArray(acc.match_history) ? acc.match_history : [];
    if (!matches || matches.length === 0) {
        return {
            winrate: Number(acc.winrate) || 0,
            games: Number(acc.games_played) || 0,
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
        winrate: accountWinrate(acc),
        games: Math.max(Number(acc.games_played) || 0, n),
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

// Win rate for an account, preferring what its saved matches actually show.
// acc.winrate is the stored lifetime figure from the remote stat sync and
// sits at 0 whenever that sync last failed - which is when every winrate on
// the card looks broken even though the match list right there says otherwise.
function accountWinrate(acc) {
    const matches = Array.isArray(acc.match_history) ? acc.match_history : [];
    let wins = 0, decided = 0;
    for (const m of matches) {
        const o = (m.outcome || m.result || "").toUpperCase();
        if (o === "VICTORY" || o === "WIN") { wins++; decided++; }
        else if (o === "DEFEAT" || o === "LOSS") { decided++; }
        else if (o === "DRAW" || o === "TIE") { wins += 0.5; decided++; }
    }
    if (decided > 0) return Math.round((wins / decided) * 100);
    return Number(acc.winrate) || 0;
}

/** Backend-derived eligibility is the sole source for the badge, filter and glow. */
function isLegacyRankedEligible(acc) {
    return acc && acc.is_legacy_ranked_eligible === true;
}

/** Shared per-account view model used by both the grid and table renderers. */
function buildAccountView(acc) {
    const tier = (acc.rank_tier || "UNRANKED").toUpperCase();
    const rankInfo = TIER_ICONS[tier] || TIER_ICONS.UNRANKED;
    const effectiveTag = acc.tag && !['Smurf', 'Ranked', 'Unrated', ''].includes(acc.tag)
        ? acc.tag
        : ((acc.ranked_capable || acc.competitive_queue_eligible || acc.level >= 20)
            ? 'Ranked' : 'Unrated');
    const winrate = accountWinrate(acc);

    // The signed-in account gets a live badge and a PLAY button instead of
    // LOGIN; anything Riot hasn't confirmed yet gets a Check Account button.
    const isActive = state.activeAccountId === acc.id;
    const needsCheck = acc.needs_check === true;
    const isHighlighted = state.highlightId === acc.id;
    // Backend-derived: this account is under the level gate but Riot still
    // reports it as Competitive-eligible ("Legacy Ranked").
    const isLegacyRanked = isLegacyRankedEligible(acc);

    const lastLoginFormatted = isActive
        ? '<span class="last-login-val is-active"><span class="live-dot-mini"></span> Active Now</span>'
        : (acc.last_login
            ? `<span class="last-login-val">${formatTimeAgo(acc.last_login)}</span>`
            : '<span class="last-login-val is-never">Never</span>');

    return {
        isActive,
        needsCheck,
        isLegacyRanked,
        cardFlags: [
            isActive ? "is-active-session" : "",
            isHighlighted ? "is-highlighted" : "",
            isLegacyRanked ? "is-legacy-ranked" : "",
        ].filter(Boolean).join(" "),
        legacyBadge: isLegacyRanked
            ? '<span class="badge-legacy" title="Legacy Ranked Access&#10;This account can access Competitive below the normal level requirement."><i class="fa-solid fa-gem"></i> Legacy Ranked</span>'
            : "",
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
        gamesPlayed: Math.max(
            Number(acc.games_played) || 0,
            Array.isArray(acc.match_history) ? acc.match_history.length : 0
        ),
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
                    ${v.legacyBadge}
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
                            <span class="hero-stat-value">${combat.games || 0}</span>
                        </div>
                    </div>

                    ${buildWinrateGraph(acc, v)}

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
                    <button class="btn-hero-play ${isValRunning ? 'is-running is-dashboard' : ''}" onclick="${isValRunning ? 'openDashboard()' : `playAccount(${acc.id})`}" title="${isValRunning ? 'Open Live Match Dashboard' : 'Launch VALORANT on this account'}">
                        <div class="hero-play-text-wrap">
                            <span class="hero-play-title">${isValRunning ? 'DASHBOARD' : 'PLAY VALORANT'}</span>
                            <span class="hero-play-sub">${isValRunning ? 'Open Live Match Dashboard' : 'Launch Game Client'}</span>
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
                        <button class="btn btn-secondary hero-action-btn hero-matches-btn ${isValRunning ? 'is-expanded' : ''}" onclick="openMatchesModal(${acc.id})" title="View Match History & Details">
                            <i class="fa-solid fa-clock-rotate-left"></i>
                            <span>Matches (${combat.games || 0})</span>
                        </button>
                        ${isValRunning ? '' : `<button class="btn btn-primary hero-action-btn hero-dashboard-btn" onclick="openDashboard()" title="Open Live Match Dashboard">
                            <i class="fa-solid fa-gauge-high"></i>
                            <span>Dashboard</span>
                        </button>`}
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
            <div class="account-card ${acc.favorite ? 'is-favorite' : ''} ${v.needsCheck ? 'needs-check' : ''} ${v.cardFlags}" data-id="${acc.id}" style="--i:${Math.min(animIndex, 24)}">
                <!-- Header -->
                <div class="card-header">
                    <div class="card-badges">
                        ${v.needsCheck ? `
                            <span class="badge-unset" title="Log in once to verify these credentials and pull live account data">
                                <span class="mini-spinner"></span> Unverified
                            </span>
                            <span class="badge-region is-muted" title="Region not confirmed yet">Region: <span class="mini-spinner"></span></span>
                        ` : `
                            <span class="badge-region">${escapeHtml(acc.region || 'NA')}</span>
                            <span class="badge-tag ${v.tagClass}">${escapeHtml(v.effectiveTag)}</span>
                            ${v.statusBadge}
                        `}
                        ${v.legacyBadge}
                        ${v.liveBadge}
                    </div>
                    <button class="card-favorite-btn ${acc.favorite ? 'active' : ''}" onclick="toggleFavorite(${acc.id})" title="Pin Account">
                        <i class="fa-${acc.favorite ? 'solid' : 'regular'} fa-star"></i>
                    </button>
                </div>

                <!-- Profile Info & Official Emblem -->
                <div class="card-profile">
                    <div class="rank-emblem-wrap ${v.tierClass}" title="Current Rank: ${v.rankTitle}">
                        <img src="${v.rankIconSrc}" alt="${v.rankTitle}" class="rank-emblem-img" loading="lazy" decoding="async" onerror="this.onerror=null; this.src='${DEFAULT_TIER_ICON}';">
                        <span class="level-bubble${v.needsCheck ? ' is-unset' : ''}">${v.needsCheck ? '<span class="mini-spinner"></span> LV ?' : 'LV ' + (acc.level || "-")}</span>
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
                        ${v.needsCheck
                            ? `<span class="rank-tier-title is-unset"><span class="mini-spinner"></span> No rank data</span>`
                            : `<span class="rank-tier-title ${v.rankInfo.colorClass}">${v.rankTitle}</span>`}
                        ${v.needsCheck ? '' : peakBadge}
                        ${acc.notes ? `<p class="account-notes" title="${escapeHtml(acc.notes)}"><i class="fa-solid fa-note-sticky"></i> ${escapeHtml(acc.notes)}</p>` : ''}
                    </div>
                </div>

                <!-- Winrate & Matches -->
                <div class="card-stats-row">
                    ${v.needsCheck ? `
                        <div class="winrate-meta is-unset">
                            <span><span class="mini-spinner"></span> Winrate no data</span>
                            <span>Matches <span class="mini-spinner"></span></span>
                        </div>
                        <div class="winrate-bar-track">
                            <div class="winrate-bar-fill is-unset" style="width: 100%;"></div>
                        </div>
                    ` : `
                        <div class="winrate-meta">
                            <span>Winrate <strong>${v.winrate}%</strong></span>
                            <span>Matches <strong>${v.gamesPlayed}</strong></span>
                        </div>
                        <div class="winrate-bar-track">
                            <div class="winrate-bar-fill ${v.wrClass}" style="width: ${v.winrate}%;"></div>
                        </div>
                    `}
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

                <!-- Actions Footer -->
                <div class="card-actions">
                    ${v.isActive ? `
                        <button class="btn-launch-card is-play" onclick="playAccount(${acc.id})" title="Launch VALORANT on this account">
                            <i class="fa-solid fa-play"></i> PLAY
                        </button>
                    ` : v.needsCheck ? `
                        <button class="btn-launch-card btn-check-inline" id="btn-check-${acc.id}" onclick="checkAccount(${acc.id})" title="Log in once to confirm the username and password work, and pull the real Riot ID, level and rank">
                            <i class="fa-solid fa-shield-halved"></i><span class="account-check-loader" aria-hidden="true"></span> CHECK ACCOUNT
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
                <td>${v.statusBadge}${v.legacyBadge}${v.liveBadge}</td>
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
                        <img src="${v.rankIconSrc}" class="table-rank-icon" alt="${v.rankTitle}" loading="lazy" decoding="async" onerror="this.onerror=null; this.src='${DEFAULT_TIER_ICON}';">
                        <span class="${v.rankInfo.colorClass}"><strong>${v.rankTitle}</strong></span>
                    </div>
                </td>
                <td>
                    ${acc.peak_rank_tier ? `
                        <div class="table-rank-cell">
                            ${v.peakIconSrc ? `<img src="${v.peakIconSrc}" class="table-rank-icon" alt="Peak" loading="lazy" decoding="async" onerror="this.style.display='none';">` : '<i class="fa-solid fa-trophy text-gold"></i>'}
                            <span class="text-gold"><strong>${escapeHtml(acc.peak_rank_tier)} ${escapeHtml(acc.peak_rank_division || '')}</strong></span>
                        </div>
                    ` : '<span class="text-dim">---</span>'}
                </td>
                <td><span class="level-chip">LV ${acc.level || "-"}</span></td>
                <td>${v.winrate}% <span class="text-dim">(${v.gamesPlayed}G)</span></td>
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
                            <button class="btn btn-icon btn-sm is-warning" id="btn-check-${acc.id}" onclick="checkAccount(${acc.id})" title="Check Account - verify the credentials and pull live data"><i class="fa-solid fa-shield-halved"></i><span class="account-check-loader" aria-hidden="true"></span></button>
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

    const rankInfo = ValorantAssets.getRank(acc.rank_tier, acc.rank_division);
    const peakInfo = ValorantAssets.getRank(acc.peak_rank_tier, acc.peak_rank_division);

    DOM.matchModalRiotId.textContent = acc.display_name || acc.username;
    DOM.matchModalRankImg.src = acc.rank_icon_url || rankInfo.icon;
    DOM.matchMetaCurrent.textContent = formatRankTitle(acc);
    DOM.matchMetaPeak.textContent = acc.peak_rank_tier ? `${acc.peak_rank_tier} ${acc.peak_rank_division || ''}` : 'None';
    
    if (DOM.matchMetaPeakImg) {
        DOM.matchMetaPeakImg.src = acc.peak_rank_icon_url || peakInfo.icon;
        DOM.matchMetaPeakImg.style.display = "inline-block";
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
        DOM.matchMetaWinrate.textContent = recentWinrateLabel(matches, acc.winrate);
    } catch (err) {
        DOM.matchesListContainer.innerHTML = '<div class="no-matches-msg">Failed to load match history.</div>';
    }
}

// A recent match arrives in one of two shapes: the Account-Manager path
// (HenrikDev scrape: `outcome` VICTORY/DEFEAT, `kdr`, `hs_pct`, `game_date`
// string) and the Dashboard / Live Stats path (local client: `result`
// Win/Loss, `kd`, `hs`, `started_at` epoch millis). These helpers normalise
// both so a single card component renders either identically.

function matchOutcome(m) {
    const raw = String(m.outcome || m.result || "").toUpperCase();
    if (raw === "VICTORY" || raw === "WIN") return { text: "VICTORY", cls: "outcome-victory" };
    if (raw === "DEFEAT" || raw === "LOSS") return { text: "DEFEAT", cls: "outcome-defeat" };
    return { text: raw || "DRAW", cls: "outcome-draw" };
}

// Same date the Account-Manager rows show: prefer the server-formatted
// `game_date` string, fall back to formatting the epoch `started_at` locally
// (same wording), and finally to "Recent" - exactly the Account-Manager
// fallback. No separate date system.
function matchDateLabel(m) {
    if (m && m.game_date) return m.game_date;
    const millis = Number(m && (m.started_at || m.game_start_millis) || 0);
    if (millis > 0) {
        const d = new Date(millis);
        if (!isNaN(d)) {
            const h12 = d.getHours() % 12 || 12;
            const mer = d.getHours() < 12 ? "AM" : "PM";
            const day = d.toLocaleDateString(undefined, { weekday: "long" });
            const month = d.toLocaleDateString(undefined, { month: "long" });
            return `${day}, ${month} ${d.getDate()}, ${d.getFullYear()} ${h12}:${String(d.getMinutes()).padStart(2, "0")} ${mer}`;
        }
    }
    return "Recent";
}

/**
 * A short "Aug 30, 2026" form of the same date, for narrow layouts. Parses the
 * full `game_date` string (or the epoch) - it does NOT introduce a second date
 * source, just a compact rendering of the one we already have.
 */
function matchDateShort(m) {
    const full = matchDateLabel(m);
    if (full === "Recent") return "Recent";
    // "Weekday, Month D, YYYY h:mm AM" -> "Mon D, YYYY"
    const mo = full.match(/([A-Za-z]+) (\d{1,2}), (\d{4})/);
    if (mo) return `${mo[1].slice(0, 3)} ${mo[2]}, ${mo[3]}`;
    const millis = Number(m && (m.started_at || m.game_start_millis) || 0);
    if (millis > 0) {
        const d = new Date(millis);
        if (!isNaN(d)) return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    }
    return full;
}

/**
 * One match row - the single shared component for every match-history entry
 * point (Account Manager modal, Dashboard / Live Stats, player-profile lookup).
 * One fixed-column grid so the same match reads identically everywhere:
 *   [agent] [map + date] [result] [K/D/A] [KD] [HS%] [>]
 */
function matchCardHtml(m, i, source) {
    const outcome = matchOutcome(m);
    const mapAsset = ValorantAssets.getMap(m.map);
    const agentAsset = ValorantAssets.getAgent(m.agent || m.character);
    const agentIcon = m.agent_icon || agentAsset.icon;
    const agentName = agentAsset.unresolved ? "Agent" : agentAsset.name;

    // A degraded scrape (wrong region, unauthenticated key, some TDM rows) can
    // return the map/agent/result but an all-zero combat line and an empty
    // date. Treat "every combat number is zero/absent" as no data and show a
    // dash rather than a misleading "0 / 0 / 0".
    const k = Number(m.kills || 0), d = Number(m.deaths || 0), a = Number(m.assists || 0);
    const kdrGiven = m.kdr != null || m.kd != null;
    const hasCombat = kdrGiven || k > 0 || d > 0 || a > 0;
    const kdrRaw = m.kdr ?? m.kd ?? (hasCombat ? k / Math.max(1, d) : null);
    const kdrVal = kdrRaw != null ? Number(kdrRaw).toFixed(2) : "—";
    const kdrClass = kdrVal === "—" ? "is-neutral"
        : (kdrVal >= 1.5 ? "is-stellar" : (kdrVal >= 1.0 ? "is-positive" : "is-negative"));
    const kda = hasCombat ? `${k} / ${d} / ${a}` : "—";
    const hsRaw = m.hs_pct ?? m.hs;
    const hsPct = !hasCombat ? "—" : `${hsRaw != null ? hsRaw : 0}%`;
    const score = m.placement ? `#${m.placement}`
        : (m.rounds_won != null || m.rounds_lost != null ? `${m.rounds_won ?? 0} : ${m.rounds_lost ?? 0}` : "");
    const mode = `${m.mode || "Competitive"}${m.surrendered ? " · Surr." : ""}`;

    return `
        <button class="match-card ${outcome.cls}" style="--i:${i}; --map-splash: url('${mapAsset.splash}');" type="button" onclick="openMatchDetail(${i}, '${source}')" title="Open full match details">
            <span class="mh-splash" aria-hidden="true"></span>
            <span class="mh-scrim" aria-hidden="true"></span>
            <span class="mh-cell mh-agent">
                <span class="mh-avatar ${agentIcon ? "" : "is-empty"}">
                    ${agentIcon
                        ? `<img src="${agentIcon}" alt="${escapeHtml(agentName)}" onerror="this.closest('.mh-avatar').classList.add('is-empty'); this.remove();">`
                        : `<i class="fa-solid fa-user"></i>`}
                    ${agentAsset.roleIcon ? `<img class="mh-role" src="${agentAsset.roleIcon}" alt="" title="${escapeHtml(agentAsset.role)}">` : ""}
                </span>
                <span class="mh-agent-text">
                    <span class="mh-agent-name">${escapeHtml(agentName)}</span>
                    <span class="mh-mode">${escapeHtml(mode)}</span>
                </span>
            </span>

            <span class="mh-cell mh-map">
                <span class="mh-map-name">${escapeHtml(mapAsset.displayName)}</span>
                <span class="mh-date" title="${escapeHtml(matchDateLabel(m))}"><span class="mh-date-full">${escapeHtml(matchDateLabel(m))}</span><span class="mh-date-short">${escapeHtml(matchDateShort(m))}</span></span>
            </span>

            <span class="mh-cell mh-result">
                <span class="mh-outcome">${escapeHtml(outcome.text)}</span>
                ${score ? `<span class="mh-score">${escapeHtml(score)}</span>` : ""}
            </span>

            <span class="mh-cell mh-stat mh-stat-kda">
                <span class="mh-stat-label">K / D / A</span>
                <span class="mh-stat-val">${escapeHtml(kda)}</span>
            </span>
            <span class="mh-cell mh-stat mh-stat-kd">
                <span class="mh-stat-label">KD</span>
                <span class="mh-stat-val ${kdrClass}">${escapeHtml(kdrVal)}</span>
            </span>
            <span class="mh-cell mh-stat mh-stat-hs">
                <span class="mh-stat-label">HS%</span>
                <span class="mh-stat-val is-hs">${escapeHtml(hsPct)}</span>
            </span>

            <span class="mh-cell mh-chevron"><i class="fa-solid fa-chevron-right"></i></span>
        </button>
    `;
}

function renderMatchHistoryList(matches) {
    if (!matches || matches.length === 0) {
        DOM.matchesListContainer.innerHTML = `
            <div class="no-matches-msg">
                <i class="fa-solid fa-shield-halved" style="font-size: 32px; margin-bottom: 12px; color: var(--accent-purple);"></i>
                <p>No recent match data available for this account.</p>
                <p style="font-size: 12px; color: var(--text-dim); margin-top: 4px;">Play a game or check if your Riot ID is correct.</p>
            </div>
        `;
        return;
    }

    DOM.matchesListContainer.innerHTML = matches.map((m, i) => matchCardHtml(m, i, "account")).join("");
}

// The "Recent Winrate" figure in the match modal should reflect the matches
// actually on screen, not the account's stored lifetime winrate (which is 0
// for accounts whose last stat lookup failed). Falls back to the stored value
// when there are no decided matches to count.
function recentWinrateLabel(matches, storedWinrate) {
    let wins = 0, decided = 0;
    for (const m of (matches || [])) {
        const outcome = (m.outcome || "").toUpperCase();
        if (outcome === "VICTORY") { wins++; decided++; }
        else if (outcome === "DEFEAT") { decided++; }
    }
    if (!decided) return `${storedWinrate || 0}%`;
    return `${Math.round((wins / decided) * 100)}%`;
}

function profileStatsHtml(profile) {
    const currentRank = ValorantAssets.getRank(profile.rank_tier, profile.rank_division);
    const peakRank = ValorantAssets.getRank(profile.peak_rank_tier, profile.peak_rank_division);
    const currentLabel = [profile.rank_tier, profile.rank_division].filter(Boolean).join(" ") || "Unrated";
    const peakLabel = [profile.peak_rank_tier, profile.peak_rank_division].filter(Boolean).join(" ") || "No recorded peak";
    const matches = profile.match_history || [];
    const combat = profile.combat || {};
    const combatAvailable = combat.matches_analyzed || combat.last5_games;
    
    let wins = 0;
    let losses = 0;
    matches.forEach(m => {
        const outcome = (m.outcome || m.result || "").toUpperCase();
        if (outcome === "VICTORY" || outcome === "WIN") wins++;
        else if (outcome === "DEFEAT" || outcome === "LOSS") losses++;
    });
    const winrate = profile.winrate !== undefined ? profile.winrate : (matches.length ? Math.round((wins / matches.length) * 100) : 0);

    return `
        <!-- Profile 4-Card Showcase Grid -->
        <div class="profile-cards-grid">
            <div class="profile-card profile-rank-card current-rank" style="--tier-color: ${currentRank.color}; --tier-glow: ${currentRank.glow};">
                <div class="rank-emblem-wrap">
                    <img src="${profile.rank_icon_url || currentRank.icon}" alt="${escapeHtml(currentLabel)}" class="rank-emblem-img">
                </div>
                <div class="profile-card-info">
                    <span class="profile-card-label">CURRENT RANK</span>
                    <strong class="profile-card-val" style="color: ${currentRank.color};">${escapeHtml(currentLabel)}</strong>
                    <span class="profile-card-sub">${profile.lp !== undefined && profile.lp !== null && profile.lp > 0 ? `${profile.lp} RR` : "Competitive"}</span>
                </div>
            </div>

            <div class="profile-card profile-rank-card peak-rank" style="--tier-color: ${peakRank.color}; --tier-glow: ${peakRank.glow};">
                <div class="rank-emblem-wrap">
                    <img src="${profile.peak_rank_icon_url || peakRank.icon}" alt="${escapeHtml(peakLabel)}" class="rank-emblem-img">
                </div>
                <div class="profile-card-info">
                    <span class="profile-card-label">PEAK RANK</span>
                    <strong class="profile-card-val" style="color: ${peakRank.color};">${escapeHtml(peakLabel)}</strong>
                    <span class="profile-card-sub">${escapeHtml(profile.peak_rank_season || "All-Time Peak")}</span>
                </div>
            </div>

            <div class="profile-card profile-level-card">
                <div class="level-icon-wrap">
                    <i class="fa-solid fa-trophy"></i>
                </div>
                <div class="profile-card-info">
                    <span class="profile-card-label">ACCOUNT LEVEL</span>
                    <strong class="profile-card-val level-val">${profile.level || "—"}</strong>
                    <span class="profile-card-sub">Progression</span>
                </div>
            </div>

            <div class="profile-card profile-winrate-card">
                <div class="winrate-badge-wrap">
                    <i class="fa-solid fa-chart-pie"></i>
                </div>
                <div class="profile-card-info">
                    <span class="profile-card-label">RECENT WIN RATE</span>
                    <strong class="profile-card-val text-cyan">${winrate}%</strong>
                    <span class="profile-card-sub">${wins}W - ${losses}L</span>
                </div>
            </div>
        </div>

        ${combatAvailable ? `
        <h4 class="detail-section-title"><i class="fa-solid fa-crosshairs"></i> Recent Performance</h4>
        <div class="detail-stat-grid">
            <div><span>K/D ratio</span><strong><i class="fa-solid fa-bolt text-gold"></i> ${combat.kd ?? 0}</strong></div>
            <div><span>K / D / A</span><strong>${combat.kills ?? 0} / ${combat.deaths ?? 0} / ${combat.assists ?? 0}</strong></div>
            <div><span>Headshot %</span><strong class="text-hs"><i class="fa-solid fa-bullseye"></i> ${combat.hs_pct ?? 0}%</strong></div>
            <div><span>ADR / ACS</span><strong>${combat.adr ?? 0} / ${combat.acs ?? 0}</strong></div>
        </div>` : ""}

        <h4 class="detail-section-title"><i class="fa-solid fa-clock-rotate-left"></i> Recent Matches</h4>
        <div class="matches-list matches-list-compact">
            ${matches.length
                ? matches.map((m, i) => matchCardHtml(m, i, "profile")).join("")
                : '<p class="no-matches-msg">No public recent-match data is available for this player.</p>'}
        </div>`;
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

function matchTeamHtml(m, teamObj, matchMvpPuuid, teamIndex) {
    const players = (teamObj.players || []).slice().sort((a, b) => Number(b.score || b.acs || 0) - Number(a.score || a.acs || 0));
    const teamMvpPuuid = players.length > 0 ? (players[0].puuid || players[0].riot_id) : null;
    const isWinner = teamObj.won || (teamObj.rounds > (m.rounds_lost || 0));
    const isBlue = /blue/i.test(teamObj.key);
    const isRed = /red/i.test(teamObj.key);
    const teamClass = isBlue ? "team-blue" : (isRed ? "team-red" : "");

    return `
        <section class="detail-team ${isWinner ? "is-winner" : ""} ${teamClass}">
            <div class="detail-team-head">
                <span>
                    <i class="fa-solid ${isBlue ? 'fa-shield' : (isRed ? 'fa-fire' : 'fa-people-group')}"></i> 
                    ${escapeHtml(teamObj.name)}
                </span>
                <strong>${teamObj.rounds} rounds <em class="${isWinner ? 'win-pill' : 'loss-pill'}">${isWinner ? "WIN" : "LOSS"}</em></strong>
            </div>
            <div class="detail-score-head">
                <span>Agent / Player</span>
                <span>K / D / A</span>
                <span>ACS</span>
                <span>Score</span>
                <span>ADR</span>
                <span>HS%</span>
            </div>
            <div class="detail-score-body">${players.map(p => {
                const riotId = p.riot_id && p.riot_id.includes("#") ? p.riot_id : (p.name || "Riot ID resolving…");
                const clickId = encodeURIComponent(p.riot_id || p.name || "");
                const clickPuuid = encodeURIComponent(p.puuid || "");
                const agentAsset = ValorantAssets.getAgent(p.agent || p.agent_icon);
                const agentIcon = p.agent_icon || agentAsset.icon;
                const agentSub = agentAsset.unresolved
                    ? "Agent resolving…"
                    : `${agentAsset.name}${agentAsset.role ? ` · ${agentAsset.role}` : ""}`;
                const pId = p.puuid || p.riot_id;
                const isMatchMvp = pId && pId === matchMvpPuuid;
                const isTeamMvp = pId && !isMatchMvp && pId === teamMvpPuuid;

                return `
                <button type="button" class="detail-score-player ${p.is_self ? "is-self" : ""}" onclick="openPlayerProfile(decodeURIComponent('${clickId}'), decodeURIComponent('${clickPuuid}'))" title="Click to view ${escapeHtml(riotId)}'s profile">
                    <span class="detail-score-identity">
                        <div class="detail-score-agent-icon-wrap ${agentIcon ? "" : "is-empty"}">
                            ${agentIcon
                                ? `<img src="${agentIcon}" alt="${escapeHtml(agentAsset.name)}" onerror="this.closest('.detail-score-agent-icon-wrap').classList.add('is-empty'); this.remove();">`
                                : `<i class="fa-solid fa-user"></i>`}
                            ${agentAsset.roleIcon ? `<img src="${agentAsset.roleIcon}" class="detail-score-role-icon" title="${agentAsset.role}">` : ''}
                        </div>
                        <span class="detail-score-names">
                            <strong>
                                ${escapeHtml(riotId)}
                                ${p.is_self ? '<span class="self-tag">YOU</span>' : ''}
                                ${isMatchMvp ? '<span class="mvp-tag match-mvp" title="Match MVP"><i class="fa-solid fa-crown"></i> MVP</span>' : ''}
                                ${isTeamMvp ? '<span class="mvp-tag team-mvp" title="Team MVP"><i class="fa-solid fa-star"></i> TEAM MVP</span>' : ''}
                            </strong>
                            <small>${escapeHtml(agentSub)}</small>
                        </span>
                    </span>
                    <b><span class="kda-kills">${p.kills ?? 0}</span> / <span class="kda-deaths">${p.deaths ?? 0}</span> / <span class="kda-assists">${p.assists ?? 0}</span></b>
                    <b class="text-acs">${p.acs ?? 0}</b>
                    <b class="text-score">${p.score ?? 0}</b>
                    <b class="text-adr">${p.adr ?? 0}</b>
                    <b class="text-hs">${p.hs_pct ?? 0}%</b>
                </button>`;
            }).join("")}</div>
        </section>`;
}

function openMatchDetail(index, source) {
    const matches = source === "account" ? state.currentAccountMatches : source === "profile" ? state.profileMatches : state.dashboardMatches;
    const m = matches && matches[index];
    if (!m) return;

    const outcome = (m.outcome || m.result || "Match").toUpperCase();
    const isWin = outcome === "VICTORY" || outcome === "WIN";
    const isLoss = outcome === "DEFEAT" || outcome === "LOSS";
    const outcomeClass = isWin ? "outcome-victory" : (isLoss ? "outcome-defeat" : "outcome-draw");
    const mapAsset = ValorantAssets.getMap(m.map);
    const selfAgent = ValorantAssets.getAgent(m.agent || m.character);
    const roster = (m.roster || []).slice();

    // Deduplicate roster players by PUUID / Riot ID to prevent duplicate player rows
    const uniqueRoster = [];
    const seenPuuids = new Set();
    for (const p of roster) {
        const key = (p.puuid || p.riot_id || Math.random().toString()).trim().toLowerCase();
        if (!seenPuuids.has(key)) {
            seenPuuids.add(key);
            uniqueRoster.push(p);
        }
    }

    // Determine Match MVP (highest ACS / score across entire match)
    let matchMvpPuuid = null;
    let maxMatchScore = -1;
    uniqueRoster.forEach(p => {
        const scoreVal = Number(p.score || p.acs || 0);
        if (scoreVal > maxMatchScore) {
            maxMatchScore = scoreVal;
            matchMvpPuuid = p.puuid || p.riot_id;
        }
    });

    // Group teams case-insensitively and canonicalize
    const teamMap = new Map();

    // 1. Seed teams from match summary
    (m.teams || []).forEach(t => {
        const rawName = String(t.team || "").trim();
        if (!rawName) return;
        const key = rawName.toLowerCase();
        if (!teamMap.has(key)) {
            teamMap.set(key, {
                key: key,
                rawId: rawName,
                name: /blue/i.test(key) ? "Blue Team" : (/red/i.test(key) ? "Red Team" : (rawName.charAt(0).toUpperCase() + rawName.slice(1))),
                rounds: Number(t.rounds_won || 0),
                won: Boolean(t.won),
                players: []
            });
        }
    });

    // 2. Add players into team groups
    uniqueRoster.forEach(p => {
        const rawTeam = String(p.team || "Unassigned").trim();
        const key = rawTeam.toLowerCase();
        if (!teamMap.has(key)) {
            teamMap.set(key, {
                key: key,
                rawId: rawTeam,
                name: /blue/i.test(key) ? "Blue Team" : (/red/i.test(key) ? "Red Team" : (rawTeam.charAt(0).toUpperCase() + rawTeam.slice(1))),
                rounds: 0,
                won: false,
                players: []
            });
        }
        teamMap.get(key).players.push(p);
    });

    // 3. Filter only teams with players
    const activeTeams = Array.from(teamMap.values()).filter(t => t.players.length > 0);

    // 4. If rounds won/lost were not in team summary, infer from match headline
    if (activeTeams.length === 2 && activeTeams[0].rounds === 0 && activeTeams[1].rounds === 0) {
        const selfPlayer = uniqueRoster.find(p => p.is_self);
        if (selfPlayer) {
            const selfKey = String(selfPlayer.team || "").toLowerCase();
            const selfTeamObj = activeTeams.find(t => t.key === selfKey) || activeTeams[0];
            const otherTeamObj = activeTeams.find(t => t !== selfTeamObj) || activeTeams[1];
            selfTeamObj.rounds = Number(m.rounds_won || 0);
            otherTeamObj.rounds = Number(m.rounds_lost || 0);
            selfTeamObj.won = Number(m.rounds_won || 0) > Number(m.rounds_lost || 0);
            otherTeamObj.won = Number(m.rounds_lost || 0) > Number(m.rounds_won || 0);
        } else {
            activeTeams[0].rounds = Number(m.rounds_won || 0);
            activeTeams[1].rounds = Number(m.rounds_lost || 0);
            activeTeams[0].won = Number(m.rounds_won || 0) > Number(m.rounds_lost || 0);
            activeTeams[1].won = Number(m.rounds_lost || 0) > Number(m.rounds_won || 0);
        }
    }

    DOM.detailModalTitle.textContent = `${mapAsset.displayName} · ${outcome}`;
    DOM.detailModalSub.textContent = `${m.mode || "Competitive"} · ${m.rounds_won ?? 0} : ${m.rounds_lost ?? 0} · ${matchDateLabel(m)}`;

    DOM.matchDetailContent.innerHTML = `
        <!-- Match Hero Splash Banner -->
        <div class="match-hero-banner ${outcomeClass}" style="--map-splash: url('${mapAsset.splash}');">
            <div class="match-hero-overlay"></div>
            <div class="match-hero-content">
                <div class="match-hero-left">
                    <div class="match-hero-agent-portrait ${selfAgent.icon ? "" : "is-empty"}">
                        ${selfAgent.icon
                            ? `<img src="${selfAgent.icon}" alt="${escapeHtml(selfAgent.name)}" onerror="this.closest('.match-hero-agent-portrait').classList.add('is-empty'); this.remove();">`
                            : `<i class="fa-solid fa-user"></i>`}
                    </div>
                    <div class="match-hero-meta">
                        <span class="match-hero-mode">${escapeHtml(m.mode || "Competitive")}</span>
                        <h2 class="match-hero-map">${escapeHtml(mapAsset.displayName)}</h2>
                        <span class="match-hero-date"><i class="fa-regular fa-clock"></i> ${escapeHtml(matchDateLabel(m))}</span>
                    </div>
                </div>

                <div class="match-hero-center">
                    <div class="match-hero-outcome-badge ${outcomeClass}">${outcome}</div>
                    <div class="match-hero-score">${m.rounds_won ?? 0} <span class="score-divider">:</span> ${m.rounds_lost ?? 0}</div>
                </div>

                <div class="match-hero-right">
                    <div class="hero-stat-pill">
                        <span class="hero-stat-label">K/D/A</span>
                        <span class="hero-stat-val">${m.kills ?? 0}/${m.deaths ?? 0}/${m.assists ?? 0}</span>
                    </div>
                    <div class="hero-stat-pill">
                        <span class="hero-stat-label">KD RATIO</span>
                        <span class="hero-stat-val text-cyan">${(m.kdr ?? m.kd ?? (m.kills / Math.max(1, m.deaths || 1))).toFixed ? (m.kdr ?? m.kd ?? (m.kills / Math.max(1, m.deaths || 1))).toFixed(2) : (m.kdr ?? m.kd ?? 0)}</span>
                    </div>
                    <div class="hero-stat-pill">
                        <span class="hero-stat-label">HEADSHOT</span>
                        <span class="hero-stat-val text-hs">${m.hs_pct ?? m.hs ?? 0}%</span>
                    </div>
                </div>
            </div>
        </div>

        <h4 class="detail-section-title">
            <i class="fa-solid fa-table-list"></i> Full Scoreboard 
            <small>Click any player to view their profile and match history</small>
        </h4>

        <div class="detail-scoreboard">
            ${activeTeams.length ? activeTeams.map((teamObj, i) => matchTeamHtml(m, teamObj, matchMvpPuuid, i)).join("") : '<p class="no-matches-msg">Scoreboard data will appear after this history is refreshed.</p>'}
        </div>

        ${(m.round_results || []).length ? `
        <h4 class="detail-section-title"><i class="fa-solid fa-timeline"></i> Round Timeline</h4>
        <div class="detail-rounds">
            ${m.round_results.map(r => `
                <span class="${/blue/i.test(r.winner) ? "is-blue" : "is-red"}" title="Round ${r.round}: ${escapeHtml(r.result || (r.winner ? `${r.winner} Win` : "Round"))}">
                    ${r.round}
                </span>`).join("")}
        </div>` : ""}`;

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
        } else if (sortBy === "recent") {
            // Never-logged-in accounts sink to the bottom instead of floating
            // to the top on an empty string compare.
            const la = a.last_login || "", lb = b.last_login || "";
            if (!la !== !lb) return la ? -1 : 1;
            return lb.localeCompare(la) || (b.level || 0) - (a.level || 0);
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

    // A login that failed because the Riot Client is elevated needs Vortex
    // elevated too - offer that instead of a plain retry that would just fail
    // the same way.
    const needsElevation = stage === "error" && !!prog.needs_elevation;
    if (DOM.btnElevateLaunch) DOM.btnElevateLaunch.style.display = needsElevation ? "inline-flex" : "none";

    // Retry only makes sense once something has actually failed.
    if (DOM.btnRetryLaunch) {
        DOM.btnRetryLaunch.style.display = (stage === "error" && !needsElevation) ? "inline-flex" : "none";
    }
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
 * Relaunches Vortex elevated (one UAC prompt) so it can drive an elevated
 * Riot Client's login window. This instance exits once the new one starts.
 */
async function relaunchVortexElevated() {
    const btn = DOM.btnElevateLaunch;
    if (btn) { btn.disabled = true; btn.innerHTML = `<i class="fa-solid fa-spinner rotating"></i> Waiting for UAC…`; }
    try {
        const res = await fetch("/api/relaunch-elevated", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            stopLaunchPolling();
            renderLaunchProgress({ stage: "opening", message: data.message || "Restarting as administrator…" });
        } else {
            showToast(data.message || "Couldn't restart as administrator.", "error");
        }
    } catch (err) {
        showToast("Couldn't reach the app's backend.", "error");
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = `<i class="fa-solid fa-shield-halved"></i> Restart as administrator`; }
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
                stopLaunchPolling();
                showToast(data.message || "Could not start login", "info");
                renderLaunchProgress({ stage: "error", message: data.message || "Could not start login." });
            }
        })
        .catch(() => {
            stopLaunchPolling();
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

// The three telemetry keys move together behind one user-facing toggle. Any
// one of them being on is treated as the feature being on (covers existing
// users who had only the Overwolf provider enabled before the merge).
function liveMatchFeaturesOn() {
    return state.settings.live_hud_enabled === "1"
        || state.settings.overwolf_enabled === "1"
        || state.settings.valorant_tracker_enabled === "1";
}

function openSettingsModal() {
    DOM.settingsClientPath.value = state.settings.riot_client_path || "";
    DOM.settingsApiKey.value = state.settings.riot_api_key || "";
    if (DOM.settingsLiveMatchEnabled) DOM.settingsLiveMatchEnabled.checked = liveMatchFeaturesOn();
    if (DOM.settingsPostValorantEnabled) DOM.settingsPostValorantEnabled.checked = (state.settings.post_valorant_launch_enabled || "0") !== "0";
    if (DOM.settingsPostValorantPath) {
        DOM.settingsPostValorantPath.value = state.settings.post_valorant_launch_path || "";
        if (state.settings.post_valorant_launch_default_path)
            DOM.settingsPostValorantPath.placeholder = state.settings.post_valorant_launch_default_path;
    }
    if (DOM.settingsAppVersion) {
        DOM.settingsAppVersion.value = state.appVersion ? `v${state.appVersion}` : "Loading...";
    }
    loadLoginLogPath();
    if (DOM.settingsStaySignedIn) DOM.settingsStaySignedIn.checked = (state.settings.stay_signed_in || "1") !== "0";
    if (DOM.settingsAutoLaunch) DOM.settingsAutoLaunch.checked = state.settings.auto_launch_after_login === "1";
    openModal(DOM.modalSettings);
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
    // One user-facing toggle drives all three telemetry providers. Enabling it
    // turns on the aim HUD plus the Overwolf feed and keeps the Valorant
    // Tracker log as an internal fallback; disabling it turns all three off.
    const liveMatchOn = !!DOM.settingsLiveMatchEnabled?.checked;
    const payload = {
        settings: {
            riot_client_path: DOM.settingsClientPath ? DOM.settingsClientPath.value.trim() : (state.settings.riot_client_path || ""),
            riot_api_key: DOM.settingsApiKey ? DOM.settingsApiKey.value.trim() : (state.settings.riot_api_key || ""),
            live_hud_enabled: liveMatchOn ? "1" : "0",
            overwolf_enabled: liveMatchOn ? "1" : "0",
            valorant_tracker_enabled: liveMatchOn ? "1" : "0",
            stay_signed_in: DOM.settingsStaySignedIn?.checked ? "1" : "0",
            auto_launch_after_login: DOM.settingsAutoLaunch?.checked ? "1" : "0",
            post_valorant_launch_enabled: DOM.settingsPostValorantEnabled?.checked ? "1" : "0",
            post_valorant_launch_path: (DOM.settingsPostValorantPath?.value || "").trim()
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
            void setLiveHudEnabled(liveMatchOn);
            showToast("Settings saved", "success");
            closeModal(DOM.modalSettings);
        }
    } catch (err) {
        showToast("Failed to save settings", "error");
    }
}

/** Applies the HUD switch immediately in the desktop build; browser mode just saves it. */
async function setLiveHudEnabled(enabled) {
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.setLiveHudEnabled !== "function") return;
    try {
        const result = await api.setLiveHudEnabled(!!enabled);
        if (result && result.restart_required) {
            showToast("Restart Vortex once to enable the Live Aim HUD.", "info");
        }
    } catch (err) {
        console.warn("Couldn't update the live HUD window", err);
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
    const filename = `valorant_accounts_backup_${new Date().toISOString().slice(0, 10)}.json`;
    try {
        const res = await fetch("/api/export");
        const text = await res.text();

        // In the desktop build WebView2 blocks a programmatic <a download>, so
        // route the save through the native dialog exposed by app.py. The
        // browser build has no such bridge and falls back to the blob link.
        const api = window.pywebview && window.pywebview.api;
        if (api && typeof api.saveBackup === "function") {
            const result = await api.saveBackup(text, filename);
            if (result && result.cancelled) return;
            if (!result || !result.success) {
                showToast("Failed to export", "error");
                return;
            }
        } else {
            const url = window.URL.createObjectURL(new Blob([text], { type: "application/json" }));
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        }

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
            const bannedList = Array.isArray(parsed) ? [] : (parsed.banned_accounts || []);

            if (accountsList.length === 0 && bannedList.length === 0) {
                showToast("No accounts found in backup", "error");
                return;
            }

            const res = await fetch("/api/import", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    ...parsed,
                    accounts: accountsList
                })
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
const LIVE_POLL_MENUS = 5000;
const LIVE_POLL_SIGNED_IN = 20000;
const LIVE_POLL_IDLE = 30000;
const LIVE_POLL_HIDDEN = 60000;

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
    if (titleEl) titleEl.textContent = isValRunning ? "DASHBOARD" : "PLAY VALORANT";
    if (subEl) subEl.textContent = isValRunning ? "Open Live Match Dashboard" : "Launch Game Client";

    const chipEl = heroCard.querySelector(".session-state-chip");
    if (chipEl) {
        chipEl.className = `session-state-chip ${sessionInfo.cls}`;
        chipEl.textContent = isValRunning ? sessionInfo.label : "Riot Session Active";
    }

    const playBtn = heroCard.querySelector(".btn-hero-play");
    if (playBtn) {
        playBtn.classList.toggle("is-running", isValRunning);
        playBtn.classList.toggle("is-dashboard", isValRunning);
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
    const wasValorantRunning = !!(state.live && state.live.available && state.live.valorant_running);
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
    const isValorantRunning = !!(live.available && live.valorant_running);
    if (previousId !== state.activeAccountId || (live.available && !hadHero) || wasBanned !== nowBanned || wasValorantRunning !== isValorantRunning) {
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

// Horizontal slide between the roster and the dashboard, so PLAY -> dashboard
// (and back) reads as one movement instead of a hard cut. `swap` flips the
// view classes while both panels are briefly mounted together; the outgoing
// panel is pinned on top and slid off while the incoming one slides in. The
// returned promise resolves once the slide has finished. `back` mirrors the
// direction so leaving feels like the reverse of entering.
function runViewSlide(swap, { back = false } = {}) {
    const swapEl = DOM.viewSwap;
    const leaving = back ? DOM.dashView : DOM.accountsView;
    const entering = back ? DOM.accountsView : DOM.dashView;

    // No container or reduced motion: skip straight to the swapped state.
    if (!swapEl || !leaving || !entering || PREFERS_REDUCED_MOTION) {
        return Promise.resolve(swap());
    }

    // Pin the slot to its current height and hold the outgoing panel in place
    // (absolute, on top) while the synchronous view-state flip makes the
    // incoming panel available for measurement.
    swapEl.style.height = swapEl.offsetHeight + "px";
    swapEl.classList.add("is-sliding");
    leaving.classList.add("view-leaving");

    swap();
    return new Promise(resolve => {
        entering.classList.add("view-entering");

        // Ease the slot between the two panel heights alongside the slide,
        // then kick off the slide itself on the next frame.
        const endH = entering.offsetHeight;
        requestAnimationFrame(() => {
            swapEl.style.transition = "height var(--dur-4) var(--ease-out)";
            swapEl.style.height = endH + "px";
            swapEl.classList.add(back ? "slide-back" : "slide-forward");
        });

        let settled = false;
        const finish = () => {
            if (settled) return;
            settled = true;
            swapEl.classList.remove("is-sliding", "slide-back", "slide-forward");
            leaving.classList.remove("view-leaving");
            entering.classList.remove("view-entering");
            swapEl.style.transition = "";
            swapEl.style.height = "";
            resolve();
        };

        // Only the slide's own animation ends the slide - the dashboard is
        // full of nested entrance animations whose animationend also bubbles
        // up to this element.
        const onEnd = e => {
            if (e.target !== entering) return;
            entering.removeEventListener("animationend", onEnd);
            finish();
        };
        entering.addEventListener("animationend", onEnd);
        // Safety net in case animationend never lands (tab hidden mid-slide).
        window.setTimeout(finish, 900);
    });
}

async function openDashboard() {
    if (state.dashboardOpen || state._dashTransitioning) return;
    state._dashTransitioning = true;

    const transition = runViewSlide(() => {
        state.dashboardOpen = true;

        document.body.classList.add("dashboard-mode");
        if (DOM.dashView) {
            DOM.dashView.classList.add("is-open");
            DOM.dashView.setAttribute("aria-hidden", "false");
        }

        moveTabGlide();

        if (state.live) renderDashboard(state.live);
        scheduleLivePoll(0);
        // The roster collapses out from under the page, so anchor back to the
        // top rather than leaving the view stranded mid-document.
        window.scrollTo({ top: 0, behavior: "auto" });
    });

    // The incoming view is now mounted and the slide has been scheduled.
    // Loading agent ownership must never delay first motion or expose an
    // intermediate overlap; update the already-visible dashboard afterward.
    void loadLiveAgents().then(() => {
        if (!state.dashboardOpen) return;
        renderModeGrid();
        renderAgentGrid();
        refreshInstalockStatus(true);
    });

    await transition;

    state._dashTransitioning = false;
}

async function closeDashboard() {
    if (!state.dashboardOpen || state._dashTransitioning) return;
    state._dashTransitioning = true;

    await runViewSlide(() => {
        state.dashboardOpen = false;

        document.body.classList.remove("dashboard-mode");
        if (DOM.dashView) {
            DOM.dashView.classList.remove("is-open");
            DOM.dashView.setAttribute("aria-hidden", "true");
        }
        stopLiveTimers();
        clearTimeout(state._statsTimer);
        window.scrollTo({ top: 0, behavior: "auto" });
    }, { back: true });

    state._dashTransitioning = false;
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

function getQueueElapsed() {
    return state.queueStartedAt
        ? Math.max(0, Math.floor((Date.now() - state.queueStartedAt) / 1000))
        : 0;
}

function queueStatusText(live, elapsed) {
    const queueId = activeQueueId(live);
    const mode = modeById(queueId);
    const modeName = mode ? mode.name : (live.queue_label || "Competitive");
    return `Matchmaking (In Queue) · ${live.queue_label || modeName} · ${formatClock(elapsed)}`;
}

function syncQueueTimer(live, inQueue) {
    if (!inQueue) {
        stopQueueClock();
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
    if (!state.queueStartedAt) return;
    const elapsed = getQueueElapsed();
    if (DOM.dashQueueClock) DOM.dashQueueClock.textContent = formatClock(elapsed);

    // Both queue readouts use this same local timer. The live-session poll
    // still determines whether the queue exists, but no longer drives the
    // visible seconds under the Cancel Queue button.
    const live = state.live;
    if (DOM.dashQueueStatus && live && live.party && live.party.in_queue) {
        DOM.dashQueueStatus.textContent = queueStatusText(live, elapsed);
    }
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
}

function stopLiveTimers() {
    stopQueueClock();
    state.pregameEndsAt = 0;
    if (_pregameTimerInterval) {
        clearInterval(_pregameTimerInterval);
        _pregameTimerInterval = null;
    }
}

// -- match hero, personal line, rosters -----------------------------------

const DEFAULT_UNRANKED_ICON =
    `${LOCAL_GAME_ASSET_ROOT}competitivetiers/03621f52-342b-cf4e-4f86-9350a49c6d04/0/largeicon.png`;

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

/** Compact, round-by-round aim graph for the live player card and HUD. */
function renderAccuracyGraph(current, share) {
    const reports = Array.isArray(current.accuracy_history) ? current.accuracy_history.slice(-12) : [];
    const values = reports.map(report => {
        const head = Number(report.headshots || 0);
        const body = Number(report.bodyshots || 0);
        const leg = Number(report.legshots || 0);
        const hits = head + body + leg;
        return hits ? Math.round((head / hits) * 100) : 0;
    });
    const chartValues = values.length ? values : [Number(current.hs_pct || 0)];
    const width = 252;
    const height = 58;
    const pad = 7;
    const step = chartValues.length > 1 ? (width - pad * 2) / (chartValues.length - 1) : 0;
    const point = (value, index) => {
        const x = chartValues.length === 1 ? width / 2 : pad + index * step;
        const y = height - pad - ((Math.max(0, Math.min(100, value)) / 100) * (height - pad * 2));
        return [x.toFixed(1), y.toFixed(1)];
    };
    const points = chartValues.map((value, index) => point(value, index).join(",")).join(" ");
    const first = point(chartValues[0], 0);
    const last = point(chartValues[chartValues.length - 1], chartValues.length - 1);
    const area = `${first[0]},${height - pad} ${points} ${last[0]},${height - pad}`;
    const hs = current.hs_pct != null ? Number(current.hs_pct).toFixed(1) : "--";
    const observed = Number(current.rounds_observed || reports.length || 0);

    return '<div class="dash-accuracy-card" title="Headshot accuracy by observed round">' +
        '<div class="dash-accuracy-heading">' +
            '<span><i class="fa-solid fa-chart-line"></i> Aim trace</span>' +
            '<strong>' + hs + '% <small>HS</small></strong>' +
        '</div>' +
        '<div class="dash-accuracy-plot">' +
            '<span class="dash-accuracy-grid g1"></span><span class="dash-accuracy-grid g2"></span><span class="dash-accuracy-grid g3"></span>' +
            '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" aria-hidden="true">' +
                '<defs><linearGradient id="aim-trace-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fb7185" stop-opacity=".42"/><stop offset="1" stop-color="#fb7185" stop-opacity="0"/></linearGradient></defs>' +
                '<polygon points="' + area + '" fill="url(#aim-trace-fill)"></polygon>' +
                '<polyline points="' + points + '" fill="none" stroke="#fb7185" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></polyline>' +
                '<circle cx="' + last[0] + '" cy="' + last[1] + '" r="3.1" fill="#fff" stroke="#fb7185" stroke-width="2"></circle>' +
            '</svg>' +
        '</div>' +
        '<div class="dash-accuracy-meta">' +
            '<span><i class="dot is-head"></i> Head ' + share(current.headshots) + '%</span>' +
            '<span><i class="dot is-body"></i> Body ' + share(current.bodyshots) + '%</span>' +
            '<span><i class="dot is-leg"></i> Leg ' + share(current.legshots) + '%</span>' +
            '<span class="dash-hs-dmg">' + Number(current.damage || 0).toLocaleString() + ' dmg · ' + observed + ' rds</span>' +
        '</div>' +
    '</div>';
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
    const gepLive = cur.source === "overwolf_gep" || cur.source === "vortex_telemetry";

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
        { k: cur.hs_pct != null ? "Headshot" : "HS Kills", v: cur.hs_pct != null ? pct(cur.hs_pct) : pct(cur.headshot_kill_pct), c: hasCombat ? "is-hs" : "is-pending" },
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
            k: "Round Win",
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
        { k: "Avg HS", v: pct(recent.hs_pct), c: "is-hs" },
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

    // GEP combat is real live data, so don't waste space on a warning banner.
    // The graph below communicates the source and updates every observed round.
    const pendingHtml = gepLive ? "" : (hasCombat ? "" :
        '<div class="dash-me-pending">' +
            '<i class="fa-solid fa-hourglass-half"></i>' +
            '<span>' + escapeHtml(cur.reason || "Waiting on Riot for this match's combat stats.") +
            ' Rounds, sides and streak above are live now; K/D/A, HS%, ADR and ACS appear when Vortex Telemetry is connected.</span>' +
        '</div>');

    const hitHtml = (hasCombat && shots)
        ? renderAccuracyGraph(cur, share)
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

        // Show exact current-game K/D when Overwolf's live provider has it for
        // this player; otherwise the recent-match averages, same as always. The
        // averages are never relabelled as live.
        const live = (p.live && p.live.available) ? p.live : null;
        const liveKd = live ? (Number(live.kills || 0) / Math.max(1, Number(live.deaths || 0))) : 0;
        const liveKda = live
            ? (live.assists != null
                ? `${live.kills}/${live.deaths}/${live.assists}`
                : `${live.kills}/${live.deaths}`)
            : "";
        const liveStatsHtml = live
            ? stat("is-kd", "fa-crosshairs", liveKda, "Current match kills / deaths" + (live.assists != null ? " / assists" : "")) +
              stat("is-kd", "fa-chart-line", `${liveKd.toFixed(2)} KD`, "Current match K/D") +
              `<span class="dash-player-stat-pill is-live" title="Exact current-game numbers from Overwolf"><i class="fa-solid fa-satellite-dish"></i> LIVE</span>`
            : stat("is-kd", "fa-crosshairs", p.kd > 0 ? `${p.kd} KD` : "-- KD", "Recent matches K/D") +
              stat("is-hs", "fa-bullseye", p.hs_pct > 0 ? `${p.hs_pct}% HS` : "-- HS", "Recent matches Headshot accuracy") +
              stat("is-adr", "fa-burst", p.adr > 0 ? `${p.adr} ADR` : "-- ADR", "Recent average damage per round") +
              stat("is-wr", "fa-chart-simple", wrValue, wrTitle) + formPips;

        return `
            <button type="button" class="dash-player ${p.is_self ? "is-self" : ""} ${p.locked ? "is-locked" : ""} ${group ? `has-party pg-${((group - 1) % 5) + 1}` : ""}" onclick="openPlayerProfile(decodeURIComponent('${encodeURIComponent(p.name || "")}'), decodeURIComponent('${encodeURIComponent(p.puuid || "")}'))" title="Check this player's match history">
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
                        ${liveStatsHtml}
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
 * The header PLAY button is retired: the single Play action now lives in the
 * "Start a Match" panel (renderSidePlayButton) so the closed-game state has
 * exactly one launch button. This keeps the element hidden and inert; the
 * "VALORANT CLOSED / RUNNING" chip beside it stays as status only.
 */
function renderPlayButton(live) {
    const running = !!(live && live.valorant_running);
    const launch = (live && live.launch) || {};

    // Still clear the optimistic lock once the backend owns the state, so the
    // side Play button settles correctly.
    if (state.playPending && (launch.active || running || launch.stage === "failed")) {
        state.playPending = false;
    }

    if (DOM.btnDashPlay) DOM.btnDashPlay.hidden = true;
}

/**
 * The single Play VALORANT action, in the "Start a Match" panel. Shown only
 * while VALORANT is not running (see renderQueueControls). Styling comes
 * entirely from CSS / the theme accent - nothing here forces a colour.
 */
function renderSidePlayButton(live) {
    if (!DOM.btnSidePlay) return;
    const launch = (live && live.launch) || {};
    const running = !!(live && live.valorant_running);
    const launching = !!launch.active || (state.playPending && !running);

    let title = "Play VALORANT";
    let sub = "Starts the game for this account";
    let icon = "fa-solid fa-play";
    let disabled = false;

    if (launching) {
        title = "Starting VALORANT…";
        sub = launch.message || "Launching the game";
        icon = "fa-solid fa-circle-notch fa-spin";
        disabled = true;
    } else if (launch.stage === "failed") {
        title = "VALORANT didn't start";
        sub = "Tap to try again";
        icon = "fa-solid fa-rotate-right";
    }

    if (DOM.sidePlayIcon) DOM.sidePlayIcon.className = icon;
    if (DOM.sidePlayTitle) DOM.sidePlayTitle.textContent = title;
    if (DOM.sidePlaySub) DOM.sidePlaySub.textContent = sub;
    DOM.btnSidePlay.disabled = disabled;
    DOM.btnSidePlay.classList.toggle("is-launching", launching);
}

async function forceLaunchValorant() {
    if (state.playPending) return;
    state.playPending = true;
    renderPlayButton(state.live);
    renderSidePlayButton(state.live);

    try {
        const res = await fetch("/api/live/launch", { method: "POST" });
        const data = await res.json();
        showToast(data.message || "Starting VALORANT…", data.success ? "success" : "error");

        if (!data.success) state.playPending = false;
        if (data.launch) state.live = { ...(state.live || {}), launch: data.launch };
        renderPlayButton(state.live);
        renderSidePlayButton(state.live);
    } catch (err) {
        state.playPending = false;
        showToast("Couldn't reach the app's backend", "error");
        renderPlayButton(state.live);
        renderSidePlayButton(state.live);
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

    // Single source of truth: the live snapshot's process state. When VALORANT
    // is not running the "Start a Match" panel shows ONLY "Play VALORANT" - no
    // Start-Match button, no "VALORANT isn't running" card. When it is running,
    // the normal Start-Match controls come back and Play VALORANT is gone.
    const gameRunning = !!live.valorant_running;

    // -- CTA -----------------------------------------------------------
    if (DOM.dashCtaIcon) DOM.dashCtaIcon.className = mode ? mode.icon : "fa-solid fa-trophy";

    let ctaTitle = `Start ${modeName} Match`;
    let ctaSub = `Queues up for ${modeName}`;

    if (inMatch) {
        ctaTitle = live.match.phase === "agent_select" ? "In agent select" : "You're in a match";
        ctaSub = "Finish or leave it before queueing again";
    } else if (inQueue) {
        ctaTitle = "Matchmaking (In Queue)";
        ctaSub = `Searching for ${live.queue_label || modeName}`;
    }

    if (DOM.dashCtaTitle) DOM.dashCtaTitle.textContent = ctaTitle;
    if (DOM.dashCtaSub) DOM.dashCtaSub.textContent = ctaSub;

    // Swap Start Match <-> Play VALORANT on game state.
    if (DOM.btnSidePlay) {
        DOM.btnStartRanked.hidden = !gameRunning;
        DOM.btnSidePlay.hidden = gameRunning;
        if (!gameRunning) renderSidePlayButton(live);
    }

    DOM.btnStartRanked.disabled = !canControl || inQueue || inMatch;
    DOM.btnStartRanked.classList.toggle("is-queued", inQueue);

    DOM.btnQueueStop.disabled = !canControl || !inQueue;
    DOM.btnQueueStop.style.display = (gameRunning && inQueue) ? "flex" : "none";

    // -- status line ---------------------------------------------------
    if (inQueue) {
        DOM.dashQueueStatus.textContent =
            queueStatusText(live, state.queueStartedAt
                ? getQueueElapsed()
                : (live.queue_elapsed || 0));
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
        if (data.success) stopQueueClock();
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

// Ticks locally so both queue readouts count from the same start timestamp
// instead of jumping with the live-session poll interval.
function startQueueClock() {
    if (_queueTimerInterval) clearInterval(_queueTimerInterval);
    updateQueueClockDisplay();
    _queueTimerInterval = setInterval(updateQueueClockDisplay, 500);
}

// -- insta-lock ----------------------------------------------------------

function renderAgentGrid() {
    if (!DOM.dashAgentGrid) return;

    const query = (DOM.dashAgentSearch ? DOM.dashAgentSearch.value : "").trim().toLowerCase();
    const agents = state.agents
        .filter(a => !query || a.name.toLowerCase().includes(query))
        // Owned agents float to the top; the backend already sorts by name.
        .slice()
        .sort((a, b) => (b.owned !== false ? 1 : 0) - (a.owned !== false ? 1 : 0));

    if (!agents.length) {
        DOM.dashAgentGrid.innerHTML = `<p class="dash-roster-empty">${
            state.agents.length ? "No agents match that search." : "Agent list unavailable - check your connection."
        }</p>`;
        return;
    }

    DOM.dashAgentGrid.innerHTML = agents.map(a => {
        const locked = a.owned === false;
        return `
        <button class="dash-agent-btn ${a.id === state.selectedAgentId ? "active" : ""} ${locked ? "locked" : ""}"
                data-agent="${escapeHtml(a.id)}" ${locked ? "disabled" : ""}
                title="${escapeHtml(a.name)}${a.role ? " · " + escapeHtml(a.role) : ""}${locked ? " · not owned on this account" : ""}">
            <img src="${a.icon}" alt="${escapeHtml(a.name)}"
                 loading="lazy" decoding="async" onerror="this.style.visibility='hidden';">
            <span>${escapeHtml(a.name)}</span>
        </button>`;
    }).join("");

    DOM.dashAgentGrid.querySelectorAll(".dash-agent-btn:not(.locked)").forEach(btn => {
        btn.addEventListener("click", () => selectAgent(btn.dataset.agent));
    });
}

/**
 * Picks an agent for insta-lock. When insta-lock is already armed, switching
 * agents has to re-arm the backend with the new target - otherwise the UI
 * highlight moves but the watcher keeps locking the previous agent. The
 * highlight updates optimistically, then reverts if the backend rejects it.
 */
async function selectAgent(agentId) {
    const agent = state.agents.find(a => a.id === agentId);
    if (agent && agent.owned === false) return;

    const previousId = state.selectedAgentId;
    const nextId = previousId === agentId ? null : agentId;
    const wasArmed = !!(state.instalock && state.instalock.enabled);

    state.selectedAgentId = nextId;
    renderAgentGrid();
    updateInstalockControls();

    // Only the "armed + actually changed to a different agent" case needs a
    // backend round-trip and confirmation. Clearing the pick or picking while
    // disarmed is purely local until INSTALOCK is pressed.
    if (!wasArmed || !nextId || nextId === previousId) return;

    try {
        const res = await fetch("/api/live/instalock", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: true, agent_id: nextId })
        });
        const data = await res.json();

        if (data.success && data.instalock && data.instalock.enabled &&
            (data.instalock.agent_id || "").toLowerCase() === nextId.toLowerCase()) {
            state.instalock = data.instalock;
            updateInstalockControls();
            showToast(`Autolock updated to ${agent ? agent.name : "your agent"}`, "success");
        } else {
            throw new Error(data.message || "target unchanged");
        }
    } catch (err) {
        // Revert to the agent the backend still has armed.
        state.selectedAgentId = previousId;
        await refreshInstalockStatus(true);
        renderAgentGrid();
        updateInstalockControls();
        showToast("Failed to update autolock agent", "error");
    }
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
            ${statTile("Headshot", `${combat.hs || 0}%`,
                       `Last ${combat.matches || 0} matches`, "is-accent")}
            ${statTile("K/D", combat.kd || 0, `KDA ${combat.kda || 0}`, combat.kd >= 1 ? "is-ok" : "is-bad")}
            ${statTile("ACS", combat.acs || 0, "Avg combat score", "is-gold")}
            ${statTile("Avg K/D/A", `${combat.avg_kills || 0} / ${combat.avg_deaths || 0} / ${combat.avg_assists || 0}`,
                       "Per match", "is-compact")}
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
            <div class="stat-trend-label"><i class="fa-solid fa-chart-line"></i> ${escapeHtml(s.trend_label || "Performance trend")}</div>
            ${renderSparkline((s.performance_history && s.performance_history.length) ? s.performance_history : (s.rr_history || []))}
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
            <div class="matches-list matches-list-compact">
                ${s.recent.map((m, i) => matchCardHtml(m, i, "dashboard")).join("")}
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
    if (!points || !points.length) return "";

    const w = 100, h = 30;
    const values = points.length === 1 ? [points[0], points[0]] : points;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(max - min, 1);
    const flat = max === min;

    const coords = values.map((p, i) => {
        const x = (i / (values.length - 1)) * w;
        const y = flat ? h / 2 : h - ((p - min) / span) * (h - 4) - 2;
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
    if (DOM.dashClose) DOM.dashClose.addEventListener("click", closeDashboard);
    if (DOM.btnDashPlay) DOM.btnDashPlay.addEventListener("click", forceLaunchValorant);
    if (DOM.btnSidePlay) DOM.btnSidePlay.addEventListener("click", forceLaunchValorant);

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
