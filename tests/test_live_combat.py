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
            # round_report where the per-shot headshot count is real (more
            # headshots than headshot kills) - hs_pct comes from the shots.
            self._line("match_info", "round_report", {
                "damage": 150, "hit": 5, "headshot": 3, "final_headshot": 1,
                "bodyshots": "1", "legshots": "0",
            }),
            self._line("match_info", "round_report", {
                "damage": 90, "hit": 3, "headshot": 1, "final_headshot": 0,
                "bodyshots": "1", "legshots": "1",
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
        # round 1: head 4, round 2: head 1 -> 5 total; shots 4+2+1 = 7 -> wait
        # r1 hit=5 head=4 body=1 leg=0; r2 hit=3 head=1 body=1 leg=1 -> head 5
        self.assertEqual(5, out["headshots"])
        self.assertEqual(round(5 / 8 * 100, 1), out["hs_pct"])  # 62.5
        self.assertIsNone(out["acs"])

    def test_hs_pct_falls_back_to_headshot_kill_rate_when_gep_headshots_stuck(self):
        # Real-world GEP bug: per-round "headshot" key stuck at 0, only
        # "final_headshot" fires. hs_pct should then be the headshot-KILL rate,
        # not headshot-kills / total-shots.
        self._write([
            self._line("me", "player_name", "Me#NA"),
            self._line("match_info", "match_id", self.MATCH_ID),
            self._line("kill", "kills", 4),
            self._line("death", "deaths", 1),
            self._line("kill", "headshots", 3),  # 3 headshot kills of 4
            self._line("match_info", "round_report", {
                "damage": 130, "hit": 4, "headshot": 0, "final_headshot": 1,
                "bodyshots": "3", "legshots": "0",
            }),
            self._line("match_info", "round_report", {
                "damage": 260, "hit": 6, "headshot": 0, "final_headshot": 1,
                "bodyshots": "5", "legshots": "0",
            }),
        ])
        out = LiveCombatTracker(self.temp.name).snapshot(self.MATCH_ID)
        self.assertEqual(75.0, out["hs_pct"])       # 3 hs-kills / 4 kills
        self.assertEqual(75.0, out["headshot_kill_pct"])

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
        self.assertIn("Vortex Telemetry", out["reason"])

    def test_reads_valorant_tracker_nested_log_format(self):
        # The current Valorant Tracker app logs GEP updates in a nested shape
        # to background.html*.log, not the old flat "[GEP] info update" line.
        vt_path = os.path.join(self.temp.name, "background.html.log")

        def vt(feature, key, value):
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            body = {"info": {feature: {key: value}}, "feature": feature}
            return (
                "2026-08-30 00:05:00,000 (INFO) </js/x.js> (:14) - "
                "[Overwolf | Game Events Service | Default | Info Update] "
                + json.dumps(body) + "\n"
            )

        with open(vt_path, "w", encoding="utf-8") as handle:
            handle.writelines([
                vt("me", "playerId", "my-puuid-123"),
                vt("match_info", "roster_0", {
                    "name": "Panda Marley #LAS", "player_id": "my-puuid-123",
                }),
                vt("match_info", "matchId", self.MATCH_ID),
                vt("kill", "kills", 5),
                vt("kill", "headshots", 4),
                vt("death", "deaths", 2),
                vt("match_info", "round_report", {
                    "damage": 200, "hit": 4, "headshot": 0, "final_headshot": 1,
                    "bodyshots": "3", "legshots": "0",
                }),
                vt("match_info", "kill_feed", {
                    "attacker": "somefoe", "victim": "Panda Marley", "headshot": True,
                }),
            ])

        out = LiveCombatTracker(self.temp.name).snapshot(self.MATCH_ID)
        self.assertTrue(out["available"])
        self.assertEqual((5, 2), (out["kills"], out["deaths"]))
        self.assertEqual(4, out["headshot_kills"])
        self.assertEqual(80.0, out["hs_pct"])  # 4 hs-kills / 5 kills
        self.assertEqual(200, out["damage"])
        # the local player is identified via roster player_id == me/playerId,
        # so they are kept out of the kill-feed scoreboard
        self.assertNotIn("panda marley", out["players"])

    def test_latches_available_through_a_stale_log_gap(self):
        # A match goes live, then the Valorant Tracker log goes quiet for
        # longer than the freshness window (rounds have gaps of 30-60s+).
        # The HUD must not drop to WAITING and fade back - once real combat
        # for this match has been seen, availability is latched.
        self._write([
            self._line("match_info", "match_id", self.MATCH_ID),
            self._line("kill", "kills", 10),
            self._line("death", "deaths", 1),
            self._line("kill", "assists", 2),
        ])
        tracker = LiveCombatTracker(self.temp.name)

        live = tracker.snapshot(self.MATCH_ID)
        self.assertTrue(live["available"])
        self.assertEqual((10, 1), (live["kills"], live["deaths"]))

        # Age the log well past _FRESH_PROVIDER_AGE; no new lines written.
        old = os.stat(self.path)
        os.utime(self.path, (old.st_atime - 600, old.st_mtime - 600))

        stale = tracker.snapshot(self.MATCH_ID)
        self.assertFalse(stale["provider_fresh"])   # freshness reflects the gap
        self.assertTrue(stale["available"])          # ...but the HUD stays up
        self.assertEqual((10, 1), (stale["kills"], stale["deaths"]))
        self.assertEqual("", stale["reason"])

        # A different match clears the latch.
        other = tracker.snapshot("11111111-2222-3333-4444-555555555555")
        self.assertFalse(other["available"])

    def test_accepts_direct_vortex_telemetry_events_without_a_log(self):
        tracker = LiveCombatTracker(self.temp.name)
        tracker.ingest({"featureName": "match_info", "key": "match_id", "value": self.MATCH_ID}, self.MATCH_ID)
        tracker.ingest({"featureName": "kill", "key": "kills", "value": 3}, self.MATCH_ID)
        tracker.ingest({"featureName": "kill", "key": "headshots", "value": 2}, self.MATCH_ID)
        tracker.ingest({"featureName": "death", "key": "deaths", "value": 1}, self.MATCH_ID)

        out = tracker.snapshot(self.MATCH_ID)
        self.assertTrue(out["available"])
        self.assertTrue(out["provider_fresh"])
        self.assertEqual("vortex_telemetry", out["provider"])
        self.assertEqual((3, 1, 2), (out["kills"], out["deaths"], out["headshot_kills"]))
        self.assertEqual(66.7, out["hs_pct"])


if __name__ == "__main__":
    unittest.main()
