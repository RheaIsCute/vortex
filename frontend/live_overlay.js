(() => {
    "use strict";
    const el = {
        root: document.getElementById("aim-hud"), round: document.getElementById("hud-round"), hs: document.getElementById("hud-hs"),
        sub: document.getElementById("hud-sub"), kda: document.getElementById("hud-kda"), kd: document.getElementById("hud-kd"),
        observed: document.getElementById("hud-observed"), head: document.getElementById("hud-head"), body: document.getElementById("hud-body"),
        leg: document.getElementById("hud-leg"), dmg: document.getElementById("hud-dmg"), line: document.getElementById("hud-line"),
        area: document.getElementById("hud-area"), dot: document.getElementById("hud-dot")
    };
    const WIDTH = 340, HEIGHT = 76, PAD = 7;
    const n = value => Number(value || 0);
    const pct = (part, total) => total ? Math.round(part / total * 100) : 0;

    function draw(values) {
        const series = values.length ? values : [0];
        const step = series.length > 1 ? (WIDTH - PAD * 2) / (series.length - 1) : 0;
        const point = (value, index) => {
            const x = series.length === 1 ? WIDTH / 2 : PAD + index * step;
            const y = HEIGHT - PAD - Math.max(0, Math.min(100, value)) / 100 * (HEIGHT - PAD * 2);
            return [x.toFixed(1), y.toFixed(1)];
        };
        const points = series.map((v, i) => point(v, i).join(",")).join(" ");
        const first = point(series[0], 0), last = point(series[series.length - 1], series.length - 1);
        el.line.setAttribute("points", points);
        el.area.setAttribute("points", `${first[0]},${HEIGHT - PAD} ${points} ${last[0]},${HEIGHT - PAD}`);
        el.dot.setAttribute("cx", last[0]); el.dot.setAttribute("cy", last[1]);
    }

    function waiting(text = "Waiting for match telemetry") {
        el.root.classList.add("is-waiting");
        el.round.textContent = "WAITING"; el.hs.innerHTML = "--<em>%</em>"; el.sub.textContent = text;
        el.kda.textContent = "-- / -- / --"; el.kd.textContent = "-- KD"; el.observed.textContent = "LIVE";
        el.head.textContent = el.body.textContent = el.leg.textContent = "--"; el.dmg.textContent = "-- DMG"; draw([]);
    }

    function render(data) {
        const match = data && data.match;
        const current = match && match.me && match.me.current;
        if (!match || match.phase !== "in_match" || !current || !current.available) {
            waiting((current && current.reason) || "Waiting for live match telemetry"); return;
        }
        const head = n(current.headshots), body = n(current.bodyshots), leg = n(current.legshots), shots = head + body + leg;
        const reports = Array.isArray(current.accuracy_history) ? current.accuracy_history.slice(-12) : [];
        const history = reports.map(r =>
            r.hs_pct != null ? n(r.hs_pct)
            : pct(n(r.headshots), n(r.headshots) + n(r.bodyshots) + n(r.legshots))
        );
        el.root.classList.remove("is-waiting");
        el.round.textContent = `ROUND ${current.round_number || match.round || "--"}`;
        el.hs.innerHTML = `${current.hs_pct == null ? "--" : Number(current.hs_pct).toFixed(1)}<em>%</em>`;
        el.sub.textContent = current.source === "overwolf_gep" ? "Exact live match data" : "Current match data";
        el.kda.textContent = current.kda_line || "-- / -- / --";
        el.kd.textContent = current.kd == null ? "-- KD" : `${Number(current.kd).toFixed(2)} KD`;
        el.observed.textContent = `${current.rounds_observed || reports.length || 0} ROUNDS`;
        el.head.textContent = `${pct(head,shots)}%`; el.body.textContent = `${pct(body,shots)}%`; el.leg.textContent = `${pct(leg,shots)}%`;
        el.dmg.textContent = `${n(current.damage).toLocaleString()} DMG`;
        draw(history.length ? history : [n(current.hs_pct)]);
    }

    async function refresh() {
        try { const response = await fetch("/api/live/session", {cache:"no-store"}); render(await response.json()); }
        catch (_) { waiting("Vortex service reconnecting"); }
    }
    refresh(); window.setInterval(refresh, 1000);
})();
