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
    {"id": "onefa", "name": "Replication", "icon": "fa-solid fa-clone", "ranked": False},
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


# --------------------------------------------------------------------------
# Static game data (agents, maps, client version), fetched once and cached.
# --------------------------------------------------------------------------

_STATIC_CACHE: Dict[str, Any] = {"agents": None, "maps": None, "version": None}
_STATIC_LOCK = threading.Lock()


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
_REGION_CACHE: Dict[str, Any] = {"region": None, "shard": None, "at": 0.0}
_REGION_TTL = 180.0


def _region_from_cache() -> Optional[Tuple[str, str]]:
    with _STATIC_LOCK:
        if _REGION_CACHE["region"] and (time.time() - _REGION_CACHE["at"]) < _REGION_TTL:
            return _REGION_CACHE["region"], _REGION_CACHE["shard"]
    return None


def _store_region_cache(region: str, shard: str) -> None:
    with _STATIC_LOCK:
        _REGION_CACHE.update({"region": region, "shard": shard, "at": time.time()})


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
        cached = _region_from_cache()
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
                    _store_region_cache(self.region, self.shard)
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

    def presence(self) -> Dict[str, Any]:
        """
        Decoded private presence payload for this account. This is where the
        live round score and the menus/pregame/ingame state live - the match
        endpoints don't expose a running score.
        """
        res = self._local("/chat/v4/presences")
        if not res or res.status_code != 200:
            return {}

        try:
            for p in res.json().get("presences", []) or []:
                if p.get("puuid") != self.puuid:
                    continue
                raw = p.get("private")
                if not raw:
                    return {}
                return json.loads(base64.b64decode(raw).decode("utf-8", errors="ignore"))
        except Exception:
            pass
        return {}

    # -- names -----------------------------------------------------------

    def resolve_names(self, puuids: List[str]) -> Dict[str, str]:
        if not puuids:
            return {}
        try:
            res = self._remote("PUT", f"{self.pd}/name-service/v2/players", puuids, timeout=6.0)
            if res.status_code != 200:
                return {}
            return {
                e.get("Subject", ""): f"{e.get('GameName', '')}#{e.get('TagLine', '')}"
                for e in res.json()
            }
        except Exception:
            return {}

    # -- party / queue ---------------------------------------------------

    def party_id(self) -> Optional[str]:
        res = self._remote("GET", f"{self.glz}/parties/v1/players/{self.puuid}", timeout=4.0)
        if res.status_code != 200:
            return None
        return res.json().get("CurrentPartyID")

    def party(self) -> Dict[str, Any]:
        pid = self.party_id()
        if not pid:
            return {}
        res = self._remote("GET", f"{self.glz}/parties/v1/parties/{pid}")
        if res.status_code != 200:
            return {}
        return res.json()

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

    def select_agent(self, agent_id: str, match_id: Optional[str] = None) -> bool:
        match_id = match_id or self.pregame_match_id()
        if not match_id:
            return False
        res = self._remote(
            "POST", f"{self.glz}/pregame/v1/matches/{match_id}/select/{agent_id}", timeout=3.0
        )
        return res.status_code == 200

    def lock_agent(self, agent_id: str, match_id: Optional[str] = None) -> bool:
        match_id = match_id or self.pregame_match_id()
        if not match_id:
            return False
        res = self._remote(
            "POST", f"{self.glz}/pregame/v1/matches/{match_id}/lock/{agent_id}", timeout=3.0
        )
        return res.status_code == 200

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
        res = self._remote("GET", f"{self.pd}/mmr/v1/players/{self.puuid}", timeout=6.0)
        if res.status_code != 200:
            return {}
        return res.json()

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

    def match_details(self, match_id: str) -> Dict[str, Any]:
        res = self._remote("GET", f"{self.pd}/match-details/v1/matches/{match_id}", timeout=15.0)
        if res.status_code != 200:
            return {}
        try:
            return res.json()
        except Exception:
            return {}

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
# accepts a pick. Firing the instant the match id appears is what leaves the
# character half-selected and unchangeable, so the watcher waits for the
# pregame phase to report itself active and then gives the client a further
# grace period before touching anything.
INSTALOCK_READY_TIMEOUT = 15.0   # max wait for character_select_active
INSTALOCK_SETTLE = 1.6           # grace once the phase is actually open
INSTALOCK_SELECT_HOLD = 0.9      # gap between selecting and locking
INSTALOCK_ATTEMPTS = 6


def _pregame_self(match: Dict[str, Any], puuid: str) -> Dict[str, Any]:
    """Our own entry in a pregame match payload."""
    for p in (match.get("AllyTeam") or {}).get("Players", []) or []:
        if p.get("Subject") == puuid:
            return p
    return {}


