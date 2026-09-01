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
            "overwolf_enabled": "1",
            "valorant_tracker_enabled": "1",
            "stay_signed_in": "1",
            "auto_launch_after_login": "0",
            "post_valorant_launch_enabled": "1",
            "post_valorant_launch_path": "C:\\test\\app.exe"
        })
        res = await server.update_settings(req)
        self.assertTrue(res["success"])
        self.assertEqual(res["settings"]["riot_api_key"], "HDEV-test-custom-key-12345")
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

    def test_live_match_controls_markup(self):
        root = Path(__file__).parent.parent
        index_html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
        app_js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
        styles_css = (root / "frontend" / "styles.css").read_text(encoding="utf-8")

        # 1. Start-a-Match slot has both the queue CTA and a Play alternative
        self.assertIn('id="btn-start-ranked"', index_html)
        self.assertIn('id="btn-side-play"', index_html)
        self.assertIn("renderSidePlayButton", app_js)
        self.assertIn("valorantNotRunning", app_js)

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

        # 1. One shared match-row component, used by both entry points.
        self.assertIn("function matchCardHtml(", app_js)
        self.assertIn('matchCardHtml(m, i, "account")', app_js)
        self.assertIn('matchCardHtml(m, i, "dashboard")', app_js)

        # 2. The old duplicated dashboard-only match markup is gone.
        self.assertNotIn("stat-match-kda-wrap", app_js)
        self.assertNotIn("stat-match-details-row", app_js)
        self.assertNotIn(".stat-match ", styles_css)
        self.assertNotIn(".stat-match-", styles_css)

        # 3. A single date helper, with the Account-Manager fallback ("Recent").
        self.assertIn("function matchDateLabel(", app_js)
        self.assertIn('"Recent"', app_js)
        # The detail modal reads the same helper, not a raw field.
        self.assertNotIn('m.game_date || "Recent"', app_js)

        # 4. The map splash must not sit under the stats: it is a low-opacity
        #    layer behind a near-opaque scrim, and stat values are light, so a
        #    bright map never washes out the numbers or the date.
        card_block = styles_css.split(".match-card {", 1)[1].split("\n}", 1)[0]
        self.assertNotIn("background-image: var(--map-splash)", card_block)
        before_block = styles_css.split(".match-card::before {", 1)[1].split("}", 1)[0]
        self.assertIn("opacity: 0.35", before_block)
        mask_block = styles_css.split(".match-card-bg-mask {", 1)[1].split("}", 1)[0]
        self.assertIn("rgba(13, 17, 23, 0.82)", mask_block)  # right edge stays dark
        # Missing per-match combat data shows a dash, not a misleading "0 / 0 / 0".
        self.assertIn('const hasCombat =', app_js)
        self.assertIn('"—"', app_js)
