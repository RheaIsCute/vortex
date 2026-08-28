"""
Riot Client Launcher & Official PVP API Direct Sync for Valorant.
Handles:
- Riot Client auto-detection and pure keyboard auto-login
- Local REST API session signout
- Official Riot PVP token extraction for exact Username, Riot ID, Region, Level, Rank, Peak Rank, and Account Status (Playable/Banned/Suspended)
- Batch account verification worker ("Check Accounts")
"""

import os
import json
import time
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

# Live per-session login progress, polled by the frontend to drive the
# "logging into Riot Client" animation. Single active login at a time.
LOGIN_PROGRESS: Dict[str, Any] = {
    "active": False,
    "username": "",
    "stage": "idle",   # idle | opening | signout | waiting_window | typing | submitted | done | error
    "message": "",
    "started_at": 0.0,
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
            "status": "PLAYABLE"
        }

        # 1. Parse official userinfo payload
        try:
            url_uinfo = f"https://127.0.0.1:{port}/rso-auth/v1/authorization/userinfo"
            res = requests.get(url_uinfo, auth=auth, verify=False, timeout=1.5)
            if res.status_code == 200:
                raw_json = res.json().get("userInfo", "{}")
                uinfo = json.loads(raw_json) if isinstance(raw_json, str) else raw_json

                result["username"] = uinfo.get("username") or uinfo.get("preferred_username", "")
                
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
        """Finds HWND of Riot Client window."""
        for title in ["Riot Client", "Riot Client Main"]:
            hwnd = win32gui.FindWindow(None, title)
            if hwnd and win32gui.IsWindowVisible(hwnd):
                return hwnd

        matches = []
        def enum_cb(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if "Riot Client" in title:
                        rect = win32gui.GetWindowRect(hwnd)
                        if (rect[2] - rect[0]) >= 300:
                            matches.append(hwnd)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
            if matches:
                return matches[0]
        except Exception:
            pass
        return None

    @staticmethod
    def focus_window(hwnd: int) -> bool:
        """
        Brings Riot Client to foreground.

        SetForegroundWindow silently fails when called from a background
        process that Windows doesn't consider "active" (which is exactly our
        case: a background server thread). The Alt key-tap trick helps but
        isn't reliable on its own. AttachThreadInput temporarily merges our
        thread's input state with the target window's foreground thread,
        which is the standard, much more reliable way to force focus in
        this situation.
        """
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            fg_hwnd = win32gui.GetForegroundWindow()
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

                ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)

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
        except Exception:
            return False

    @classmethod
    def auto_fill_credentials_pure_keyboard(cls, username: str, password: str, cold_start: bool = False):
        """
        Pure keyboard autofill (ZERO mouse movement):
        1. Signs out existing session via API if logged in.
        2. Waits for the login DOM inputs to finish mounting.
        3. Focuses window and types Username -> Tab -> Password -> Enter.

        When cold_start is True (Riot Client was not already running), the client
        typically shows a transient splash window before the real login window
        appears, and the login form's DOM takes noticeably longer to mount than on
        a warm relaunch. We wait longer up front and require the detected window's
        size to be stable across repeated checks before treating it as ready,
        so we don't type into a splash screen or a window that isn't finished loading.
        """
        # Ensure any running Valorant game instance is closed first so session can be cleanly switched
        cls.kill_valorant()

        _set_login_stage("signout", "Signing out of the current session...", username)
        did_sign_out = cls.api_sign_out()
        if did_sign_out:
            # Riot Client auto-navigates straight to the username/password
            # form as soon as sign-out completes - it keeps its own window
            # focused through that transition, so this only needs to be a
            # short settle delay, not a re-focus battle.
            time.sleep(0.5)

        # On cold start, give the client process time to get past its splash
        # screen before we even start looking for the real window.
        if cold_start:
            time.sleep(2.5)

        _set_login_stage("waiting_window", "Waiting for the Riot Client login window...", username)
        max_attempts = 90 if cold_start else 45
        hwnd = None
        for _ in range(max_attempts):
            hwnd = cls.find_riot_window()
            if hwnd:
                break
            time.sleep(0.12)

        if not hwnd:
            _set_login_stage("error", "Riot Client login window did not appear.", username)
            return

        if cold_start:
            # Wait until the window's rect stops changing (splash -> real login
            # window swap, or the login form finishing layout) before typing.
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

            # Extra settle time for the login form's inputs to become interactive.
            time.sleep(1.2)

            # Only fight for foreground focus on cold start, where Riot
            # Client is a brand new process and Windows' foreground-lock
            # restrictions are more likely to block SetForegroundWindow.
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
            # Warm path (already logged in -> API sign-out): Riot Client
            # auto-navigates to the login form and keeps its own window
            # focused through the transition, so we don't need to fight for
            # foreground focus here. Repeatedly tapping Alt via
            # focus_window() in this case sends real keystrokes into
            # whatever currently has focus (including Riot Client's own
            # login view), which can shift keyboard focus to an unrelated
            # element there (e.g. an alternate sign-in option) - that's what
            # was breaking this path. A single, non-repeated nudge is enough.
            cls.focus_window(hwnd)

        # A bit more settle time before typing starts - the login form can
        # be visible before its inputs are actually interactive/focused,
        # which is what causes the password to land in the username field.
        time.sleep(0.9)

        _set_login_stage("typing", "Entering credentials into Riot Client...", username)
        try:
            # Clear Username & Paste (Username field is default focused)
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.04)
            pyautogui.press('backspace')
            time.sleep(0.04)
            pyperclip.copy(username)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.15)

            # Tab to Password - extra pause here so the password field has
            # actually received focus before we start typing into it.
            pyautogui.press('tab')
            time.sleep(0.3)

            # Clear Password & Paste
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.04)
            pyautogui.press('backspace')
            time.sleep(0.04)
            pyperclip.copy(password)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.08)

            # Submit login
            pyautogui.press('enter')
            _set_login_stage("submitted", "Signing in... waiting for Riot to respond.", username)
        except Exception:
            _set_login_stage("error", "Failed to type credentials.", username)

    @staticmethod
    def is_valorant_running() -> bool:
        """Checks if VALORANT is currently running."""
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq VALORANT.exe", "/NH"],
                shell=True,
                text=True,
                stderr=subprocess.DEVNULL
            )
            if "VALORANT.exe" in output:
                return True
            output_shipping = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq VALORANT-Win64-Shipping.exe", "/NH"],
                shell=True,
                text=True,
                stderr=subprocess.DEVNULL
            )
            return "VALORANT-Win64-Shipping.exe" in output_shipping
        except Exception:
            return False

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
    def login_account(cls, username: str, password: str, client_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Opens Riot Client and logs in using API logout & pure keyboard injection.
        If VALORANT is running, exits VALORANT before proceeding.
        """
        LOGIN_PROGRESS["started_at"] = time.time()
        _set_login_stage("opening", "Opening Riot Client...", username)

        # If Valorant is running, terminate it so Riot Client can switch accounts cleanly
        if cls.is_valorant_running():
            cls.kill_valorant()
            time.sleep(1.0)

        target_path = client_path or cls.detect_riot_client_path()

        if not target_path or not os.path.exists(target_path):
            _set_login_stage("error", "Riot Client executable not found.", username)
            return {
                "success": False,
                "message": "Riot Client executable not found. Please set path in Settings."
            }

        cls.copy_to_clipboard(password)

        try:
            hwnd = cls.find_riot_window()
            was_running = bool(hwnd)
            if not was_running:
                subprocess.Popen([target_path], shell=False)

            import threading
            threading.Thread(
                target=cls.auto_fill_credentials_pure_keyboard,
                args=(username, password, not was_running),
                daemon=True
            ).start()

            return {
                "success": True,
                "message": f"Logging in to {username}..."
            }
        except Exception as e:
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

