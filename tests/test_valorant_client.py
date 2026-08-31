import time
import unittest
from unittest.mock import patch

from backend import valorant_client as vc


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _match_payload(match_id, puuid, kills):
    return {
        "matchInfo": {
            "matchId": match_id,
            "mapId": "",
            "queueID": "deathmatch",
            "gameStartMillis": 1,
        },
        "players": [{
            "subject": puuid,
            "teamId": "Blue",
            "characterId": "agent-id",
            "stats": {
                "kills": kills,
                "deaths": 1,
                "assists": 0,
                "score": kills * 100,
                "roundsPlayed": 1,
            },
        }],
        "roundResults": [{"roundResultCode": "", "playerStats": []}],
        "teams": [],
    }


class _IncrementingMatchClient(vc.ValorantLiveClient):
    def __init__(self):
        super().__init__()
        self.puuid = "player-a"
        self.remote_calls = 0

    def _remote(self, method, url, payload=None, timeout=5.0):
        self.remote_calls += 1
        return _Response(_match_payload("match-1", self.puuid, self.remote_calls))

    def resolve_names(self, _puuids):
        # This test counts match-detail reads only; name resolution has its own
        # coverage and is a separate Riot endpoint in production.
        return {}


class MatchCacheTests(unittest.TestCase):
    def setUp(self):
        with vc._MATCH_DETAILS_LOCK:
            vc._MATCH_DETAILS_CACHE.clear()
        vc._MATCH_CACHE.clear()

    @patch.object(
        vc,
        "agent_by_id",
        return_value={"id": "agent-id", "name": "Agent", "icon": ""},
    )
    def test_live_summary_bypasses_parsed_and_raw_match_caches(self, _agent):
        client = _IncrementingMatchClient()

        cached_first = vc.personal_match_summary(client, "match-1")
        cached_second = vc.personal_match_summary(client, "match-1")
        live_first = vc.personal_match_summary(client, "match-1", live=True)
        live_second = vc.personal_match_summary(client, "match-1", live=True)

        self.assertEqual(1, cached_first["kills"])
        self.assertEqual(1, cached_second["kills"])
        self.assertEqual(2, live_first["kills"])
        self.assertEqual(3, live_second["kills"])
        self.assertEqual(3, client.remote_calls)

        # Live reads neither consume nor replace the immutable-match cache.
        with vc._MATCH_DETAILS_LOCK:
            raw_cached_kills = vc._MATCH_DETAILS_CACHE["match-1"]["players"][0]["stats"]["kills"]
        self.assertEqual(1, raw_cached_kills)


class PlayerStatsCacheTests(unittest.TestCase):
    def setUp(self):
        self._reset_stats_cache()

    def tearDown(self):
        self._reset_stats_cache()

    @staticmethod
    def _reset_stats_cache(**overrides):
        state = {
            "data": None,
            "built_at": 0.0,
            "puuid": "",
            "building": False,
            "building_puuid": "",
            "generation": 0,
        }
        state.update(overrides)
        with vc._STATS_LOCK:
            vc._STATS_CACHE.clear()
            vc._STATS_CACHE.update(state)

    def test_cached_profile_is_never_served_to_a_different_account(self):
        self._reset_stats_cache(
            data={"available": True, "puuid": "player-a", "marker": "account-a"},
            built_at=time.time(),
            puuid="player-a",
        )

        with patch.object(vc, "_active_session_puuid", return_value="player-b"), \
             patch.object(vc.threading, "Thread") as thread_cls:
            result = vc.get_player_stats()

        self.assertFalse(result["available"])
        self.assertNotIn("marker", result)
        thread_cls.assert_called_once()
        self.assertEqual(("player-b", 1), thread_cls.call_args.kwargs["args"])
        with vc._STATS_LOCK:
            self.assertTrue(vc._STATS_CACHE["building"])
            self.assertEqual("player-b", vc._STATS_CACHE["building_puuid"])

    def test_cached_profile_is_reused_for_its_own_account(self):
        self._reset_stats_cache(
            data={"available": True, "puuid": "player-a", "marker": "account-a"},
            built_at=time.time(),
            puuid="player-a",
        )

        with patch.object(vc, "_active_session_puuid", return_value="player-a"), \
             patch.object(vc.threading, "Thread") as thread_cls:
            result = vc.get_player_stats()

        self.assertEqual("account-a", result["marker"])
        self.assertFalse(result["loading"])
        thread_cls.assert_not_called()

    def test_worker_discards_result_if_session_changes_during_build(self):
        self._reset_stats_cache(
            building=True,
            building_puuid="player-a",
            generation=4,
        )

        class _Client:
            puuid = "player-a"

            def connect(self):
                return True

        with patch.object(vc, "ValorantLiveClient", _Client), \
             patch.object(vc, "build_player_stats", return_value={"marker": "account-a"}), \
             patch.object(vc, "_active_session_puuid", return_value="player-b"):
            vc._stats_worker("player-a", 4)

        with vc._STATS_LOCK:
            self.assertIsNone(vc._STATS_CACHE["data"])
            self.assertFalse(vc._STATS_CACHE["building"])

    def test_older_worker_cannot_overwrite_or_clear_newer_build(self):
        self._reset_stats_cache(
            building=True,
            building_puuid="player-b",
            generation=8,
        )

        class _OldClient:
            puuid = "player-a"

            def connect(self):
                return True

        with patch.object(vc, "ValorantLiveClient", _OldClient), \
             patch.object(vc, "build_player_stats", return_value={"marker": "account-a"}), \
             patch.object(vc, "_active_session_puuid", return_value="player-a"):
            vc._stats_worker("player-a", 7)

        with vc._STATS_LOCK:
            self.assertIsNone(vc._STATS_CACHE["data"])
            self.assertTrue(vc._STATS_CACHE["building"])
            self.assertEqual("player-b", vc._STATS_CACHE["building_puuid"])
            self.assertEqual(8, vc._STATS_CACHE["generation"])


