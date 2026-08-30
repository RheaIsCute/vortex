"""Consume live VALORANT combat data from Overwolf's Game Events Provider (GEP).

Riot's local core-game endpoint exposes the live roster but not its scoreboard,
and match-details normally stays empty until the game ends. Overwolf's GEP
gives a player's own running kills/deaths/assists/headshots, per-round hit
report, and the kill feed. There is no game-memory access, input injection, or
screen scraping.

Two providers feed this tracker:

  * Vortex Telemetry - the hidden Overwolf companion POSTs normalized events
    straight to the backend (the `ingest()` path). Manual sideload for now.
  * The Valorant Tracker Overwolf app - already installed by many users. It
    logs every GEP update it receives to
    %LOCALAPPDATA%\\Overwolf\\Log\\Apps\\Valorant Tracker\\background.html*.log,
    which this module tails.

The Valorant Tracker log format (verified against real logs, Aug 2026):
  ...| Info Update] {"info": {<feature>: {<key>: <value>}}, "feature": "<f>"}
    kill / kills, kill / headshots (headshot KILLS), kill / assists  -> totals
    death / deaths                                                   -> total
    match_info / matchId                                             -> uuid
    match_info / round_report  (JSON string)                         -> a round
    match_info / kill_feed     (JSON string)                         -> one kill
    match_info / roster_N      (JSON string {"name","player_id",...}) -> roster
    me / playerId                                                    -> our puuid

(Older Overwolf builds wrote a flat `[GEP] info update {featureName,key,value}`
line to a shared "Overwolf General GameEvents Provider" log. Newer builds don't
populate that log with match data at all, so both the old and new shapes are
normalized here and both log locations are scanned.)

There is NO full live scoreboard for other players. Their kills/deaths are
rebuilt from the kill feed by game name, which is best-effort: it misses kills
that happened before Overwolf attached and can't see assists for anyone but
you. The local player is identified from the roster entry whose player_id
matches me/playerId, so their numbers always come from the exact "kill" /
"death" totals instead of the feed.
"""

from __future__ import annotations

import glob
import json
import os
import re
import threading
import time
from typing import Any, Dict, List

# Old shared-provider line: [GEP] info update {"featureName":..,"key":..,"value":..}
_INFO_RE = re.compile(r"\[GEP\] info update\s+(\{.*\})\s*$")
# New Valorant Tracker line: ...| Info Update] {"info":{..},"feature":".."}
_VT_INFO_RE = re.compile(r"Info Update\]\s+(\{.*\})\s*$")
_MAX_LOG_AGE = 12 * 60 * 60
_FRESH_PROVIDER_AGE = 90


def _json_value(value: Any) -> Any:
    """GEP nests some payloads (round_report, kill_feed) as JSON strings."""
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _blank_scoreline() -> Dict[str, int]:
    return {"kills": 0, "deaths": 0, "headshots": 0}


def _hs_pct(head_shots: int, total_shots: int, hs_kills, kills):
    """Headshot percentage for the HUD.

    Overwolf GEP gives no true per-shot hit location for non-killing hits
    (round_report.headshot is stuck at 0), so real aim accuracy isn't
    available. What IS reliable is headshot KILLS (feature "kill", key
    "headshots"), so the HUD shows the headshot-kill rate. If a future GEP
    build starts populating the per-shot count (more headshots seen than
    there were headshot kills), use that real ratio instead.
    """
    hs_kills = int(hs_kills or 0)
    kills = int(kills or 0)
    if total_shots and head_shots > hs_kills:
        return round(head_shots / total_shots * 100, 1)
    if kills:
        return round(hs_kills / kills * 100, 1)
    return None


