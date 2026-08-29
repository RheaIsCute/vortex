"""
Live FPS via system-level frame-presentation tracing (ETW), using Intel's
open-source PresentMon as the capture engine - the same technique tools like
RTSS and CapFrameX use to read a real number without touching the game.

Nothing here reads from, writes to, or injects into VALORANT's process.
PresentMon opens an ETW trace session and listens for the frame-presentation
events the GPU driver and DWM already publish system-wide (the same data
Task Manager's per-app GPU graphs come from), filtered to just the process
names this asks for.

The trade-off that comes with avoiding injection: a plain always-on-top
window can only visually appear over VALORANT while it renders through the
desktop compositor (Borderless / Windowed Fullscreen). True exclusive
Fullscreen bypasses the compositor entirely, and nothing short of drawing
inside the game's own render pipeline can sit on top of that - which is
exactly the category of technique this was built to avoid.

ETW capture of an arbitrary process's presents needs the user to either be an
administrator or a member of the "Performance Log Users" group. When neither
is true PresentMon starts but reports nothing - surfaced here as available
staying False rather than an exception, since a game just not running yet
looks identical from this module's point of view.
"""

import csv
import os
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, Optional

CREATE_NO_WINDOW = 0x08000000

DEFAULT_TARGETS = ("VALORANT-Win64-Shipping.exe",)
FPS_WINDOW_SECONDS = 1.0
_PRESENT_RETENTION_SECONDS = 2.0


def presentmon_path() -> Optional[str]:
    """Bundled PresentMon-x64.exe, next to the frontend folder in both the
    source tree and the frozen build (see build_exe.spec's datas)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "vendor", "PresentMon", "PresentMon-x64.exe")
    return path if os.path.isfile(path) else None


class FpsMonitor:
    """
    Owns one PresentMon subprocess and a reader thread that turns its live
    CSV stdout into a rolling presents-per-second count.

    A target process can have more than one active swap chain (VALORANT
    briefly does during a mode transition). Only the chain that is actually
    the busiest right now is reported, so a rarely-updating secondary chain
    can't drag a real number down.
    """

    def __init__(self, process_names=DEFAULT_TARGETS):
        self.process_names = process_names
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._presents: Dict[str, deque] = {}
        self._last_error = ""

    def start(self) -> Optional[str]:
        """Starts capturing. Returns an error string on failure, else None."""
        exe = presentmon_path()
        if not exe:
            return "PresentMon wasn't found in this build."

        self.stop()
        self._stop.clear()
        self._presents = {}
        self._last_error = ""

        args = [exe]
        for name in self.process_names:
            args += ["--process_name", name]
        args += ["--output_stdout", "--no_console_stats", "--stop_existing_session",
                  "--session_name", "VortexFPS"]

        try:
            self._proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
            )
        except OSError as e:
            return f"Couldn't start PresentMon: {e}"

        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="vortex-fps-reader")
        self._reader.start()
        return None

    def _read_loop(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        header = None
        try:
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                line = line.rstrip("\r\n")
                if not line:
                    continue
                try:
                    row = next(csv.reader([line]))
                except Exception:
                    continue
                if header is None:
                    header = row
                    continue
                if len(row) != len(header):
                    continue
                rec = dict(zip(header, row))
                chain = rec.get("SwapChainAddress") or rec.get("Application", "")
                now = time.time()
                with self._lock:
                    dq = self._presents.setdefault(chain, deque())
                    dq.append(now)
                    cutoff = now - _PRESENT_RETENTION_SECONDS
                    while dq and dq[0] < cutoff:
                        dq.popleft()
        except Exception as e:
            with self._lock:
                self._last_error = str(e)
        finally:
            if proc.stderr:
                try:
                    err = (proc.stderr.read(2000) or "").strip()
                    with self._lock:
                        if err and not any(self._presents.values()):
                            self._last_error = err[-500:]
                except Exception:
                    pass

    def current_fps(self) -> Optional[int]:
        """Presents in the trailing window on the busiest chain right now -
        None while nothing has rendered a frame yet."""
        now = time.time()
        with self._lock:
            best_count = 0
            for dq in self._presents.values():
                cutoff = now - FPS_WINDOW_SECONDS
                count = sum(1 for t in dq if t >= cutoff)
                if count > best_count:
                    best_count = count
            has_any_chain = bool(self._presents)
        if not has_any_chain:
            return None
        return best_count

    def status(self) -> Dict[str, Any]:
        running = bool(self._proc and self._proc.poll() is None)
        fps = self.current_fps() if running else None
        with self._lock:
            error = "" if running else self._last_error
        return {"running": running, "fps": fps, "available": fps is not None, "error": error}

    def stop(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        reader, self._reader = self._reader, None
        if reader and reader.is_alive():
            reader.join(timeout=1.0)


_MONITOR: Optional[FpsMonitor] = None
_MONITOR_LOCK = threading.Lock()


def ensure_started() -> Optional[str]:
    """Idempotent: does nothing if already capturing. Returns an error
    string on failure, else None."""
    global _MONITOR
    with _MONITOR_LOCK:
        if _MONITOR is None:
            _MONITOR = FpsMonitor()
        if _MONITOR._proc and _MONITOR._proc.poll() is None:
            return None
        return _MONITOR.start()


def ensure_stopped() -> None:
    global _MONITOR
    with _MONITOR_LOCK:
        if _MONITOR is not None:
            _MONITOR.stop()


def get_status() -> Dict[str, Any]:
    with _MONITOR_LOCK:
        if _MONITOR is None:
            return {"running": False, "fps": None, "available": False, "error": ""}
        return _MONITOR.status()