class PlayerStatsDerivationTests(unittest.TestCase):
    def test_placement_wins_are_read_from_wins_by_tier(self):
        mmr = {
            "LatestCompetitiveUpdate": {
                "SeasonID": "act-current", "TierAfterUpdate": 0,
                "RankedRatingAfterUpdate": 0,
            },
            "QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": {
                "act-current": {
                    "CompetitiveTier": 0, "NumberOfWins": 0,
                    "NumberOfGames": 2, "WinsByTier": {"0": 2},
                },
                "act-old": {
                    "CompetitiveTier": 5, "NumberOfWins": 0,
                    "NumberOfGames": 3, "WinsByTier": {"5": 1},
                },
            }}},
        }
        with patch.object(vc, "get_seasons", return_value={
            "act-current": "Current", "act-old": "Old",
        }):
            out = vc._mmr_summary(mmr)

        self.assertEqual({"wins": 2, "losses": 0, "games": 2, "winrate": 100.0},
                         {k: out["act"][k] for k in ("wins", "losses", "games", "winrate")})
        self.assertEqual(3, out["lifetime"]["wins"])
        self.assertEqual(2, out["lifetime"]["losses"])
        self.assertEqual(60.0, out["lifetime"]["winrate"])

    def test_recent_form_uses_real_match_outcomes_and_acs(self):
        updates = [
            {"MatchID": "new", "RankedRatingEarned": 0, "CompetitiveMovement": "MOVEMENT_UNKNOWN"},
            {"MatchID": "old", "RankedRatingEarned": 0, "CompetitiveMovement": "MOVEMENT_UNKNOWN"},
        ]
        matches = [
            {"match_id": "new", "ranked": True, "result": "Win", "map": "Summit", "acs": 415},
            {"match_id": "old", "ranked": True, "result": "Win", "map": "Ascent", "acs": 360},
        ]

        out = vc._form_from_updates(updates, matches)

        self.assertEqual(["Win", "Win"], [entry["result"] for entry in out["form"]])
        self.assertEqual([360, 415], out["performance_history"])
        self.assertEqual(2, out["streak"])
        self.assertEqual("Win", out["streak_type"])
        self.assertEqual(100.0, out["recent_winrate"])


