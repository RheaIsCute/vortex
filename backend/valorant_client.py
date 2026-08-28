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
    "status": "idle",       # idle | armed | locking | locked | failed
    "message": "",
    "last_match_id": "",
    "locked_at": 0.0,
}

_INSTALOCK_LOCK = threading.Lock()
_instalock_thread: Optional[threading.Thread] = None
_instalock_stop = threading.Event()


def _instalock_worker():
    """
    Polls pregame at a tight interval while armed. The poll only hits the
    account's own pregame endpoint, and only while the user has explicitly
    armed it from the dashboard.
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
            INSTALOCK["status"] = "locking"
            INSTALOCK["last_match_id"] = match_id
            INSTALOCK["message"] = f"Agent select found - locking {agent_name}..."

        locked = False
        for _ in range(12):
            if _instalock_stop.is_set():
                break
            try:
                client.select_agent(agent_id, match_id)
                if client.lock_agent(agent_id, match_id):
                    locked = True
                    break
            except LiveClientError:
                pass
            _instalock_stop.wait(0.25)

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
                INSTALOCK["status"] = "armed"
                INSTALOCK["message"] = f"Armed - {agent_name} locks at agent select."

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
            "status": "armed",
            "message": f"Armed - {agent_name} locks at agent select.",
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
# --------------------------------------------------------------------------

def launch_valorant(client_path: str) -> bool:
    """Starts VALORANT through the Riot Client for the current session."""
    if not client_path or not os.path.exists(client_path):
        return False
    try:
        subprocess.Popen(
            [client_path, "--launch-product=valorant", "--launch-patchline=live"],
            shell=False
        )
        return True
    except Exception:
        return False