def _wait_for_agent_select(client: "ValorantLiveClient", match_id: str) -> Dict[str, Any]:
    """
    Blocks until the client reports agent select is genuinely open (or the
    wait times out). Returns the last pregame payload seen.
    """
    deadline = time.time() + INSTALOCK_READY_TIMEOUT
    match: Dict[str, Any] = {}

    while time.time() < deadline and not _instalock_stop.is_set():
        try:
            match = client.pregame_match(match_id)
        except LiveClientError:
            match = {}

        phase = (match.get("PregameState") or "").lower()
        # "character_select_active" is the only state that accepts a pick -
        # "provisioned" means the server is still handing the match out.
        if phase == "character_select_active":
            break
        if phase and phase != "provisioned":
            break
        _instalock_stop.wait(0.3)

    _instalock_stop.wait(INSTALOCK_SETTLE)
    return match


def _instalock_worker():
    """
    Polls pregame at a tight interval while armed. The poll only hits the
    account's own pregame endpoint, and only while the user has explicitly
    turned it on from the dashboard.
    """
    handled_matches = set()
    client: Optional[ValorantLiveClient] = None
    connected_at = 0.0

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
            INSTALOCK["status"] = "waiting"
            INSTALOCK["last_match_id"] = match_id
            INSTALOCK["message"] = "Agent select found - waiting for the client..."

        _wait_for_agent_select(client, match_id)
        if _instalock_stop.is_set():
            break

        with _INSTALOCK_LOCK:
            INSTALOCK["status"] = "locking"
            INSTALOCK["message"] = f"Locking {agent_name}..."

        locked = False
        selected = False
        for attempt in range(INSTALOCK_ATTEMPTS):
            if _instalock_stop.is_set():
                break
            try:
                # Select and lock are two separate calls on purpose: sending
                # them back to back is what the client chokes on, so the pick
                # is allowed to register before the lock goes out.
                if not selected:
                    selected = client.select_agent(agent_id, match_id)
                    _instalock_stop.wait(INSTALOCK_SELECT_HOLD)

                if client.lock_agent(agent_id, match_id):
                    locked = True
                    break

                # The lock call can come back OK-looking while the client is
                # still catching up, so the pregame state is the real answer.
                state = _pregame_self(client.pregame_match(match_id), client.puuid)
                if (state.get("CharacterSelectionState") or "").lower() == "locked":
                    locked = True
                    break
            except LiveClientError:
                pass

            selected = False
            _instalock_stop.wait(0.45 + attempt * 0.2)

        handled_matches.add(match_id)
        with _INSTALOCK_LOCK:
            if locked:
                INSTALOCK["status"] = "locked"
                INSTALOCK["message"] = f"Locked {agent_name}."
                INSTALOCK["locked_at"] = time.time()
            else:
                INSTALOCK["status"] = "failed"
                INSTALOCK["message"] = f"Couldn't lock {agent_name} - it may already be taken."

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
    for image in ("VALORANT.exe", "VALORANT-Win64-Shipping.exe"):
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                capture_output=True, text=True, shell=True, timeout=8
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

_STATS_CACHE: Dict[str, Any] = {"data": None, "built_at": 0.0, "puuid": "", "building": False}
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
        ep_num = re.sub(r"\D", "", ep) or ""
        act_num = re.sub(r"\D", "", name) or ""
        labels[s.get("uuid", "")] = (
            f"E{ep_num} A{act_num}" if ep_num and act_num else (name or ep)
        )

    if labels:
        with _STATIC_LOCK:
            _STATIC_CACHE["seasons"] = labels
    return labels


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
    rounds = int(stats.get("roundsPlayed", 0) or 0)
    score = int(stats.get("score", 0) or 0)

    team_id = me.get("teamId") or me.get("TeamId") or ""
    own = enemy = None
    for t in details.get("teams") or []:
        tid = t.get("teamId") or t.get("TeamId") or ""
        if tid == team_id:
            own = t
        else:
            enemy = t

    rounds_won = int((own or {}).get("roundsWon", 0) or 0)
    rounds_lost = int((enemy or {}).get("roundsWon", 0) or 0)
    won = bool((own or {}).get("won", False))

    if own is None:
        # Deathmatch and friends have no meaningful team - rank by score.
        ranked_scores = sorted(
            (int(((p.get("stats") or {}).get("score", 0)) or 0) for p in players), reverse=True
        )
        placement = ranked_scores.index(score) + 1 if score in ranked_scores else 0
        won = placement == 1
        result = "Win" if won else "Loss"
    elif rounds_won == rounds_lost:
        result = "Draw"
    else:
        result = "Win" if won else "Loss"

    # Hit locations only exist per round, which is also how trackers do it.
    head = body = leg = 0
    for rnd in details.get("roundResults") or []:
        for ps in rnd.get("playerStats") or []:
            if ps.get("subject") != puuid:
                continue
            for dmg in ps.get("damage") or []:
                head += int(dmg.get("headshots", 0) or 0)
                body += int(dmg.get("bodyshots", 0) or 0)
                leg += int(dmg.get("legshots", 0) or 0)

    shots = head + body + leg
    agent = agent_by_id(me.get("characterId") or me.get("CharacterId") or "")

    return {
        "match_id": info.get("matchId", ""),
        "map": resolve_map(info.get("mapId", "")).get("name", ""),
        "mode": MODE_LABELS.get((info.get("queueID") or "").lower(),
                                (info.get("queueID") or "").title() or "Custom"),
        "queue_id": (info.get("queueID") or "").lower(),
        "agent": agent.get("name", ""),
        "agent_icon": agent.get("icon", ""),
        "result": result,
        "rounds_won": rounds_won,
        "rounds_lost": rounds_lost,
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kd": round(kills / deaths, 2) if deaths else float(kills),
        "acs": round(score / rounds) if rounds else 0,
        "hs": round(head / shots * 100, 1) if shots else 0.0,
        "headshots": head,
        "shots": shots,
        "rounds": rounds,
        "started_at": int(info.get("gameStartMillis", 0) or 0),
        "ranked": bool(info.get("isRanked", False)),
    }