class CurrentActMmrTests(unittest.TestCase):
    """parse_player_mmr must read the current rank from the live act only."""

    OLD_ACT = "act-old"
    CUR_ACT = "act-current"

    def _mmr(self, latest=None):
        seasons = {
            # Ranked Gold 3 last act...
            self.OLD_ACT: {
                "CompetitiveTier": 14, "Rank": 14, "RankedRating": 42,
                "NumberOfWins": 12, "NumberOfGames": 20,
            },
            # ...nothing played this act.
            self.CUR_ACT: {
                "CompetitiveTier": 0, "Rank": 0, "RankedRating": 0,
                "NumberOfWins": 0, "NumberOfGames": 0,
            },
        }
        data = {"QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": seasons}}}
        if latest is not None:
            data["LatestCompetitiveUpdate"] = latest
        return data

    def test_prior_act_rank_does_not_leak_into_current(self):
        with patch.object(vc, "current_act_id", return_value=self.CUR_ACT):
            out = vc.parse_player_mmr(self._mmr())
        self.assertEqual(0, out["tier"])
        self.assertEqual("Unranked", out["tier_label"])
        self.assertEqual(0, out["rr"])
        # Peak still remembers the Gold 3 run.
        self.assertEqual(14, out["peak_tier"])

    def test_stale_latest_update_from_prior_act_is_ignored(self):
        latest = {
            "SeasonID": self.OLD_ACT,
            "TierAfterUpdate": 14,
            "RankedRatingAfterUpdate": 42,
        }
        with patch.object(vc, "current_act_id", return_value=self.CUR_ACT):
            out = vc.parse_player_mmr(self._mmr(latest))
        self.assertEqual(0, out["tier"])
        self.assertEqual(0, out["rr"])

    def test_current_act_rank_is_reported(self):
        data = self._mmr()
        data["QueueSkills"]["competitive"]["SeasonalInfoBySeasonID"][self.CUR_ACT] = {
            "CompetitiveTier": 7, "Rank": 7, "RankedRating": 35,
            "NumberOfWins": 3, "NumberOfGames": 6,
        }
        with patch.object(vc, "current_act_id", return_value=self.CUR_ACT):
            out = vc.parse_player_mmr(data)
        self.assertEqual(7, out["tier"])
        self.assertEqual("Bronze 2", out["tier_label"])
        self.assertEqual(35, out["rr"])

    def test_falls_back_to_last_active_act_when_feed_unavailable(self):
        with patch.object(vc, "current_act_id", return_value=""):
            out = vc.parse_player_mmr(self._mmr())
        self.assertEqual(14, out["tier"])


class ResolveNamesTests(unittest.TestCase):
    """The name service hands back blanks; those must not become '#'."""

    def _client(self, payload):
        client = vc.ValorantLiveClient()  # pd resolves from the default shard
        client._remote = lambda *a, **k: _Response(payload)
        return client

    def test_blank_entries_are_skipped_not_hashed(self):
        client = self._client([
            {"Subject": "a", "GameName": "yutaaa", "TagLine": "2432"},
            {"Subject": "b", "GameName": "", "TagLine": ""},
            {"Subject": "c", "GameName": "Solo", "TagLine": ""},
        ])
        names = client.resolve_names(["a", "b", "c"])
        self.assertEqual({"a": "yutaaa#2432", "c": "Solo"}, names)
        self.assertNotIn("b", names)
        self.assertNotIn("#", names.values())


