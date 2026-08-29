"""
Riot Client Launcher & Official PVP API Direct Sync for Valorant.
Handles:
- Riot Client auto-detection and pure keyboard auto-login
- Local REST API session signout
- Official Riot PVP token extraction for exact Username, Riot ID, Region, Level, Rank, Peak Rank, and Account Status (Playable/Banned/Suspended)
- Batch account verification worker ("Check Accounts")
"""

import os
import sys
import json
import time
import logging
import logging.handlers
import subprocess
import winreg
import ctypes
import pyautogui
import pyperclip
import requests
import urllib3
import win32gui
import win32con
import win32process
import win32api
from typing import Optional, Dict, Any, Tuple, List, Callable

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
pyautogui.PAUSE = 0.04

# Enable Per-Monitor DPI awareness so window coordinates & clicks match physical pixels accurately
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

# Same per-user writable location the database uses in a packaged build, so
# the log survives updates and is somewhere a user can actually find it.
if getattr(sys, "frozen", False):
    _LOG_DIR = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "Vortex")
else:
    _LOG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(_LOG_DIR, exist_ok=True)
LOGIN_LOG_FILE = os.path.join(_LOG_DIR, "login_debug.log")

login_logger = logging.getLogger("vortex.login")
login_logger.setLevel(logging.DEBUG)
if not login_logger.handlers:
    _handler = logging.handlers.RotatingFileHandler(
        LOGIN_LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    login_logger.addHandler(_handler)
    login_logger.propagate = False

class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ('dwSize', ctypes.c_uint32),
        ('cntUsage', ctypes.c_uint32),
        ('th32ProcessID', ctypes.c_uint32),
        ('th32DefaultHeapID', ctypes.c_size_t),
        ('th32ModuleID', ctypes.c_uint32),
        ('cntThreads', ctypes.c_uint32),
        ('th32ParentProcessID', ctypes.c_uint32),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', ctypes.c_uint32),
        ('szExeFile', ctypes.c_wchar * 260)
    ]


def _is_process_running_fast(targets: set) -> bool:
    if os.name != "nt":
        return False
    try:
        CreateToolhelp32Snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot
        Process32FirstW = ctypes.windll.kernel32.Process32FirstW
        Process32NextW = ctypes.windll.kernel32.Process32NextW
        CloseHandle = ctypes.windll.kernel32.CloseHandle

        h_snap = CreateToolhelp32Snapshot(0x00000002, 0)
        if h_snap == -1 or not h_snap:
            return False
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not Process32FirstW(h_snap, ctypes.byref(entry)):
                return False
            while True:
                if entry.szExeFile.lower() in targets:
                    return True
                if not Process32NextW(h_snap, ctypes.byref(entry)):
                    break
            return False
        finally:
            CloseHandle(h_snap)
    except Exception:
        return False


_VALORANT_PROCS = {"valorant.exe", "valorant-win64-shipping.exe"}
_RIOT_PROCS = {"riotclientservices.exe", "riotclientux.exe",
               "riotclientuxrender.exe", "riotclientcrashhandler.exe"}


def is_valorant_running() -> bool:
    """Checks if VALORANT is currently running (ultra-fast Win32 check)."""
    targets = {"valorant.exe", "valorant-win64-shipping.exe"}
    try:
        return _is_process_running_fast(targets)
    except Exception:
        pass
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq VALORANT.exe", "/NH"],
            shell=False,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1.0
        )
        return "VALORANT.exe" in output
    except Exception:
        return False


# Live per-session login progress, polled by the frontend to drive the
# "logging into Riot Client" animation. Single active login at a time.
LOGIN_PROGRESS: Dict[str, Any] = {
    "active": False,
    "username": "",
    "stage": "idle",   # idle | opening | signout | waiting_window | typing | submitted | done | error
    "message": "",
    "started_at": 0.0,
    "attempt": 0,
    "can_retry": False,
}


def _set_login_stage(stage: str, message: str, username: Optional[str] = None) -> None:
    LOGIN_PROGRESS["stage"] = stage
    LOGIN_PROGRESS["message"] = message
    if username is not None:
        LOGIN_PROGRESS["username"] = username
    if stage in ("opening", "signout"):
        LOGIN_PROGRESS["active"] = True
    if stage in ("done", "error", "idle"):
        LOGIN_PROGRESS["active"] = False
    LOGIN_PROGRESS["can_retry"] = (stage == "error")

    # Every stage transition is logged so a failure can be diagnosed after
    # the fact - the UI only ever shows the last message, this keeps the
    # full sequence that led up to it.
    level = logging.ERROR if stage == "error" else logging.INFO
    login_logger.log(level, "[%s] stage=%s msg=%s", LOGIN_PROGRESS.get("username", ""), stage, message)

# Riot writes the persisted-login blob here when "Stay signed in" was ticked.
# `riot-login.persist` stays null when it wasn't - which is the only way to
# tell after the fact whether the checkbox actually took.
PRIVATE_SETTINGS_PATH = os.path.join(
    os.getenv("LOCALAPPDATA") or os.path.expanduser("~"),
    "Riot Games", "Riot Client", "Data", "RiotGamesPrivateSettings.yaml"
)


