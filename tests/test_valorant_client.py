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