class CachedNamesTests(unittest.TestCase):
    """_cached_names keeps asking until everyone is named, then stops."""

    def setUp(self):
        from backend import server
        self.server = server
        server._NAME_CACHE.clear()
        server._PLAYER_MMR_CACHE.clear()

    class _ScriptedClient:
        def __init__(self, script):
            self.script = script
            self.calls = 0

        def resolve_names(self, puuids):
            out = self.script[min(self.calls, len(self.script) - 1)]
            self.calls += 1
            return dict(out)

    def test_partial_results_merge_and_settle(self):
        client = self._ScriptedClient([{"a": "A#1"}, {"a": "A#1", "b": "B#2"}])
        puuids = ["a", "b"]

        first = self.server._cached_names(client, "m1", puuids)
        self.assertEqual({"a": "A#1"}, first)

        # Second poll inside the retry gap: no new call, still partial.
        self.server._cached_names(client, "m1", puuids)
        self.assertEqual(1, client.calls)

        # Gap elapsed -> retries, fills in the rest.
        self.server._NAME_CACHE["m1"]["next_at"] = 0.0
        done = self.server._cached_names(client, "m1", puuids)
        self.assertEqual({"a": "A#1", "b": "B#2"}, done)

        # Everyone named -> no further calls ever.
        self.server._NAME_CACHE["m1"]["next_at"] = 0.0
        self.server._cached_names(client, "m1", puuids)
        self.assertEqual(2, client.calls)

    def test_retry_budget_stops_hammering_for_unresolvable_players(self):
        client = self._ScriptedClient([{"a": "A#1"}])  # "b" never resolves
        puuids = ["a", "b"]
        for _ in range(self.server._NAME_MAX_TRIES + 5):
            self.server._cached_names(client, "m2", puuids)
            if "m2" in self.server._NAME_CACHE:
                self.server._NAME_CACHE["m2"]["next_at"] = 0.0  # ignore the retry gap
        self.assertEqual(self.server._NAME_MAX_TRIES, client.calls)

    def test_names_settled_tracks_resolution_and_giving_up(self):
        puuids = ["a", "b"]

        # Nothing asked yet -> unsettled.
        self.assertFalse(self.server._names_settled("m3", puuids))

        client = self._ScriptedClient([{"a": "A#1"}])  # "b" never resolves
        self.server._cached_names(client, "m3", puuids)
        # "b" still blank and retries left -> a blank name is "not yet".
        self.assertFalse(self.server._names_settled("m3", puuids))

        # Everyone named -> settled immediately, no need to burn the budget.
        client2 = self._ScriptedClient([{"a": "A#1", "b": "B#2"}])
        self.server._NAME_CACHE["m4"] = {"names": {}, "tries": 0, "next_at": 0.0}
        self.server._cached_names(client2, "m4", puuids)
        self.assertTrue(self.server._names_settled("m4", puuids))

        # Budget spent without "b" -> settled (a blank name now means hidden).
        for _ in range(self.server._NAME_MAX_TRIES + 2):
            self.server._cached_names(client, "m3", puuids)
            self.server._NAME_CACHE["m3"]["next_at"] = 0.0
        self.assertTrue(self.server._names_settled("m3", puuids))

    def test_roster_entry_trusts_name_service_over_payload_incognito(self):
        names = {"seen": "Seen#NA"}
        incognito_payload = {
            "Subject": "seen",
            "PlayerIdentity": {"Incognito": True, "AccountLevel": 42},
        }
        # Name service resolved this player -> show the name, drop the flag,
        # even though the match payload marks them Incognito.
        entry = self.server._roster_entry(None, incognito_payload, names, "me", True)
        self.assertEqual("Seen#NA", entry["name"])
        self.assertFalse(entry["incognito"])

        unresolved = {"Subject": "ghost", "PlayerIdentity": {"Incognito": True}}
        # Still resolving -> blank name, not yet flagged hidden.
        pending = self.server._roster_entry(None, unresolved, names, "me", False)
        self.assertEqual("", pending["name"])
        self.assertFalse(pending["incognito"])
        # Name service gave up -> now genuinely hidden.
        hidden = self.server._roster_entry(None, unresolved, names, "me", True)
        self.assertTrue(hidden["incognito"])


class MatchScoreboardTests(unittest.TestCase):
    def _details(self):
        return {
            "matchInfo": {"matchId": "scoreboard-1", "mapId": "map-1", "queueID": "competitive"},
            "players": [
                {"subject": "p1", "teamId": "Blue", "characterId": "a1",
                 "stats": {"kills": 12, "deaths": 7, "assists": 3, "score": 3200, "roundsPlayed": 20}},
                {"subject": "p2", "teamId": "Red", "characterId": "a2",
                 "stats": {"kills": 8, "deaths": 12, "assists": 4, "score": 2400, "roundsPlayed": 20}},
            ],
            "teams": [
                {"teamId": "Blue", "numPoints": 13, "won": True},
                {"teamId": "Red", "numPoints": 7, "won": False},
            ],
            "roundResults": [{
                "winningTeam": "Blue", "roundResult": "Eliminated",
                "playerStats": [
                    {"subject": "p1", "damage": [{"headshots": 2, "bodyshots": 4, "legshots": 0, "damage": 480}]},
                    {"subject": "p2", "damage": [{"headshots": 1, "bodyshots": 3, "legshots": 1, "damage": 350}]},
                ],
            }],
        }

    @patch.object(vc, "resolve_map", return_value={"name": "Ascent"})
    @patch.object(vc, "agent_by_id", side_effect=lambda agent: {"name": agent, "icon": f"/{agent}.png"})
    def test_match_contains_two_team_scoreboard_and_rounds(self, _agent, _map):
        parsed = vc._parse_match(self._details(), "p1")
        self.assertEqual([13, 7], [team["rounds_won"] for team in parsed["teams"]])
        self.assertEqual("Blue", parsed["round_results"][0]["winner"])
        self.assertEqual("p1", parsed["roster"][0]["puuid"])
        self.assertEqual(160, parsed["roster"][0]["acs"])
        self.assertEqual(480, parsed["roster"][0]["damage"])
        self.assertEqual("", parsed["roster"][0]["riot_id"])

    def test_puuid_placeholders_resolve_to_full_riot_ids(self):
        match = {"roster": [
            {"puuid": "p1", "riot_id": "", "name": ""},
            {"puuid": "p2", "riot_id": "", "name": ""},
        ]}

        class _Names:
            @staticmethod
            def resolve_names(_puuids):
                return {"p1": "PlayerOne#NA1", "p2": "PlayerTwo#NA2"}

        enriched = vc._enrich_roster_names(_Names(), match)
        self.assertEqual("PlayerOne#NA1", enriched["roster"][0]["riot_id"])
        self.assertEqual("PlayerTwo#NA2", enriched["roster"][1]["name"])