def _uia():
    """
    The UI Automation module, or None where it isn't usable.

    Imported lazily and never at module scope: it pulls in comtypes, which
    initialises COM on import, and a failure to load it must degrade the
    login to "no checkbox" rather than taking the whole launcher down.
    """
    try:
        # comtypes writes generated typelib wrappers next to its own package.
        # That path is read-only inside a frozen build, so it's told to work
        # in memory instead and use the wrappers collected at build time.
        if getattr(sys, "frozen", False):
            try:
                import comtypes.client
                comtypes.client.gen_dir = None
            except Exception:
                pass
        import uiautomation
        return uiautomation
    except Exception as e:
        login_logger.warning("UI Automation unavailable: %s", e)
        return None


def set_stay_signed_in(hwnd: int) -> Optional[bool]:
    """
    Ticks the Riot Client's "Stay signed in" checkbox, and puts keyboard focus
    back on the password field afterwards.

    Uses UI Automation to address the checkbox directly rather than counting
    Tab presses to reach it. The login form's tab order runs

        password -> Facebook -> Google -> Apple -> Xbox -> PlayStation
                 -> Stay signed in -> submit

    so every keyboard-based attempt at this has been a guess at how many
    social buttons are rendered, and landing one short means Space activates
    a social sign-in button and derails the login entirely. That is what the
    tab-walking versions were doing. The checkbox exposes a Toggle pattern,
    so it can just be found by name and set - no keystrokes, no mouse, and
    the current state is readable, so an already-ticked box is left alone
    instead of being toggled back off.

    Returns True if it ended up ticked, False if it couldn't be, None when UI
    Automation isn't available at all. Never raises.
    """
    auto = _uia()
    if auto is None or not hwnd:
        login_logger.info("stay-signed-in: UI Automation unavailable, skipping the checkbox")
        return None

    try:
        auto.SetGlobalSearchTimeout(3)
        window = auto.ControlFromHandle(hwnd)
        if not window:
            return None

        checkbox = window.CheckBoxControl(searchDepth=40, Name="Stay signed in")
        if not checkbox.Exists(2):
            login_logger.warning("stay-signed-in: checkbox not found in the login form")
            return False

        toggle = checkbox.GetTogglePattern()
        if toggle is None:
            return False

        # ToggleState: 0 off, 1 on, 2 indeterminate. Toggle() flips, so an
        # already-ticked box must be left alone or it comes back off.
        if toggle.ToggleState != 1:
            toggle.Toggle()
            time.sleep(0.35)

        ticked = checkbox.GetTogglePattern().ToggleState == 1

        # Toggling moves keyboard focus onto the checkbox, and Enter is only
        # a submit from inside the password field - so focus has to go back.
        password_field = window.EditControl(searchDepth=40, Name="PASSWORD")
        if password_field.Exists(1):
            password_field.SetFocus()
            time.sleep(0.25)

        login_logger.info("stay-signed-in: checkbox ticked=%s", ticked)
        return ticked
    except Exception as e:
        login_logger.warning("stay-signed-in: could not set the checkbox: %s", e)
        return False


