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


if __name__ == "__main__":
    unittest.main()
