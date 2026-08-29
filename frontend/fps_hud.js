(function () {
    "use strict";

    const POLL_MS = 500;
    const el = document.getElementById("fps-value");

    function tierClass(fps) {
        if (fps === null || fps === undefined) return "tier-none";
        if (fps >= 60) return "";
        if (fps >= 30) return "tier-mid";
        return "tier-low";
    }

    async function poll() {
        try {
            const res = await fetch("/api/fps/status", { cache: "no-store" });
            const data = await res.json();
            const fps = data && data.available ? data.fps : null;

            el.className = "value " + tierClass(fps);
            el.textContent = fps === null || fps === undefined ? "—" : String(fps);
        } catch (_error) {
            el.className = "value tier-none";
            el.textContent = "—";
        } finally {
            window.setTimeout(poll, POLL_MS);
        }
    }

    poll();
})();