def _cached_match(client: "ValorantLiveClient", match_id: str) -> Optional[Dict[str, Any]]:
    if match_id in _MATCH_CACHE:
        return _MATCH_CACHE[match_id]

    details = client.match_details(match_id)
    if not details:
        return None

    parsed = _parse_match(details, client.puuid)
    if parsed:
        if len(_MATCH_CACHE) > _MATCH_CACHE_MAX:
            _MATCH_CACHE.clear()
        _MATCH_CACHE[match_id] = parsed
    return parsed


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

        wins += int(entry.get("NumberOfWins", 0) or 0)
        games += int(entry.get("NumberOfGames", 0) or 0)

        if season_id == current_season:
            act_wins = int(entry.get("NumberOfWins", 0) or 0)
            act_games = int(entry.get("NumberOfGames", 0) or 0)
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


def _form_from_updates(updates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Win/loss form and the RR graph. Competitive updates carry the RR delta
    for each match, which is enough to classify the result without paying for
    a full match-details fetch per game.
    """
    form: List[Dict[str, Any]] = []
    rr_history: List[int] = []

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
        rr_history.append(int(u.get("RankedRatingAfterUpdate", 0) or 0))

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

    return {
        "form": form[:12],
        "rr_history": list(reversed(rr_history[:15])),
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

    try:
        stats.update(_form_from_updates(client.competitive_updates(20)))
    except Exception:
        stats.setdefault("form", [])
        stats.setdefault("rr_history", [])
        stats.setdefault("streak", 0)
        stats.setdefault("streak_type", "")

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

    try:
        stats["inventory"] = _inventory(client)
    except Exception:
        stats["inventory"] = {
            "skins_owned": 0, "skins_total": 0, "value_vp": 0, "agents_owned": 0,
            "buddies": 0, "sprays": 0, "cards": 0, "titles": 0, "loadout": [],
        }

    return stats


def _stats_worker(force_puuid: str) -> None:
    try:
        client = ValorantLiveClient()
        if not client.connect():
            with _STATS_LOCK:
                _STATS_CACHE["building"] = False
            return

        data = build_player_stats(client)
        with _STATS_LOCK:
            _STATS_CACHE.update({
                "data": data, "built_at": time.time(),
                "puuid": client.puuid, "building": False,
            })
    except Exception:
        with _STATS_LOCK:
            _STATS_CACHE["building"] = False


def get_player_stats(force: bool = False) -> Dict[str, Any]:
    """
    Cached profile, refreshed in the background. Returns immediately with
    whatever is already known plus a loading flag, so the dashboard can paint
    the panel on the first frame.
    """
    with _STATS_LOCK:
        data = _STATS_CACHE["data"]
        built_at = _STATS_CACHE["built_at"]
        building = _STATS_CACHE["building"]

    stale = (time.time() - built_at) > STATS_TTL
    if (force or stale or data is None) and not building:
        with _STATS_LOCK:
            _STATS_CACHE["building"] = True
        threading.Thread(target=_stats_worker, args=("",), daemon=True).start()
        building = True

    if data is None:
        return {"available": False, "loading": True, "message": "Reading your profile..."}

    out = dict(data)
    out["loading"] = building
    return out


def invalidate_player_stats() -> None:
    with _STATS_LOCK:
        _STATS_CACHE.update({"data": None, "built_at": 0.0})
