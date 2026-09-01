"""
Live VALORANT client integration.

Everything in here talks to the game/Riot Client running on this same PC,
using the local lockfile-authenticated REST API plus the official PVP
endpoints the client itself calls:

- Session state (in menus / agent select / in match) and the live round score
  come from the local chat presence payload.
- Party, queue and matchmaking control come from the GLZ party endpoints.
- Agent select and the live scoreboard come from the GLZ pregame / core-game
  endpoints.

Nothing here works unless VALORANT is actually running and logged in - every
call degrades to a "not available" result rather than raising, so the
dashboard can poll it continuously without special-casing.
"""

import os
import re
import json
import base64
import time
import threading
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CLIENT_PLATFORM = (
    "ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjogIldpbmRvd3MiLA0KCSJwbGF0"
    "Zm9ybU9TVmVyc2lvbiI6ICIxMC4wLjE5MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0"
    "IjogIlVua25vd24iDQp9"
)

FALLBACK_CLIENT_VERSION = "release-08.11-shipping-9-2516482"

# Region -> shard. LATAM and BR both play on the NA shard but keep their own
# region in the GLZ hostname.
SHARD_BY_REGION = {
    "na": "na", "latam": "na", "br": "na",
    "eu": "eu", "ap": "ap", "kr": "kr",
}

# Queues the client exposes, in the order the dashboard shows them.
GAME_MODES = [
    {"id": "competitive", "name": "Competitive", "icon": "fa-solid fa-trophy", "ranked": True},
    {"id": "unrated", "name": "Unrated", "icon": "fa-solid fa-crosshairs", "ranked": False},
    {"id": "swiftplay", "name": "Swiftplay", "icon": "fa-solid fa-bolt", "ranked": False},
    {"id": "spikerush", "name": "Spike Rush", "icon": "fa-solid fa-bomb", "ranked": False},
    {"id": "deathmatch", "name": "Deathmatch", "icon": "fa-solid fa-skull", "ranked": False},
    {"id": "hurm", "name": "Team Deathmatch", "icon": "fa-solid fa-users-rectangle", "ranked": False},
    {"id": "ggteam", "name": "Escalation", "icon": "fa-solid fa-arrow-trend-up", "ranked": False},
]

MODE_LABELS = {
    "competitive": "Competitive",
    "unrated": "Unrated",
    "swiftplay": "Swiftplay",
    "spikerush": "Spike Rush",
    "deathmatch": "Deathmatch",
    "hurm": "Team Deathmatch",
    "ggteam": "Escalation",
    "onefa": "Replication",
    "newmap": "New Map",
    "snowball": "Snowball Fight",
}

TIER_NAMES = [
    "UNRANKED", "Unused1", "Unused2",
    "IRON 1", "IRON 2", "IRON 3",
    "BRONZE 1", "BRONZE 2", "BRONZE 3",
    "SILVER 1", "SILVER 2", "SILVER 3",
    "GOLD 1", "GOLD 2", "GOLD 3",
    "PLATINUM 1", "PLATINUM 2", "PLATINUM 3",
    "DIAMOND 1", "DIAMOND 2", "DIAMOND 3",
    "ASCENDANT 1", "ASCENDANT 2", "ASCENDANT 3",
    "IMMORTAL 1", "IMMORTAL 2", "IMMORTAL 3",
    "RADIANT"
]

TIER_BASE_URL = "https://media.valorant-api.com/competitivetiers/03621f52-342b-cf4e-4f86-9350a49c6d04"


def tier_label(tier_num: int) -> str:
    if isinstance(tier_num, int) and 0 < tier_num < len(TIER_NAMES):
        return TIER_NAMES[tier_num].title()
    return "Unranked"


def tier_icon(tier_num: int) -> str:
    idx = tier_num if isinstance(tier_num, int) and 0 <= tier_num < len(TIER_NAMES) else 0
    return f"{TIER_BASE_URL}/{idx}/largeicon.png"


