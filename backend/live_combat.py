"""Read exact live VALORANT combat data from Overwolf's first-party GEP log.

Riot's local core-game endpoint exposes the live roster but not its scoreboard,
and match-details normally stays empty until the game ends. Overwolf's official
VALORANT Game Events Provider (GEP) writes a log while you play that carries
your own running kills/deaths/assists/headshots, a per-round hit report, and a
kill feed. This module tails that log - no game memory, no injected input, no
scraping another app's UI.

What GEP actually gives us (verified against real logs):
  featureName "kill"       key "kills" / "assists" / "headshots"  -> your totals
  featureName "death"      key "deaths"                           -> your total
  featureName "me"         key "player_name"                      -> "Name#Tag"
  featureName "match_info" key "match_id"                         -> match uuid
  featureName "match_info" key "round_report"  (JSON string)      -> your round
  featureName "match_info" key "kill_feed"     (JSON string)      -> one kill

There is NO full live scoreboard for other players. Their kills/deaths are
rebuilt from the kill feed by game name, which is best-effort: it misses kills
that happened before Overwolf attached and can't see assists for anyone but
you. The local player shows in the feed under a client-locale token
("自分", "You", ...), so their numbers always come from the exact "kill" /
"death" totals instead.
"""

from __future__ import annotations

import glob
import json
import os
import re
import threading
import time
from typing import Any, Dict, List

_INFO_RE = re.compile(r"\[GEP\] info update\s+(\{.*\})\s*$")
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
    """Stateful tailer for Overwolf's current VALORANT GEP session."""

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

    def _log_dir(self) -> str:
        if self._log_dir_override:
            return self._log_dir_override
        return os.path.join(
            os.getenv("LOCALAPPDATA") or "", "Overwolf", "Log", "Apps",
            "Overwolf General GameEvents Provider",
        )

    def _files(self) -> List[str]:
        now = time.time()
        fresh = []
        for path in glob.glob(os.path.join(self._log_dir(), "index.html*.log")):
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
        self._clear_match_state()

    def _clear_match_state(self) -> None:
        self._local = {"kills": None, "deaths": None, "assists": None, "headshot_kills": None}
        self._feed = {}
        self._round_reports = []
        self._latest_event_at = 0.0

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
            now_active = str(value or "").lower() == wanted_match.lower()
            if now_active and not self._active:
                # Entering our match - drop anything gathered from an earlier
                # match still sitting in the same log file.
                self._clear_match_state()
            self._active = now_active
            return

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
        found = _INFO_RE.search(line)
        if not found:
            return
        try:
            payload = json.loads(found.group(1))
        except (TypeError, ValueError):
            return
        if isinstance(payload, dict):
            self._consume_update(payload, wanted_match)

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
            files = self._read_updates(match_id)

            provider_mtime = 0.0
            for path in files:
                try:
                    provider_mtime = max(provider_mtime, os.path.getmtime(path))
                except OSError:
                    pass
            provider_fresh = bool(provider_mtime and time.time() - provider_mtime <= _FRESH_PROVIDER_AGE)

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

            if not files:
                reason = "Setting up the live combat provider (Overwolf + Valorant Tracker) - this installs itself in the background and works from your next match."
            elif not provider_fresh:
                reason = "Valorant Tracker is installing / warming up - live K/D/A, HS% and ADR start from your next match."
            elif not self._active:
                reason = "Waiting for the live provider to attach to this match."
            else:
                reason = ""

            return {
                "available": available,
                "provider": "overwolf_gep",
                "source": "overwolf_gep",
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