def is_session_persisted() -> Optional[bool]:
    """
    True when Riot has a persisted login stored ("Stay signed in" is on),
    False when it doesn't, None when the file can't be read.

    Deliberately a dumb line scan rather than a YAML parse: the file holds
    auth cookies, this only ever needs to know whether one key is null, and
    adding a YAML dependency to read one boolean isn't worth it.
    """
    try:
        with open(PRIVATE_SETTINGS_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
    except OSError:
        return None

    in_section = False
    for i, raw in enumerate(lines):
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0:
            in_section = stripped.startswith("riot-login:")
            continue
        if not (in_section and stripped.startswith("persist:")):
            continue

        inline = stripped.split(":", 1)[1].strip().lower()
        if inline:
            return inline not in ("null", "~", "{}", "[]")

        # "persist:" with nothing after it is a block header, not an empty
        # value - the session is stored in the indented lines below it. Reading
        # the empty inline value as "off" would make every login re-tick the
        # checkbox and so untick one that was already on.
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            return (len(nxt) - len(nxt.lstrip())) > indent
        return False
    return False


DEFAULT_VALORANT_PATHS = [
    r"C:\Riot Games\Riot Client\RiotClientServices.exe",
    r"D:\Riot Games\Riot Client\RiotClientServices.exe",
    r"E:\Riot Games\Riot Client\RiotClientServices.exe",
    r"F:\Riot Games\Riot Client\RiotClientServices.exe",
    r"C:\Program Files\Riot Client\RiotClientServices.exe",
    r"C:\Program Files (x86)\Riot Client\RiotClientServices.exe",
]

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


class ClientLauncher:
    @staticmethod
    def detect_riot_client_path() -> Optional[str]:
        """Scans standard installation paths and Windows Registry for Riot Client."""
        for path in DEFAULT_VALORANT_PATHS:
            if os.path.exists(path):
                return path

        registry_keys = [
            (winreg.HKEY_CURRENT_USER, r"Software\Riot Games\Riot Client", "RiotClientPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Riot Games, Inc\Riot Client", "RiotClientPath"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game valorant.live", "InstallLocation")
        ]

        for hkey, subkey, val_name in registry_keys:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, val_name)
                    if val and os.path.exists(val):
                        if os.path.isdir(val):
                            possible_exe = os.path.join(val, "RiotClientServices.exe")
                            if os.path.exists(possible_exe):
                                return possible_exe
                        else:
                            return val
            except Exception:
                continue

        return None

    @staticmethod
    def copy_to_clipboard(text: str) -> bool:
        """Copies text to the system clipboard."""
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            return False

    @staticmethod
    def get_lockfile_auth() -> Optional[Tuple[int, str]]:
        """Reads port and password from Riot Client lockfile."""
        try:
            local_appdata = os.getenv("LOCALAPPDATA")
            if not local_appdata:
                return None
            lockfile_path = os.path.join(local_appdata, "Riot Games", "Riot Client", "Config", "lockfile")
            if os.path.exists(lockfile_path):
                with open(lockfile_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                parts = content.split(":")
                if len(parts) >= 5:
                    port = int(parts[2])
                    password = parts[3]
                    return port, password
        except Exception:
            pass
        return None

    @classmethod
    def get_active_riot_account(cls, expected_username: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Auto-detects the currently logged-in account's Username, Riot ID, Region,
        Level, Current Rank, Peak Rank, and Ban/Suspension Status directly from Riot Client APIs.
        If expected_username is provided, ensures the active session matches that username.
        """
        auth_info = cls.get_lockfile_auth()
        if not auth_info:
            return None

        port, password = auth_info
        auth = ("riot", password)

        result = {
            "found": False,
            "username": "",
            "display_name": "",
            "region": "NA",
            "rank_tier": "UNRANKED",
            "rank_division": "",
            "lp": 0,
            "rank_icon_url": f"{TIER_BASE_URL}/0/largeicon.png",
            "peak_rank_tier": "",
            "peak_rank_division": "",
            "peak_rank_icon_url": "",
            "status": "PLAYABLE",
            "puuid": ""
        }

        # 1. Parse official userinfo payload
        try:
            url_uinfo = f"https://127.0.0.1:{port}/rso-auth/v1/authorization/userinfo"
            res = requests.get(url_uinfo, auth=auth, verify=False, timeout=1.5)
            if res.status_code == 200:
                raw_json = res.json().get("userInfo", "{}")
                uinfo = json.loads(raw_json) if isinstance(raw_json, str) else raw_json

                result["username"] = uinfo.get("username") or uinfo.get("preferred_username", "")
                # Riot's stable per-account id. This is the key the account's
                # local VALORANT settings folder is named after, so capturing
                # it here is what makes crosshair/keybind copying possible.
                result["puuid"] = (uinfo.get("sub") or uinfo.get("puuid") or "").strip()
                
                # Verify expected username if supplied
                if expected_username and result["username"]:
                    if result["username"].strip().lower() != expected_username.strip().lower():
                        return None

                if result["username"]:
                    result["found"] = True

                acct = uinfo.get("acct", {})
                game_name = acct.get("game_name", "")
                tag_line = acct.get("tag_line", "")
                if game_name and tag_line:
                    result["display_name"] = f"{game_name}#{tag_line}"

                # Status parsing (Playable vs Banned vs Suspended)
                acct_state = (acct.get("state") or "").upper()
                ban_data = uinfo.get("ban", {}) or {}
                restrictions = ban_data.get("restrictions", []) or []

                if acct_state in ("BANNED", "PERMA_BANNED") or any(r.get("type") in ("PERMANENT_BAN", "BANNED") for r in restrictions):
                    result["status"] = "BANNED"
                elif acct_state in ("SUSPENDED", "TEMP_BANNED") or any(r.get("type") in ("TEMPORARY_BAN", "SUSPENDED") for r in restrictions):
                    result["status"] = "SUSPENDED"
                else:
                    result["status"] = "PLAYABLE"

                # Region parsing from official region ID
                region_id = (uinfo.get("region", {}).get("id") or uinfo.get("original_platform_id", "")).upper()
                if any(x in region_id for x in ["LA", "LAN", "LAS", "LATAM"]):
                    result["region"] = "LATAM"
                elif "BR" in region_id:
                    result["region"] = "BR"
                elif any(x in region_id for x in ["EU", "TR", "RU"]):
                    result["region"] = "EU"
                elif "KR" in region_id:
                    result["region"] = "KR"
                elif any(x in region_id for x in ["AP", "OC", "JP"]):
                    result["region"] = "AP"
                else:
                    result["region"] = "NA"
        except Exception:
            pass

        # userinfo comes back empty while the game is mid-session, but the
        # entitlements token always carries the puuid as its subject.
        if not result["puuid"]:
            try:
                url_ent = f"https://127.0.0.1:{port}/entitlements/v1/token"
                res = requests.get(url_ent, auth=auth, verify=False, timeout=1.5)
                if res.status_code == 200:
                    result["puuid"] = (res.json().get("subject") or "").strip()
            except Exception:
                pass

        # Fallback chat session for Riot ID & region if userinfo was incomplete
        if not result["display_name"]:
            try:
                url_chat = f"https://127.0.0.1:{port}/chat/v1/session"
                res = requests.get(url_chat, auth=auth, verify=False, timeout=1.5)
                if res.status_code == 200:
                    data = res.json()
                    game_name = data.get("game_name", "").strip()
                    tag_line = data.get("game_tag", "").strip()
                    pid = data.get("pid", "").lower()
                    if not result["puuid"]:
                        result["puuid"] = (data.get("puuid") or "").strip()
                    
                    if "la1" in pid or "la2" in pid or "las" in pid: result["region"] = "LATAM"
                    elif "br" in pid: result["region"] = "BR"
                    elif "eu" in pid or "tr" in pid: result["region"] = "EU"
                    elif "kr" in pid: result["region"] = "KR"
                    elif "ap" in pid or "jp" in pid: result["region"] = "AP"

                    if game_name and tag_line:
                        result["found"] = True
                        result["display_name"] = f"{game_name}#{tag_line}"
            except Exception:
                pass

        if not result["found"] and not result["username"]:
            return None

        # 2. Extract Entitlements Token for Official PVP Level & MMR sync
        try:
            url_token = f"https://127.0.0.1:{port}/entitlements/v1/token"
            r_token = requests.get(url_token, auth=auth, verify=False, timeout=1.5)
            if r_token.status_code == 200:
                tok = r_token.json()
                access_token = tok.get("accessToken")
                entitlements_token = tok.get("token")
                puuid = tok.get("subject")

                if access_token and entitlements_token and puuid:
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "X-Riot-Entitlements-JWT": entitlements_token,
                        "X-Riot-ClientVersion": "release-08.11-shipping-9-2516482",
                        "X-Riot-ClientPlatform": "ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjogIldpbmRvd3MiLA0KCSJwbGF0Zm9ybU9TVmVyc2lvbiI6ICIxMC4wLjE5MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0IjogIlVua25vd24iDQp9"
                    }

                    # PVP routing
                    region_sub = result["region"].lower()
                    if region_sub in ("latam", "br"): region_sub = "na"

                    # Fetch Official Level from Account-XP.
                    # Only set "level" when we actually got a real value back -
                    # leaving the key absent tells callers "no data this time"
                    # so they don't overwrite a good stored level. Defaulting
                    # to 1 here is indistinguishable from a real level-1
                    # account and would wipe the stored level on any failure.
                    url_xp = f"https://pd.{region_sub}.a.pvp.net/account-xp/v1/players/{puuid}"
                    r_xp = requests.get(url_xp, headers=headers, timeout=2.0)
                    if r_xp.status_code == 200:
                        xp_data = r_xp.json()
                        xp_level = (xp_data.get("Progress") or {}).get("Level")
                        if isinstance(xp_level, int) and xp_level > 0:
                            result["level"] = xp_level

                    # Fetch MMR & Peak Rank from Official MMR API
                    url_mmr = f"https://pd.{region_sub}.a.pvp.net/mmr/v1/players/{puuid}"
                    r_mmr = requests.get(url_mmr, headers=headers, timeout=2.0)
                    if r_mmr.status_code == 200:
                        mmr_data = r_mmr.json()
                        latest_update = mmr_data.get("LatestCompetitiveUpdate", {})
                        curr_tier_num = latest_update.get("TierAfterUpdate", 0)
                        result["lp"] = latest_update.get("RankedRatingAfterUpdate", 0)

                        if curr_tier_num and curr_tier_num < len(TIER_NAMES):
                            full_name = TIER_NAMES[curr_tier_num]
                            parts = full_name.split()
                            result["rank_tier"] = parts[0]
                            if len(parts) > 1: result["rank_division"] = parts[1]
                            result["rank_icon_url"] = f"{TIER_BASE_URL}/{curr_tier_num}/largeicon.png"

                        # Calculate All-Time Peak Tier from seasonal history
                        queue_skills = mmr_data.get("QueueSkills", {}).get("competitive", {})
                        seasonal = queue_skills.get("SeasonalInfoBySeasonID") or {}
                        peak_tier_num = 0
                        for _, s_info in seasonal.items():
                            t = s_info.get("CompetitiveTier", 0)
                            if t > peak_tier_num:
                                peak_tier_num = t

                        if peak_tier_num > 0 and peak_tier_num < len(TIER_NAMES):
                            p_name = TIER_NAMES[peak_tier_num]
                            p_parts = p_name.split()
                            result["peak_rank_tier"] = p_parts[0]
                            if len(p_parts) > 1: result["peak_rank_division"] = p_parts[1]
                            result["peak_rank_icon_url"] = f"{TIER_BASE_URL}/{peak_tier_num}/largeicon.png"
        except Exception:
            pass

        return result

    @classmethod
    def check_login_error(cls) -> Optional[str]:
        """
        Checks if Riot Client encountered an auth/credential error.
        """
        auth_info = cls.get_lockfile_auth()
        if not auth_info:
            return None

        port, password = auth_info
        auth = ("riot", password)

        try:
            url = f"https://127.0.0.1:{port}/rso-auth/v1/authorization"
            res = requests.get(url, auth=auth, verify=False, timeout=1.0)
            if res.status_code == 200:
                data = res.json()
                err = data.get("error") or data.get("type")
                if err in ("auth_failure", "invalid_credentials", "login_error"):
                    return str(err)
        except Exception:
            pass
        return None

    @classmethod
    def api_sign_out(cls) -> bool:
        """
        Signs out active account instantly using Riot Client's internal REST API.
        """
        auth_info = cls.get_lockfile_auth()
        if not auth_info:
            return False

        port, password = auth_info
        url = f"https://127.0.0.1:{port}/rso-auth/v1/session"
        try:
            res = requests.get(url, auth=("riot", password), verify=False, timeout=1.0)
            if res.status_code == 200 and res.json().get("type") == "authenticated":
                del_res = requests.delete(url, auth=("riot", password), verify=False, timeout=1.5)
                return del_res.status_code in (200, 204)
        except Exception:
            pass
        return False

    @classmethod
    def find_riot_window(cls) -> Optional[int]:
        """Finds HWND of the main visible Riot Client window."""
        candidates = []

        def enum_cb(hwnd, _):
            try:
                if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if "Riot Client" in title:
                        rect = win32gui.GetWindowRect(hwnd)
                        w = rect[2] - rect[0]
                        h = rect[3] - rect[1]
                        if w >= 300 and h >= 200:
                            candidates.append((w * h, hwnd))
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
            if candidates:
                # Sort by window area descending so the largest visible main window is preferred
                candidates.sort(reverse=True)
                return candidates[0][1]
        except Exception:
            pass

        for title in ["Riot Client", "Riot Client Main"]:
            hwnd = win32gui.FindWindow(None, title)
            if hwnd and win32gui.IsWindowVisible(hwnd):
                rect = win32gui.GetWindowRect(hwnd)
                if (rect[2] - rect[0]) >= 300 and (rect[3] - rect[1]) >= 200:
                    return hwnd

        return None

    @staticmethod
    def focus_window(hwnd: int) -> bool:
        """
        Brings Riot Client to foreground reliably without sending
        defocusing keystrokes like Alt.
        """
        try:
            if not hwnd or not win32gui.IsWindow(hwnd):
                return False

            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            try:
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass

            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd != hwnd:
                target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
                current_thread = win32api.GetCurrentThreadId()
                fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0] if fg_hwnd else 0

                attached_fg = False
                attached_self = False
                try:
                    if fg_thread and fg_thread != target_thread:
                        win32process.AttachThreadInput(fg_thread, target_thread, True)
                        attached_fg = True
                    if current_thread != target_thread:
                        win32process.AttachThreadInput(current_thread, target_thread, True)
                        attached_self = True

                    # Elevate z-order using TOPMOST toggle
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                    )
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                    )
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetForegroundWindow(hwnd)
                finally:
                    if attached_fg:
                        try:
                            win32process.AttachThreadInput(fg_thread, target_thread, False)
                        except Exception:
                            pass
                    if attached_self:
                        try:
                            win32process.AttachThreadInput(current_thread, target_thread, False)
                        except Exception:
                            pass

            return True
        except Exception as e:
            login_logger.warning("focus_window failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Verified login steps
    #
    # Every step below checks that it actually happened instead of sleeping
    # for a plausible length of time and hoping. The old flow was a chain of
    # fixed delays - wait 2.5s for the splash, wait 0.9s for the form to be
    # "interactive", type, hope - and when any one of them was short on a
    # slow machine the login failed with nothing in the log to say which.
    # ------------------------------------------------------------------

    @classmethod
    def wait_for_signed_out(cls, timeout: float = 8.0) -> bool:
        """
        Blocks until the Riot Client reports no authenticated session.

        Sign-out is a request, not an instant state change - returning as soon
        as the DELETE is accepted means the next steps can race a session that
        is still tearing down, and the client then re-renders the login form
        underneath whatever has already been typed.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            auth = cls.get_lockfile_auth()
            if not auth:
                # No lockfile means no client session at all - signed out by
                # definition.
                return True
            port, pw = auth
            try:
                res = requests.get(
                    f"https://127.0.0.1:{port}/rso-auth/v1/session",
                    auth=("riot", pw), verify=False, timeout=1.0
                )
                if res.status_code != 200 or res.json().get("type") != "authenticated":
                    return True
            except Exception:
                return True
            time.sleep(0.25)
        return False

    @staticmethod
    def wait_for_processes_gone(names: set, timeout: float = 8.0) -> bool:
        """Blocks until none of `names` is running. Lowercase exe names."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _is_process_running_fast(names):
                return True
            time.sleep(0.2)
        return not _is_process_running_fast(names)

    @classmethod
    def wait_for_login_form(cls, timeout: float = 45.0):
        """
        Blocks until the Riot Client is showing the credential section, and
        returns (window, username_field, password_field) - or None on timeout.

        This is the real "the client has finished opening" signal. The old
        check watched the window rectangle until it stopped changing, which
        is satisfied by the splash screen, by a half-drawn client, and by the
        client sitting on a completely different screen. Waiting for the two
        input controls to exist and be enabled cannot be satisfied by any of
        those.

        Returns None when UI Automation isn't available, so the caller can
        fall back to the timing-based path.
        """
        auto = _uia()
        if auto is None:
            return None

        deadline = time.time() + timeout
        last_seen = ""
        while time.time() < deadline:
            hwnd = cls.find_riot_window()
            if not hwnd:
                last_seen = "no Riot Client window yet"
                time.sleep(0.3)
                continue
            try:
                auto.SetGlobalSearchTimeout(1)
                window = auto.ControlFromHandle(hwnd)
                if window:
                    user_field = window.EditControl(searchDepth=40, Name="USERNAME")
                    pass_field = window.EditControl(searchDepth=40, Name="PASSWORD")
                    if user_field.Exists(0.6) and pass_field.Exists(0.6):
                        if user_field.IsEnabled and pass_field.IsEnabled:
                            login_logger.info("login form is up and interactive")
                            return window, user_field, pass_field
                        last_seen = "credential fields present but not enabled yet"
                    else:
                        last_seen = "window up, credential fields not mounted yet"
            except Exception as e:
                last_seen = f"reading the window failed: {e}"
            time.sleep(0.3)

        login_logger.warning("login form never appeared - last state: %s", last_seen)
        return None

    @staticmethod
    def _field_text(field) -> str:
        """Current text of an edit control, or '' if it can't be read."""
        try:
            vp = field.GetValuePattern()
            if vp is not None:
                return vp.Value or ""
        except Exception:
            pass
        try:
            return field.GetLegacyIAccessiblePattern().Value or ""
        except Exception:
            return ""

    @classmethod
    def fill_field_verified(cls, field, value: str, label: str,
                            masked: bool = False, attempts: int = 3) -> bool:
        """
        Puts `value` into one field and confirms it landed, retrying if not.

        The username field reads back as plain text, so it can be compared
        exactly. The password field reads back as bullets, so the check is on
        the character count - which is still enough to catch the two failures
        that actually happen: nothing landing at all, and the value landing in
        the wrong field (the classic "password typed into the username box").
        """
        for attempt in range(1, attempts + 1):
            try:
                field.SetFocus()
            except Exception as e:
                login_logger.warning("%s: could not focus the field: %s", label, e)
                return False
            time.sleep(0.18)

            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.05)
            pyautogui.press('backspace')
            time.sleep(0.05)

            pyperclip.copy(value)
            time.sleep(0.05)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.25)

            got = cls._field_text(field)
            ok = (len(got) == len(value)) if masked else (got == value)
            if ok:
                login_logger.info("%s: entered and verified (attempt %d)", label, attempt)
                return True

            login_logger.warning(
                "%s: did not land on attempt %d - field holds %d chars, expected %d",
                label, attempt, len(got), len(value)
            )
            time.sleep(0.3)

        login_logger.error("%s: gave up after %d attempts", label, attempts)
        return False

    @classmethod
    def submit_login_form(cls, window, pass_field) -> bool:
        """
        Submits the form from inside the password field, which is the only
        submission path the Riot Client handles reliably. Focus is re-asserted
        first, because ticking the checkbox moves it.
        """
        try:
            pass_field.SetFocus()
            time.sleep(0.2)
        except Exception:
            pass
        pyautogui.press('enter')
        return True

    @classmethod
    def auto_fill_credentials(cls, username: str, password: str, cold_start: bool = False,
                              stay_signed_in: bool = True):
        """
        Enters the credentials, checking at every step that the step actually
        happened rather than sleeping for a plausible length of time.

        The verified path, when UI Automation is available:
          1. Wait until the credential fields exist and are enabled - the real
             "the client has finished opening" signal, which a splash screen
             or a half-drawn client cannot satisfy.
          2. Focus the username field explicitly and type it, then read it
             back and retry if it didn't land.
          3. Focus the password field explicitly - no Tab, so it cannot end up
             somewhere else - type it, and confirm the right number of
             characters arrived.
          4. Tick "Stay signed in" by addressing the checkbox directly.
          5. Put focus back in the password field and submit with Enter.

        When UI Automation isn't available it falls back to the timing-based
        keyboard sequence, which is the one that has always worked; nothing in
        the fallback changed.
        """
        # Wait for the window to exist at all before looking for the form, so
        # the progress the user sees distinguishes "the client hasn't opened"
        # from "the client is open but hasn't reached the login screen".
        _set_login_stage("waiting_window", "Waiting for the Riot Client to open...", username)
        hwnd = None
        for _ in range(120):
            hwnd = cls.find_riot_window()
            if hwnd:
                break
            time.sleep(0.25)

        if not hwnd:
            _set_login_stage("error", "The Riot Client never opened.", username)
            return

        login_logger.info("[%s] Riot Client window is up", username)
        _set_login_stage("waiting_window", "Waiting for the sign-in screen...", username)

        form = cls.wait_for_login_form(timeout=35.0)

        if form is None:
            # Either UI Automation isn't usable in this build, or the client
            # is up but never showed a credential section. Fall back to the
            # timing-based path rather than refusing to log in - it can't
            # verify anything, but it is the sequence that has always worked.
            login_logger.info(
                "[%s] no readable login form - falling back to the timing-based entry path", username
            )
            cls._fill_credentials_blind(hwnd, username, password, cold_start, stay_signed_in)
            return

        window, user_field, pass_field = form
        hwnd = cls.find_riot_window() or hwnd

        # The window has to be foreground for the paste keystrokes to reach
        # it. Fields are focused through UI Automation, so this only needs to
        # win once rather than being fought for repeatedly.
        _set_login_stage("waiting_window", "Riot Client is ready - entering credentials...", username)
        for _ in range(8):
            cls.focus_window(hwnd)
            time.sleep(0.2)
            try:
                if win32gui.GetForegroundWindow() == hwnd:
                    break
            except Exception:
                break

        _set_login_stage("typing", "Entering username...", username)

        try:
            orig_clipboard = pyperclip.paste()
        except Exception:
            orig_clipboard = ""

        try:
            if not cls.fill_field_verified(user_field, username, "username"):
                _set_login_stage(
                    "error",
                    "The username didn't go into the Riot Client's login box - nothing was submitted.",
                    username
                )
                return

            _set_login_stage("typing", "Entering password...", username)
            if not cls.fill_field_verified(pass_field, password, "password", masked=True):
                _set_login_stage(
                    "error",
                    "The password didn't go into the Riot Client's login box - nothing was submitted.",
                    username
                )
                return

            # Both fields are confirmed correct before anything is submitted,
            # so a mistyped login can no longer burn a Riot rate-limit slot.
            login_logger.info("[%s] both fields verified - submitting", username)

            if stay_signed_in:
                _set_login_stage("typing", "Ticking \"Stay signed in\"...", username)
                set_stay_signed_in(hwnd)

            _set_login_stage("typing", "Submitting the login...", username)
            cls.submit_login_form(window, pass_field)
            _set_login_stage("submitted", "Signing in... waiting for Riot to respond.", username)
        except Exception as e:
            login_logger.exception("[%s] Failed to enter credentials: %s", username, e)
            _set_login_stage("error", f"Failed to type credentials: {e}", username)
        finally:
            try:
                pyperclip.copy(orig_clipboard or "")
            except Exception:
                pass

    @classmethod
    def _fill_credentials_blind(cls, hwnd: int, username: str, password: str,
                                cold_start: bool, stay_signed_in: bool):
        """
        The timing-based entry path, for when UI Automation can't be used.

        This is the v3 sequence unchanged - the one that logs in reliably.
        There is deliberately no keyboard route to the "Stay signed in"
        checkbox here: reaching it means tabbing across the social sign-in
        buttons, and landing one short activates one of them instead.
        """
        if cold_start:
            stable_checks = 0
            last_rect = None
            for _ in range(60):
                time.sleep(0.15)
                current_hwnd = cls.find_riot_window()
                if not current_hwnd:
                    continue
                hwnd = current_hwnd
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                except Exception:
                    rect = None
                if rect and rect == last_rect and rect[2] - rect[0] > 300:
                    stable_checks += 1
                    if stable_checks >= 6:
                        break
                else:
                    stable_checks = 0
                last_rect = rect

            time.sleep(1.2)

            focused_ok = False
            for _ in range(6):
                cls.focus_window(hwnd)
                time.sleep(0.25)
                try:
                    if win32gui.GetForegroundWindow() == hwnd:
                        focused_ok = True
                        break
                except Exception:
                    pass
            if not focused_ok:
                _set_login_stage("error", "Could not focus the Riot Client window.", username)
                return
        else:
            cls.focus_window(hwnd)

        time.sleep(0.9)
        _set_login_stage("typing", "Entering credentials into Riot Client...", username)

        try:
            orig_clipboard = pyperclip.paste()
        except Exception:
            orig_clipboard = ""

        try:
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.04)
            pyautogui.press('backspace')
            time.sleep(0.04)
            pyperclip.copy(username)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.15)

            pyautogui.press('tab')
            time.sleep(0.3)

            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.04)
            pyautogui.press('backspace')
            time.sleep(0.04)
            pyperclip.copy(password)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.08)

            pyautogui.press('enter')
            _set_login_stage("submitted", "Signing in... waiting for Riot to respond.", username)
        except Exception as e:
            login_logger.exception("[%s] Failed to type credentials: %s", username, e)
            _set_login_stage("error", f"Failed to type credentials: {e}", username)
        finally:
            try:
                pyperclip.copy(orig_clipboard or "")
            except Exception:
                pass

    # Backward compatibility alias
    auto_fill_credentials_pure_keyboard = auto_fill_credentials

    @staticmethod
    def is_valorant_running() -> bool:
        """Checks if VALORANT is currently running (ultra-fast Win32 check)."""
        return is_valorant_running()

    @staticmethod
    def kill_valorant() -> bool:
        """Force closes any running VALORANT game instances."""
        try:
            res = subprocess.run(
                ["taskkill", "/F", "/T", "/IM", "VALORANT.exe", "/IM", "VALORANT-Win64-Shipping.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True
            )
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def login_account(cls, username: str, password: str, client_path: Optional[str] = None,
                      stay_signed_in: bool = True) -> Dict[str, Any]:
        """
        Signs out, restarts the Riot Client, and logs the account in.

        Every login now starts the client from scratch rather than reusing
        whatever is already on screen. A client that has been sitting open
        can be on any screen - a half-filled form, an error banner, a "session
        expired" notice, the region picker - and the old warm path assumed a
        clean login form and typed into whatever was actually there. Killing
        it first costs a few seconds and removes that entire class of failure,
        along with any stale keyboard focus or leftover text in the fields.

        Each step is confirmed before the next one runs, so a failure names
        the step that failed instead of surfacing as credentials going
        somewhere unexpected.
        """
        LOGIN_PROGRESS["started_at"] = time.time()
        LOGIN_PROGRESS["attempt"] = LOGIN_PROGRESS.get("attempt", 0) + 1
        LOGIN_PROGRESS["stay_signed_in"] = None
        _set_login_stage("opening", "Closing VALORANT and the Riot Client...", username)

        target_path = client_path or cls.detect_riot_client_path()
        if not target_path or not os.path.exists(target_path):
            _set_login_stage("error", "Riot Client executable not found.", username)
            return {
                "success": False,
                "message": "Riot Client executable not found. Please set path in Settings."
            }

        try:
            # 1. VALORANT first - the Riot Client can't switch accounts under a
            #    running game, and confirm it's actually gone before moving on.
            if cls.is_valorant_running():
                cls.kill_valorant()
                if cls.wait_for_processes_gone(_VALORANT_PROCS, timeout=8.0):
                    login_logger.info("[%s] VALORANT closed", username)
                else:
                    login_logger.warning("[%s] VALORANT did not exit in time", username)

            # 2. Sign the current session out through the API before killing
            #    the client. Killing it alone doesn't end the session, so a
            #    client with "stay signed in" set would come back up already
            #    logged into the previous account and never show the form.
            _set_login_stage("signout", "Signing out of the current session...", username)
            if cls.get_lockfile_auth():
                cls.api_sign_out()
                if cls.wait_for_signed_out(timeout=8.0):
                    login_logger.info("[%s] previous session signed out", username)
                else:
                    login_logger.warning(
                        "[%s] sign-out not confirmed - restarting the client anyway", username
                    )

            # 3. Restart the client from scratch.
            _set_login_stage("opening", "Restarting the Riot Client...", username)
            cls.force_kill_riot_client()
            if cls.wait_for_processes_gone(_RIOT_PROCS, timeout=10.0):
                login_logger.info("[%s] Riot Client processes closed", username)
            else:
                login_logger.warning(
                    "[%s] some Riot Client processes are still running", username
                )
            # Windows needs a moment to release the client's file locks and
            # its single-instance mutex, or the relaunch is swallowed.
            time.sleep(1.2)

            subprocess.Popen([target_path], shell=False)
            _set_login_stage("waiting_window", "Waiting for the Riot Client to open...", username)

            def _run_autofill():
                # This runs on its own thread with no caller left to see an
                # uncaught exception - without this it would just leave the
                # login modal stuck on its last stage forever.
                try:
                    cls.auto_fill_credentials(username, password, True, stay_signed_in)
                except Exception as e:
                    login_logger.exception("[%s] auto-fill worker crashed", username)
                    _set_login_stage("error", f"Login automation crashed: {e}", username)

            import threading
            threading.Thread(target=_run_autofill, daemon=True).start()

            return {
                "success": True,
                "message": f"Logging in to {username}..."
            }
        except Exception as e:
            login_logger.exception("[%s] login_account failed to start", username)
            _set_login_stage("error", f"Failed to start Riot Client: {str(e)}", username)
            return {
                "success": False,
                "message": f"Failed to start Riot Client: {str(e)}"
            }

    @staticmethod
    def force_kill_riot_client():
        """Force closes all Riot Client processes cleanly to reset rate limits and release session lock."""
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", "RiotClientServices.exe", "/IM", "RiotClientUx.exe", "/IM", "RiotClientCrashHandler.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True
            )
        except Exception:
            pass

