/*
 * Vortex Telemetry intentionally has no desktop or in-game windows.  It is a
 * small background controller that asks GEP for Vortex's own combat events
 * and forwards them to the FastAPI server that Vortex binds to 127.0.0.1.
 */
(function () {
  "use strict";

  const VALORANT_GAME_ID = 21640;
  const FEATURES = ["kill", "death", "match_info", "me"];
  const VORTEX_PORTS = Array.from({ length: 50 }, (_, index) => 8765 + index);
  const state = { matchId: "", vortexPort: 0, enabled: false };

  function log(message) {
    if (window.console) console.log("[Vortex Telemetry] " + message);
  }

  function valueOf(update) {
    if (!update) return undefined;
    return update.value !== undefined ? update.value : update.data;
  }

  function normalizedUpdate(update) {
    if (!update || typeof update !== "object") return null;
    const feature = update.featureName || update.feature;
    const key = update.key;
    if (!feature || !key) return null;
    return {
      feature: String(feature),
      category: String(update.categoryName || update.category || feature),
      key: String(key),
      value: valueOf(update)
    };
  }

  function matchesSuccess(result) {
    return Boolean(result && (
      result.success === true || result.status === "success" ||
      result.status === 200 || result.statusCode === 200
    ));
  }

  function postAtPort(port, body, done) {
    const web = overwolf.web;
    const method = web.enums && web.enums.HttpRequestMethods
      ? web.enums.HttpRequestMethods.Post
      : "POST";
    web.sendHttpRequest(
      "http://127.0.0.1:" + port + "/api/telemetry/gep",
      method,
      [{ key: "Content-Type", value: "application/json" }],
      JSON.stringify(body),
      function (result) { done(matchesSuccess(result)); }
    );
  }

  function forward(update) {
    const normalized = normalizedUpdate(update);
    if (!normalized) return;

    // The match id update is the first event that can be routed. Cache it and
    // send it immediately; subsequent events always carry the same id.
    if (normalized.feature === "match_info" && normalized.key === "match_id") {
      state.matchId = String(normalized.value || "");
    }
    if (!state.matchId) return;

    const body = { match_id: state.matchId, event: normalized };
    const ports = state.vortexPort
      ? [state.vortexPort].concat(VORTEX_PORTS.filter(p => p !== state.vortexPort))
      : VORTEX_PORTS;
    let index = 0;
    const tryNext = function () {
      if (index >= ports.length) return;
      const port = ports[index++];
      postAtPort(port, body, function (ok) {
        if (ok) {
          state.vortexPort = port;
        } else {
          tryNext();
        }
      });
    };
    tryNext();
  }

  function collectInfoUpdates(event) {
    // Native GEP versions either pass a single info-update, an `info` object,
    // or an array under `infoUpdates`; tolerate all of them.
    const entries = event && (event.infoUpdates || event.updates || event.info)
      ? (event.infoUpdates || event.updates || event.info)
      : event;
    (Array.isArray(entries) ? entries : [entries]).forEach(forward);
  }

  function enableGep() {
    if (state.enabled) return;
    overwolf.games.events.setRequiredFeatures(FEATURES, function (result) {
      if (result && result.success === false) {
        log("GEP features unavailable: " + JSON.stringify(result));
        return;
      }
      state.enabled = true;
      log("GEP ready");
      overwolf.games.events.getInfo(function (result) {
        if (result && result.res) collectInfoUpdates(result.res);
      });
    });
  }

  overwolf.games.events.onInfoUpdates2.addListener(collectInfoUpdates);
  overwolf.games.events.onNewEvents.addListener(function (event) {
    const events = event && (event.events || event.game_events);
    (Array.isArray(events) ? events : [events]).forEach(forward);
  });

  overwolf.games.onGameInfoUpdated.addListener(function (game) {
    if (game && Number(game.gameId) === VALORANT_GAME_ID) enableGep();
  });
  overwolf.games.getRunningGameInfo(function (game) {
    if (game && Number(game.gameInfo && game.gameInfo.id) === VALORANT_GAME_ID) enableGep();
  });
  log("background controller started");
}());
