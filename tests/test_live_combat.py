import json
import os
import tempfile
import unittest

from backend.live_combat import LiveCombatTracker


class LiveCombatTrackerTests(unittest.TestCase):
    MATCH_ID = "0e34b23a-ba24-4671-9968-b1daabef9668"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "index.html.log")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _line(feature, key, value):
        # GEP writes "value" as a JSON string for nested payloads; mirror that.
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        payload = {"featureName": feature, "categoryName": feature, "key": key, "value": value}
        return (
            "2026-08-29 17:00:00,000 (INFO) </index/index.js> (:2) - "
            "[GEP] info update " + json.dumps(payload) + "\n"
        )

    def _write(self, lines, mode="w"):
        with open(self.path, mode, encoding="utf-8") as handle:
            handle.writelines(lines)

    def test_local_totals_from_kill_and_death_features(self):
        self._write([
            self._line("me", "player_name", "Me#NA"),
            self._line("match_info", "match_id", self.MATCH_ID),
            self._line("kill", "kills", 7),
            self._line("death", "deaths", 2),
            self._line("kill", "assists", 1),
            self._line("kill", "headshots", 4),
            self._line("match_info", "round_report", {
                "damage": 150, "hit": 4, "headshot": 1, "final_headshot": 1,
                "bodyshots": "2", "legshots": "0",
            }),
            self._line("match_info", "round_report", {
                "damage": 90, "hit": 3, "headshot": 0, "final_headshot": 0,
                "bodyshots": "2", "legshots": "1",
            }),
        ])

        out = LiveCombatTracker(self.temp.name).snapshot(self.MATCH_ID)
        self.assertTrue(out["available"])
        self.assertEqual((7, 2, 1), (out["kills"], out["deaths"], out["assists"]))
        self.assertEqual(4, out["headshot_kills"])
        self.assertEqual(57.1, out["headshot_kill_pct"])
        self.assertEqual(240, out["damage"])
        self.assertEqual(120, out["adr"])
        self.assertEqual(2, out["rounds_observed"])
        self.assertEqual(2, out["headshots"])
        self.assertEqual(28.6, out["hs_pct"])
        self.assertIsNone(out["acs"])

    def test_kill_feed_builds_other_player_scoreboard(self):
        def feed(attacker, victim, headshot=False):
            return self._line("match_info", "kill_feed", {
                "attacker": attacker, "victim": victim, "headshot": headshot,
                "assist1": "", "assist2": "", "assist3": "", "assist4": "",
            })

        self._write([
            self._line("me", "player_name", "Me#NA"),
            self._line("match_info", "match_id", self.MATCH_ID),
            feed("Me", "foe1", headshot=True),      # local player -> excluded
            feed("ally1", "foe2"),
            feed("foe2", "ally1", headshot=True),
            feed("foe2", "Me"),
        ])

        out = LiveCombatTracker(self.temp.name).snapshot(self.MATCH_ID)
        self.assertTrue(out["available"])
        self.assertNotIn("me", out["players"])
        self.assertEqual({"available": True, "kills": 1, "deaths": 1, "headshots": 0}, out["players"]["ally1"])
        self.assertEqual({"available": True, "kills": 2, "deaths": 1, "headshots": 1}, out["players"]["foe2"])
        self.assertEqual(1, out["players"]["foe1"]["deaths"])

    def test_ignores_other_matches_and_tails_new_lines(self):
        self._write([
            self._line("match_info", "match_id", "wrong-match"),
            self._line("kill", "kills", 99),
            self._line("match_info", "match_id", self.MATCH_ID),
            self._line("kill", "kills", 1),
            self._line("death", "deaths", 0),
        ])
        tracker = LiveCombatTracker(self.temp.name)
        first = tracker.snapshot(self.MATCH_ID)
        self.assertEqual(1, first["kills"])

        self._write([self._line("kill", "kills", 2)], mode="a")
        second = tracker.snapshot(self.MATCH_ID)
        self.assertEqual(2, second["kills"])

    def test_unavailable_when_no_provider_log(self):
        out = LiveCombatTracker(self.temp.name).snapshot(self.MATCH_ID)
        self.assertFalse(out["available"])
        self.assertIn("Overwolf", out["reason"])


if __name__ == "__main__":
    unittest.main()
