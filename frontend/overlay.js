(function () {
    "use strict";

    const POLL_INTERVAL_MS = 3000;
    const CONFIRM_WINDOW_MS = 8000;

    const view = {
        shell: document.getElementById("overlay-shell"),
        sessionCard: document.querySelector(".session-card"),
        sessionName: document.getElementById("session-name"),
        sessionChip: document.getElementById("session-chip"),
        sessionDetail: document.getElementById("session-detail"),
        btnRefresh: document.getElementById("btn-refresh"),
        btnClose: document.getElementById("btn-close"),
        btnOpenMain: document.getElementById("btn-open-main"),
        btnEmptyOpenMain: document.getElementById("btn-empty-open-main"),
        tabs: Array.from(document.querySelectorAll(".tab-button")),
        panels: Array.from(document.querySelectorAll(".tab-panel")),
        accountCount: document.getElementById("account-count"),
        crosshairCount: document.getElementById("crosshair-count"),
        accountSearch: document.getElementById("account-search"),
        accountFilters: document.getElementById("account-filters"),
        accountList: document.getElementById("account-list"),
        accountsEmpty: document.getElementById("accounts-empty"),
        accountsEmptyDetail: document.getElementById("accounts-empty-detail"),
        gameWarning: document.getElementById("game-warning"),
        gameWarningText: document.getElementById("game-warning-text"),
        crosshairList: document.getElementById("crosshair-list"),
        launchGame: document.getElementById("toggle-launch-game"),
        toastStack: document.getElementById("toast-stack")
    };

    const model = {
        live: {
            available: false,
            valorant_running: false,
            account_id: null,
            state: "OFFLINE"
        },
        accounts: [],
        crosshairs: [],
        settings: {},
        connected: false,
        firstLoad: true,
        loadingState: false,
        busyAccountId: null,
        pendingConfirm: null,
        confirmTimer: null,
        activeTab: "accounts",
        accountFilter: "all",
        launchGame: readLaunchPreference(),
        crosshairsLoaded: false
    };

    function readLaunchPreference() {
        try {
            const stored = window.localStorage.getItem("vortex.overlay.launchGame");
            return stored === null ? true : stored === "1";
        } catch (_error) {
            return true;
        }
    }

    function saveLaunchPreference(enabled) {
        try {
            window.localStorage.setItem("vortex.overlay.launchGame", enabled ? "1" : "0");
        } catch (_error) {
            // The desktop view may run in private storage mode; persistence is optional.
        }
    }

    function asArray(value) {
        if (Array.isArray(value)) return value;
        if (value && Array.isArray(value.presets)) return value.presets;
        if (value && Array.isArray(value.crosshairs)) return value.crosshairs;
        return [];
    }

    function cleanText(value, fallback = "") {
        if (value === null || value === undefined) return fallback;
        const text = String(value).trim();
        return text || fallback;
    }

    function accountLabel(account) {
        return cleanText(account.display_name, cleanText(account.username, "Unnamed account"));
    }

    const LOCAL_GAME_ASSET_ROOT = "/static/assets/valorant-api/";
    const localGameAssetUrl = value => typeof value === "string"
        ? value.replace(/^https:\/\/media\.valorant-api\.com\//i, LOCAL_GAME_ASSET_ROOT)
        : value;
    const DEFAULT_TIER_ICON = `${LOCAL_GAME_ASSET_ROOT}competitivetiers/03621f52-342b-cf4e-4f86-9350a49c6d04/0/largeicon.png`;

    function accountRank(account) {
        if (account.rank_label) return cleanText(account.rank_label);
        const rank = [account.rank_tier, account.rank_division]
            .map(value => cleanText(value))
            .filter(Boolean)
            .join(" ");
        return rank || "Unranked";
    }

    function accountRankDetail(account) {
        const label = accountRank(account);
        const rr = Number(account.lp);
        return Number.isFinite(rr) && rr > 0 ? `${label} · ${rr} RR` : label;
    }

    function accountRankIcon(account) {
        return localGameAssetUrl(cleanText(account.rank_icon_url)) || DEFAULT_TIER_ICON;
    }

    async function apiRequest(url, options = {}) {
        const request = {
            cache: "no-store",
            headers: { "Accept": "application/json", ...(options.headers || {}) },
            ...options
        };
        if (request.body !== undefined && typeof request.body !== "string") {
            request.headers["Content-Type"] = "application/json";
            request.body = JSON.stringify(request.body);
        }

        const response = await fetch(url, request);
        const contentType = response.headers.get("content-type") || "";
        const data = contentType.includes("application/json")
            ? await response.json()
            : { message: await response.text() };

        if (!response.ok) {
            const detail = typeof data.detail === "string" ? data.detail : "";
            throw new Error(detail || data.message || `Request failed (${response.status})`);
        }
        return data;
    }

    async function fetchFallbackCrosshairs() {
        if (model.crosshairsLoaded) return;
        try {
            const response = await fetch("assets/crosshairs.json", { cache: "no-store" });
            if (!response.ok) throw new Error("Crosshair library unavailable");
            const data = await response.json();
            model.crosshairs = asArray(data);
            model.crosshairsLoaded = true;
            renderCrosshairs();
        } catch (_error) {
            model.crosshairs = [];
            renderCrosshairs();
        }
    }

    async function refreshState({ announceError = false } = {}) {
        if (model.loadingState) return;
        model.loadingState = true;
        view.btnRefresh.classList.add("is-spinning");

        try {
            const data = await apiRequest("/api/overlay/state");
            model.live = data.live && typeof data.live === "object" ? data.live : model.live;
            model.accounts = asArray(data.accounts);
            model.settings = data.settings && typeof data.settings === "object" ? data.settings : {};

            const incomingCrosshairs = asArray(data.crosshairs);
            if (incomingCrosshairs.length) {
                model.crosshairs = incomingCrosshairs;
                model.crosshairsLoaded = true;
            } else if (!model.crosshairsLoaded) {
                void fetchFallbackCrosshairs();
            }

            model.connected = true;
            renderAll();
        } catch (error) {
            model.connected = false;
            renderLiveState();
            if (model.firstLoad) {
                model.accounts = [];
                renderAccounts();
            }
            if (announceError) showToast(error.message || "Could not refresh the quick panel.", "error");
            void fetchFallbackCrosshairs();
        } finally {
            model.firstLoad = false;
            model.loadingState = false;
            view.btnRefresh.classList.remove("is-spinning");
        }
    }

    function renderAll() {
        renderLiveState();
        renderAccounts();
        renderCrosshairs();
    }

    function renderLiveState() {
        const live = model.live || {};
        const rawState = cleanText(live.state, "OFFLINE").toUpperCase();
        let visualState = rawState.toLowerCase();
        let chip = rawState;
        let name = cleanText(live.display_name, cleanText(live.username));
        let detail = cleanText(live.message);

        if (!model.connected) {
            visualState = model.firstLoad ? "connecting" : "offline";
            chip = model.firstLoad ? "CONNECTING" : "OFFLINE";
            name = model.firstLoad ? "Checking Riot session…" : "Vortex service unavailable";
            detail = model.firstLoad
                ? "Loading your current account and game state."
                : "Open the full app or press refresh to reconnect.";
        } else if (!live.available) {
            visualState = "offline";
            chip = "SIGNED OUT";
            name = "No Riot account signed in";
            detail = "Choose an account below for a quick login.";
        } else if (!live.valorant_running) {
            visualState = "client";
            chip = "RIOT CLIENT";
            detail = cleanText(live.rank_label, "Signed in — VALORANT is closed.");
        } else if (rawState === "INGAME") {
            visualState = "ingame";
            chip = "IN MATCH";
            detail = live.queue_label
                ? `${cleanText(live.queue_label)} — switching will close the game.`
                : "Match active — switching will close the game.";
        } else if (rawState === "PREGAME") {
            visualState = "pregame";
            chip = "AGENT SELECT";
            detail = "Agent select active — switching will close the game.";
        } else {
            visualState = "menus";
            chip = "IN MENUS";
            detail = live.queue_label
                ? cleanText(live.queue_label)
                : "VALORANT is running.";
        }

        view.sessionCard.dataset.state = visualState;
        view.sessionName.textContent = name || "Riot session";
        view.sessionChip.textContent = chip;
        view.sessionDetail.textContent = detail;
        renderGameWarning();
    }

    function renderGameWarning() {
        const running = Boolean(model.live && model.live.valorant_running);
        if (!running) {
            view.gameWarning.hidden = true;
            view.gameWarning.classList.remove("is-confirming");
            return;
        }

        view.gameWarning.hidden = false;
        if (model.pendingConfirm) {
            view.gameWarning.classList.add("is-confirming");
            view.gameWarningText.textContent = `Press Confirm on ${model.pendingConfirm.label} again to close VALORANT and switch.`;
            return;
        }

        view.gameWarning.classList.remove("is-confirming");
        const state = cleanText(model.live.state, "").toUpperCase();
        view.gameWarningText.textContent = state === "INGAME" || state === "PREGAME"
            ? "A match is active. Switching accounts closes VALORANT and requires a second confirmation."
            : "VALORANT is running. Switching accounts closes it and requires a second confirmation.";
    }

    function filteredAccounts() {
        const query = cleanText(view.accountSearch.value).toLowerCase();
        const accounts = model.accounts.slice().sort((a, b) => {
            const favoriteDiff = Number(Boolean(b.favorite)) - Number(Boolean(a.favorite));
            if (favoriteDiff) return favoriteDiff;
            return accountLabel(a).localeCompare(accountLabel(b), undefined, { sensitivity: "base" });
        });
        return accounts.filter(account => {
            const rank = accountRank(account).toLowerCase();
            if (model.accountFilter === "favorites" && !account.favorite) return false;
            if (model.accountFilter === "ranked" && rank.includes("unranked")) return false;
            if (model.accountFilter === "unranked" && !rank.includes("unranked")) return false;
            if (!query) return true;
            const haystack = [account.display_name, account.username, account.tag, account.rank_label, account.rank_tier]
                .map(value => cleanText(value).toLowerCase())
                .join(" ");
            return haystack.includes(query);
        });
    }

    function renderAccounts() {
        const accounts = filteredAccounts();
        const allCount = model.accounts.length;
        const activeId = Number(model.live && model.live.account_id) || null;
        const gameRunning = Boolean(model.live && model.live.valorant_running);
        const fragment = document.createDocumentFragment();

        view.accountCount.textContent = String(allCount);
        view.accountList.replaceChildren();

        accounts.forEach((account, index) => {
            const id = Number(account.id);
            const isActive = activeId !== null && id === activeId;
            const isPending = Boolean(model.pendingConfirm && model.pendingConfirm.id === id);
            const isBusy = model.busyAccountId !== null;
            const row = document.createElement("article");
            row.className = "account-row";
            if (isActive) row.classList.add("is-active");
            if (isPending) row.classList.add("is-pending");

            const avatar = document.createElement("span");
            avatar.className = "account-rank-badge";
            avatar.title = accountRankDetail(account);
            const badgeIcon = document.createElement("img");
            badgeIcon.src = accountRankIcon(account);
            badgeIcon.alt = accountRank(account);
            badgeIcon.loading = "lazy";
            badgeIcon.addEventListener("error", () => {
                badgeIcon.onerror = null;
                badgeIcon.src = DEFAULT_TIER_ICON;
            }, { once: true });
            avatar.appendChild(badgeIcon);

            const info = document.createElement("div");
            info.className = "account-info";

            const nameRow = document.createElement("div");
            nameRow.className = "account-name-row";

            const name = document.createElement("span");
            name.className = "account-name";
            name.textContent = accountLabel(account);
            name.title = accountLabel(account);
            nameRow.appendChild(name);

            if (account.favorite) {
                const favorite = document.createElement("span");
                favorite.className = "favorite-star";
                favorite.textContent = "★";
                favorite.title = "Favorite";
                nameRow.appendChild(favorite);
            }

            if (isActive) {
                const active = document.createElement("span");
                active.className = "active-label";
                active.textContent = "ACTIVE";
                nameRow.appendChild(active);
            }

            const rankRow = document.createElement("div");
            rankRow.className = "account-rank-row";

            const rank = document.createElement("span");
            rank.className = "account-rank-text";
            rank.textContent = accountRankDetail(account);
            rankRow.appendChild(rank);

            const meta = document.createElement("div");
            meta.className = "account-meta";

            const tagText = cleanText(account.tag);
            if (tagText) {
                const tag = document.createElement("span");
                tag.textContent = tagText;
                meta.appendChild(tag);
            }

            const username = cleanText(account.username);
            if (username && username.toLowerCase() !== accountLabel(account).toLowerCase()) {
                if (tagText) {
                    const dot = document.createElement("i");
                    dot.setAttribute("aria-hidden", "true");
                    meta.appendChild(dot);
                }
                const login = document.createElement("span");
                login.textContent = username;
                login.title = username;
                meta.appendChild(login);
            }

            info.append(nameRow, rankRow, meta);

            const action = document.createElement("button");
            action.type = "button";
            action.className = "account-action";

            if (model.busyAccountId === id) {
                action.textContent = "Working";
                action.classList.add("is-busy");
                action.disabled = true;
            } else if (isPending) {
                action.textContent = "Confirm";
                action.classList.add("is-confirm");
                action.disabled = isBusy;
            } else if (isActive && gameRunning) {
                action.textContent = "Active";
                action.classList.add("is-active");
                action.disabled = true;
            } else if (isActive && !model.launchGame) {
                action.textContent = "Active";
                action.classList.add("is-active");
                action.disabled = true;
            } else if (isActive) {
                action.textContent = "Launch";
                action.disabled = isBusy;
            } else if (!model.live.available) {
                action.textContent = model.launchGame ? "Login + Play" : "Log in";
                action.disabled = isBusy;
            } else {
                action.textContent = model.launchGame ? "Switch + Play" : "Switch";
                action.disabled = isBusy;
            }

            const status = cleanText(account.status, "PLAYABLE").toUpperCase();
            if (status === "BANNED" || status === "SUSPENDED") {
                action.textContent = status === "BANNED" ? "Banned" : "Suspended";
                action.disabled = true;
                action.title = "This account cannot be switched to.";
            } else {
                action.addEventListener("click", () => handleAccountAction(account, isActive));
            }

            row.append(avatar, info, action);
            fragment.appendChild(row);
        });

        view.accountList.appendChild(fragment);
        const noMatches = accounts.length === 0;
        view.accountList.hidden = noMatches;
        view.accountsEmpty.hidden = !noMatches;
        view.accountsEmptyDetail.textContent = allCount
            ? "Try a different account search."
            : "Add accounts from the full Vortex app.";
    }

    async function handleAccountAction(account, isActive) {
        const id = Number(account.id);
        if (!id || model.busyAccountId !== null) return;

        const gameRunning = Boolean(model.live && model.live.valorant_running);
        if (gameRunning && !isActive) {
            if (!model.pendingConfirm || model.pendingConfirm.id !== id) {
                setPendingConfirmation(id, accountLabel(account));
                showToast("Switching closes VALORANT. Press Confirm to continue.", "warning");
                return;
            }
        }

        const confirmedClose = Boolean(gameRunning && !isActive && model.pendingConfirm && model.pendingConfirm.id === id);
        clearPendingConfirmation(false);
        model.busyAccountId = id;
        renderAccounts();

        try {
            const data = await apiRequest(`/api/overlay/accounts/${encodeURIComponent(id)}/switch`, {
                method: "POST",
                body: {
                    launch_game: Boolean(model.launchGame),
                    confirm_close_game: confirmedClose
                }
            });
            if (data.success === false) throw new Error(data.message || "Account switch could not start.");
            showToast(data.message || (model.launchGame ? "Switching account and starting VALORANT…" : "Switching account…"), "success");
            window.setTimeout(() => void refreshState(), 900);
            window.setTimeout(() => void hideOverlay(), 1200);
        } catch (error) {
            showToast(error.message || "Account switch failed.", "error");
        } finally {
            model.busyAccountId = null;
            renderAccounts();
        }
    }

    function setPendingConfirmation(id, label) {
        clearPendingConfirmation(false);
        model.pendingConfirm = { id, label };
        model.confirmTimer = window.setTimeout(() => {
            model.pendingConfirm = null;
            model.confirmTimer = null;
            renderAccounts();
            renderGameWarning();
        }, CONFIRM_WINDOW_MS);
        renderAccounts();
        renderGameWarning();
    }

    function clearPendingConfirmation(render = true) {
        if (model.confirmTimer !== null) window.clearTimeout(model.confirmTimer);
        model.confirmTimer = null;
        model.pendingConfirm = null;
        if (render) {
            renderAccounts();
            renderGameWarning();
        }
    }

    function renderCrosshairs() {
        const crosshairs = model.crosshairs;
        const fragment = document.createDocumentFragment();
        view.crosshairCount.textContent = String(crosshairs.length);
        view.crosshairList.replaceChildren();

        crosshairs.forEach((crosshair, index) => {
            const card = document.createElement("article");
            card.className = "crosshair-card";

            const preview = document.createElement("div");
            preview.className = "crosshair-preview";
            preview.setAttribute("aria-label", `${cleanText(crosshair.name, `Preset ${index + 1}`)} approximate preview`);
            const previewData = crosshair.preview && typeof crosshair.preview === "object" ? crosshair.preview : {};
            preview.style.setProperty("--crosshair-color", cleanText(previewData.color, "#ffffff"));
            preview.style.setProperty("--crosshair-length", `${Number(previewData.length) || 12}px`);
            preview.style.setProperty("--crosshair-gap", `${Number(previewData.gap) || 5}px`);
            preview.style.setProperty("--crosshair-thickness", `${Number(previewData.thickness) || 2}px`);
            ["left", "right", "top", "bottom"].forEach(direction => {
                const line = document.createElement("span");
                line.className = `crosshair-line is-${direction}`;
                preview.appendChild(line);
            });

            const title = document.createElement("h3");
            title.textContent = cleanText(crosshair.name, `Preset ${index + 1}`);

            const description = document.createElement("p");
            description.textContent = cleanText(crosshair.description, "Built-in VALORANT crosshair profile.");

            const copy = document.createElement("button");
            copy.type = "button";
            copy.className = "crosshair-copy";
            copy.textContent = "Copy import code";
            copy.disabled = !cleanText(crosshair.code);
            copy.addEventListener("click", () => copyCrosshair(crosshair, copy));

            card.append(preview, title, description, copy);
            fragment.appendChild(card);
        });

        if (!crosshairs.length && model.crosshairsLoaded) {
            const empty = document.createElement("div");
            empty.className = "empty-state";
            const title = document.createElement("strong");
            title.textContent = "No crosshair presets available";
            const detail = document.createElement("p");
            detail.textContent = "The built-in library could not be loaded.";
            empty.append(title, detail);
            fragment.appendChild(empty);
        }

        view.crosshairList.appendChild(fragment);
    }

    async function copyCrosshair(crosshair, button) {
        const code = cleanText(crosshair.code);
        if (!code || button.disabled) return;
        button.disabled = true;

        try {
            const data = await apiRequest("/api/copy", { method: "POST", body: { text: code } });
            if (data.success === false) throw new Error("Vortex could not access the clipboard.");
            button.textContent = "Copied — paste in VALORANT";
            button.classList.add("is-copied");
            showToast(`${cleanText(crosshair.name, "Crosshair")} code copied.`, "success");
        } catch (apiError) {
            try {
                if (!navigator.clipboard || !window.isSecureContext) throw apiError;
                await navigator.clipboard.writeText(code);
                button.textContent = "Copied — paste in VALORANT";
                button.classList.add("is-copied");
                showToast(`${cleanText(crosshair.name, "Crosshair")} code copied.`, "success");
            } catch (error) {
                showToast(error.message || "Could not copy the crosshair code.", "error");
            }
        } finally {
            window.setTimeout(() => {
                button.disabled = false;
                button.textContent = "Copy import code";
                button.classList.remove("is-copied");
            }, 2200);
        }
    }

function setActiveTab(tabName, focus = false) {
        if (!view.tabs.some(tab => tab.dataset.tab === tabName)) return;
        model.activeTab = tabName;
        view.tabs.forEach(tab => {
            const active = tab.dataset.tab === tabName;
            tab.classList.toggle("is-active", active);
            tab.setAttribute("aria-selected", String(active));
            tab.tabIndex = active ? 0 : -1;
            if (active && focus) tab.focus();
        });
        view.panels.forEach(panel => {
            const active = panel.id === `panel-${tabName}`;
            panel.hidden = !active;
            panel.classList.toggle("is-active", active);
        });
    }

    function showToast(message, type = "info") {
        const text = cleanText(message);
        if (!text) return;

        while (view.toastStack.children.length >= 3) {
            view.toastStack.firstElementChild.remove();
        }

        const toast = document.createElement("div");
        toast.className = `toast is-${type}`;
        toast.textContent = text;
        view.toastStack.appendChild(toast);

        window.setTimeout(() => {
            toast.classList.add("is-leaving");
            window.setTimeout(() => toast.remove(), 180);
        }, type === "error" ? 4200 : 3000);
    }

    async function callDesktopBridge(methodNames) {
        const api = window.pywebview && window.pywebview.api;
        if (!api) throw new Error("Desktop bridge unavailable");
        for (const method of methodNames) {
            if (typeof api[method] === "function") return api[method]();
        }
        throw new Error("Desktop bridge unavailable");
    }

    async function hideOverlay() {
        clearPendingConfirmation(false);
        view.accountSearch.blur();
        try {
            // hideOverlay is the desktop bridge contract used by app.py.
            await callDesktopBridge(["hideOverlay"]);
        } catch (_error) {
            // Browser development mode has no native window bridge.
        }
    }

    async function openMainApp() {
        try {
            await callDesktopBridge(["showMainApp", "showMainWindow", "openMainApp"]);
            await hideOverlay();
        } catch (_error) {
            const opened = window.open("/", "_blank", "noopener");
            if (!opened) showToast("Open Vortex from its taskbar icon.", "info");
        }
    }

    function bindEvents() {
        view.btnClose.addEventListener("click", () => void hideOverlay());
        view.btnOpenMain.addEventListener("click", () => void openMainApp());
        view.btnEmptyOpenMain.addEventListener("click", () => void openMainApp());
        view.btnRefresh.addEventListener("click", () => void refreshState({ announceError: true }));

        view.tabs.forEach(tab => {
            tab.addEventListener("click", () => setActiveTab(tab.dataset.tab));
            tab.addEventListener("keydown", event => {
                if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                event.preventDefault();
                const direction = event.key === "ArrowRight" ? 1 : -1;
                const current = view.tabs.indexOf(tab);
                const next = (current + direction + view.tabs.length) % view.tabs.length;
                setActiveTab(view.tabs[next].dataset.tab, true);
            });
        });

        view.accountSearch.addEventListener("input", renderAccounts);

        view.accountFilters.addEventListener("click", event => {
            const button = event.target.closest("[data-filter]");
            if (!button) return;
            model.accountFilter = button.dataset.filter || "all";
            view.accountFilters.querySelectorAll("[data-filter]").forEach(chip => {
                chip.classList.toggle("is-active", chip === button);
            });
            renderAccounts();
        });
        view.launchGame.checked = model.launchGame;
        view.launchGame.addEventListener("change", () => {
            model.launchGame = Boolean(view.launchGame.checked);
            saveLaunchPreference(model.launchGame);
            clearPendingConfirmation(false);
            renderAccounts();
            renderGameWarning();
        });
        document.addEventListener("keydown", event => {
            if (event.key === "Escape") {
                event.preventDefault();
                void hideOverlay();
                return;
            }
            if (event.key === "/" && model.activeTab === "accounts" && document.activeElement !== view.accountSearch) {
                event.preventDefault();
                view.accountSearch.focus();
            }
        });

        window.addEventListener("focus", () => void refreshState());
        window.addEventListener("pywebviewready", () => void refreshState());
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) void refreshState();
        });
    }

    bindEvents();
    void fetchFallbackCrosshairs();
    void refreshState();
    window.setInterval(() => {
        if (!document.hidden) void refreshState();
    }, POLL_INTERVAL_MS);
})();
