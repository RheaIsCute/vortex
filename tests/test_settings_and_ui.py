import unittest
from pathlib import Path
from backend import server
from backend.database import Database

class SettingsAndUITests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_api_persistence(self):
        # 1. Test get_settings
        settings = await server.get_settings()
        self.assertIn("riot_api_key", settings)

        # 2. Test update_settings
        req = server.SettingsUpdate(settings={
            "riot_client_path": "C:\\Riot Games\\Riot Client\\RiotClientServices.exe",
            "riot_api_key": "HDEV-test-custom-key-12345",
            "live_hud_enabled": "1",
            "stay_signed_in": "1",
            "auto_launch_after_login": "0",
            "post_valorant_launch_enabled": "1",
            "post_valorant_launch_path": "C:\\test\\app.exe"
        })
        res = await server.update_settings(req)
        self.assertTrue(res["success"])
        self.assertEqual(res["settings"]["riot_api_key"], "HDEV-test-custom-key-12345")
        self.assertEqual(res["settings"]["live_hud_enabled"], "1")
        self.assertEqual(res["settings"]["post_valorant_launch_enabled"], "1")
        self.assertEqual(res["settings"]["post_valorant_launch_path"], "C:\\test\\app.exe")

    async def test_login_log_path_api(self):
        res = await server.login_log_path()
        self.assertIn("path", res)

    async def test_app_version_api(self):
        res = await server.app_version()
        self.assertIn("version", res)

    def test_frontend_settings_and_search_markup(self):
        root = Path(__file__).parent.parent
        index_html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
        app_js = (root / "frontend" / "app.js").read_text(encoding="utf-8")

        # 1. Ctrl K removed
        self.assertNotIn("Ctrl K", index_html)
        self.assertNotIn('search-kbd', index_html)
        self.assertNotIn('e.key.toLowerCase() === "k"', app_js)
        self.assertNotIn('ctrlKey', app_js)

        # 2. Search placeholder remains
        self.assertIn("Search accounts, Riot IDs, notes...", index_html)

        # 3. Renamed sections
        self.assertIn("Post-Game Actions", index_html)
        self.assertIn("Launch & Login", index_html)
        self.assertNotIn("After VALORANT Closes", index_html)
        self.assertNotIn("Login Behaviour", index_html)

        # 4. Advanced / Developer settings exists and contains API key and debug log button
        self.assertIn("Advanced / Developer Settings", index_html)
        self.assertIn('id="settings-api-key"', index_html)
        self.assertIn('id="btn-open-log"', index_html)

        # 5. Normal settings does not contain the old settings-log-path input box
        self.assertNotIn('id="settings-log-path"', index_html)

        # 6. The single Live Match switch also explains the external cleanup.
        self.assertIn("closes the VAL Tracker / Overwolf integration", index_html)
        self.assertIn("disables related startup entries", index_html)

    def test_legacy_ranked_rendering_uses_backend_eligibility_and_repaints(self):
        root = Path(__file__).parent.parent
        app_js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
        styles_css = (root / "frontend" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function isLegacyRankedEligible(acc)", app_js)
        self.assertIn("return acc && acc.is_legacy_ranked_eligible === true", app_js)
        self.assertIn("newAccounts.filter(isLegacyRankedEligible)", app_js)
        self.assertIn("const isLegacyRanked = isLegacyRankedEligible(acc)", app_js)
        self.assertIn("a.is_legacy_ranked_eligible, a.ranked_capable", app_js)
        self.assertIn(".account-card.is-legacy-ranked.is-favorite", styles_css)

    def test_live_match_controls_markup(self):
        root = Path(__file__).parent.parent
        index_html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
        app_js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
        styles_css = (root / "frontend" / "styles.css").read_text(encoding="utf-8")

        # 1. Start-a-Match slot: queue CTA + the single Play VALORANT action.
        self.assertIn('id="btn-start-ranked"', index_html)
        self.assertIn('id="btn-side-play"', index_html)
        self.assertIn("renderSidePlayButton", app_js)
        # State is driven by the live snapshot's process flag, one source only.
        self.assertIn("const gameRunning = !!live.valorant_running", app_js)
        # Closed state shows no "VALORANT isn't running / Press PLAY" card.
        self.assertNotIn("Press PLAY to start the game first", app_js)
        self.assertNotIn('ctaTitle = "VALORANT isn\'t running"', app_js)
        # Header PLAY button is retired (kept hidden).
        self.assertIn("DOM.btnDashPlay.hidden = true", app_js)
        # [hidden] must beat the button's own display so exactly one shows.
        self.assertIn(".btn-ranked-cta[hidden]", styles_css)

        # 2. Insta-lock agent switch re-arms the backend and confirms
        self.assertIn("Autolock updated to", app_js)
        self.assertIn("Failed to update autolock agent", app_js)

        # 3. Play button follows the theme accent - no hardcoded green
        self.assertNotIn("#16d38a", styles_css)
        self.assertNotIn("rgba(22, 211, 138", styles_css)
        self.assertIn(".btn-dash-play", styles_css)

        # 4. Agent portraits use smooth scaling, never hard-pixel rendering,
        #    and are not pinned to a non-DPI-aware GPU raster layer.
        agent_img_block = styles_css.split(".dash-agent-btn img {", 1)[1].split("}", 1)[0]
        self.assertIn("image-rendering: auto", agent_img_block)
        self.assertNotIn("transform:", agent_img_block)
        self.assertNotIn("image-rendering: pixelated", styles_css)

    def test_match_history_is_unified_between_entry_points(self):
        root = Path(__file__).parent.parent
        app_js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
        styles_css = (root / "frontend" / "styles.css").read_text(encoding="utf-8")

        # 1. ONE shared match-row component for every entry point.
        self.assertIn("function matchCardHtml(", app_js)
        self.assertIn('matchCardHtml(m, i, "account")', app_js)
        self.assertIn('matchCardHtml(m, i, "dashboard")', app_js)
        self.assertIn('matchCardHtml(m, i, "profile")', app_js)

        # 2. Every older per-entry-point match-row implementation is gone.
        for dead in ("stat-match", "detail-history-row", "detail-history-inner",
                     "detail-kda-stat", "detail-kdr-badge", "detail-outcome-pill",
                     "match-agent-section", "match-stats-section", "match-card-inner"):
            self.assertNotIn(dead, app_js, f"{dead} still in app.js")
            self.assertNotIn(dead, styles_css, f"{dead} still in styles.css")

        # 3. The row is one fixed-column grid (not floating flex sections).
        card_block = styles_css.split("\n.match-card {", 1)[1].split("\n}", 1)[0]
        self.assertIn("display: grid", card_block)
        self.assertIn("grid-template-columns:", card_block)

        # 4. A single date helper, with the Account-Manager fallback ("Recent").
        self.assertIn("function matchDateLabel(", app_js)
        self.assertIn('"Recent"', app_js)
        self.assertNotIn('m.game_date || "Recent"', app_js)

        # The role badge must remain a small secondary element instead of
        # inheriting the full agent portrait dimensions.
        self.assertIn('class="mh-role"', app_js)
        self.assertIn(".mh-avatar > img:not(.mh-role)", styles_css)
        role_block = styles_css.split(".mh-role {", 1)[1].split("}", 1)[0]
        self.assertIn("right: -4px", role_block)
        self.assertIn("bottom: -4px", role_block)
        self.assertIn("width: 15px", role_block)
        self.assertIn("height: 15px", role_block)
        self.assertIn("object-fit: contain", role_block)
        self.assertIn("z-index: 2", role_block)

        # 5. Map art is a faint layer behind a near-opaque scrim; stat values
        #    are light so a bright map never washes them out.
        self.assertNotIn("background-image: var(--map-splash)", card_block)
        splash_block = styles_css.split(".mh-splash {", 1)[1].split("}", 1)[0]
        self.assertIn("opacity: 0.28", splash_block)
        scrim_block = styles_css.split(".mh-scrim {", 1)[1].split("}", 1)[0]
        self.assertIn("rgba(13, 17, 23, 0.86)", scrim_block)  # far-right stays dark
        val_block = styles_css.split(".mh-stat-val {", 1)[1].split("}", 1)[0]
        self.assertIn("color: #fff", val_block)

        # 6. Missing combat data shows a dash, not a misleading "0 / 0 / 0".
        self.assertIn("const hasCombat =", app_js)
        self.assertIn('"—"', app_js)