def parse_player_mmr(mmr_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts tier, RR, peak tier, and seasonal stats from raw MMR JSON."""
    result = {
        "tier": 0,
        "tier_label": "Unranked",
        "tier_icon": tier_icon(0),
        "rr": 0,
        "peak_tier": 0,
        "peak_tier_label": "Unranked",
        "peak_tier_icon": tier_icon(0),
        "wins": 0,
        "games": 0,
        "winrate": 0,
    }
    if not mmr_data or not isinstance(mmr_data, dict):
        return result

    skills = mmr_data.get("QueueSkills", {}).get("competitive", {})
    if not skills:
        return result

    seasons = skills.get("SeasonalInfoBySeasonID", {}) or {}
    act_id = current_act_id()
    peak_t = 0
    current_tier = 0
    current_rr = 0
    total_wins = 0
    total_games = 0

    for s_id, s_info in seasons.items():
        if not isinstance(s_info, dict):
            continue
        c_tier = int(s_info.get("CompetitiveTier") or 0)
        r_tier = int(s_info.get("Rank") or 0)
        t_high = max(c_tier, r_tier)
        if t_high > peak_t:
            peak_t = t_high

        wins = int(s_info.get("NumberOfWins") or 0)
        games = int(s_info.get("NumberOfGames") or 0)
        total_wins += wins
        total_games += games

        if act_id:
            # Riot's seasonal dict isn't ordered, so only the entry for the
            # act that's live right now decides the current rank. No entry (or
            # a zeroed one) means Unranked this act, even with prior-act ranks.
            if s_id == act_id:
                current_tier = c_tier
                current_rr = int(s_info.get("RankedRating") or 0)
        elif c_tier > 0 or games > 0:
            # Feed unavailable: fall back to "last season with activity wins".
            current_tier = c_tier
            current_rr = int(s_info.get("RankedRating") or 0)

    latest = mmr_data.get("LatestCompetitiveUpdate", {}) or {}
    latest_season = latest.get("SeasonID", "") or ""
    if act_id:
        if latest_season == act_id and latest.get("TierAfterUpdate") is not None:
            current_tier = int(latest.get("TierAfterUpdate") or 0)
            current_rr = int(latest.get("RankedRatingAfterUpdate") or current_rr)
    elif latest.get("TierAfterUpdate"):
        current_tier = int(latest.get("TierAfterUpdate") or current_tier)
        current_rr = int(latest.get("RankedRatingAfterUpdate") or current_rr)

    if peak_t < current_tier:
        peak_t = current_tier

    result["tier"] = current_tier
    result["tier_label"] = tier_label(current_tier) or "Unranked"
    result["tier_icon"] = tier_icon(current_tier) or tier_icon(0)
    result["rr"] = current_rr
    result["peak_tier"] = peak_t
    result["peak_tier_label"] = tier_label(peak_t) or "Unranked"
    result["peak_tier_icon"] = tier_icon(peak_t) or tier_icon(0)
    result["wins"] = total_wins
    result["games"] = total_games
    result["winrate"] = round((total_wins / total_games * 100)) if total_games > 0 else 0

    return result


# --------------------------------------------------------------------------
# Static game data (agents, maps, client version), fetched once and cached.
# --------------------------------------------------------------------------

_STATIC_CACHE: Dict[str, Any] = {"agents": None, "maps": None, "version": None}
_STATIC_LOCK = threading.Lock()
_MATCH_DETAILS_CACHE: Dict[str, Any] = {}
_MATCH_DETAILS_LOCK = threading.Lock()


def _fetch_json(url: str, timeout: float = 6.0) -> Optional[Any]:
    try:
        res = requests.get(url, timeout=timeout)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None


def get_agents() -> List[Dict[str, str]]:
    """Playable agents from valorant-api, cached for the process lifetime."""
    with _STATIC_LOCK:
        if _STATIC_CACHE["agents"]:
            return _STATIC_CACHE["agents"]

    data = _fetch_json("https://valorant-api.com/v1/agents?isPlayableCharacter=true")
    agents = []
    for a in (data or {}).get("data", []) or []:
        agents.append({
            "id": a.get("uuid", ""),
            "name": a.get("displayName", ""),
            "icon": a.get("displayIcon") or a.get("displayIconSmall") or "",
            "portrait": a.get("fullPortrait") or "",
            "role": ((a.get("role") or {}).get("displayName") or ""),
        })
    agents.sort(key=lambda x: x["name"])

    if agents:
        with _STATIC_LOCK:
            _STATIC_CACHE["agents"] = agents
    return agents


def agent_by_id(agent_id: str) -> Dict[str, str]:
    target = (agent_id or "").lower()
    for a in get_agents():
        if a["id"].lower() == target:
            return a
    return {"id": agent_id or "", "name": "", "icon": "", "portrait": "", "role": ""}


# Agents every account can play without unlocking them.  The store entitlements
# endpoint only lists agents unlocked through a contract or bought outright, so
# these have to be folded in by hand.
DEFAULT_AGENT_IDS = {
    "9f0d8ba9-4140-b941-57d3-a7ad57c6b417",  # Brimstone
    "add6443a-41bd-e414-f6ad-e58d267f4e95",  # Jett
    "eb93336a-449b-9c1b-0a54-a891f7921d69",  # Phoenix
    "569fdd95-4d10-43ab-ca70-79becc718b46",  # Sage
    "320b2a48-4d9b-a075-30f1-1f93a9b638fa",  # Sova
}


def owned_agent_ids() -> Optional[set]:
    """Lowercased ids of agents the signed-in account can play, or None when the
    Riot Client can't be reached to ask (so callers should assume all)."""
    client = ValorantLiveClient()
    if not client.connect():
        return None
    raw = client.entitlements(ITEM_AGENT)
    if not raw:
        # Either the request failed or the account has unlocked nothing yet -
        # don't gray out the whole roster on a guess.
        return None
    return {a.lower() for a in raw if a} | DEFAULT_AGENT_IDS


def get_maps() -> Dict[str, Dict[str, str]]:
    """Map metadata keyed by both mapUrl and uuid, so either id form resolves."""
    with _STATIC_LOCK:
        if _STATIC_CACHE["maps"]:
            return _STATIC_CACHE["maps"]

    data = _fetch_json("https://valorant-api.com/v1/maps")
    maps: Dict[str, Dict[str, str]] = {}
    for m in (data or {}).get("data", []) or []:
        entry = {
            "name": m.get("displayName", ""),
            "splash": m.get("splash") or "",
            "icon": m.get("listViewIcon") or "",
        }
        if m.get("mapUrl"):
            maps[m["mapUrl"]] = entry
        if m.get("uuid"):
            maps[m["uuid"]] = entry

    if maps:
        with _STATIC_LOCK:
            _STATIC_CACHE["maps"] = maps
    return maps


def resolve_map(map_id: str) -> Dict[str, str]:
    if not map_id:
        return {"name": "", "splash": "", "icon": ""}
    entry = get_maps().get(map_id)
    if entry:
        return entry
    # Fall back to the last path segment of a map URL ("/Game/Maps/Ascent/Ascent").
    tail = map_id.rstrip("/").split("/")[-1]
    return {"name": tail, "splash": "", "icon": ""}


MODE_TAIL_LABELS = {
    "BombGameMode": "Standard",
    "QuickBomb": "Spike Rush",
    "DeathmatchGameMode": "Deathmatch",
    "GunGameTeamsGameMode": "Escalation",
    "OneForAll": "Replication",
    "HURMGameMode": "Team Deathmatch",
    "SwiftPlayGameMode": "Swiftplay",
}


def resolve_mode(mode_id: str, queue_id: str = "") -> str:
    if queue_id and queue_id.lower() in MODE_LABELS:
        return MODE_LABELS[queue_id.lower()]
    if not mode_id:
        return ""
    tail = mode_id.rstrip("/").split("/")[-1].split(".")[0]
    return MODE_TAIL_LABELS.get(tail, tail)


def get_client_version() -> str:
    with _STATIC_LOCK:
        cached = _STATIC_CACHE["version"]
    if cached:
        return cached

    data = _fetch_json("https://valorant-api.com/v1/version", timeout=4.0)
    version = ((data or {}).get("data") or {}).get("riotClientVersion") or FALLBACK_CLIENT_VERSION
    with _STATIC_LOCK:
        _STATIC_CACHE["version"] = version
    return version


# Region/shard only change when the game is restarted into another region, so
# the lookup is cached briefly rather than repeated on every poll.
_REGION_CACHE: Dict[str, Any] = {
    "region": None,
    "shard": None,
    "at": 0.0,
    # A Riot Client restart rotates its lockfile credentials, and an account
    # swap changes the PUUID.  Both must invalidate routing: otherwise an EU
    # account opened after an NA account can spend the cache TTL talking to
    # the wrong shard.
    "session_key": None,
}
_REGION_TTL = 180.0


def _region_session_key(puuid: str = "", port: Optional[int] = None,
                        local_password: str = "") -> Tuple[str, int, str]:
    return ((puuid or "").strip(), int(port or 0), local_password or "")


def _region_from_cache(puuid: str = "", port: Optional[int] = None,
                       local_password: str = "") -> Optional[Tuple[str, str]]:
    session_key = _region_session_key(puuid, port, local_password)
    with _STATIC_LOCK:
        if (
            _REGION_CACHE["region"]
            and _REGION_CACHE.get("session_key") == session_key
            and (time.time() - _REGION_CACHE["at"]) < _REGION_TTL
        ):
            return _REGION_CACHE["region"], _REGION_CACHE["shard"]
    return None


def _store_region_cache(region: str, shard: str, puuid: str = "",
                        port: Optional[int] = None, local_password: str = "") -> None:
    with _STATIC_LOCK:
        _REGION_CACHE.update({
            "region": region,
            "shard": shard,
            "at": time.time(),
            "session_key": _region_session_key(puuid, port, local_password),
        })


class LiveClientError(Exception):
    """Raised for user-facing failures (game not running, request rejected)."""


class ValorantLiveClient:
    """
    Thin wrapper over the local + PVP endpoints. Construct it per request -
    the lockfile auth and tokens are cheap to read and go stale when the
    client restarts, so there's nothing worth holding onto between calls.
    """

    def __init__(self):
        self.port: Optional[int] = None
        self.local_password: Optional[str] = None
        self.access_token: Optional[str] = None
        self.entitlements_token: Optional[str] = None
        self.puuid: Optional[str] = None
        self.region: str = "na"
        self.shard: str = "na"

    # -- connection ------------------------------------------------------

    @staticmethod
    def read_lockfile() -> Optional[Tuple[int, str]]:
        try:
            local_appdata = os.getenv("LOCALAPPDATA")
            if not local_appdata:
                return None
            path = os.path.join(local_appdata, "Riot Games", "Riot Client", "Config", "lockfile")
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                parts = f.read().strip().split(":")
            if len(parts) >= 5:
                return int(parts[2]), parts[3]
        except Exception:
            pass
        return None

    def connect(self) -> bool:
        """Reads lockfile auth + entitlement tokens. False if unavailable."""
        lock = self.read_lockfile()
        if not lock:
            return False
        self.port, self.local_password = lock

        try:
            res = requests.get(
                f"https://127.0.0.1:{self.port}/entitlements/v1/token",
                auth=("riot", self.local_password), verify=False, timeout=2.0
            )
            if res.status_code != 200:
                return False
            tok = res.json()
            self.access_token = tok.get("accessToken")
            self.entitlements_token = tok.get("token")
            self.puuid = tok.get("subject")
        except Exception:
            return False

        if not (self.access_token and self.entitlements_token and self.puuid):
            return False

        self._detect_region()
        return True

    def _detect_region(self):
        """
        The GLZ hostname needs both region and shard. The game logs the exact
        URL it uses on every launch, which is the only fully reliable source -
        region-locale alone can't tell LATAM/BR apart from NA's shard.

        Only the head of the log is read: VALORANT starts a fresh
        ShooterGame.log per launch and logs the URL during startup, so the
        first match is this session's - and the file grows to megabytes while
        you play, which this is polled far too often to read in full.
        """
        cached = _region_from_cache(self.puuid or "", self.port, self.local_password or "")
        if cached:
            self.region, self.shard = cached
            return

        try:
            log_path = os.path.join(
                os.getenv("LOCALAPPDATA") or "", "VALORANT", "Saved", "Logs", "ShooterGame.log"
            )
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(1_000_000)
                found = re.search(r"https://glz-([a-z0-9-]+)-1\.([a-z0-9]+)\.a\.pvp\.net", head)
                if found:
                    self.region, self.shard = found.group(1), found.group(2)
                    _store_region_cache(
                        self.region, self.shard,
                        self.puuid or "", self.port, self.local_password or "",
                    )
                    return
        except Exception:
            pass

        try:
            res = requests.get(
                f"https://127.0.0.1:{self.port}/riotclient/region-locale",
                auth=("riot", self.local_password), verify=False, timeout=1.5
            )
            if res.status_code == 200:
                reg = (res.json().get("region") or "na").lower()
                self.region = reg
                self.shard = SHARD_BY_REGION.get(reg, "na")
                _store_region_cache(
                    self.region, self.shard,
                    self.puuid or "", self.port, self.local_password or "",
                )
                return
        except Exception:
            pass

        self.region, self.shard = "na", "na"

    # -- request helpers -------------------------------------------------

    @property
    def glz(self) -> str:
        return f"https://glz-{self.region}-1.{self.shard}.a.pvp.net"

    @property
    def pd(self) -> str:
        return f"https://pd.{self.shard}.a.pvp.net"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Riot-Entitlements-JWT": self.entitlements_token,
            "X-Riot-ClientPlatform": CLIENT_PLATFORM,
            "X-Riot-ClientVersion": get_client_version(),
            "Content-Type": "application/json",
        }

    def _remote(self, method: str, url: str, payload: Any = None, timeout: float = 5.0):
        try:
            return requests.request(
                method, url, headers=self._headers(),
                json=payload if payload is not None else None, timeout=timeout
            )
        except Exception as e:
            raise LiveClientError(f"Couldn't reach Riot's servers: {e}")

    def _local(self, path: str, timeout: float = 2.0):
        try:
            return requests.get(
                f"https://127.0.0.1:{self.port}{path}",
                auth=("riot", self.local_password), verify=False, timeout=timeout
            )
        except Exception:
            return None

    # -- presence (session state + live score) ---------------------------

    @staticmethod
    def _flatten_presence(decoded: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise Riot's private presence to the flat shape the rest of the
        app reads.

        Around client release 13.04 Riot moved the match/party fields out of
        the top level into nested `matchPresenceData` / `partyPresenceData`
        objects, and left a top-level `provisioningFlow: "Invalid"` behind.
        Everything downstream still expects `sessionLoopState`,
        `provisioningFlow`, `matchMap`, `partyState`, `partyOwnerMatchCurrentTeam`
        at the top level, so lift them back up (old layout wins if present).
        """
        if not isinstance(decoded, dict):
            return {}
        match = decoded.get("matchPresenceData") or {}
        party = decoded.get("partyPresenceData") or {}

        # "Invalid" is Riot's placeholder for "no value" - never surface it.
        def pick(*values):
            for v in values:
                if v not in (None, "", "Invalid"):
                    return v
            return ""

        flat = dict(decoded)
        flat["sessionLoopState"] = pick(
            decoded.get("sessionLoopState"),
            match.get("sessionLoopState"),
            party.get("partyOwnerSessionLoopState"),
        )
        flat["provisioningFlow"] = pick(
            decoded.get("provisioningFlow") if decoded.get("provisioningFlow") != "Invalid" else None,
            match.get("provisioningFlow"),
            party.get("partyOwnerProvisioningFlow"),
        )
        flat["queueId"] = pick(
            decoded.get("queueId"), match.get("queueId"), party.get("queueId")
        )
        flat["matchMap"] = pick(
            decoded.get("matchMap"), match.get("matchMap"), party.get("partyOwnerMatchMap")
        )
        flat["partyState"] = pick(decoded.get("partyState"), party.get("partyState"))
        flat["partyOwnerMatchCurrentTeam"] = pick(
            decoded.get("partyOwnerMatchCurrentTeam"),
            match.get("partyOwnerMatchCurrentTeam"),
            party.get("partyOwnerMatchCurrentTeam"),
        )
        for key in (
            "partyOwnerMatchScoreAllyTeam",
            "partyOwnerMatchScoreEnemyTeam",
            "partyOwnerProvisioningStartTime",
        ):
            if not flat.get(key):
                flat[key] = decoded.get(key) or party.get(key) or match.get(key) or 0
        return flat

    def presence(self) -> Dict[str, Any]:
        """
        Decoded private presence payload for this account, flattened to the
        legacy field layout. This is where the live round score and the
        menus/pregame/ingame state live - the match endpoints don't expose a
        running score.
        """
        res = self._local("/chat/v4/presences")
        if not res or res.status_code != 200:
            return {}

        best_payload = {}
        try:
            for p in res.json().get("presences", []) or []:
                if p.get("puuid") != self.puuid:
                    continue
                raw = p.get("private")
                if not raw:
                    continue
                try:
                    decoded = json.loads(base64.b64decode(raw).decode("utf-8", errors="ignore"))
                except Exception:
                    continue
                flat = self._flatten_presence(decoded)
                # Return as soon as a payload carries real session/match/party state.
                if (
                    flat.get("sessionLoopState")
                    or flat.get("partyOwnerMatchCurrentTeam")
                    or flat.get("provisioningFlow")
                    or decoded.get("matchPresenceData")
                    or decoded.get("partyPresenceData")
                ):
                    return flat
                if not best_payload:
                    best_payload = flat
        except Exception:
            pass
        return best_payload

    # -- names -----------------------------------------------------------

    def resolve_names(self, puuids: List[str]) -> Dict[str, str]:
        """
        PUUID -> "Name#TAG" for everyone the name service will actually name.
        Riot returns an entry for every PUUID asked, but with GameName/TagLine
        blank for players it won't reveal yet (early agent select) or won't
        reveal at all (streamer mode). Those are skipped rather than turned
        into a bare "#" - the caller retries and fills them in later.
        """
        if not puuids:
            return {}
        try:
            res = self._remote("PUT", f"{self.pd}/name-service/v2/players", puuids, timeout=6.0)
            if res.status_code != 200:
                return {}
            out: Dict[str, str] = {}
            for e in res.json():
                subject = e.get("Subject", "")
                game_name = (e.get("GameName") or "").strip()
                tag_line = (e.get("TagLine") or "").strip()
                if not subject or not game_name:
                    continue
                out[subject] = f"{game_name}#{tag_line}" if tag_line else game_name
            return out
        except Exception:
            return {}

    # -- party / queue ---------------------------------------------------

    def party_id(self, retries: int = 3) -> Optional[str]:
        """The account's current party id.

        Retried a few times: right after the client reaches the menus the
        party service can 404 or time out for a second or two, and a single
        miss there is what made "Start match" fail with "No party found"
        even though the player was sitting in the lobby.
        """
        for attempt in range(max(1, retries)):
            try:
                res = self._remote(
                    "GET", f"{self.glz}/parties/v1/players/{self.puuid}", timeout=4.0
                )
            except LiveClientError:
                res = None
            if res is not None and res.status_code == 200:
                pid = res.json().get("CurrentPartyID")
                if pid:
                    return pid
            if attempt < retries - 1:
                time.sleep(0.6)
        return None

    def party(self) -> Dict[str, Any]:
        pid = self.party_id()
        if not pid:
            return {}
        res = self._remote("GET", f"{self.glz}/parties/v1/parties/{pid}")
        if res.status_code != 200:
            return {}
        return res.json()

    def eligible_queue_ids(self) -> Optional[set]:
        """Return the party's Riot-advertised queue ids, or ``None`` if unknown.

        This read-only party endpoint is the only useful signal for a legacy
        low-level account: it answers whether the signed-in party may select
        Competitive now.  It does not enqueue, change a queue, or infer
        eligibility from account age/rank history.
        """
        pid = self.party_id(retries=1)
        if not pid:
            return None
        try:
            res = self._remote("GET", f"{self.glz}/parties/v1/parties/{pid}/eligiblequeues")
        except LiveClientError:
            return None
        if res.status_code != 200:
            return None
        try:
            payload = res.json()
        except Exception:
            return None

        entries = payload.get("Queues") if isinstance(payload, dict) else payload
        if isinstance(payload, dict) and entries is None:
            # Riot has used both ``Queues`` and ``EligibleQueues`` casing in
            # different client builds; accept either without changing the
            # semantics of an unavailable response.
            entries = (
                payload.get("EligibleQueues")
                or payload.get("eligibleQueues")
                or payload.get("queueIDs")
                or payload.get("QueueIDs")
            )
        if isinstance(entries, dict):
            entries = entries.get("Queues") or entries.get("queueIDs") or entries.get("QueueIDs") or []
        if not isinstance(entries, list):
            return None
        ids = set()
        for entry in entries:
            if isinstance(entry, str):
                ids.add(entry.lower())
            elif isinstance(entry, dict):
                queue_id = entry.get("QueueID") or entry.get("queueID") or entry.get("id")
                if queue_id:
                    ids.add(str(queue_id).lower())
        return ids

    def change_queue(self, queue_id: str) -> Dict[str, Any]:
        pid = self.party_id()
        if not pid:
            raise LiveClientError("No party found - open VALORANT and return to the menus first.")
        res = self._remote(
            "POST", f"{self.glz}/parties/v1/parties/{pid}/queue", {"queueID": queue_id}
        )
        if res.status_code not in (200, 204):
            raise LiveClientError(
                self._error_text(res, f"Couldn't switch to {MODE_LABELS.get(queue_id, queue_id)}")
            )
        return {"queue_id": queue_id}

    def start_queue(self) -> Dict[str, Any]:
        pid = self.party_id()
        if not pid:
            raise LiveClientError("No party found - open VALORANT and return to the menus first.")
        res = self._remote("POST", f"{self.glz}/parties/v1/parties/{pid}/matchmaking/join")
        if res.status_code not in (200, 204):
            raise LiveClientError(self._error_text(res, "Couldn't start matchmaking"))
        return {"queued": True}

    def stop_queue(self) -> Dict[str, Any]:
        pid = self.party_id()
        if not pid:
            raise LiveClientError("No party found.")
        res = self._remote("POST", f"{self.glz}/parties/v1/parties/{pid}/matchmaking/leave")
        if res.status_code not in (200, 204):
            raise LiveClientError(self._error_text(res, "Couldn't cancel the queue"))
        return {"queued": False}

    @staticmethod
    def _error_text(res, fallback: str) -> str:
        """
        Riot's rejections carry a machine-readable errorCode that's far more
        useful than the status code (e.g. trying to queue competitive on an
        account that hasn't unlocked it).
        """
        try:
            body = res.json()
            code = body.get("errorCode") or body.get("message") or ""
        except Exception:
            code = ""

        friendly = {
            "PARTY_NOT_ELIGIBLE": "This account can't queue that mode yet - competitive needs level 20 and 10 unrated wins.",
            "NOT_ENOUGH_PLAYERS": "Not enough players in the party for that mode.",
            "PLAYER_BANNED_FROM_QUEUE": "This account is currently restricted from queueing.",
            "INVALID_QUEUE": "That mode isn't available right now.",
            "QUEUE_DISABLED": "Riot has that queue disabled right now.",
        }.get(code)

        if friendly:
            return friendly
        if code:
            return f"{fallback}: {code}"
        return f"{fallback} (HTTP {res.status_code})."

    # -- pregame (agent select) ------------------------------------------

    def pregame_match_id(self) -> Optional[str]:
        res = self._remote("GET", f"{self.glz}/pregame/v1/players/{self.puuid}", timeout=3.0)
        if res.status_code != 200:
            return None
        return res.json().get("MatchID")

    def pregame_match(self, match_id: Optional[str] = None) -> Dict[str, Any]:
        match_id = match_id or self.pregame_match_id()
        if not match_id:
            return {}
        res = self._remote("GET", f"{self.glz}/pregame/v1/matches/{match_id}")
        if res.status_code != 200:
            return {}
        return res.json()

    def _pregame_post(self, verb: str, agent_id: str, match_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        select / lock share a shape: both answer with the freshly updated
        pregame match. Handing that payload back means the caller can verify
        the pick landed without paying for another round trip.
        """
        res = self._remote(
            "POST", f"{self.glz}/pregame/v1/matches/{match_id}/{verb}/{agent_id}", timeout=4.0
        )
        try:
            payload = res.json() or {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return res.status_code == 200, payload

    def select_agent_ex(self, agent_id: str, match_id: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        match_id = match_id or self.pregame_match_id()
        if not match_id:
            return False, {}
        return self._pregame_post("select", agent_id, match_id)

    def lock_agent_ex(self, agent_id: str, match_id: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        match_id = match_id or self.pregame_match_id()
        if not match_id:
            return False, {}
        return self._pregame_post("lock", agent_id, match_id)

    def select_agent(self, agent_id: str, match_id: Optional[str] = None) -> bool:
        return self.select_agent_ex(agent_id, match_id)[0]

    def lock_agent(self, agent_id: str, match_id: Optional[str] = None) -> bool:
        return self.lock_agent_ex(agent_id, match_id)[0]

    # -- core game (live match) ------------------------------------------

    def coregame_match_id(self) -> Optional[str]:
        res = self._remote("GET", f"{self.glz}/core-game/v1/players/{self.puuid}", timeout=3.0)
        if res.status_code != 200:
            return None
        return res.json().get("MatchID")

    def coregame_match(self, match_id: Optional[str] = None) -> Dict[str, Any]:
        match_id = match_id or self.coregame_match_id()
        if not match_id:
            return {}
        res = self._remote("GET", f"{self.glz}/core-game/v1/matches/{match_id}")
        if res.status_code != 200:
            return {}
        return res.json()

    # -- player stats (rank, career, combat, inventory) -------------------

    def mmr(self) -> Dict[str, Any]:
        """Full MMR record: current tier/RR plus every act the player ranked in."""
        return self.player_mmr(self.puuid)

    def player_mmr(self, puuid: str) -> Dict[str, Any]:
        """Full MMR record for any player PUUID in the active match."""
        if not puuid or not self.pd:
            return {}
        res = self._remote("GET", f"{self.pd}/mmr/v1/players/{puuid}", timeout=4.0)
        if res.status_code != 200:
            return {}
        try:
            return res.json()
        except Exception:
            return {}

    def competitive_updates(self, count: int = 20) -> List[Dict[str, Any]]:
        """
        Recent competitive results with the RR delta for each one. This is a
        single cheap request that covers far more matches than pulling full
        match details, so it drives the streak and the RR graph.
        """
        url = (f"{self.pd}/mmr/v1/players/{self.puuid}/competitiveupdates"
               f"?startIndex=0&endIndex={max(1, min(count, 20))}&queue=competitive")
        res = self._remote("GET", url, timeout=8.0)
        if res.status_code != 200:
            return []
        return res.json().get("Matches", []) or []

    def match_history(self, count: int = 15, queue: str = "") -> List[Dict[str, Any]]:
        url = (f"{self.pd}/match-history/v1/history/{self.puuid}"
               f"?startIndex=0&endIndex={max(1, min(count, 20))}")
        if queue:
            url += f"&queue={queue}"
        res = self._remote("GET", url, timeout=8.0)
        if res.status_code != 200:
            return []
        return res.json().get("History", []) or []

    def match_details(self, match_id: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Full details for one match.

        Finished matches are immutable and safe to memoise.  Active modes can
        expose a partial payload that changes as the match runs, so their
        callers pass ``use_cache=False`` to bypass both reads and writes of the
        raw-details cache.
        """
        if use_cache:
            with _MATCH_DETAILS_LOCK:
                cached = _MATCH_DETAILS_CACHE.get(match_id)
            if cached is not None:
                return cached
        res = self._remote("GET", f"{self.pd}/match-details/v1/matches/{match_id}", timeout=6.0)
        if res.status_code != 200:
            return {}
        try:
            data = res.json()
            if data and use_cache:
                with _MATCH_DETAILS_LOCK:
                    if len(_MATCH_DETAILS_CACHE) > 30:
                        _MATCH_DETAILS_CACHE.clear()
                    _MATCH_DETAILS_CACHE[match_id] = data
            return data
        except Exception:
            return {}

    def player_combat_summary(self, puuid: str, max_matches: int = 5) -> Dict[str, Any]:
        """Computes K/D, KDA, ADR, ACS, Headshot %, 5-match winrate and party partners across recent matches."""
        result = {
            "kd": 0.0, "kda": 0.0, "hs_pct": 0, "kills": 0, "deaths": 0, "assists": 0,
            "adr": 0, "acs": 0, "rounds": 0, "matches_analyzed": 0, "parties": {},
            "party_partners": [], "winrate_last5": 0, "last5_wins": 0, "last5_losses": 0,
            "last5_games": 0, "last5_form": []
        }
        if not puuid or not self.pd:
            return result
        try:
            url = f"{self.pd}/match-history/v1/history/{puuid}?startIndex=0&endIndex={max_matches}"
            res = self._remote("GET", url, timeout=5.0)
            if res.status_code != 200:
                return result
            history = res.json().get("History", []) or []
            if not history:
                return result

            total_kills = 0
            total_deaths = 0
            total_assists = 0
            total_hs = 0
            total_bs = 0
            total_ls = 0
            total_damage = 0
            total_score = 0
            total_rounds = 0
            valid_matches = 0
            wins_count = 0
            losses_count = 0
            form_list = []
            party_partners_set = set()

            for h in history[:max_matches]:
                m_id = h.get("MatchID")
                if not m_id:
                    continue
                details = self.match_details(m_id)
                if not details:
                    continue

                all_players = details.get("players", []) or []
                p_entry = next((p for p in all_players if p.get("subject") == puuid), None)
                if not p_entry:
                    continue

                # Recent matches are the only place Riot publishes a party
                # id, and it is what the premade grouping is built from.
                party_id = p_entry.get("partyId") or ""
                if party_id:
                    result["parties"][m_id] = party_id
                    # Find all other players in this match who shared the exact same party_id
                    for op in all_players:
                        op_subject = op.get("subject") or ""
                        if op_subject and op_subject != puuid and op.get("partyId") == party_id:
                            party_partners_set.add(op_subject)

                # Determine match result (Win, Loss, Draw)
                p_team_id = p_entry.get("teamId") or p_entry.get("TeamId") or ""
                teams = details.get("teams", []) or []
                own_team = next((t for t in teams if (t.get("teamId") or t.get("TeamId") or "") == p_team_id), None)
                other_team = next((t for t in teams if (t.get("teamId") or t.get("TeamId") or "") != p_team_id), None)

                round_results = details.get("roundResults", []) or []
                played_rounds = [r for r in round_results if (r.get("roundResultCode") or "").lower() != "surrendered"]
                has_surrender = any((r.get("roundResultCode") or "").lower() == "surrendered" for r in round_results)

                if len(teams) == 2 and own_team is not None:
                    if has_surrender and played_rounds:
                        rw = sum(1 for r in played_rounds if (r.get("winningTeam") or "") == p_team_id)
                        rl = sum(1 for r in played_rounds if (r.get("winningTeam") or "") != p_team_id)
                    elif own_team.get("numPoints") is not None and other_team and other_team.get("numPoints") is not None:
                        rw = int(own_team.get("numPoints", 0) or 0)
                        rl = int(other_team.get("numPoints", 0) or 0)
                    else:
                        rw = int(own_team.get("roundsWon", 0) or 0)
                        rl = int(other_team.get("roundsWon", 0) or 0) if other_team else 0

                    if rw == rl:
                        res_str = "D"
                    elif bool(own_team.get("won")) or rw > rl:
                        res_str = "W"
                        wins_count += 1
                    else:
                        res_str = "L"
                        losses_count += 1
                else:
                    score_val = int((p_entry.get("stats") or {}).get("score", 0) or 0)
                    ranked_scores = sorted(
                        (int(((p.get("stats") or {}).get("score", 0)) or 0) for p in all_players), reverse=True
                    )
                    place = ranked_scores.index(score_val) + 1 if score_val in ranked_scores else 0
                    if place == 1:
                        res_str = "W"
                        wins_count += 1
                    else:
                        res_str = "L"
                        losses_count += 1
                form_list.append(res_str)

                p_stats = p_entry.get("stats") or {}
                total_kills += int(p_stats.get("kills") or 0)
                total_deaths += int(p_stats.get("deaths") or 0)
                total_assists += int(p_stats.get("assists") or 0)
                total_score += int(p_stats.get("score") or 0)

                total_rounds += len(round_results) or int(p_stats.get("roundsPlayed") or 0)
                for r in round_results:
                    for ps in r.get("playerStats", []) or []:
                        if ps.get("subject") == puuid:
                            for d in ps.get("damage", []) or []:
                                total_hs += int(d.get("headshots") or 0)
                                total_bs += int(d.get("bodyshots") or 0)
                                total_ls += int(d.get("legshots") or 0)
                                total_damage += int(d.get("damage") or 0)
                valid_matches += 1

            if valid_matches > 0:
                total_hits = total_hs + total_bs + total_ls
                result["kd"] = round(total_kills / max(1, total_deaths), 2)
                result["kda"] = round((total_kills + total_assists) / max(1, total_deaths), 2)
                result["hs_pct"] = round((total_hs / max(1, total_hits)) * 100) if total_hits > 0 else 0
                result["kills"] = total_kills
                result["deaths"] = total_deaths
                result["assists"] = total_assists
                result["rounds"] = total_rounds
                result["adr"] = round(total_damage / max(1, total_rounds)) if total_rounds else 0
                result["acs"] = round(total_score / max(1, total_rounds)) if total_rounds else 0
                result["matches_analyzed"] = valid_matches
                result["party_partners"] = list(party_partners_set)
                result["last5_wins"] = wins_count
                result["last5_losses"] = losses_count
                result["last5_games"] = valid_matches
                result["last5_form"] = form_list
                result["winrate_last5"] = round((wins_count / valid_matches) * 100)
            return result
        except Exception:
            return result

    def loadout(self) -> Dict[str, Any]:
        """Currently equipped skins/sprays, straight off the local client."""
        res = self._local(f"/personalization/v2/players/{self.puuid}/playerloadout", timeout=4.0)
        if not res or res.status_code != 200:
            return {}
        try:
            return res.json()
        except Exception:
            return {}

    def entitlements(self, item_type_id: str) -> List[str]:
        """Owned item ids of one type (skin levels, agents, buddies, ...)."""
        res = self._remote(
            "GET", f"{self.pd}/store/v1/entitlements/{self.puuid}/{item_type_id}", timeout=10.0
        )
        if res.status_code != 200:
            return []
        try:
            return [e.get("ItemID", "") for e in res.json().get("Entitlements", []) or []]
        except Exception:
            return []

    def store_offers(self) -> Dict[str, int]:
        """OfferID -> VP price, used to price up the owned-skin collection."""
        res = self._remote("GET", f"{self.pd}/store/v1/offers/", timeout=10.0)
        if res.status_code != 200:
            return {}
        prices: Dict[str, int] = {}
        try:
            for offer in res.json().get("Offers", []) or []:
                cost = offer.get("Cost") or {}
                for _, value in cost.items():
                    prices[offer.get("OfferID", "")] = int(value or 0)
                    break
        except Exception:
            return {}
        return prices


# --------------------------------------------------------------------------
# Insta-lock watcher
#
# Arms a background thread that waits for agent select to start and then
# selects + locks the chosen agent. Only one can be armed at a time;
# re-arming replaces the previous one.
# --------------------------------------------------------------------------

INSTALOCK: Dict[str, Any] = {
    "enabled": False,
    "agent_id": "",
    "agent_name": "",
    "status": "idle",       # idle | on | waiting | locking | locked | failed
    "message": "",
    "last_match_id": "",
    "locked_at": 0.0,
}

_INSTALOCK_LOCK = threading.Lock()
_instalock_thread: Optional[threading.Thread] = None
_instalock_stop = threading.Event()

# Agent select needs a moment to finish coming up on the client before it
# accepts a pick, and the pick itself has to be acknowledged by the server
# before the lock can go out. Firing both back to back is what leaves the
# character half-selected and unchangeable, or locks it server-side while the
# client's own picker keeps spinning - so every step below is confirmed
# against the pregame payload before the next one is sent.
INSTALOCK_READY_TIMEOUT = 25.0     # max wait for character_select_active
INSTALOCK_SETTLE = 1.25            # grace once the phase is actually open
INSTALOCK_SELECT_HOLD = 1.15       # gap between a confirmed select and the lock
INSTALOCK_SELECT_ATTEMPTS = 5
INSTALOCK_LOCK_ATTEMPTS = 6
INSTALOCK_CONFIRM_TIMEOUT = 2.5    # how long a select/lock gets to show up

# Worst case the retries above run for about 40s, which still fits inside a
# 100s agent select. The happy path is ~3s from the phase opening: settle,
# select, confirm, hold, lock.

# Stand-in for callers that have nothing to cancel with. Never set.
_NEVER_SET = threading.Event()


def _pregame_self(match: Dict[str, Any], puuid: str) -> Dict[str, Any]:
    """Our own entry in a pregame match payload.

    Normally we are on AllyTeam, but check every player container Riot has
    used (AllyTeam.Players, a flat Players list, EnemyTeam for customs) so a
    payload-shape change can't hide our own pick state.
    """
    if not isinstance(match, dict):
        return {}
    buckets = [
        (match.get("AllyTeam") or {}).get("Players", []),
        (match.get("EnemyTeam") or {}).get("Players", []),
        match.get("Players", []),
    ]
    for players in buckets:
        for p in players or []:
            if p.get("Subject") == puuid:
                return p
    return {}


def _pregame_phase(match: Dict[str, Any]) -> str:
    """The agent-select phase string, lowercased, tolerant of field renames."""
    if not isinstance(match, dict):
        return ""
    return (
        match.get("PregameState")
        or match.get("PregameStateName")
        or match.get("Phase")
        or ""
    ).lower()


def _pick_state(match: Dict[str, Any], puuid: str) -> Tuple[str, str]:
    """(character id, selection state) for us, both lowercased."""
    me = _pregame_self(match, puuid)
    return (
        (me.get("CharacterID") or "").lower(),
        (me.get("CharacterSelectionState") or "").lower(),
    )


def _wait_for_agent_select(
    client: "ValorantLiveClient",
    match_id: str,
    stop_evt: threading.Event,
    timeout: float = INSTALOCK_READY_TIMEOUT,
) -> Dict[str, Any]:
    """
    Blocks until the client reports agent select is genuinely open, then
    returns the pregame payload. Only "character_select_active" counts as
    open: every other phase means the server is still handing the match out,
    and picking during one of those is exactly what desyncs the picker.
    """
    deadline = time.time() + timeout
    match: Dict[str, Any] = {}
    ready = False
    saw_match = False

    while time.time() < deadline and not stop_evt.is_set():
        try:
            match = client.pregame_match(match_id)
        except LiveClientError:
            match = {}

        phase = _pregame_phase(match)
        if phase == "character_select_active":
            ready = True
            break
        # Already past the picker - we (or the client) locked something.
        if _pick_state(match, client.puuid)[1] == "locked":
            return match
        # Fallback for a phase-string rename: the payload has our player entry
        # and an unlocked pick and some non-terminal phase - treat that as
        # "select is open" rather than timing out for 25s on a name we don't
        # recognise.
        if _pregame_self(match, client.puuid) and phase and phase not in (
            "provisioned", "match_provisioned", "closed", "complete",
        ):
            if not saw_match:
                saw_match = True
                stop_evt.wait(0.5)  # give the real phase one more poll to appear
                continue
            ready = True
            break
        stop_evt.wait(0.25)

    if ready:
        # The phase flips a beat before the game has finished drawing agent
        # select. A pick sent inside that window registers on the server and
        # never on screen, which is the "it locked but the UI is stuck" bug.
        stop_evt.wait(INSTALOCK_SETTLE)
        try:
            match = client.pregame_match(match_id) or match
        except LiveClientError:
            pass
    return match


def _confirm_pick(
    client: "ValorantLiveClient",
    match_id: str,
    agent_id: str,
    want: str,
    stop_evt: threading.Event,
    seed: Optional[Dict[str, Any]] = None,
    timeout: float = INSTALOCK_CONFIRM_TIMEOUT,
) -> bool:
    """
    Polls pregame until our own entry actually reports the requested agent in
    the requested state ("selected" - locked counts too - or "locked"). The
    POST response body is itself a fresh pregame payload, so it is checked
    first and polling only happens if that hasn't caught up yet.
    """
    target = (agent_id or "").lower()
    match = seed if isinstance(seed, dict) else {}
    deadline = time.time() + timeout

    while True:
        cid, sel = _pick_state(match, client.puuid)
        if cid == target and sel:
            if sel == "locked" or want == "selected":
                return True
        if stop_evt.is_set() or time.time() >= deadline:
            return False
        stop_evt.wait(0.3)
        try:
            match = client.pregame_match(match_id)
        except LiveClientError:
            match = {}


def lock_agent_flow(
    client: "ValorantLiveClient",
    agent_id: str,
    agent_name: str = "",
    match_id: Optional[str] = None,
    stop_evt: Optional[threading.Event] = None,
    wait_for_open: bool = True,
    on_status=None,
) -> Tuple[bool, str]:
    """
    Picks and locks an agent the way the client itself does it: select, wait
    for the server to acknowledge the select, then lock - each step verified
    against pregame rather than trusted from a 200. Returns (locked, message).
    """
    stop_evt = stop_evt if stop_evt is not None else _NEVER_SET
    agent_name = agent_name or agent_by_id(agent_id).get("name") or "that agent"
    target = (agent_id or "").lower()

    def say(status: str, message: str) -> None:
        if on_status:
            try:
                on_status(status, message)
            except Exception:
                pass

    try:
        match_id = match_id or client.pregame_match_id()
    except LiveClientError as e:
        return False, str(e)
    if not match_id:
        return False, "You are not in agent select right now."

    if wait_for_open:
        say("waiting", "Agent select found - waiting for the client to be ready...")
        match = _wait_for_agent_select(client, match_id, stop_evt)
    else:
        try:
            match = client.pregame_match(match_id)
        except LiveClientError:
            match = {}

    if stop_evt.is_set():
        return False, "Cancelled."

    cid, sel = _pick_state(match, client.puuid)
    if sel == "locked":
        if cid == target:
            return True, f"{agent_name} is already locked."
        return False, "An agent is already locked in for this match."

    say("locking", f"Locking {agent_name}...")

    # -- 1. select, and confirm the server took it ----------------------
    selected = bool(cid == target and sel)
    for attempt in range(INSTALOCK_SELECT_ATTEMPTS):
        if selected or stop_evt.is_set():
            break
        try:
            ok, payload = client.select_agent_ex(agent_id, match_id)
        except LiveClientError:
            ok, payload = False, {}

        # A rejected select is usually the phase not being open yet - but it
        # can also land and answer non-200, so the state is the real answer.
        selected = _confirm_pick(
            client, match_id, agent_id, "selected", stop_evt,
            seed=payload if ok else None,
            timeout=INSTALOCK_CONFIRM_TIMEOUT if ok else 1.0,
        )
        if not selected:
            stop_evt.wait(0.35 + attempt * 0.15)

    if stop_evt.is_set():
        return False, "Cancelled."
    if not selected:
        return False, (f"Couldn't pick {agent_name} - the client never took the "
                       f"selection. Check the agent is unlocked on this account.")

    # -- 2. let the client catch up before locking ----------------------
    # Sending the lock in the same breath as the select is what makes the
    # picker freeze on a half-applied pick. The pause is the actual fix.
    stop_evt.wait(INSTALOCK_SELECT_HOLD)

    # -- 3. lock, and confirm it stuck ----------------------------------
    for attempt in range(INSTALOCK_LOCK_ATTEMPTS):
        if stop_evt.is_set():
            break
        try:
            ok, payload = client.lock_agent_ex(agent_id, match_id)
        except LiveClientError:
            ok, payload = False, {}

        if _confirm_pick(client, match_id, agent_id, "locked", stop_evt,
                         seed=payload if ok else None):
            return True, f"Locked {agent_name}."

        # Deliberately never re-sends the select here: re-picking an agent
        # that is already selected is what makes the picker stop responding.
        stop_evt.wait(0.4 + attempt * 0.2)

    if stop_evt.is_set():
        return False, "Cancelled."
    return False, f"{agent_name} is picked but the lock didn't go through - lock it manually."


def _instalock_worker():
    """
    Polls pregame at a tight interval while armed. The poll only hits the
    account's own pregame endpoint, and only while the user has explicitly
    turned it on from the dashboard.
    """
    handled_matches = set()
    client: Optional[ValorantLiveClient] = None
    connected_at = 0.0

    def _status(status: str, message: str) -> None:
        with _INSTALOCK_LOCK:
            INSTALOCK["status"] = status
            INSTALOCK["message"] = message

    while not _instalock_stop.is_set():
        with _INSTALOCK_LOCK:
            if not INSTALOCK["enabled"]:
                break
            agent_id = INSTALOCK["agent_id"]
            agent_name = INSTALOCK["agent_name"]

        # One connection is reused across polls - reconnecting per tick would
        # re-read the lockfile and tokens several times a second. It's
        # refreshed periodically so a client restart or an expired token
        # doesn't leave the watcher stuck on dead credentials.
        if client is None or (time.time() - connected_at) > 120:
            candidate = ValorantLiveClient()
            if not candidate.connect():
                client = None
                _instalock_stop.wait(1.5)
                continue
            client, connected_at = candidate, time.time()

        try:
            match_id = client.pregame_match_id()
        except LiveClientError:
            client = None
            _instalock_stop.wait(1.0)
            continue

        if not match_id or match_id in handled_matches:
            _instalock_stop.wait(0.35)
            continue

        with _INSTALOCK_LOCK:
            INSTALOCK["last_match_id"] = match_id

        locked, message = lock_agent_flow(
            client, agent_id, agent_name, match_id,
            stop_evt=_instalock_stop, on_status=_status,
        )
        if _instalock_stop.is_set():
            break

        handled_matches.add(match_id)
        if len(handled_matches) > 20:
            handled_matches = {match_id}

        with _INSTALOCK_LOCK:
            INSTALOCK["status"] = "locked" if locked else "failed"
            INSTALOCK["message"] = message
            if locked:
                INSTALOCK["locked_at"] = time.time()

        # Hold the result briefly so the dashboard can show it, then go back
        # to watching for the next agent select.
        _instalock_stop.wait(4.0)
        with _INSTALOCK_LOCK:
            if INSTALOCK["enabled"]:
                INSTALOCK["status"] = "on"
                INSTALOCK["message"] = f"On - {agent_name} locks at agent select."

    with _INSTALOCK_LOCK:
        if not INSTALOCK["enabled"]:
            INSTALOCK["status"] = "idle"
            INSTALOCK["message"] = ""


def arm_instalock(agent_id: str, agent_name: str) -> Dict[str, Any]:
    global _instalock_thread
    disarm_instalock()

    with _INSTALOCK_LOCK:
        INSTALOCK.update({
            "enabled": True,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "status": "on",
            "message": f"On - {agent_name} locks at agent select.",
            "last_match_id": "",
        })

    _instalock_stop.clear()
    _instalock_thread = threading.Thread(target=_instalock_worker, daemon=True)
    _instalock_thread.start()
    return instalock_status()


def disarm_instalock() -> Dict[str, Any]:
    global _instalock_thread
    with _INSTALOCK_LOCK:
        INSTALOCK["enabled"] = False
    _instalock_stop.set()

    thread = _instalock_thread
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
    _instalock_thread = None

    with _INSTALOCK_LOCK:
        INSTALOCK.update({"status": "idle", "message": "", "agent_id": "", "agent_name": ""})
        return dict(INSTALOCK)


def instalock_status() -> Dict[str, Any]:
    with _INSTALOCK_LOCK:
        return dict(INSTALOCK)


# --------------------------------------------------------------------------
# Launching the game
#
# Re-running RiotClientServices.exe usually just focuses the window when the
# client is already open, which is why "Play" could look like it did nothing.
# The client's own PLAY button hits a local REST endpoint instead, so that is
# tried first, with the .exe and the installed game's own launcher kept as
# fallbacks. The attempt is then verified against the running process list
# rather than trusted, and escalates through the fallbacks if nothing starts.
# --------------------------------------------------------------------------

_PROGRAM_DATA = os.getenv("PROGRAMDATA") or r"C:\ProgramData"
RIOT_CLIENT_INSTALLS = os.path.join(_PROGRAM_DATA, "Riot Games", "RiotClientInstalls.json")
VALORANT_PRODUCT_SETTINGS = os.path.join(
    _PROGRAM_DATA, "Riot Games", "Metadata", "valorant.live", "valorant.live.product_settings.yaml"
)

FALLBACK_CLIENT_PATHS = [
    r"C:\Riot Games\Riot Client\RiotClientServices.exe",
    r"D:\Riot Games\Riot Client\RiotClientServices.exe",
    r"E:\Riot Games\Riot Client\RiotClientServices.exe",
    r"F:\Riot Games\Riot Client\RiotClientServices.exe",
    r"C:\Program Files\Riot Client\RiotClientServices.exe",
    r"C:\Program Files (x86)\Riot Client\RiotClientServices.exe",
]

# Detached, so closing Vortex never takes the game down with it.
_DETACHED_FLAGS = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

LAUNCH_STATE: Dict[str, Any] = {
    "active": False,
    "stage": "idle",     # idle | starting | waiting | running | failed
    "message": "",
    "method": "",
    "started_at": 0.0,
    "finished_at": 0.0,
}

_LAUNCH_LOCK = threading.Lock()
_launch_thread: Optional[threading.Thread] = None

# How long to keep watching for the game process before giving up. A cold
# start on a slow disk genuinely takes this long.
LAUNCH_VERIFY_TIMEOUT = 90.0


def _set_launch(**fields) -> None:
    with _LAUNCH_LOCK:
        LAUNCH_STATE.update(fields)


def launch_state() -> Dict[str, Any]:
    with _LAUNCH_LOCK:
        state = dict(LAUNCH_STATE)
    # A stale "active" from a crashed watcher would wedge the Play button on.
    if state["active"] and (time.time() - state["started_at"]) > LAUNCH_VERIFY_TIMEOUT + 30:
        _set_launch(active=False, stage="failed", message="Launch timed out.")
        with _LAUNCH_LOCK:
            state = dict(LAUNCH_STATE)
    return state


def clear_launch_state() -> None:
    _set_launch(active=False, stage="idle", message="", method="", finished_at=time.time())


def find_riot_client(preferred: str = "") -> Optional[str]:
    """Riot Client path: caller's setting, then the installer's own record."""
    if preferred and os.path.exists(preferred):
        return preferred

    # RiotClientInstalls.json is written by the installer and is the only
    # source that stays correct for non-default drives.
    try:
        with open(RIOT_CLIENT_INSTALLS, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        for key in ("rc_live", "rc_default", "rc_beta"):
            path = data.get(key)
            if path and os.path.exists(path):
                return path
    except Exception:
        pass

    for path in FALLBACK_CLIENT_PATHS:
        if os.path.exists(path):
            return path
    return None


def valorant_install_dir() -> Optional[str]:
    """Where VALORANT itself is installed, per the game's own metadata."""
    try:
        with open(VALORANT_PRODUCT_SETTINGS, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        found = re.search(r"product_install_full_path:\s*[\"\']?([^\"\'\r\n]+)", text)
        if found:
            path = found.group(1).strip().replace("/", os.sep)
            if os.path.isdir(path):
                return path
    except Exception:
        pass

    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game valorant.live"
        ) as key:
            path, _ = winreg.QueryValueEx(key, "InstallLocation")
            if path and os.path.isdir(path):
                return path
    except Exception:
        pass
    return None


def valorant_launcher_exe() -> Optional[str]:
    """
    The game's own launcher stub inside the install folder. Running it is the
    "use the game files" path - it asks the Riot Client to bring the game up
    the same way a desktop shortcut does.
    """
    base = valorant_install_dir()
    if not base:
        return None

    for candidate in (
        os.path.join(base, "VALORANT.exe"),
        os.path.join(base, "live", "VALORANT.exe"),
        os.path.join(base, "ShooterGame", "Binaries", "Win64", "VALORANT-Win64-Shipping.exe"),
        os.path.join(base, "live", "ShooterGame", "Binaries", "Win64", "VALORANT-Win64-Shipping.exe"),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def is_game_running() -> bool:
    """True while either VALORANT process is alive."""
    try:
        from .client_launcher import _is_process_running_fast
        return _is_process_running_fast({"valorant.exe", "valorant-win64-shipping.exe"})
    except Exception:
        pass
    for image in ("VALORANT.exe", "VALORANT-Win64-Shipping.exe"):
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                capture_output=True, text=True, shell=False, timeout=1.0
            ).stdout or ""
            if image.lower() in out.lower():
                return True
        except Exception:
            continue
    return False


def _spawn(args: List[str], cwd: Optional[str] = None) -> bool:
    try:
        subprocess.Popen(
            args, cwd=cwd, shell=False,
            creationflags=_DETACHED_FLAGS,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return True
    except Exception:
        return False


def _launch_via_client_api() -> bool:
    """
    Asks the running Riot Client to start VALORANT through the same local
    endpoint its own PLAY button uses. Only possible while the client is up
    and logged in - which is exactly when re-running the .exe does nothing.
    """
    lock = ValorantLiveClient.read_lockfile()
    if not lock:
        return False
    port, password = lock

    for path in (
        "/product-launcher/v1/products/valorant/patchlines/live",
        "/patch-proxy/v1/products/valorant/patchlines/live/launch",
    ):
        try:
            res = requests.post(
                f"https://127.0.0.1:{port}{path}",
                auth=("riot", password), verify=False, timeout=6.0
            )
            if res.status_code in (200, 201, 202, 204):
                return True
        except Exception:
            continue
    return False


def _launch_via_client_exe(client_path: Optional[str]) -> bool:
    if not client_path or not os.path.exists(client_path):
        return False
    return _spawn([
        client_path,
        "--launch-product=valorant",
        "--launch-patchline=live",
    ], cwd=os.path.dirname(client_path))


def _launch_via_game_files() -> bool:
    exe = valorant_launcher_exe()
    if not exe:
        return False
    return _spawn([exe], cwd=os.path.dirname(exe))


def _launch_watcher(client_path: Optional[str]) -> None:
    """
    Waits for the game process to appear, escalating to the next launch
    method if nothing shows up. Everything the UI needs to decide whether
    Play is clickable again comes out of LAUNCH_STATE.
    """
    deadline = time.time() + LAUNCH_VERIFY_TIMEOUT
    escalated_exe = False
    escalated_files = False

    while time.time() < deadline:
        if is_game_running():
            _set_launch(active=False, stage="running", message="VALORANT is running.",
                        finished_at=time.time())
            return

        waited = time.time() - LAUNCH_STATE["started_at"]

        # Nothing after ~18s means the first method didn't take - fall back
        # rather than sitting on a spinner that never resolves.
        if waited > 18 and not escalated_exe:
            escalated_exe = True
            if _launch_via_client_exe(client_path):
                _set_launch(method="client-exe", message="Starting VALORANT through the Riot Client...")

        if waited > 40 and not escalated_files:
            escalated_files = True
            if _launch_via_game_files():
                _set_launch(method="game-files", message="Starting VALORANT from the game files...")

        time.sleep(1.5)

    _set_launch(
        active=False, stage="failed", finished_at=time.time(),
        message="VALORANT didn't start. Make sure the Riot Client is signed in, then try again."
    )


def launch_valorant(client_path: str = "", force: bool = True) -> Dict[str, Any]:
    """
    Force-starts VALORANT and tracks the attempt so the UI can keep Play
    disabled until the game is either confirmed running or confirmed failed.
    """
    global _launch_thread

    if is_game_running():
        _set_launch(active=False, stage="running", message="VALORANT is already running.",
                    method="", finished_at=time.time())
        return {"success": True, "already_running": True, "message": "VALORANT is already running."}

    state = launch_state()
    if state["active"] and not force:
        return {"success": True, "already_launching": True, "message": state["message"]}

    resolved = find_riot_client(client_path)

    _set_launch(active=True, stage="starting", message="Starting VALORANT...",
                method="", started_at=time.time(), finished_at=0.0)

    started = False
    if _launch_via_client_api():
        started = True
        _set_launch(method="client-api")
    elif _launch_via_client_exe(resolved):
        started = True
        _set_launch(method="client-exe")
    elif _launch_via_game_files():
        started = True
        _set_launch(method="game-files")

    if not started:
        _set_launch(active=False, stage="failed", finished_at=time.time(),
                    message="Couldn't find the Riot Client. Set its path in Settings.")
        return {"success": False, "message": "Couldn't find the Riot Client. Set its path in Settings."}

    _set_launch(stage="waiting", message="Starting VALORANT - this can take a minute...")

    if _launch_thread and _launch_thread.is_alive():
        return {"success": True, "message": "Starting VALORANT..."}

    _launch_thread = threading.Thread(target=_launch_watcher, args=(resolved,), daemon=True)
    _launch_thread.start()
    return {"success": True, "message": "Starting VALORANT..."}


# --------------------------------------------------------------------------
# Player stats / inventory
#
# A tracker-style profile for the signed-in account, built entirely from the
# session's own tokens: rank + RR from the MMR record, form and RR history
# from competitive updates, combat numbers from recent match details, and the
# collection from the store entitlements plus the equipped loadout.
#
# Match details are big and immutable, so each one is parsed once and kept.
# The whole profile is built on a background thread and served from cache -
# the dashboard never waits on Riot.
# --------------------------------------------------------------------------

# Store item type ids (Riot's own constants).
ITEM_SKIN_LEVEL = "e7c63390-eda7-46e0-bb7a-a6abdacd2433"
ITEM_AGENT = "01bb38e1-da47-4e6a-9b3d-945fe4655707"
ITEM_BUDDY = "dd3bf334-87f3-40bd-b043-682a57a8dc3a"
ITEM_SPRAY = "d5f120f8-ff8c-4aac-92ea-f2b5acbe9475"
ITEM_CARD = "3f296c07-64c3-494c-923b-fe692a4fa1bd"
ITEM_TITLE = "de7caa6b-adf7-4588-bbd1-143831e786c6"

# Weapons shown in the loadout strip, in the order players think about them.
LOADOUT_ORDER = [
    "Vandal", "Phantom", "Operator", "Sheriff", "Classic", "Ghost", "Spectre",
    "Guardian", "Marshal", "Outlaw", "Judge", "Bulldog", "Frenzy", "Stinger",
    "Shorty", "Bucky", "Ares", "Odin", "Melee",
]

MATCH_DETAIL_SAMPLE = 8       # how many recent matches get fully parsed
_MATCH_CACHE: Dict[str, Dict[str, Any]] = {}
_MATCH_CACHE_MAX = 60

_STATS_CACHE: Dict[str, Any] = {
    "data": None,
    "built_at": 0.0,
    "puuid": "",
    "building": False,
    "building_puuid": "",
    # Every replacement build gets a token.  A worker from the account that
    # was signed in previously may finish later, but its old token prevents it
    # from overwriting the new account's profile.
    "generation": 0,
}
_STATS_LOCK = threading.Lock()
STATS_TTL = 240.0


def get_weapon_data() -> Dict[str, Any]:
    """
    Weapon + skin metadata from valorant-api, flattened into the three
    lookups the profile needs: weapon names, skin details, and skin-level to
    skin so an owned entitlement resolves back to its skin.
    """
    with _STATIC_LOCK:
        cached = _STATIC_CACHE.get("weapons")
    if cached:
        return cached

    data = _fetch_json("https://valorant-api.com/v1/weapons", timeout=10.0)
    tiers = _fetch_json("https://valorant-api.com/v1/contenttiers", timeout=8.0)

    tier_map = {
        t.get("uuid", ""): {
            "name": t.get("devName", ""),
            "color": "#" + (t.get("highlightColor") or "ffffffff")[:6],
            "icon": t.get("displayIcon", ""),
            "rank": t.get("rank", 0),
        }
        for t in (tiers or {}).get("data", []) or []
    }

    weapons: Dict[str, str] = {}
    skins: Dict[str, Dict[str, Any]] = {}
    levels: Dict[str, str] = {}
    premium_total = 0

    for w in (data or {}).get("data", []) or []:
        wid = w.get("uuid", "")
        wname = w.get("displayName", "")
        weapons[wid] = wname

        for s in w.get("skins", []) or []:
            sid = s.get("uuid", "")
            tier = tier_map.get(s.get("contentTierUuid") or "", {})
            skins[sid] = {
                "name": s.get("displayName", ""),
                "icon": s.get("displayIcon") or (
                    (s.get("chromas") or [{}])[0].get("fullRender", "")
                ),
                "weapon": wname,
                "tier": tier.get("name", ""),
                "tier_color": tier.get("color", ""),
                "tier_icon": tier.get("icon", ""),
            }
            if tier:
                premium_total += 1
            for lvl in s.get("levels", []) or []:
                levels[lvl.get("uuid", "")] = sid

    result = {
        "weapons": weapons,
        "skins": skins,
        "levels": levels,
        "premium_total": premium_total,
    }
    if weapons and skins:
        with _STATIC_LOCK:
            _STATIC_CACHE["weapons"] = result
    return result


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}


def _season_number(name: str) -> str:
    """
    Act/episode number out of a display name. Riot writes acts in roman
    numerals ("ACT II") and episodes in digits ("EPISODE 9"), so both forms
    have to resolve or the peak-rank caption falls back to raw text.
    """
    if not name:
        return ""
    digits = re.sub(r"\D", "", name)
    if digits:
        return digits
    tail = name.strip().split()[-1].lower()
    value = _ROMAN.get(tail)
    return str(value) if value else ""


def get_seasons() -> Dict[str, str]:
    """Act uuid -> readable label ("E9 A2"), for the peak-rank caption."""
    with _STATIC_LOCK:
        cached = _STATIC_CACHE.get("seasons")
    if cached:
        return cached

    data = _fetch_json("https://valorant-api.com/v1/seasons", timeout=8.0)
    entries = (data or {}).get("data", []) or []

    episodes = {
        s.get("uuid", ""): (s.get("displayName") or "")
        for s in entries if not s.get("parentUuid")
    }

    labels: Dict[str, str] = {}
    for s in entries:
        parent = s.get("parentUuid")
        name = (s.get("displayName") or "").strip()
        if not parent:
            continue
        ep = episodes.get(parent, "")
        ep_num = _season_number(ep)
        act_num = _season_number(name)
        labels[s.get("uuid", "")] = (
            f"E{ep_num} A{act_num}" if ep_num and act_num else (name or ep)
        )

    if labels:
        with _STATIC_LOCK:
            _STATIC_CACHE["seasons"] = labels
    return labels


def current_act_id() -> str:
    """
    UUID of the act (competitive season) that's live right now, picked by
    comparing the seasons feed's start/end windows against the wall clock.
    Cached for the process. Returns "" if the feed can't be reached, in which
    case callers fall back to their old best-guess behaviour.
    """
    with _STATIC_LOCK:
        cached = _STATIC_CACHE.get("current_act")
    if cached is not None:
        return cached

    data = _fetch_json("https://valorant-api.com/v1/seasons", timeout=8.0)
    entries = (data or {}).get("data", []) or []
    now = datetime.now(timezone.utc)
    found = ""
    for s in entries:
        if not s.get("parentUuid"):  # episodes have no parent; acts do
            continue
        try:
            start = datetime.fromisoformat((s.get("startTime") or "").replace("Z", "+00:00"))
            end = datetime.fromisoformat((s.get("endTime") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if start <= now < end:
            found = s.get("uuid", "") or ""
            break

    if entries:  # only cache once we actually got the feed
        with _STATIC_LOCK:
            _STATIC_CACHE["current_act"] = found
    return found


def _format_match_date(start_millis: int) -> str:
    """
    Human-readable local start time for a recent match, matching the string the
    Account-Manager path already shows (HenrikDev's `game_start_patched`), e.g.
    "Friday, August 29, 2025 5:00 PM". Returns "" when the timestamp is missing
    so callers can fall back exactly like the Account-Manager rows do.
    """
    if not start_millis:
        return ""
    try:
        dt = datetime.fromtimestamp(start_millis / 1000)
    except (OSError, OverflowError, ValueError):
        return ""
    # %-d / %#d (no-leading-zero day/hour) is platform-specific, so assemble the
    # numeric parts explicitly. Result: "Friday, August 29, 2025 5:00 PM".
    hour_12 = dt.hour % 12 or 12
    meridiem = "AM" if dt.hour < 12 else "PM"
    return f"{dt:%A, %B} {dt.day}, {dt.year} {hour_12}:{dt.minute:02d} {meridiem}"


def _parse_match(details: Dict[str, Any], puuid: str) -> Optional[Dict[str, Any]]:
    """One recent-match row, from this player's point of view."""
    info = details.get("matchInfo") or {}
    players = details.get("players") or []

    me = next((p for p in players if p.get("Subject") == puuid or p.get("subject") == puuid), None)
    if not me:
        return None

    stats = me.get("stats") or me.get("Stats") or {}
    kills = int(stats.get("kills", 0) or 0)
    deaths = int(stats.get("deaths", 0) or 0)
    assists = int(stats.get("assists", 0) or 0)
    round_results = details.get("roundResults") or []
    played_rounds = [r for r in round_results if (r.get("roundResultCode") or "").lower() != "surrendered"]
    has_surrender = any((r.get("roundResultCode") or "").lower() == "surrendered" for r in round_results)
    actual_rounds_count = len(played_rounds) if played_rounds else int(stats.get("roundsPlayed", 0) or 0)
    rounds = max(1, actual_rounds_count)

    score = int(stats.get("score", 0) or 0)

    team_id = me.get("teamId") or me.get("TeamId") or ""
    teams = details.get("teams") or []
    own = next((t for t in teams if (t.get("teamId") or t.get("TeamId") or "") == team_id), None)
    others = [t for t in teams if t is not own]

    rounds_won = rounds_lost = placement = 0

    if len(teams) == 2 and own is not None:
        other_team = others[0] if others else {}
        if has_surrender and played_rounds:
            rounds_won = sum(1 for r in played_rounds if (r.get("winningTeam") or "") == team_id)
            rounds_lost = sum(1 for r in played_rounds if (r.get("winningTeam") or "") != team_id)
        elif own.get("numPoints") is not None and other_team.get("numPoints") is not None:
            rounds_won = int(own.get("numPoints", 0) or 0)
            rounds_lost = int(other_team.get("numPoints", 0) or 0)
        else:
            rounds_won = int(own.get("roundsWon", 0) or 0)
            rounds_lost = int(other_team.get("roundsWon", 0) or 0)

        if rounds_won == rounds_lost:
            result = "Draw"
        else:
            result = "Win" if own.get("won") else "Loss"
    else:
        ranked_scores = sorted(
            (int(((p.get("stats") or {}).get("score", 0)) or 0) for p in players), reverse=True
        )
        placement = ranked_scores.index(score) + 1 if score in ranked_scores else 0
        result = "Win" if placement == 1 else "Loss"

    # Hit locations and damage per round for every participant. Keeping this
    # per-player lets the detail modal behave like an actual scoreboard rather
    # than showing only the selected account's four headline stats.
    combat_by_player: Dict[str, Dict[str, int]] = {}
    round_timeline: List[Dict[str, Any]] = []
    for rnd in played_rounds if played_rounds else round_results:
        round_timeline.append({
            "round": len(round_timeline) + 1,
            "winner": rnd.get("winningTeam") or "",
            "result": rnd.get("roundResult") or rnd.get("roundResultCode") or "",
        })
        for ps in rnd.get("playerStats") or []:
            subject = ps.get("subject") or ps.get("Subject") or ""
            totals = combat_by_player.setdefault(
                subject, {"headshots": 0, "bodyshots": 0, "legshots": 0, "damage": 0}
            )
            for dmg in ps.get("damage") or []:
                totals["headshots"] += int(dmg.get("headshots", 0) or 0)
                totals["bodyshots"] += int(dmg.get("bodyshots", 0) or 0)
                totals["legshots"] += int(dmg.get("legshots", 0) or 0)
                totals["damage"] += int(dmg.get("damage", 0) or 0)

    my_combat = combat_by_player.get(
        puuid, {"headshots": 0, "bodyshots": 0, "legshots": 0, "damage": 0}
    )
    head = my_combat["headshots"]
    body = my_combat["bodyshots"]
    leg = my_combat["legshots"]
    total_damage = my_combat["damage"]

    shots = head + body + leg
    agent = agent_by_id(me.get("characterId") or me.get("CharacterId") or "")
    adr = round(total_damage / max(1, rounds)) if rounds else 0
    hs_pct = round(head / shots * 100, 1) if shots else 0.0

    # Match-details identifies participants by PUUID. The name-service pass in
    # _enrich_roster_names replaces these placeholders with Name#TAG before
    # the payload reaches the UI; the PUUID stays as a click-through fallback.
    roster = []
    for participant in players:
        participant_stats = participant.get("stats") or participant.get("Stats") or {}
        participant_id = participant.get("subject") or participant.get("Subject") or ""
        participant_agent = agent_by_id(participant.get("characterId") or participant.get("CharacterId") or "")
        game_name = participant.get("gameName") or participant.get("name") or ""
        tag_line = participant.get("tagLine") or participant.get("tag") or ""
        riot_id = f"{game_name}#{tag_line}" if tag_line and "#" not in game_name else game_name
        participant_rounds = max(1, int(participant_stats.get("roundsPlayed", 0) or rounds))
        participant_score = int(participant_stats.get("score", 0) or 0)
        participant_combat = combat_by_player.get(
            participant_id, {"headshots": 0, "bodyshots": 0, "legshots": 0, "damage": 0}
        )
        participant_shots = (
            participant_combat["headshots"]
            + participant_combat["bodyshots"]
            + participant_combat["legshots"]
        )
        roster.append({
            "puuid": participant_id,
            "riot_id": riot_id,
            "name": game_name,
            "team": participant.get("teamId") or participant.get("TeamId") or "",
            "is_self": participant_id == puuid,
            "agent": participant_agent.get("name", ""),
            "agent_icon": participant_agent.get("icon", ""),
            "kills": int(participant_stats.get("kills", 0) or 0),
            "deaths": int(participant_stats.get("deaths", 0) or 0),
            "assists": int(participant_stats.get("assists", 0) or 0),
            "score": participant_score,
            "acs": round(participant_score / participant_rounds),
            "damage": participant_combat["damage"],
            "adr": round(participant_combat["damage"] / participant_rounds),
            "hs_pct": round(participant_combat["headshots"] / participant_shots * 100, 1)
                      if participant_shots else 0.0,
        })

    team_summaries = []
    for team in teams:
        summary_id = team.get("teamId") or team.get("TeamId") or ""
        points = team.get("numPoints")
        if points is None:
            points = team.get("roundsWon", 0)
        team_summaries.append({
            "team": summary_id,
            "rounds_won": int(points or 0),
            "won": bool(team.get("won")),
        })

    return {
        "match_id": info.get("matchId", ""),
        "map": resolve_map(info.get("mapId", "")).get("name", ""),
        "mode": MODE_LABELS.get((info.get("queueID") or "").lower(),
                                (info.get("queueID") or "").title() or "Custom"),
        "queue_id": (info.get("queueID") or "").lower(),
        "agent": agent.get("name", ""),
        "agent_icon": agent.get("icon", ""),
        "result": result,
        "surrendered": has_surrender,
        "rounds_won": rounds_won,
        "rounds_lost": rounds_lost,
        "placement": placement,
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kda": f"{kills}/{deaths}/{assists}",
        "kd": round(kills / max(1, deaths), 2),
        "acs": round(score / max(1, rounds)) if rounds else 0,
        "hs": hs_pct,
        "hs_pct": hs_pct,
        "adr": adr,
        "headshots": head,
        "bodyshots": body,
        "legshots": leg,
        "total_damage": total_damage,
        "shots": shots,
        "rounds": rounds,
        "started_at": int(info.get("gameStartMillis", 0) or 0),
        "game_date": _format_match_date(int(info.get("gameStartMillis", 0) or 0)),
        "ranked": bool(info.get("isRanked", False)),
        "teams": team_summaries,
        "round_results": round_timeline,
        "roster": roster,
    }


def _enrich_roster_names(client: "ValorantLiveClient", match: Dict[str, Any]) -> Dict[str, Any]:
    """Replace match-detail PUUID placeholders with Riot's current Name#TAG."""
    roster = match.get("roster") or []
    unresolved = [
        p.get("puuid", "") for p in roster
        if p.get("puuid") and "#" not in (p.get("riot_id") or "")
    ]
    if not unresolved:
        return match
    names = client.resolve_names(unresolved)
    for player in roster:
        riot_id = names.get(player.get("puuid", ""), "")
        if not riot_id:
            continue
        player["riot_id"] = riot_id
        player["name"] = riot_id
    return match


def _cached_match(client: "ValorantLiveClient", match_id: str,
                  use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """
    Parsed match line for an id, memoised by default.

    `use_cache=False` is for a match that is still being played: its numbers
    change every round, so serving the first answer forever would freeze the
    live scoreline at whatever it was the first time it was read.
    """
    if use_cache and match_id in _MATCH_CACHE:
        return _enrich_roster_names(client, _MATCH_CACHE[match_id])

    details = client.match_details(match_id, use_cache=use_cache)
    if not details:
        return None

    parsed = _parse_match(details, client.puuid)
    if parsed:
        parsed = _enrich_roster_names(client, parsed)
    if parsed and use_cache:
        if len(_MATCH_CACHE) > _MATCH_CACHE_MAX:
            _MATCH_CACHE.clear()
        _MATCH_CACHE[match_id] = parsed
    return parsed


def personal_match_summary(client: "ValorantLiveClient", match_id: str,
                           live: bool = False) -> Optional[Dict[str, Any]]:
    """
    This player's line for one match id - K/D/A, HS%, ADR, ACS and the round
    score. Returns None while Riot has nothing to give: match-details stays
    empty until a match has actually finished (customs, deathmatch and
    practice are the exceptions and do answer mid-match), so a miss here is
    expected, not an error.

    Pass live=True for a match still in progress so the answer is re-read
    rather than served from the cache.
    """
    if not match_id:
        return None
    try:
        return _cached_match(client, match_id, use_cache=not live)
    except Exception:
        return None


def _rank_block(tier: int, rr: int = 0, leaderboard: int = 0) -> Dict[str, Any]:
    return {
        "tier": tier,
        "label": tier_label(tier),
        "icon": tier_icon(tier),
        "rr": rr,
        "leaderboard": leaderboard,
    }


def _mmr_summary(mmr: Dict[str, Any]) -> Dict[str, Any]:
    """Current rank, peak rank and lifetime competitive record."""
    seasons = get_seasons()
    comp = ((mmr.get("QueueSkills") or {}).get("competitive") or {})
    by_season = comp.get("SeasonalInfoBySeasonID") or {}

    latest = mmr.get("LatestCompetitiveUpdate") or {}
    current_tier = int(latest.get("TierAfterUpdate", 0) or 0)
    current_rr = int(latest.get("RankedRatingAfterUpdate", 0) or 0)
    current_season = latest.get("SeasonID", "") or ""

    peak_tier, peak_season = 0, ""
    wins = games = 0
    act_wins = act_games = 0
    leaderboard = 0

    for season_id, entry in by_season.items():
        season_tier = max(
            int(entry.get("CompetitiveTier", 0) or 0),
            int(entry.get("Rank", 0) or 0),
        )
        # WinsByTier is the only record of a tier reached mid-act and then
        # dropped out of, so peak has to consider it too.
        for tier_key in (entry.get("WinsByTier") or {}):
            try:
                season_tier = max(season_tier, int(tier_key))
            except (TypeError, ValueError):
                continue

        if season_tier > peak_tier:
            peak_tier = season_tier
            peak_season = seasons.get(season_id, "")

        # During placements Riot leaves NumberOfWins at zero but still records
        # the real wins in WinsByTier (usually under tier 0).  Treating only
        # NumberOfWins as authoritative made a 2-0 act render as 0-2 and also
        # corrupted the lifetime record.
        tier_wins = 0
        for count in (entry.get("WinsByTier") or {}).values():
            try:
                tier_wins += int(count or 0)
            except (TypeError, ValueError):
                continue
        season_wins = max(int(entry.get("NumberOfWins", 0) or 0), tier_wins)
        season_games = int(entry.get("NumberOfGames", 0) or 0)

        wins += season_wins
        games += season_games

        if season_id == current_season:
            act_wins = season_wins
            act_games = season_games
            leaderboard = int(entry.get("LeaderboardRank", 0) or 0)
            if not current_tier:
                current_tier = season_tier

    return {
        "rank": _rank_block(current_tier, current_rr, leaderboard),
        "peak": dict(_rank_block(peak_tier), season=peak_season),
        "lifetime": {
            "wins": wins,
            "losses": max(games - wins, 0),
            "games": games,
            "winrate": round(wins / games * 100, 1) if games else 0.0,
        },
        "act": {
            "wins": act_wins,
            "losses": max(act_games - act_wins, 0),
            "games": act_games,
            "winrate": round(act_wins / act_games * 100, 1) if act_games else 0.0,
            "label": seasons.get(current_season, "This Act"),
        },
    }


def _form_from_updates(updates: List[Dict[str, Any]],
                       matches: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Win/loss form and the RR graph. Competitive updates carry the RR delta
    for each match, which is enough to classify the result without paying for
    a full match-details fetch per game.

    Riot returns these newest-first. The streak is read in that order, but
    both series are handed out oldest-first and over the same matches, so the
    graph and the W/L pips under it describe the same games in the same
    direction - they used to run opposite ways over different lengths.
    """
    form: List[Dict[str, Any]] = []
    rr_history: List[int] = []
    performance_history: List[int] = []
    update_by_match = {
        str(u.get("MatchID") or ""): u for u in updates if u.get("MatchID")
    }

    # Match details are the ground truth for W/L. Placement matches commonly
    # report zero RR and MOVEMENT_UNKNOWN, which the old implementation
    # mislabeled as Draw. When details are available, drive the whole form from
    # those real outcomes and graph actual match ACS instead of fake tier*100.
    ranked_matches = [m for m in (matches or []) if m.get("ranked")]
    if ranked_matches:
        for match in ranked_matches:
            update = update_by_match.get(str(match.get("match_id") or ""), {})
            form.append({
                "result": match.get("result") or "Draw",
                "rr": int(update.get("RankedRatingEarned", 0) or 0),
                "tier": int(update.get("TierAfterUpdate", 0) or 0),
                "map": match.get("map") or resolve_map(update.get("MapID", "")).get("name", ""),
                "acs": int(match.get("acs", 0) or 0),
            })
            performance_history.append(int(match.get("acs", 0) or 0))
    else:
        for u in updates:
            if not u.get("MatchID"):
                continue
            delta = int(u.get("RankedRatingEarned", 0) or 0)
            movement = (u.get("CompetitiveMovement") or "").upper()

            if movement in ("PROMOTED", "MAJOR_INCREASE", "MINOR_INCREASE"):
                result = "Win"
            elif movement in ("DEMOTED", "MAJOR_DECREASE", "MINOR_DECREASE"):
                result = "Loss"
            elif delta > 0:
                result = "Win"
            elif delta < 0:
                result = "Loss"
            else:
                result = "Draw"

            form.append({
                "result": result,
                "rr": delta,
                "tier": int(u.get("TierAfterUpdate", 0) or 0),
                "map": resolve_map(u.get("MapID", "")).get("name", ""),
            })
            rr_history.append(
                int(u.get("TierAfterUpdate", 0) or 0) * 100
                + int(u.get("RankedRatingAfterUpdate", 0) or 0)
            )

    streak, streak_type = 0, ""
    for entry in form:
        if entry["result"] == "Draw":
            break
        if not streak_type:
            streak_type = entry["result"]
        if entry["result"] != streak_type:
            break
        streak += 1

    wins = sum(1 for f in form if f["result"] == "Win")
    losses = sum(1 for f in form if f["result"] == "Loss")

    FORM_GAMES = 12
    return {
        "form": list(reversed(form[:FORM_GAMES])),
        "rr_history": list(reversed(rr_history[:FORM_GAMES])),
        "performance_history": list(reversed(performance_history[:FORM_GAMES])),
        "trend_label": "ACS trend" if performance_history else "Rank trend",
        "streak": streak,
        "streak_type": streak_type,
        "recent_wins": wins,
        "recent_losses": losses,
        "recent_winrate": round(wins / (wins + losses) * 100, 1) if (wins + losses) else 0.0,
    }


def _combat_from_matches(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not matches:
        return {
            "matches": 0, "kd": 0.0, "kda": 0.0, "hs": 0.0, "acs": 0,
            "avg_kills": 0.0, "avg_deaths": 0.0, "avg_assists": 0.0, "winrate": 0.0,
        }

    kills = sum(m["kills"] for m in matches)
    deaths = sum(m["deaths"] for m in matches)
    assists = sum(m["assists"] for m in matches)
    head = sum(m["headshots"] for m in matches)
    shots = sum(m["shots"] for m in matches)
    rounds = sum(m["rounds"] for m in matches)
    acs_total = sum(m["acs"] * m["rounds"] for m in matches)
    wins = sum(1 for m in matches if m["result"] == "Win")
    decided = sum(1 for m in matches if m["result"] in ("Win", "Loss"))
    n = len(matches)

    return {
        "matches": n,
        "kd": round(kills / deaths, 2) if deaths else float(kills),
        "kda": round((kills + assists) / deaths, 2) if deaths else float(kills + assists),
        "hs": round(head / shots * 100, 1) if shots else 0.0,
        "acs": round(acs_total / rounds) if rounds else 0,
        "avg_kills": round(kills / n, 1),
        "avg_deaths": round(deaths / n, 1),
        "avg_assists": round(assists / n, 1),
        "winrate": round(wins / decided * 100, 1) if decided else 0.0,
    }


def _top_agents(matches: List[Dict[str, Any]], limit: int = 4) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for m in matches:
        name = m["agent"] or "Unknown"
        b = buckets.setdefault(name, {
            "name": name, "icon": m["agent_icon"], "matches": 0,
            "wins": 0, "decided": 0, "kills": 0, "deaths": 0,
        })
        b["matches"] += 1
        b["kills"] += m["kills"]
        b["deaths"] += m["deaths"]
        if m["result"] in ("Win", "Loss"):
            b["decided"] += 1
            b["wins"] += 1 if m["result"] == "Win" else 0

    out = []
    for b in buckets.values():
        out.append({
            "name": b["name"],
            "icon": b["icon"],
            "matches": b["matches"],
            "winrate": round(b["wins"] / b["decided"] * 100) if b["decided"] else 0,
            "kd": round(b["kills"] / b["deaths"], 2) if b["deaths"] else float(b["kills"]),
        })
    out.sort(key=lambda x: (-x["matches"], -x["winrate"]))
    return out[:limit]


def _inventory(client: "ValorantLiveClient") -> Dict[str, Any]:
    """Equipped loadout plus the size and VP value of the owned collection."""
    meta = get_weapon_data()
    levels, skins, weapons = meta["levels"], meta["skins"], meta["weapons"]

    owned_levels = client.entitlements(ITEM_SKIN_LEVEL)
    prices = client.store_offers()

    owned_skins = {levels.get(lvl) for lvl in owned_levels if levels.get(lvl)}
    value = sum(prices.get(lvl, 0) for lvl in owned_levels)

    equipped: List[Dict[str, Any]] = []
    loadout = client.loadout()
    for gun in loadout.get("Guns", []) or []:
        weapon_name = weapons.get(gun.get("ID", ""), "")
        skin = skins.get(gun.get("SkinID", ""))
        if not weapon_name or not skin:
            continue
        equipped.append({
            "weapon": weapon_name,
            "skin": skin["name"],
            "icon": skin["icon"],
            "tier": skin["tier"],
            "tier_color": skin["tier_color"],
            "tier_icon": skin["tier_icon"],
            # A skin named after its own weapon is the default one.
            "is_default": skin["name"].lower().startswith("standard")
                          or skin["name"].lower() == weapon_name.lower(),
        })

    order = {name.lower(): i for i, name in enumerate(LOADOUT_ORDER)}
    equipped.sort(key=lambda e: order.get(e["weapon"].lower(), 99))

    return {
        "skins_owned": len(owned_skins),
        "skins_total": meta["premium_total"],
        "value_vp": value,
        "agents_owned": len(client.entitlements(ITEM_AGENT)),
        "buddies": len(client.entitlements(ITEM_BUDDY)),
        "sprays": len(client.entitlements(ITEM_SPRAY)),
        "cards": len(client.entitlements(ITEM_CARD)),
        "titles": len(client.entitlements(ITEM_TITLE)),
        "loadout": equipped,
    }


def build_player_stats(client: "ValorantLiveClient") -> Dict[str, Any]:
    """The whole profile. Every section degrades to empty on its own."""
    stats: Dict[str, Any] = {
        "available": True,
        "puuid": client.puuid,
        "updated_at": time.time(),
    }

    try:
        stats.update(_mmr_summary(client.mmr()))
    except Exception:
        stats.setdefault("rank", _rank_block(0))
        stats.setdefault("peak", dict(_rank_block(0), season=""))
        stats.setdefault("lifetime", {"wins": 0, "losses": 0, "games": 0, "winrate": 0.0})
        stats.setdefault("act", {"wins": 0, "losses": 0, "games": 0, "winrate": 0.0, "label": ""})

    updates: List[Dict[str, Any]] = []
    try:
        updates = client.competitive_updates(20)
    except Exception:
        pass

    matches: List[Dict[str, Any]] = []
    try:
        history = client.match_history(15)
        for entry in history[:MATCH_DETAIL_SAMPLE]:
            parsed = _cached_match(client, entry.get("MatchID", ""))
            if parsed:
                matches.append(parsed)
    except Exception:
        pass

    stats["recent"] = matches
    stats["combat"] = _combat_from_matches(matches)
    stats["top_agents"] = _top_agents(matches)
    stats.update(_form_from_updates(updates, matches))

    try:
        stats["inventory"] = _inventory(client)
    except Exception:
        stats["inventory"] = {
            "skins_owned": 0, "skins_total": 0, "value_vp": 0, "agents_owned": 0,
            "buddies": 0, "sprays": 0, "cards": 0, "titles": 0, "loadout": [],
        }

    return stats


def _active_session_puuid() -> str:
    """PUUID in the current lockfile-authenticated Riot session, if any."""
    lock = ValorantLiveClient.read_lockfile()
    if not lock:
        return ""
    port, password = lock
    try:
        res = requests.get(
            f"https://127.0.0.1:{port}/entitlements/v1/token",
            auth=("riot", password), verify=False, timeout=1.5,
        )
        if res.status_code == 200:
            return (res.json().get("subject") or "").strip()
    except Exception:
        pass
    return ""


def _finish_stats_build(generation: int) -> None:
    """Release the build flag only if this is still the newest worker."""
    with _STATS_LOCK:
        if _STATS_CACHE.get("generation") == generation:
            _STATS_CACHE.update({"building": False, "building_puuid": ""})


def _stats_worker(expected_puuid: str, generation: int) -> None:
    try:
        client = ValorantLiveClient()
        if not client.connect():
            _finish_stats_build(generation)
            return

        actual_puuid = (client.puuid or "").strip()
        if expected_puuid and actual_puuid != expected_puuid:
            # The account changed between scheduling this thread and reading
            # the lockfile.  Its result belongs to neither requested build.
            _finish_stats_build(generation)
            return

        data = build_player_stats(client)

        # A profile build performs several remote requests and can outlive an
        # account swap.  Re-check before publishing it.  If this probe happens
        # to fail transiently the result is still safe to retain: it remains
        # tagged with actual_puuid and get_player_stats will not serve it to an
        # unknown or different session.
        current_puuid = _active_session_puuid()
        if current_puuid and current_puuid != actual_puuid:
            _finish_stats_build(generation)
            return

        with _STATS_LOCK:
            if _STATS_CACHE.get("generation") != generation:
                return
            _STATS_CACHE.update({
                "data": data,
                "built_at": time.time(),
                "puuid": actual_puuid,
                "building": False,
                "building_puuid": "",
            })
    except Exception:
        _finish_stats_build(generation)


def get_player_stats(force: bool = False) -> Dict[str, Any]:
    """
    Cached profile, refreshed in the background. Returns immediately with
    whatever is already known plus a loading flag, so the dashboard can paint
    the panel on the first frame.
    """
    session_puuid = _active_session_puuid()
    worker_args: Optional[Tuple[str, int]] = None

    # Selection, invalidation and the build reservation are one transaction.
    # Without that, two simultaneous HTTP requests can both observe
    # building=False and start duplicate profile crawls.
    with _STATS_LOCK:
        cached_puuid = (_STATS_CACHE.get("puuid") or "").strip()
        cache_matches = bool(session_puuid and cached_puuid == session_puuid)
        data = _STATS_CACHE.get("data") if cache_matches else None
        built_at = float(_STATS_CACHE.get("built_at") or 0.0) if cache_matches else 0.0
        stale = (time.time() - built_at) > STATS_TTL

        building = bool(_STATS_CACHE.get("building"))
        building_puuid = (_STATS_CACHE.get("building_puuid") or "").strip()
        same_build = building and (
            not session_puuid or building_puuid == session_puuid
        )

        if (force or stale or data is None) and not same_build:
            generation = int(_STATS_CACHE.get("generation") or 0) + 1
            _STATS_CACHE.update({
                "generation": generation,
                "building": True,
                "building_puuid": session_puuid,
            })
            worker_args = (session_puuid, generation)
            building = True
            building_puuid = session_puuid

        loading = building and (
            not session_puuid or building_puuid == session_puuid
        )

    if worker_args is not None:
        threading.Thread(target=_stats_worker, args=worker_args, daemon=True).start()

    if data is None:
        return {"available": False, "loading": True, "message": "Reading your profile..."}

    out = dict(data)
    out["loading"] = loading
    return out


def invalidate_player_stats() -> None:
    with _STATS_LOCK:
        _STATS_CACHE.update({
            "data": None,
            "built_at": 0.0,
            "puuid": "",
            "building": False,
            "building_puuid": "",
            "generation": int(_STATS_CACHE.get("generation") or 0) + 1,
        })