class RegionCacheTests(unittest.TestCase):
    def setUp(self):
        with vc._STATIC_LOCK:
            vc._REGION_CACHE.update({
                "region": None,
                "shard": None,
                "at": 0.0,
                "session_key": None,
            })

    def test_region_cache_is_scoped_to_puuid_and_lockfile_session(self):
        vc._store_region_cache("na", "na", "player-a", 1234, "secret-a")

        self.assertEqual(
            ("na", "na"),
            vc._region_from_cache("player-a", 1234, "secret-a"),
        )
        self.assertIsNone(vc._region_from_cache("player-b", 1234, "secret-a"))
        self.assertIsNone(vc._region_from_cache("player-a", 1234, "secret-b"))
        self.assertIsNone(vc._region_from_cache("player-a", 4321, "secret-a"))


class PresenceFlattenTests(unittest.TestCase):
    """Riot moved the match/party fields into nested objects around client
    13.04 and left a top-level provisioningFlow:'Invalid' behind. The flatten
    has to lift the real values back to the legacy top-level shape."""

    def test_nested_13_04_presence_is_flattened(self):
        nested = {
            "isValid": True,
            "provisioningFlow": "Invalid",
            "queueId": "competitive",
            "partyOwnerMatchScoreAllyTeam": 3,
            "partyOwnerMatchScoreEnemyTeam": 2,
            "matchPresenceData": {
                "matchMap": "/Game/Maps/Jam/Jam",
                "provisioningFlow": "Matchmaking",
                "queueId": "competitive",
                "sessionLoopState": "INGAME",
            },
            "partyPresenceData": {
                "partyState": "DEFAULT",
                "partyOwnerSessionLoopState": "INGAME",
                "partyOwnerProvisioningFlow": "Matchmaking",
                "partyOwnerMatchMap": "/Game/Maps/Jam/Jam",
            },
        }
        flat = vc.ValorantLiveClient._flatten_presence(nested)
        self.assertEqual(flat["sessionLoopState"], "INGAME")
        self.assertEqual(flat["provisioningFlow"], "Matchmaking")
        self.assertEqual(flat["matchMap"], "/Game/Maps/Jam/Jam")
        self.assertEqual(flat["partyState"], "DEFAULT")
        self.assertEqual(flat["partyOwnerMatchScoreAllyTeam"], 3)

    def test_legacy_flat_presence_is_left_alone(self):
        legacy = {
            "sessionLoopState": "PREGAME",
            "provisioningFlow": "Matchmaking",
            "queueId": "unrated",
            "partyOwnerMatchCurrentTeam": "Blue",
        }
        flat = vc.ValorantLiveClient._flatten_presence(legacy)
        self.assertEqual(flat["sessionLoopState"], "PREGAME")
        self.assertEqual(flat["provisioningFlow"], "Matchmaking")
        self.assertEqual(flat["partyOwnerMatchCurrentTeam"], "Blue")

    def test_menus_presence_has_no_loop_state(self):
        menus = {
            "isValid": True,
            "provisioningFlow": "Invalid",
            "matchPresenceData": {"sessionLoopState": "", "provisioningFlow": "Invalid"},
            "partyPresenceData": {"partyState": "DEFAULT"},
        }
        flat = vc.ValorantLiveClient._flatten_presence(menus)
        self.assertEqual(flat["sessionLoopState"], "")
        self.assertEqual(flat["provisioningFlow"], "")


if __name__ == "__main__":
    unittest.main()