class LiveCombatTracker:
    """Stateful receiver for Vortex Telemetry's current VALORANT GEP session."""

    def __init__(self, log_dir: str = "") -> None:
        self._lock = threading.Lock()
        self._log_dir_override = log_dir
        self._match_id = ""
        self._active = False
        self._offsets: Dict[str, int] = {}
        self._local_name = ""
        self._local = {"kills": None, "deaths": None, "assists": None, "headshot_kills": None}
        self._feed: Dict[str, Dict[str, int]] = {}
        self._round_reports: List[Dict[str, Any]] = []
        self._latest_event_at = 0.0
        self._direct_match_id = ""
        self._direct_last_event_at = 0.0
        # me/playerId (our puuid) and roster_N entries, used to work out which
        # kill-feed game name is us in the new Valorant Tracker log format.
        self._my_puuid = ""
        self._roster: Dict[str, str] = {}  # player_id -> "Name #TAG"
        self._last_seen_match_id = ""

    def _log_dirs(self) -> List[str]:
        if self._log_dir_override:
            return [self._log_dir_override]
        base = os.path.join(os.getenv("LOCALAPPDATA") or "", "Overwolf", "Log", "Apps")
        return [
            # New: the Valorant Tracker app logs every GEP update it receives.
            os.path.join(base, "Valorant Tracker"),
            # Old: the shared provider log (no match data on newer Overwolf).
            os.path.join(base, "Overwolf General GameEvents Provider"),
        ]

    def _files(self) -> List[str]:
        now = time.time()
        fresh = []
        for d in self._log_dirs():
            for pattern in ("background.html*.log", "index.html*.log"):
                for path in glob.glob(os.path.join(d, pattern)):
                    try:
                        if now - os.path.getmtime(path) <= _MAX_LOG_AGE:
                            fresh.append(path)
                    except OSError:
                        continue
        return sorted(fresh, key=lambda p: (os.path.getmtime(p), p))

    def _reset(self, match_id: str) -> None:
        self._match_id = match_id
        self._active = False
        self._offsets = {}
        self._last_seen_match_id = ""
        self._clear_match_state()

    def _clear_match_state(self) -> None:
        self._local = {"kills": None, "deaths": None, "assists": None, "headshot_kills": None}
        self._feed = {}
        self._round_reports = []
        self._latest_event_at = 0.0
        # Roster is per-match; our puuid and resolved name carry over so the
        # feed can still be attributed before this match's roster_N lines land.
        self._roster = {}

    def ingest(self, payload: Dict[str, Any], match_id: str) -> bool:
        """Accept one normalized GEP update from the hidden Vortex companion."""
        if not isinstance(payload, dict) or not match_id:
            return False
        with self._lock:
            if self._match_id != match_id:
                self._reset(match_id)
            self._direct_match_id = match_id
            self._direct_last_event_at = time.time()
            self._consume_update(payload, match_id)
        return True

    def _feed_for(self, name: str) -> Dict[str, int]:
        return self._feed.setdefault(name, _blank_scoreline())

    def _consume_kill_feed(self, kf: Dict[str, Any]) -> None:
        # assist1..4 hold agent icon asset names, not players, so kill-feed
        # scorelines are kills/deaths/headshots only.
        attacker = str(kf.get("attacker") or "").strip().lower()
        victim = str(kf.get("victim") or "").strip().lower()
        if attacker:
            line = self._feed_for(attacker)
            line["kills"] += 1
            if kf.get("headshot"):
                line["headshots"] += 1
        if victim:
            self._feed_for(victim)["deaths"] += 1

    def _consume_update(self, payload: Dict[str, Any], wanted_match: str) -> None:
        feature = str(payload.get("featureName") or "")
        key = str(payload.get("key") or "")
        value = _json_value(payload.get("value"))

        if feature == "me" and key == "player_name" and value:
            self._local_name = str(value)
            return

        if feature == "match_info" and key == "match_id":
            seen = str(value or "").lower()
            self._last_seen_match_id = seen
            now_active = seen == wanted_match.lower()
            if now_active != self._active:
                # Crossing a match boundary either way - drop anything gathered
                # for a different match sitting in the same log file.
                self._clear_match_state()
            self._active = now_active
            return

        if not self._active:
            # The match-id line is emitted once, at match start. If the log was
            # opened mid-match (Vortex launched late, or the log rotated) we
            # never saw it - but combat events for a match we're being asked
            # about are proof enough. Only adopt this when nothing has told us
            # we're looking at a different match.
            combat = (
                (feature in ("kill", "death"))
                or (feature == "match_info" and key in ("round_report", "kill_feed"))
            )
            if combat and wanted_match and not self._last_seen_match_id:
                self._active = True
            if not self._active:
                return
        self._latest_event_at = time.time()

        if feature == "kill" and key in ("kills", "assists", "headshots"):
            self._local["headshot_kills" if key == "headshots" else key] = int(value or 0)
            return
        if feature == "death" and key == "deaths":
            self._local["deaths"] = int(value or 0)
            return

        if feature == "match_info" and key == "round_report" and isinstance(value, dict):
            def _num(v):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return 0
            head = _num(value.get("headshot")) + _num(value.get("final_headshot"))
            body = _num(value.get("bodyshots"))
            leg = _num(value.get("legshots"))
            hits = _num(value.get("hit"))
            # GEP's per-location counts are the shaky part - the "headshot" key
            # is often stuck at 0 while "hit" is right. If the parts don't add
            # up to the reported hit count, trust `hit` and treat the shortfall
            # as body shots so the ratio stays sane.
            if hits and head + body + leg != hits:
                body = max(0, hits - head - leg)
            self._round_reports.append({
                "damage": float(value.get("damage") or 0),
                "headshots": head,
                "bodyshots": body,
                "legshots": leg,
                "hits": hits or (head + body + leg),
                # cumulative kill/headshot-kill totals as of this round, so the
                # trace can plot a rolling headshot-kill rate
                "cum_kills": int(self._local["kills"] or 0),
                "cum_hs_kills": int(self._local["headshot_kills"] or 0),
            })
            return

        if feature == "match_info" and key == "kill_feed" and isinstance(value, dict):
            self._consume_kill_feed(value)

    def _consume_line(self, line: str, wanted_match: str) -> None:
        # Old flat shape: {"featureName":"kill","key":"kills","value":"19"}
        found = _INFO_RE.search(line)
        if found:
            try:
                payload = json.loads(found.group(1))
            except (TypeError, ValueError):
                return
            if isinstance(payload, dict):
                self._consume_update(payload, wanted_match)
            return

        # New Valorant Tracker shape:
        #   {"info": {"kill": {"kills": "19"}}, "feature": "kill"}
        found = _VT_INFO_RE.search(line)
        if not found:
            return
        try:
            wrapper = json.loads(found.group(1))
        except (TypeError, ValueError):
            return
        if not isinstance(wrapper, dict):
            return
        info = wrapper.get("info")
        if not isinstance(info, dict):
            return
        for feature, kv in info.items():
            if not isinstance(kv, dict):
                continue
            for key, value in kv.items():
                self._consume_vt_pair(str(feature), str(key), value, wanted_match)

    def _consume_vt_pair(self, feature: str, key: str, value: Any,
                         wanted_match: str) -> None:
        """One (feature, key, value) from the new nested log format."""
        # Learn who we are: me/playerId is our puuid; roster_N carries every
        # player's id + "Name #TAG". Once both are known, the roster entry that
        # matches our puuid tells us our own kill-feed game name.
        if feature == "me" and key == "playerId" and value:
            self._my_puuid = str(value).lower()
            self._resolve_local_name()
            return
        if feature == "match_info" and key.startswith("roster_"):
            entry = _json_value(value)
            if isinstance(entry, dict):
                pid = str(entry.get("player_id") or entry.get("playerId") or "").lower()
                name = str(entry.get("name") or "").replace(" #", "#").strip()
                if pid and name:
                    self._roster[pid] = name
                    self._resolve_local_name()
            return
        if feature == "match_info" and key.startswith("player_"):
            entry = _json_value(value)
            if isinstance(entry, dict):
                pid = str(entry.get("playerId") or entry.get("player_id") or "").lower()
                if pid and entry.get("isLocal"):
                    self._my_puuid = pid
                name = str(entry.get("playerName") or "").replace(" #", "#").strip()
                if pid and name and name.lower() not in ("null", "none"):
                    self._roster[pid] = name
                self._resolve_local_name()
            return

        # Normalize the rest onto the flat shape _consume_update already knows.
        if feature == "match_info" and key == "matchId":
            self._consume_update(
                {"featureName": "match_info", "key": "match_id", "value": value},
                wanted_match,
            )
            return
        if feature == "kill" and key in ("kills", "assists", "headshots"):
            self._consume_update(
                {"featureName": "kill", "key": key, "value": value}, wanted_match
            )
            return
        if feature == "death" and key == "deaths":
            self._consume_update(
                {"featureName": "death", "key": "deaths", "value": value}, wanted_match
            )
            return
        if feature == "match_info" and key in ("round_report", "kill_feed"):
            self._consume_update(
                {"featureName": "match_info", "key": key, "value": value}, wanted_match
            )
            return

    def _resolve_local_name(self) -> None:
        if self._local_name or not self._my_puuid:
            return
        name = self._roster.get(self._my_puuid)
        if name:
            self._local_name = name

    def _read_updates(self, wanted_match: str) -> List[str]:
        files = self._files()
        live_set = set(files)
        self._offsets = {p: n for p, n in self._offsets.items() if p in live_set}
        for path in files:
            try:
                size = os.path.getsize(path)
                offset = self._offsets.get(path, 0)
                if size < offset:
                    offset = 0
                if size == offset:
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    handle.seek(offset)
                    for line in handle:
                        self._consume_line(line, wanted_match)
                    self._offsets[path] = handle.tell()
            except OSError:
                continue
        return files

    def _players_payload(self) -> Dict[str, Dict[str, Any]]:
        """Kill-feed scorelines keyed by lowercase game name (no tag)."""
        local_key = self._local_name.split("#")[0].strip().lower()
        out: Dict[str, Dict[str, Any]] = {}
        for name, line in self._feed.items():
            if name == local_key:
                continue  # local player is the exact-totals path, not the feed
            out[name] = {
                "available": True,
                "kills": line["kills"],
                "deaths": line["deaths"],
                "headshots": line["headshots"],
            }
        return out

    def snapshot(self, match_id: str) -> Dict[str, object]:
        """Current-game local combat totals plus a best-effort kill-feed scoreboard."""
        if not match_id:
            return {"available": False, "provider": "overwolf_gep"}

        with self._lock:
            if self._match_id != match_id:
                self._reset(match_id)
            direct_fresh = bool(
                self._direct_match_id.lower() == match_id.lower()
                and time.time() - self._direct_last_event_at <= _FRESH_PROVIDER_AGE
            )
            # Do not mix Vortex Telemetry with stale Valorant Tracker logs.
            files = [] if direct_fresh else self._read_updates(match_id)

            provider_mtime = 0.0
            for path in files:
                try:
                    provider_mtime = max(provider_mtime, os.path.getmtime(path))
                except OSError:
                    pass
            log_provider_fresh = bool(provider_mtime and time.time() - provider_mtime <= _FRESH_PROVIDER_AGE)
            provider_fresh = direct_fresh or log_provider_fresh

            kills = self._local["kills"]
            deaths = self._local["deaths"]
            assists = self._local["assists"]
            hs_kills = self._local["headshot_kills"]

            damage = round(sum(r["damage"] for r in self._round_reports))
            head = sum(r["headshots"] for r in self._round_reports)
            body = sum(r["bodyshots"] for r in self._round_reports)
            leg = sum(r["legshots"] for r in self._round_reports)
            hits = sum(r.get("hits", 0) for r in self._round_reports)
            shots = head + body + leg
            observed_rounds = len(self._round_reports)

            players = self._players_payload()

            # GEP only emits a "kill"/"death" update once you actually score, so
            # a fresh match reads as None/None. Once a round has been reported
            # you are demonstrably in the game, so unscored totals are really 0.
            if observed_rounds > 0:
                kills = int(kills or 0)
                deaths = int(deaths or 0)
                assists = int(assists or 0)
            have_local = kills is not None or deaths is not None
            available = bool(self._active and (have_local or players))

            if direct_fresh:
                reason = "" if self._active else "Waiting for Vortex Telemetry to attach to this match."
            elif not files:
                reason = "Waiting for Overwolf. Open the Valorant Tracker app (or start Vortex Telemetry) before a match."
            elif not provider_fresh:
                reason = "Overwolf's live game events look stale - is the Valorant Tracker app running?"
            elif not self._active:
                reason = "Waiting for the live match to start..."
            else:
                reason = ""

            return {
                "available": available,
                "provider": "vortex_telemetry" if direct_fresh else "overwolf_gep",
                "source": "vortex_telemetry" if direct_fresh else "overwolf_gep",
                "provider_fresh": provider_fresh,
                "reason": reason,
                "players": players,
                "kills": int(kills) if kills is not None else None,
                "deaths": int(deaths) if deaths is not None else None,
                "assists": int(assists) if assists is not None else None,
                "headshot_kills": int(hs_kills or 0),
                "headshot_kill_pct": (
                    round(int(hs_kills or 0) / max(1, int(kills or 0)) * 100, 1)
                    if kills is not None else None
                ),
                "headshots": head,
                "bodyshots": body,
                "legshots": leg,
                "shots": shots,
                # HS% shown on the HUD. GEP's per-shot headshot count is often
                # stuck at 0 while headshot KILLS (feature "kill" key
                # "headshots") are reliable, so prefer the headshot-kill rate
                # and only fall back to the shot breakdown when it looks real
                # (some headshots recorded on more shots than kills).
                "hs_pct": _hs_pct(head, shots, hs_kills, kills),
                "damage": damage,
                "rounds_observed": observed_rounds,
                "adr": round(damage / observed_rounds) if observed_rounds else None,
                "acs": None,
                # Per-round trace for the HUD aim graph: a rolling headshot %
                # up to and including each round, so the line is smooth and
                # trends rather than spiking 0/33/0 on GEP's shaky per-round
                # headshot counts.
                "accuracy_history": self._rolling_hs_history(),
            }

    def _rolling_hs_history(self) -> List[Dict[str, Any]]:
        """Per-round trace for the HUD aim graph: the rolling headshot % up to
        and including each round. Uses the real shot breakdown when GEP gives
        one, otherwise the rolling headshot-kill rate (same fallback as the
        headline number)."""
        out: List[Dict[str, Any]] = []
        h = b = leg = 0
        for r in self._round_reports:
            h += r["headshots"]
            b += r["bodyshots"]
            leg += r["legshots"]
            total = h + b + leg
            cum_kills = r.get("cum_kills", 0)
            cum_hs_kills = r.get("cum_hs_kills", 0)
            pct = _hs_pct(h, total, cum_hs_kills, cum_kills)
            out.append({
                "headshots": h,
                "bodyshots": b,
                "legshots": leg,
                "hs_pct": pct if pct is not None else 0.0,
            })
        return out[-12:]
