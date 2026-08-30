/* ==========================================================================
   Vortex boot screen orchestration.
   Runs immediately (before app.js). Plays the logo build + bloom, then a
   loader. app.js reports progress and readiness via window.__vortexBoot;
   a failsafe timer dismisses the screen even if app.js never calls back.
   ========================================================================== */
(function () {
    "use strict";

    var boot = document.getElementById("vortex-boot");
    if (!boot) return;

    var reduced = false;
    try {
        reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (_) {}
    if (reduced) boot.classList.add("vb-reduced");

    var statusEl = boot.querySelector(".vb-status");
    var removed = false;
    var readyCalled = false;

    // Rough sequence timing (ms from now). Compressed hard when reduced.
    var T_BLOOM = reduced ? 120 : 1650;   // last stroke lands -> bloom
    var T_LOADING = reduced ? 200 : 1950; // wordmark + loader appear
    var T_FAILSAFE = 7000;                // dismiss no matter what
    var T_MIN_VISIBLE = reduced ? 300 : 2300; // don't flash past the animation

    var startedAt = Date.now();

    var bloomTimer = setTimeout(function () {
        boot.classList.add("vb-bloom");
    }, T_BLOOM);

    var loadingTimer = setTimeout(function () {
        boot.classList.add("vb-loading");
        setStatus("Loading your library");
    }, T_LOADING);

    var failsafe = setTimeout(function () {
        finish();
    }, T_FAILSAFE);

    function setStatus(text) {
        if (!statusEl || removed) return;
        statusEl.classList.add("vb-status-swap");
        setTimeout(function () {
            if (removed) return;
            statusEl.textContent = text || "";
            statusEl.classList.remove("vb-status-swap");
        }, 160);
    }

    function finish() {
        if (removed) return;
        var elapsed = Date.now() - startedAt;
        if (elapsed < T_MIN_VISIBLE) {
            setTimeout(finish, T_MIN_VISIBLE - elapsed);
            return;
        }
        removed = true;
        clearTimeout(bloomTimer);
        clearTimeout(loadingTimer);
        clearTimeout(failsafe);

        boot.classList.add("vb-loading", "vb-done");
        setStatus("Ready");

        setTimeout(function () {
            boot.classList.add("vb-out");
            var done = function () {
                if (boot && boot.parentNode) boot.parentNode.removeChild(boot);
                document.documentElement.classList.remove("vb-booting");
            };
            boot.addEventListener("transitionend", done, { once: true });
            setTimeout(done, 700); // fallback if transitionend never fires
        }, reduced ? 120 : 360);
    }

    // Public hook used by app.js.
    window.__vortexBoot = {
        status: function (text) { setStatus(text); },
        ready: function () {
            if (readyCalled) return;
            readyCalled = true;
            finish();
        },
        // Hard escape hatch if something goes very wrong in app init.
        abort: function () { removed = false; finish(); }
    };

    // If app.js has already flagged readiness before this script's hook existed.
    if (window.__vortexBootReady) window.__vortexBoot.ready();
})();
