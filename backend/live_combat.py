"""Read-only, best-effort live combat events from VALORANT's own game log.

Riot's match-details endpoint often withholds combat totals until the match is
finished. The game does append local-agent voice events while a round is
happening. This tails that file without touching the game process or input.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Dict


_AGENT_RE = re.compile(r"(?i)Current character:\s+Default__([A-Za-z0-9]+)_PC_C")
_MATCH_RE = re.compile(r"(?i)MatchId:\s*([a-f0-9-]{36})")
_INGAME_RE = re.compile(r"Reconcile called with the current state: InGame", re.I)
_KILL_RE = re.compile(r"(?i)Play_VO_([A-Za-z0-9]+)_E02_Kill")
_DEATH_RE = re.compile(r"(?i)Play_VO_([A-Za-z0-9]+)_DeathEffort")
_HEADSHOT_RE = re.compile(r"(?i)Play_VO_([A-Za-z0-9]+)(?:_E\d+)?_HeadshotKill(?:_\d+)?")


class LiveCombatTracker:
    """Stateful tailer for the current local match."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._match_id = ""
        self._offset = 0
        self._agent = ""
        self._active = False
        self._counts = {"kills": 0, "deaths": 0, "headshot_kills": 0}

    @staticmethod
    def _log_path() -> str:
        return os.path.join(os.getenv("LOCALAPPDATA") or "", "VALORANT", "Saved", "Logs", "ShooterGame.log")

    def _reset(self, match_id: str) -> None:
        self._match_id, self._offset, self._agent, self._active = match_id, 0, "", False
        self._counts = {"kills": 0, "deaths": 0, "headshot_kills": 0}

    def _consume_line(self, line: str, wanted_match: str) -> None:
        agent = _AGENT_RE.search(line)
        if agent:
            self._agent = agent.group(1).lower()

        match = _MATCH_RE.search(line)
        if match and match.group(1).lower() == wanted_match.lower():
            self._active = True
            self._counts = {"kills": 0, "deaths": 0, "headshot_kills": 0}
            return
        if not self._active and _INGAME_RE.search(line):
            self._active = True
            self._counts = {"kills": 0, "deaths": 0, "headshot_kills": 0}
            return
        if not self._active or not self._agent:
            return

        kill = _KILL_RE.search(line)
        if kill and kill.group(1).lower() == self._agent:
            self._counts["kills"] += 1
            return
        death = _DEATH_RE.search(line)
        if death and death.group(1).lower() == self._agent:
            self._counts["deaths"] += 1
            return
        headshot = _HEADSHOT_RE.search(line)
        if headshot and headshot.group(1).lower() == self._agent:
            self._counts["headshot_kills"] += 1

    def snapshot(self, match_id: str) -> Dict[str, object]:
        """Return immediately updated local event totals, if the log has them."""
        path = self._log_path()
        if not match_id or not os.path.exists(path):
            return {"available": False}

        with self._lock:
            if self._match_id != match_id:
                self._reset(match_id)
            try:
                size = os.path.getsize(path)
                if self._offset == 0 or size < self._offset:
                    start = max(0, size - 8 * 1024 * 1024)
                    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                        handle.seek(start)
                        if start:
                            handle.readline()
                        for line in handle:
                            self._consume_line(line, match_id)
                        self._offset = handle.tell()
                elif size > self._offset:
                    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                        handle.seek(self._offset)
                        for line in handle:
                            self._consume_line(line, match_id)
                        self._offset = handle.tell()
            except OSError:
                return {"available": False}

            if not self._active:
                return {"available": False}
            kills = self._counts["kills"]
            return {
                "available": True,
                "source": "game_log",
                "kills": kills,
                "deaths": self._counts["deaths"],
                "assists": None,
                "headshot_kills": self._counts["headshot_kills"],
                "headshot_kill_pct": round(self._counts["headshot_kills"] / kills * 100, 1) if kills else 0.0,
            }
