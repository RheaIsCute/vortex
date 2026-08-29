"""
FastAPI Backend Server for Valorant Account Manager.
Serves REST API endpoints for accounts, live rank stats, match histories,
batch text combo imports, status detection (PLAYABLE/BANNED/SUSPENDED),
and automated full-roster account checker ("Check Accounts").
"""

import os
import time
import asyncio
import threading
import subprocess
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.database import Database
from backend.scraper import StatScraper
from backend.client_launcher import ClientLauncher
from backend import client_launcher
from backend import valorant_client
from backend import game_config
from backend.version import APP_VERSION
from backend import updater

app = FastAPI(title="Vortex Valorant Account Manager API", version=APP_VERSION)

db = Database()
launcher = ClientLauncher()

# Global status tracker for "Check Accounts" batch verification
CHECK_PROGRESS = {
    "running": False,
    "current": 0,
    "total": 0,
    "account": "",
    "message": ""
}


class AccountCreate(BaseModel):
    username: str
    password: str
    region: Optional[str] = "NA"
    display_name: Optional[str] = ""
    tag: Optional[str] = ""
    notes: Optional[str] = ""
    rank_tier: Optional[str] = "UNRANKED"
    rank_division: Optional[str] = ""
    lp: Optional[int] = 0
    level: Optional[int] = 1
    rank_icon_url: Optional[str] = ""
    peak_rank_tier: Optional[str] = ""
    peak_rank_division: Optional[str] = ""
    peak_rank_icon_url: Optional[str] = ""
    peak_rank_season: Optional[str] = ""
    card_small_url: Optional[str] = None
    status: Optional[str] = None
    favorite: Optional[bool] = None


class AccountUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    region: Optional[str] = None
    display_name: Optional[str] = None
    tag: Optional[str] = None
    notes: Optional[str] = None
    rank_tier: Optional[str] = None
    rank_division: Optional[str] = None
    lp: Optional[int] = None
    level: Optional[int] = None
    winrate: Optional[float] = None
    games_played: Optional[int] = None
    rank_icon_url: Optional[str] = None
    peak_rank_tier: Optional[str] = None
    peak_rank_division: Optional[str] = None
    peak_rank_icon_url: Optional[str] = None
    peak_rank_season: Optional[str] = None
    card_small_url: Optional[str] = None
    status: Optional[str] = None
    favorite: Optional[bool] = None


class CopyRequest(BaseModel):
    text: str


class SettingsUpdate(BaseModel):
    settings: Dict[str, Any]


class ImportRequest(BaseModel):
    accounts: List[Dict[str, Any]]


class ImportTextRequest(BaseModel):
    text: str


def account_needs_check(acc: Dict[str, Any]) -> bool:
    """
    Whether an account still needs verifying against Riot. An account counts
    as checked once a real Riot ID has been pulled for it, it has a sync
    timestamp, and its last known status wasn't unverified/banned/suspended.
    """
    has_riot_id = bool(acc.get("display_name") and "#" in acc.get("display_name", ""))
    was_synced = bool(acc.get("last_updated"))
    has_region = bool((acc.get("region") or "").strip())
    status = (acc.get("status") or "").upper()
    return not (has_riot_id and was_synced and has_region and status not in ("UNVERIFIED", "BANNED", "SUSPENDED"))


# Which account this process last saw signed in. The session poll runs every
# few seconds, so "last login" is only stamped when the signed-in account
# actually changes - otherwise it would just track "last seen" and rewrite the
# row (and re-render the roster) on every single tick.
_ACTIVE_SESSION: Dict[str, Any] = {"account_id": None}


def _mark_session_login(account_id: int, stored_last_login: Optional[str]) -> bool:
    """True when this sync is a new sign-in worth stamping a login time on."""
    if _ACTIVE_SESSION["account_id"] == account_id and stored_last_login:
        return False
    _ACTIVE_SESSION["account_id"] = account_id
    return True


def note_account_login(account_id: int) -> None:
    """Records an explicit login/launch as this process's active session."""
    _ACTIVE_SESSION["account_id"] = account_id


def _stay_signed_in_pref() -> bool:
    """Whether automated logins should tick Riot's "Stay signed in"."""
    return db.get_settings().get("stay_signed_in", "1") != "0"


def _auto_launch_pref() -> bool:
    """Whether a plain Login should start VALORANT once it lands."""
    return db.get_settings().get("auto_launch_after_login", "0") == "1"


def apply_account_update(account_id: int, update_payload: dict) -> bool:
    """
    Persists a live-info update for an account, then moves it into the
    Banned tab if the freshly detected status is BANNED/SUSPENDED so it
    doesn't linger in the main roster. Returns True if it was moved.
    """
    status = (update_payload.get("status") or "").upper()
    db.update_account(account_id, update_payload)
    if status in ("BANNED", "SUSPENDED"):
        db.move_to_banned(account_id)
        return True
    return False


async def background_scrape_account(account_id: int, display_name: str, region: str):
    """Background task to fetch live stats, official emblems, peak rank, and match history."""
    info = await asyncio.to_thread(launcher.get_active_riot_account)
    if info and info.get("found") and info.get("display_name", "").lower() == display_name.lower():
        update_data = {k: v for k, v in info.items() if k not in ("found", "username")}
        update_data["last_updated"] = datetime.now().isoformat()
        apply_account_update(account_id, update_data)
        return

    settings = db.get_settings()
    scraper = StatScraper(riot_api_key=settings.get("riot_api_key"))
    stats = await scraper.fetch_account_stats(display_name, region)
    stats["last_updated"] = datetime.now().isoformat()
    apply_account_update(account_id, stats)


async def background_auto_detect_and_link(account_id: int):
    """
    Background worker that watches for successful login in Riot Client,
    automatically grabs the logged-in Riot ID, Region, Level, Rank, Status, and Peak Rank
    directly from Riot servers and updates the database.
    """
    acc_data = db.get_account_by_id(account_id)
    target_username = acc_data.get("username") if acc_data else None

    detected = False
    for _ in range(16):
        await asyncio.sleep(1.8)

        # Check for immediate auth error from Riot lockfile API
        auth_err = await asyncio.to_thread(launcher.check_login_error)
        if auth_err:
            if auth_err in ("auth_failure", "invalid_credentials"):
                client_launcher._set_login_stage(
                    "error", "Invalid username or password. Please check your credentials.", target_username
                )
                return
            elif auth_err in ("rate_limited", "login_error"):
                client_launcher._set_login_stage(
                    "error", "Riot rate limit or login error. Please wait a moment and try again.", target_username
                )
                return

        info = await asyncio.to_thread(launcher.get_active_riot_account, target_username)
        if info and info.get("found") and (info.get("display_name") or info.get("username")):
            detected = True
            client_launcher._set_login_stage(
                "done", f"Logged in as {info.get('display_name') or info.get('username')}"
            )
            update_payload = {k: v for k, v in info.items() if k not in ("found", "username")}
            update_payload["last_updated"] = datetime.now().isoformat()

            lvl = int(info.get("level", 1) or 1)
            current_acc = db.get_account_by_id(account_id)
            if current_acc and current_acc.get("tag") in ("Smurf", "Ranked", "Unrated", "", None):
                update_payload["tag"] = "Ranked" if lvl >= 20 else "Unrated"

            if apply_account_update(account_id, update_payload):
                break

            # Whether "Stay signed in" actually took. Riot only writes the
            # persisted-login blob once auth completes, so this is the first
            # moment it can be checked - and the only way to know, since the
            # checkbox itself can't be read back.
            if _stay_signed_in_pref():
                persisted = await asyncio.to_thread(client_launcher.is_session_persisted)
                client_launcher.LOGIN_PROGRESS["stay_signed_in"] = persisted
                client_launcher.login_logger.info(
                    "[%s] stay-signed-in after login: %s", target_username, persisted
                )

            # Force borderless now rather than only on a Vortex-initiated
            # launch, so the setting still holds if the game gets started from
            # the Riot Client's own Play button.
            session_puuid = (info.get("puuid") or "").strip() or                 await asyncio.to_thread(_current_puuid)
            await _apply_launch_prefs(session_puuid)

            # Start the game straight away when the user has asked for it, so
            # Login behaves like Play without needing the second click.
            if _auto_launch_pref():
                asyncio.create_task(_launch_game_for_current_session())

            # Also fetch match history in background if playable
            detected_id = info.get("display_name")
            detected_region = info.get("region", "NA")
            if detected_id:
                settings = db.get_settings()
                scraper = StatScraper(riot_api_key=settings.get("riot_api_key"))
                stats = await scraper.fetch_account_stats(detected_id, detected_region)
                if stats.get("match_history"):
                    db.update_account(account_id, {"match_history": stats["match_history"]})
            break

    # If we typed the credentials but Riot never confirmed a signed-in
    # session in the time we waited, surface it as an explicit, retryable error.
    if not detected and client_launcher.LOGIN_PROGRESS.get("stage") not in ("done", "error", "idle"):
        client_launcher.login_logger.warning(
            "[%s] auto-detect timed out after login - no confirmed session within 30s", target_username
        )
        client_launcher._set_login_stage(
            "error",
            "Login didn't finish - Riot never confirmed the session. Check the credentials and try again.",
            target_username
        )



async def run_batch_account_check():
    """
    Sequentially logs into accounts with rate-limit pacing,
    extracts Level, Region, Riot ID, Ranks, and Ban/Suspension Status,
    and force closes Riot Client after verification.
    """
    global CHECK_PROGRESS
    accounts = db.get_all_accounts()

    # Skip accounts that have already been verified
    to_check = [a for a in accounts if account_needs_check(a)]

    if not to_check:
        CHECK_PROGRESS["running"] = False
        CHECK_PROGRESS["message"] = f"All {len(accounts)} accounts are already checked!"
        return

    CHECK_PROGRESS["running"] = True
    CHECK_PROGRESS["total"] = len(to_check)
    CHECK_PROGRESS["current"] = 0

    settings = db.get_settings()
    custom_path = settings.get("riot_client_path", "")

    # Clean start: close any previous stuck Riot Client / Valorant
    await asyncio.to_thread(launcher.kill_valorant)
    await asyncio.to_thread(launcher.force_kill_riot_client)
    await asyncio.sleep(1.5)

    for idx, acc in enumerate(to_check, start=1):
        if not CHECK_PROGRESS["running"]:
            break

        CHECK_PROGRESS["current"] = idx
        CHECK_PROGRESS["account"] = acc["username"]
        CHECK_PROGRESS["message"] = f"Checking {acc['username']} ({idx}/{len(to_check)})..."

        # 1. Login via pure keyboard
        await asyncio.to_thread(
            launcher.login_account,
            acc["username"],
            acc["password"],
            custom_path if custom_path else None,
            _stay_signed_in_pref()
        )

        # 2. Rate-limit aware wait & poll loop (up to 7.0s) strictly for this account's username
        detected_info = None
        for _ in range(14):
            if not CHECK_PROGRESS["running"]:
                break
            await asyncio.sleep(0.5)
            info = await asyncio.to_thread(launcher.get_active_riot_account, acc["username"])
            if info and info.get("found") and info.get("username", "").strip().lower() == acc["username"].strip().lower():
                detected_info = info
                break

        # 3. Save captured metadata, or move banned/suspended accounts into
        # the separate banned-accounts store (data kept, not deleted), or
        # remove genuinely dead/invalid credentials.
        if detected_info and detected_info.get("found"):
            status = (detected_info.get("status") or "").upper()
            if status in ("BANNED", "SUSPENDED"):
                update_payload = {k: v for k, v in detected_info.items() if k not in ("found", "username")}
                update_payload["last_updated"] = datetime.now().isoformat()
                db.update_account(acc["id"], update_payload)
                db.move_to_banned(acc["id"])
                CHECK_PROGRESS["message"] = f"Moved banned account to Banned Accounts: {acc['username']}"
            else:
                update_payload = {k: v for k, v in detected_info.items() if k not in ("found", "username")}
                update_payload["last_updated"] = datetime.now().isoformat()

                # Automatically tag level >= 20 as Ranked and < 20 as Unrated
                lvl = int(detected_info.get("level", 1) or 1)
                if acc.get("tag") in ("Ranked", "Unrated", "Smurf", "", None):
                    update_payload["tag"] = "Ranked" if lvl >= 20 else "Unrated"

                db.update_account(acc["id"], update_payload)

                # Scrape match history if display_name found
                if detected_info.get("display_name"):
                    scraper = StatScraper(riot_api_key=settings.get("riot_api_key"))
                    stats = await scraper.fetch_account_stats(detected_info["display_name"], detected_info.get("region", "NA"))
                    if stats.get("match_history"):
                        db.update_account(acc["id"], {"match_history": stats["match_history"]})
        else:
            # Login failed / dead credentials -> auto remove account from database
            db.delete_account(acc["id"])
            CHECK_PROGRESS["message"] = f"Removed dead/invalid account: {acc['username']}"

        # 4. Clean sign out & cooling delay to avoid Riot rate-limits
        await asyncio.to_thread(launcher.api_sign_out)
        await asyncio.sleep(2.0)

        # Reset Riot Client process every 4 accounts to clear UI cache & memory
        if idx % 4 == 0 and idx < len(to_check):
            await asyncio.to_thread(launcher.force_kill_riot_client)
            await asyncio.sleep(1.5)

    # 5. Clean finish: force close Riot Client
    await asyncio.to_thread(launcher.force_kill_riot_client)
    CHECK_PROGRESS["running"] = False
    CHECK_PROGRESS["message"] = "Verification complete! Riot Client closed."


@app.get("/api/accounts")
async def get_accounts(
    search: str = "",
    region: str = "",
    tag: str = "",
    status: str = "",
    sort_by: str = "level"
):
    accounts = db.get_all_accounts(search=search, region=region, tag=tag, status=status, sort_by=sort_by)
    for acc in accounts:
        acc["needs_check"] = account_needs_check(acc)
    return {"accounts": accounts}


@app.get("/api/banned-accounts")
async def get_banned_accounts():
    """Returns accounts moved to the Banned tab - data is kept, not deleted."""
    return {"accounts": db.get_banned_accounts()}


@app.put("/api/banned-accounts/{account_id}")
async def update_banned_account(account_id: int, updates: AccountUpdate):
    """
    Edits an account that lives in the Banned tab.

    Being flagged banned should never make a record read-only: the credentials
    may simply have been typed wrong, or the user may want to correct the Riot
    ID/notes before rechecking. If the edit sets the status back to something
    playable, the account moves back onto the main roster and its new id is
    returned so the caller can follow it.
    """
    acc = db.get_banned_account_by_id(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Banned account not found")

    data = {k: v for k, v in updates.dict().items() if v is not None}
    status = str(data.get("status", "") or "").upper()

    if status and status not in ("BANNED", "SUSPENDED"):
        # Explicitly un-flagged - apply the edit, then move it back.
        if data:
            db.update_banned_account(account_id, data)
        new_id = db.restore_from_banned(account_id)
        if new_id:
            return {
                "success": True,
                "restored_from_banned": True,
                "account": db.get_account_by_id(new_id),
            }

    if data:
        db.update_banned_account(account_id, data)
    return {"success": True, "account": db.get_banned_account_by_id(account_id)}


@app.post("/api/banned-accounts/{account_id}/restore")
async def restore_banned_account(account_id: int):
    """Moves a banned account back onto the main roster without a recheck."""
    if not db.get_banned_account_by_id(account_id):
        raise HTTPException(status_code=404, detail="Banned account not found")

    new_id = db.restore_from_banned(account_id)
    if not new_id:
        raise HTTPException(status_code=404, detail="Banned account not found")

    invalidate_live_snapshot()
    return {"success": True, "account": db.get_account_by_id(new_id)}


@app.delete("/api/banned-accounts/{account_id}")
async def delete_banned_account(account_id: int):
    """Permanently deletes one banned account record (explicit action, not automatic)."""
    success = db.delete_banned_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Banned account not found")
    invalidate_live_snapshot()
    return {"success": True}


@app.post("/api/banned-accounts/{account_id}/recheck")
async def recheck_banned_account(account_id: int):
    """
    Re-verifies a single banned account: logs in, checks its current
    status. If it's actually playable again, moves it back to the main
    roster; if still banned/suspended, refreshes its stored info in place.
    """
    acc = db.get_banned_account_by_id(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Banned account not found")

    settings = db.get_settings()
    custom_path = settings.get("riot_client_path", "")

    await asyncio.to_thread(launcher.force_kill_riot_client)
    await asyncio.sleep(1.0)

    await asyncio.to_thread(
        launcher.login_account,
        acc["username"],
        acc["password"],
        custom_path if custom_path else None,
        _stay_signed_in_pref()
    )

    detected_info = None
    for _ in range(14):
        await asyncio.sleep(0.5)
        info = await asyncio.to_thread(launcher.get_active_riot_account, acc["username"])
        if info and info.get("found") and info.get("username", "").strip().lower() == acc["username"].strip().lower():
            detected_info = info
            break

    await asyncio.to_thread(launcher.api_sign_out)
    await asyncio.to_thread(launcher.force_kill_riot_client)

    if not detected_info or not detected_info.get("found"):
        return {"success": False, "still_banned": True, "message": f"Could not verify {acc['username']} - login failed."}

    status = (detected_info.get("status") or "").upper()
    update_payload = {k: v for k, v in detected_info.items() if k not in ("found", "username")}
    update_payload["last_updated"] = datetime.now().isoformat()

    if status in ("BANNED", "SUSPENDED"):
        db.update_banned_account(account_id, update_payload)
        return {"success": True, "still_banned": True, "message": f"{acc['username']} is still {status.lower()}."}

    db.update_banned_account(account_id, update_payload)
    new_id = db.restore_from_banned(account_id)
    return {
        "success": True,
        "still_banned": False,
        "message": f"{acc['username']} is playable again - moved back to your accounts.",
        "new_account_id": new_id
    }


@app.post("/api/accounts")
async def add_account(account: AccountCreate, background_tasks: BackgroundTasks):
    account_dict = account.dict()
    
    # Auto-fill from active Riot Client only when the logged-in session is
    # actually the account being added. Without this guard, adding account B
    # while account X is signed into the Riot Client stamps X's Riot ID, rank
    # and level onto B.
    typed_username = (account_dict.get("username") or "").strip()
    if not account_dict.get("display_name"):
        info = await asyncio.to_thread(
            launcher.get_active_riot_account,
            typed_username or None,
        )
        if info and info.get("found"):
            if not account_dict.get("username"):
                account_dict["username"] = info.get("username", "")
            account_dict["display_name"] = info.get("display_name", "")
            account_dict["region"] = info.get("region", "NA")
            account_dict["level"] = info.get("level", 1)
            account_dict["rank_tier"] = info.get("rank_tier", "UNRANKED")
            account_dict["rank_division"] = info.get("rank_division", "")
            account_dict["rank_icon_url"] = info.get("rank_icon_url", "")
            account_dict["peak_rank_tier"] = info.get("peak_rank_tier", "")
            account_dict["peak_rank_division"] = info.get("peak_rank_division", "")
            account_dict["peak_rank_icon_url"] = info.get("peak_rank_icon_url", "")
            account_dict["status"] = info.get("status", "PLAYABLE")

    # Don't create a duplicate of something already stored, whether it's in
    # the main roster or sitting in the banned list.
    existing = db.account_exists(account_dict.get("username", ""))
    if existing == "banned":
        return {
            "success": False,
            "duplicate": True,
            "message": f"'{account_dict.get('username', '')}' is already in your Banned Accounts."
        }
    if existing == "active":
        return {
            "success": False,
            "duplicate": True,
            "message": f"'{account_dict.get('username', '')}' is already in your accounts."
        }

    lvl = int(account_dict.get("level", 1) or 1)
    if account_dict.get("tag") in ("Smurf", "Ranked", "Unrated", "", None):
        account_dict["tag"] = "Ranked" if lvl >= 20 else "Unrated"

    account_id = db.add_account(account_dict)
    
    if account_dict.get("display_name"):
        background_tasks.add_task(
            background_scrape_account, account_id, account_dict["display_name"], account_dict.get("region", "NA")
        )
        
    created = db.get_account_by_id(account_id)
    if not created:
        # Was automatically moved to banned
        banned = db.get_banned_account_by_id(account_id)
        return {"success": True, "account": banned, "moved_to_banned": True}
    return {"success": True, "account": created}


# STATIC SUB-ROUTES DECLARED BEFORE {account_id}
@app.post("/api/accounts/check-all")
async def check_all_accounts(background_tasks: BackgroundTasks):
    """Starts the sequential account verification process, skipping already checked accounts."""
    global CHECK_PROGRESS
    if CHECK_PROGRESS["running"]:
        return {"success": False, "message": "Account check is already in progress"}

    accounts = db.get_all_accounts()
    unverified = [a for a in accounts if account_needs_check(a)]

    if not unverified:
        return {
            "success": True, 
            "to_check_count": 0, 
            "skipped_count": len(accounts), 
            "message": f"All {len(accounts)} accounts are already checked! Use 'Sync All' to refresh live ranks."
        }

    background_tasks.add_task(run_batch_account_check)
    skipped_count = len(accounts) - len(unverified)
    skip_msg = f" (skipping {skipped_count} already checked)" if skipped_count > 0 else ""
    return {
        "success": True, 
        "to_check_count": len(unverified), 
        "skipped_count": skipped_count,
        "message": f"Checking {len(unverified)} unverified accounts{skip_msg}..."
    }



@app.get("/api/accounts/check-status")
async def check_accounts_status():
    """Returns current progress of the batch account check."""
    return CHECK_PROGRESS


@app.post("/api/accounts/cancel-check")
async def cancel_check_accounts():
    """Cancels the running batch account check and force-closes Riot Client."""
    global CHECK_PROGRESS
    CHECK_PROGRESS["running"] = False
    CHECK_PROGRESS["message"] = "Verification cancelled. Riot Client closed."
    await asyncio.to_thread(launcher.force_kill_riot_client)
    return {"success": True, "message": "Account check cancelled"}


@app.post("/api/kill-client")
async def kill_riot_client():
    """Force closes all running Riot Client processes."""
    await asyncio.to_thread(launcher.force_kill_riot_client)
    return {"success": True, "message": "Riot Client closed"}



async def run_full_refresh() -> int:
    """
    Refreshes every active account against Riot: live rank/RR, level, peak
    rank, match history, and ban status. Also repairs "ghost" accounts that
    are present in the database but missing a status, so they reappear in
    the roster. Returns the number of accounts whose stats were fetched.

    Shared by the manual "Sync All" button and the periodic auto-refresh.
    """
    global LAST_FULL_REFRESH_AT

    # Repair ghost rows first (NULL/blank status -> PLAYABLE) so they're
    # included in the sync below.
    db.repair_ghost_accounts()

    accounts = db.get_all_accounts()

    # Auto-sync the account currently signed into the Riot Client.
    active_info = await asyncio.to_thread(launcher.get_active_riot_account)
    if active_info and active_info.get("found"):
        act_user = (active_info.get("username") or "").lower()
        act_display = (active_info.get("display_name") or "").lower()
        for acc in accounts:
            if (act_user and act_user == acc["username"].lower()) or (act_display and act_display == acc.get("display_name", "").lower()):
                update_data = {k: v for k, v in active_info.items() if k not in ("found", "username")}
                update_data["last_updated"] = datetime.now().isoformat()
                apply_account_update(acc["id"], update_data)
                break

    settings = db.get_settings()
    scraper = StatScraper(riot_api_key=settings.get("riot_api_key"))

    async def process_acc(acc):
        if not acc.get("display_name"):
            return
        stats = await scraper.fetch_account_stats(acc["display_name"], acc["region"])
        stats["last_updated"] = datetime.now().isoformat()
        apply_account_update(acc["id"], stats)

    accounts = db.get_all_accounts()
    tasks = [process_acc(acc) for acc in accounts if acc.get("display_name")]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    LAST_FULL_REFRESH_AT = time.time()
    return len(tasks)


@app.post("/api/accounts/refresh-all")
async def refresh_all_accounts():
    count = await run_full_refresh()
    return {"success": True, "refreshed_count": count}


# How often the background auto-refresh sweeps the whole roster.
AUTO_REFRESH_INTERVAL_SECONDS = 30 * 60
LAST_FULL_REFRESH_AT = 0.0
_auto_refresh_task = None


async def _auto_refresh_loop():
    """Periodically runs a full roster refresh in the background."""
    # Small initial delay so it doesn't fight the first-launch UI load.
    await asyncio.sleep(90)
    while True:
        try:
            await run_full_refresh()
        except Exception:
            pass
        await asyncio.sleep(AUTO_REFRESH_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_background_workers():
    global _auto_refresh_task
    # Repair ghost accounts immediately on boot, even before the first sweep.
    try:
        db.repair_ghost_accounts()
    except Exception:
        pass
    if _auto_refresh_task is None:
        _auto_refresh_task = asyncio.create_task(_auto_refresh_loop())


# DYNAMIC PARAMETERIZED ROUTES
@app.get("/api/accounts/{account_id}")
async def get_account(account_id: int):
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account": account}


@app.put("/api/accounts/{account_id}")
async def update_account(account_id: int, updates: AccountUpdate, background_tasks: BackgroundTasks):
    data = {k: v for k, v in updates.dict().items() if v is not None}
    moved = apply_account_update(account_id, data)
    if moved:
        return {"success": True, "moved_to_banned": True, "account": db.get_banned_account_by_id(account_id)}

    updated = db.get_account_by_id(account_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found")

    if updates.display_name:
        background_tasks.add_task(
            background_scrape_account, account_id, updated["display_name"], updated["region"]
        )

    return {"success": True, "account": updated}


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int):
    success = db.delete_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"success": True}


@app.post("/api/accounts/{account_id}/toggle-favorite")
async def toggle_favorite(account_id: int):
    success = db.toggle_favorite(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"success": True, "account": db.get_account_by_id(account_id)}


@app.post("/api/accounts/{account_id}/refresh")
async def refresh_account_stats(account_id: int):
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    info = await asyncio.to_thread(launcher.get_active_riot_account, account["username"])
    if info and info.get("found"):
        act_user = (info.get("username") or "").lower()
        act_display = (info.get("display_name") or "").lower()
        if (act_user and act_user == account["username"].lower()) or (act_display and act_display == account.get("display_name", "").lower()):
            update_data = {k: v for k, v in info.items() if k not in ("found", "username")}
            update_data["last_updated"] = datetime.now().isoformat()
            moved = apply_account_update(account_id, update_data)
            if moved:
                return {"success": True, "moved_to_banned": True,
                        "message": f"{account['username']} is banned/suspended - moved to Banned Accounts."}
            return {"success": True, "account": db.get_account_by_id(account_id)}

    if not account["display_name"]:
        return {"success": False, "message": "No Riot ID found. Log in to this account to auto-sync stats."}

    settings = db.get_settings()
    scraper = StatScraper(riot_api_key=settings.get("riot_api_key"))
    stats = await scraper.fetch_account_stats(account["display_name"], account["region"])
    stats["last_updated"] = datetime.now().isoformat()
    moved = apply_account_update(account_id, stats)
    if moved:
        return {"success": True, "moved_to_banned": True,
                "message": f"{account['username']} is banned/suspended - moved to Banned Accounts."}

    return {"success": True, "account": db.get_account_by_id(account_id)}


@app.get("/api/accounts/{account_id}/matches")
async def get_account_matches(account_id: int):
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    matches = account.get("match_history", [])
    if not matches and account["display_name"]:
        settings = db.get_settings()
        scraper = StatScraper(riot_api_key=settings.get("riot_api_key"))
        stats = await scraper.fetch_account_stats(account["display_name"], account["region"])
        stats["last_updated"] = datetime.now().isoformat()
        db.update_account(account_id, stats)
        account = db.get_account_by_id(account_id)
        matches = account.get("match_history", []) if account else []

    return {
        "success": True,
        "account_id": account_id,
        "display_name": account.get("display_name", "") if account else "",
        "matches": matches
    }


@app.get("/api/sync-active-account")
async def sync_active_account():
    """
    Called every 4-5s by frontend to automatically sync the currently logged-in
    Riot Client session with the corresponding account in SQLite.
    """
    info = await asyncio.to_thread(launcher.get_active_riot_account)
    if not info or not info.get("found"):
        return {"success": True, "synced": False, "message": "No active logged-in Riot Client session."}

    accounts = db.get_all_accounts()
    act_user = (info.get("username") or "").lower()
    act_display = (info.get("display_name") or "").lower()

    matched_acc = None
    for acc in accounts:
        if act_user and acc["username"].strip().lower() == act_user.strip().lower():
            matched_acc = acc
            break

    if matched_acc:
        update_data = {k: v for k, v in info.items() if k not in ("found", "username")}
        update_data["last_updated"] = datetime.now().isoformat()
        if _mark_session_login(matched_acc["id"], matched_acc.get("last_login")):
            update_data["last_login"] = datetime.now().isoformat()
        moved = apply_account_update(matched_acc["id"], update_data)
        return {
            "success": True,
            "synced": True,
            "moved_to_banned": moved,
            "account_id": matched_acc["id"],
            "display_name": info.get("display_name"),
            "region": info.get("region"),
            "level": info.get("level"),
            "status": info.get("status")
        }

    # Check if this active account is in banned_accounts
    banned_accs = db.get_banned_accounts()
    for b_acc in banned_accs:
        if act_user and b_acc["username"].strip().lower() == act_user.strip().lower():
            status = (info.get("status") or "").upper()
            update_data = {k: v for k, v in info.items() if k not in ("found", "username")}
            update_data["last_updated"] = datetime.now().isoformat()
            if status == "PLAYABLE":
                db.update_banned_account(b_acc["id"], update_data)
                new_id = db.restore_from_banned(b_acc["id"])
                return {
                    "success": True,
                    "synced": True,
                    "restored_from_banned": True,
                    "account_id": new_id,
                    "display_name": info.get("display_name"),
                    "status": "PLAYABLE"
                }
            else:
                db.update_banned_account(b_acc["id"], update_data)
                return {
                    "success": True,
                    "synced": True,
                    "is_banned": True,
                    "account_id": b_acc["id"],
                    "display_name": info.get("display_name"),
                    "status": status
                }

    return {"success": True, "synced": False, "found_riot_id": info.get("display_name")}


@app.post("/api/accounts/{account_id}/launch")
async def launch_account(account_id: int, background_tasks: BackgroundTasks,
                         in_place: bool = False):
    """
    Logs an account in. `in_place` retries into the sign-in page that is
    already open instead of restarting the client - what the Retry button
    wants, since the window on screen is usually fine and only reloaded.
    """
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    settings = db.get_settings()
    custom_path = settings.get("riot_client_path", "")

    result = await asyncio.to_thread(
        launcher.login_account,
        account["username"],
        account["password"],
        custom_path if custom_path else None,
        _stay_signed_in_pref(),
        not in_place
    )

    # Only a login that actually started should change account history or arm
    # a verifier.  Failed/busy clicks previously looked like successful use.
    if result.get("success"):
        db.update_account(account_id, {"last_login": datetime.now().isoformat()})
        note_account_login(account_id)
        background_tasks.add_task(background_auto_detect_and_link, account_id)
    
    return {
        "success": result["success"],
        "message": result["message"],
        "account_id": account_id,
        "copied": "password" if result.get("success") else ""
    }


@app.get("/api/login-progress")
async def login_progress():
    """Live progress of the in-flight Riot Client login, for the UI animation."""
    return client_launcher.LOGIN_PROGRESS


@app.get("/api/detect-active-account")
async def detect_active_account():
    info = await asyncio.to_thread(launcher.get_active_riot_account)
    if info:
        return {"success": True, **info}
    return {"success": True, "found": False, "message": "No active logged-in Riot Client session found."}


@app.post("/api/copy")
async def copy_text(req: CopyRequest):
    success = launcher.copy_to_clipboard(req.text)
    return {"success": success}


@app.get("/api/stats-summary")
async def stats_summary():
    return db.get_stats_summary()


@app.get("/api/settings")
async def get_settings():
    return db.get_settings()


@app.post("/api/settings")
async def update_settings(req: SettingsUpdate):
    db.update_settings(req.settings)
    return {"success": True, "settings": db.get_settings()}


@app.get("/api/detect-client")
async def detect_client():
    path = launcher.detect_riot_client_path()
    return {"found": bool(path), "path": path or ""}


@app.get("/api/diagnostics")
async def diagnostics():
    """
    Whether the pieces the login depends on are actually working in this
    build. UI Automation in particular behaves differently frozen than it
    does from source, and it's the only way the "Stay signed in" checkbox
    can be set - so if it ever stops loading, this says so plainly instead
    of the checkbox silently never being ticked.
    """
    def probe():
        uia = client_launcher._uia()
        return {
            "ui_automation": uia is not None,
            "riot_window": bool(launcher.find_riot_window()),
            "session_persisted": client_launcher.is_session_persisted(),
            "stay_signed_in_enabled": _stay_signed_in_pref(),
            "auto_launch_after_login": _auto_launch_pref(),
            "version": APP_VERSION,
        }

    return await asyncio.to_thread(probe)


@app.get("/api/login-log-path")
async def login_log_path():
    """Where the login/check debug log lives, for Settings' 'Open Log' button."""
    return {"path": client_launcher.LOGIN_LOG_FILE, "exists": os.path.exists(client_launcher.LOGIN_LOG_FILE)}


@app.post("/api/open-login-log")
async def open_login_log():
    """Opens Explorer with the debug log selected, same pattern the updater uses."""
    path = client_launcher.LOGIN_LOG_FILE
    if not os.path.exists(path):
        return {"success": False, "message": "No log file yet - nothing has been logged this session."}
    try:
        await asyncio.to_thread(
            subprocess.Popen, ["explorer.exe", "/select,", os.path.normpath(path)]
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "message": f"Couldn't open the log folder: {e}"}


@app.get("/api/app-version")
async def app_version():
    """Returns the running app's version, for display in Settings/About."""
    return {"version": APP_VERSION}


@app.get("/api/check-update")
async def check_update():
    """
    Checks asarii.xyz for a newer release. Returns available:false if this
    is already the latest version, or if the check fails for any reason
    (offline, host unreachable, etc.) - never raises.
    """
    update_info = await asyncio.to_thread(updater.check_for_update)
    if not update_info:
        return {"available": False, "current_version": APP_VERSION}
    return {
        "available": True,
        "current_version": APP_VERSION,
        "latest_version": update_info["version"],
        "download_url": update_info["url"],
        "notes": update_info.get("notes", "")
    }


@app.post("/api/download-and-install-update")
async def download_and_install_update():
    """
    Downloads the latest installer and triggers an automated silent update & relaunch.
    """
    update_info = await asyncio.to_thread(updater.check_for_update)
    if not update_info:
        return {"success": False, "message": "No update available."}

    installer_path = await asyncio.to_thread(updater.download_installer, update_info["url"], update_info["version"])
    if not installer_path:
        return {"success": False, "message": "Failed to download the update. Check your connection and try again."}

    # The background updater has to confirm it is armed before Vortex will
    # close. If it can't, the app stays open and the user gets the installer
    # in Explorer - far better than an app that exits into nothing and has to
    # be reinstalled by hand.
    launched = await asyncio.to_thread(updater.apply_and_relaunch, installer_path, update_info["version"])
    if not launched:
        await asyncio.to_thread(updater.reveal_installer, installer_path)
        return {
            "success": True,
            "relaunching": False,
            "message": f"Version {update_info['version']} downloaded, but the automatic "
                       f"restart couldn't start. Vortex is staying open - run the installer "
                       f"that just opened to finish updating."
        }

    # Schedule clean app exit after 1.2s so response reaches client
    def _exit_app():
        time.sleep(1.2)
        # Releases the updater. It does nothing until this lands.
        updater.commit_update()
        os._exit(0)

    threading.Thread(target=_exit_app, daemon=True).start()

    return {
        "success": True,
        "relaunching": True,
        "message": f"Updating to v{update_info['version']}... Vortex will restart in a moment."
    }


@app.get("/api/export")
async def export_accounts():
    accounts = db.export_all()
    return JSONResponse(
        content={"accounts": accounts, "exported_at": datetime.now().isoformat()},
        headers={"Content-Disposition": "attachment; filename=valorant_accounts_backup.json"}
    )


@app.post("/api/import")
async def import_accounts(req: ImportRequest):
    result = db.import_all(req.accounts)
    return {
        "success": True,
        "imported_count": result["imported"],
        "skipped_existing": result["skipped_existing"],
        "skipped_banned": result["skipped_banned"]
    }


@app.post("/api/import-text")
async def import_text_accounts(req: ImportTextRequest, background_tasks: BackgroundTasks):
    result = db.import_from_text(req.text)
    created = result["created"]

    for acc in created:
        if acc.get("display_name"):
            background_tasks.add_task(
                background_scrape_account, acc["id"], acc["display_name"], acc.get("region", "NA")
            )

    return {
        "success": True,
        "imported_count": len(created),
        "skipped_existing": result["skipped_existing"],
        "skipped_banned": result["skipped_banned"],
        "accounts": created
    }


# ==========================================================================
# LIVE SESSION / MATCH DASHBOARD
#
# Everything below drives the dashboard that opens for whichever account is
# currently signed in to the Riot Client: live match tracking, queue and
# mode control, and the insta-lock watcher.
# ==========================================================================

# The dashboard polls once a second or two and several widgets read the same
# snapshot, so one build is shared for a short window rather than firing a
# fresh set of Riot requests per caller.
_LIVE_SNAPSHOT: Dict[str, Any] = {"data": None, "built_at": 0.0}
_LIVE_SNAPSHOT_TTL = 1.2

# Identity seen on the previous poll for a username that isn't in the DB yet,
# keyed by username: (identity_tuple, seen_at). Used to require a stable read
# before auto-creating an account row - see build_live_snapshot().
_PENDING_AUTO_ADD: Dict[str, Any] = {}
_LIVE_SNAPSHOT_LOCK = threading.Lock()
_LIVE_OWNER_PUUID = ""

# Roster names don't change inside a match, so they're resolved once per match.
_NAME_CACHE: Dict[str, Dict[str, str]] = {}


class ModeRequest(BaseModel):
    queue_id: str


class QueueStartRequest(BaseModel):
    queue_id: Optional[str] = None


class InstalockRequest(BaseModel):
    agent_id: Optional[str] = ""
    enabled: bool = True


class LockNowRequest(BaseModel):
    agent_id: str


class GameConfigSettingsRequest(BaseModel):
    force_borderless: Optional[bool] = None
    autoapply: Optional[bool] = None
    profile_account_id: Optional[int] = None  # 0 clears it
    stay_signed_in: Optional[bool] = None
    auto_launch_after_login: Optional[bool] = None


class GameConfigCopyRequest(BaseModel):
    source_account_id: int
    target_account_id: Optional[int] = None  # omitted = whoever's signed in now
    gameplay: bool = True
    video: bool = True


class PresetCaptureRequest(BaseModel):
    account_id: Optional[int] = None   # omitted = whoever's signed in now
    set_as_profile: bool = True


class PresetApplyRequest(BaseModel):
    account_id: Optional[int] = None   # omitted = whoever's signed in now
    all_accounts: bool = False


class GameConfigCopyAllRequest(BaseModel):
    source_account_id: int
    gameplay: bool = True
    video: bool = True


class GameConfigBorderlessRequest(BaseModel):
    account_id: Optional[int] = None  # omitted = whoever's signed in now
    all_accounts: bool = False        # set every account that has config here


class OverlaySettingsRequest(BaseModel):
    overlay_enabled: Optional[bool] = None
    fps_enabled: Optional[bool] = None


class OverlaySwitchRequest(BaseModel):
    launch_game: bool = True
    confirm_close_game: bool = False


# Matchmaking start time. The party payload carries one, but it's only
# trustworthy while the party is actually queueing - the fallback is the
# moment this process first saw the party flip into MATCHMAKING.
_QUEUE_TIMER: Dict[str, Any] = {"key": "", "started_at": 0.0}


def _queue_elapsed(party: Dict[str, Any], in_queue: bool) -> int:
    """Seconds spent in the current queue, or 0 when not queueing."""
    if not in_queue:
        _QUEUE_TIMER.update({"key": "", "started_at": 0.0})
        return 0

    raw = (party.get("QueueEntryTime") or "").strip()
    started = 0.0
    if raw and not raw.startswith("0001"):
        for fmt in ("%Y.%m.%d-%H.%M.%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                parsed = datetime.strptime(raw, fmt)
                started = parsed.replace(tzinfo=timezone.utc).timestamp()
                break
            except ValueError:
                continue

    key = f"{party.get('ID', '')}:{(party.get('MatchmakingData') or {}).get('QueueID', '')}"
    if started <= 0:
        if _QUEUE_TIMER["key"] != key or not _QUEUE_TIMER["started_at"]:
            _QUEUE_TIMER.update({"key": key, "started_at": time.time()})
        started = _QUEUE_TIMER["started_at"]
    else:
        _QUEUE_TIMER.update({"key": key, "started_at": started})

    return max(0, int(time.time() - started))


def _match_account_to_session(username: str, display_name: str = "", puuid: str = "") -> Optional[Dict[str, Any]]:
    """Finds the stored account matching the signed-in Riot Client username, display name, or PUUID."""
    accounts = db.get_all_accounts()
    u_target = username.strip().lower() if username else ""
    d_target = display_name.strip().lower() if display_name else ""
    p_target = puuid.strip() if puuid else ""

    # 1. Match by username
    if u_target:
        for acc in accounts:
            if acc.get("username", "").strip().lower() == u_target:
                return acc

    # 2. Match by display name (Riot ID e.g. Name#TAG)
    if d_target:
        for acc in accounts:
            if acc.get("display_name", "").strip().lower() == d_target:
                return acc

    # 3. Match by PUUID
    if p_target:
        for acc in accounts:
            if acc.get("puuid") and acc["puuid"].strip() == p_target:
                return acc

    return None


def _match_banned_to_session(username: str, display_name: str = "") -> Optional[Dict[str, Any]]:
    """
    Same lookup as _match_account_to_session, but over the banned store.

    A banned account is still a real, signed-in session - it just lives in a
    different table. Without this the live snapshot came back with no
    account_id at all, which is what left the "currently logged in" card
    pointing at nothing and refusing to edit or delete.
    """
    u_target = (username or "").strip().lower()
    d_target = (display_name or "").strip().lower()
    if not (u_target or d_target):
        return None

    banned = db.get_banned_accounts()
    if u_target:
        for acc in banned:
            if (acc.get("username") or "").strip().lower() == u_target:
                return acc
    if d_target:
        for acc in banned:
            if (acc.get("display_name") or "").strip().lower() == d_target:
                return acc
    return None


_PLAYER_MMR_CACHE: Dict[str, Dict[str, Any]] = {}
_PLAYER_MMR_TTL = 10 * 60.0
_PLAYER_MMR_NEGATIVE_TTL = 30.0


def _player_stats_cache_fresh(puuid: str) -> bool:
    cached = _PLAYER_MMR_CACHE.get(puuid) or {}
    cached_at = float(cached.get("_cached_at") or 0.0)
    ttl = float(cached.get("_cache_ttl") or _PLAYER_MMR_TTL)
    return bool(cached_at and (time.monotonic() - cached_at) < ttl)


def _get_player_stats(client, puuid: str, fallback_tier: int = 0) -> Dict[str, Any]:
    if not puuid:
        return valorant_client.parse_player_mmr({})
    if _player_stats_cache_fresh(puuid):
        return _PLAYER_MMR_CACHE[puuid]

    try:
        raw_mmr = client.player_mmr(puuid)
        stats = valorant_client.parse_player_mmr(raw_mmr)
    except Exception:
        stats = valorant_client.parse_player_mmr({})

    combat_keys = (
        "kd", "kda", "hs_pct", "kills", "deaths", "assists", "adr", "acs",
        "winrate_last5", "last5_wins", "last5_losses", "last5_games", "last5_form"
    )
    try:
        combat = client.player_combat_summary(puuid, max_matches=5)
    except Exception:
        combat = {}
    for key in combat_keys:
        if key in ("kd", "kda"):
            stats[key] = combat.get(key, 0.0)
        elif key == "last5_form":
            stats[key] = combat.get(key, [])
        else:
            stats[key] = combat.get(key, 0)
    # Kept off the roster payload - it only feeds the premade grouping.
    stats["parties"] = combat.get("parties") or {}
    stats["party_partners"] = combat.get("party_partners") or []

    if stats["tier"] == 0 and fallback_tier > 0:
        stats["tier"] = fallback_tier
        stats["tier_label"] = valorant_client.tier_label(fallback_tier)
        stats["tier_icon"] = valorant_client.tier_icon(fallback_tier)
        if stats["peak_tier"] < fallback_tier:
            stats["peak_tier"] = fallback_tier
            stats["peak_tier_label"] = stats["tier_label"]
            stats["peak_tier_icon"] = stats["tier_icon"]

    has_real_data = bool(
        stats.get("tier") or stats.get("games") or stats.get("last5_games")
        or stats.get("kills") or stats.get("deaths")
    )
    stats["_cached_at"] = time.monotonic()
    stats["_cache_ttl"] = _PLAYER_MMR_TTL if has_real_data else _PLAYER_MMR_NEGATIVE_TTL

    if len(_PLAYER_MMR_CACHE) > 60:
        _PLAYER_MMR_CACHE.clear()
    _PLAYER_MMR_CACHE[puuid] = stats
    return stats


def _roster_entry(client, player: Dict[str, Any], names: Dict[str, str], self_puuid: str) -> Dict[str, Any]:
    agent = valorant_client.agent_by_id(player.get("CharacterID", ""))
    seasonal_tier = (player.get("SeasonalBadgeInfo") or {}).get("Rank") or player.get("CompetitiveTier") or 0
    subject = player.get("Subject", "")
    identity = player.get("PlayerIdentity", {}) or {}
    level = identity.get("AccountLevel", 0)

    stats = _get_player_stats(client, subject, seasonal_tier)

    tier = stats.get("tier") or seasonal_tier or 0
    tier_label = stats.get("tier_label") or valorant_client.tier_label(tier)
    tier_icon = stats.get("tier_icon") or valorant_client.tier_icon(tier)

    return {
        "puuid": subject,
        "name": names.get(subject, "") or ("Hidden" if identity.get("Incognito") else ""),
        "agent": agent.get("name", ""),
        "agent_icon": agent.get("icon", ""),
        "team": player.get("TeamID", ""),
        "level": level,
        "tier": tier,
        "tier_label": tier_label,
        "tier_icon": tier_icon,
        "rr": stats.get("rr", 0),
        "peak_tier": stats.get("peak_tier", 0),
        "peak_tier_label": stats.get("peak_tier_label", "Unranked"),
        "peak_tier_icon": stats.get("peak_tier_icon", valorant_client.tier_icon(0)),
        "wins": stats.get("wins", 0),
        "games": stats.get("games", 0),
        "winrate": stats.get("winrate", 0),
        "winrate_last5": stats.get("winrate_last5", 0),
        "last5_wins": stats.get("last5_wins", 0),
        "last5_losses": stats.get("last5_losses", 0),
        "last5_games": stats.get("last5_games", 0),
        "last5_form": stats.get("last5_form", []),
        "kd": stats.get("kd", 0.0),
        "kda": stats.get("kda", 0.0),
        "hs_pct": stats.get("hs_pct", 0),
        "adr": stats.get("adr", 0),
        "acs": stats.get("acs", 0),
        "is_self": subject == self_puuid,
        "locked": (player.get("CharacterSelectionState", "") == "locked"),
    }


_MY_PARTY: Dict[str, Any] = {"at": 0.0, "puuid": "", "members": []}


def _my_party_members(client) -> List[str]:
    """
    PUUIDs in your current party. This is the one grouping Riot will state
    outright, so it anchors the premade detection. Cached briefly - party
    membership can't change mid-match and the snapshot already calls it.
    """
    if _MY_PARTY.get("puuid") == client.puuid and time.time() - _MY_PARTY["at"] < 8.0:
        return _MY_PARTY["members"]
    try:
        members = [
            (m.get("Subject") or "")
            for m in (client.party().get("Members") or [])
            if m.get("Subject")
        ]
    except Exception:
        members = []
    _MY_PARTY.update({"at": time.time(), "puuid": client.puuid, "members": members})
    return members


def _cached_names(client, match_id: str, puuids: List[str]) -> Dict[str, str]:
    cached = _NAME_CACHE.get(match_id)
    if cached is not None:
        return cached

    names = client.resolve_names(puuids)
    if names:
        # One entry per match is plenty - drop the oldest once it grows.
        if len(_NAME_CACHE) > 8:
            _NAME_CACHE.clear()
        _NAME_CACHE[match_id] = names
    return names


# --------------------------------------------------------------------------
# LIVE MATCH PROGRESS
#
# Riot publishes the running score through presence but never a round-by-round
# history, and match-details stays empty until a match is actually over. So
# the round ledger below is built by watching the score change while the
# dashboard polls, and the personal scoreline is filled in the moment Riot
# will answer for that match id.
# --------------------------------------------------------------------------

# How many rounds win the match, per queue. Modes without a round race (the
# deathmatches, escalation, snowball) map to 0 and just don't show a target.
ROUNDS_TO_WIN = {
    "competitive": 13,
    "unrated": 13,
    "premier": 13,
    "newmap": 13,
    "onefa": 13,
    "swiftplay": 5,
    "spikerush": 4,
}

_MATCH_PROGRESS: Dict[str, Any] = {
    "match_id": "",
    "ally": 0,
    "enemy": 0,
    "rounds": [],
    "started_at": 0.0,
}

# Best-effort probe for the live match's own stats. Ranked and unrated only
# answer once the match ends, so this is retried slowly rather than per poll.
_LIVE_PROBE: Dict[str, Any] = {"match_id": "", "next_at": 0.0, "data": None, "at_rounds": -1}
# How often the in-progress match is re-read. Modes that answer mid-match
# (deathmatch, custom, practice) update at this cadence; modes that don't
# answer until the end just miss this often, which is cheap.
_LIVE_PROBE_INTERVAL = 6.0

# The match that just finished, resolved after the fact. Details take a few
# seconds to appear, so the lookup is retried on a backoff before giving up.
_LAST_MATCH: Dict[str, Any] = {
    "watch_id": "", "match_id": "", "data": None, "next_at": 0.0, "tries": 0,
}
_LAST_MATCH_MAX_TRIES = 12

# Everything played while this app has been running, for the session strip.
_SESSION: Dict[str, Any] = {"puuid": "", "ids": [], "matches": [], "started_at": 0.0}


def _half_length(queue_id: str) -> int:
    """Regulation rounds per half for the queues that use round halves."""
    return {
        "swiftplay": 4,
        "spikerush": 3,
    }.get((queue_id or "").lower(), 12)


def _side_for_round(starting_side: str, rounds_played: int, queue_id: str = "") -> str:
    """Which side you are on for the round after `rounds_played` completed ones."""
    other = "Attacker" if starting_side == "Defender" else "Defender"
    half = _half_length(queue_id)
    if rounds_played < half:
        return starting_side
    if rounds_played < half * 2:
        return other
    # Competitive overtime swaps attack/defence after every round.
    return other if (rounds_played - half * 2) % 2 == 0 else starting_side


def _track_rounds(match_id: str, ally: int, enemy: int, starting_side: str,
                  queue_id: str = "") -> List[Dict[str, Any]]:
    """
    Appends whatever rounds have completed since the last poll and returns the
    full ledger. A match the dashboard joined late is seeded from the score
    with the entries flagged `known: false`, because the order in which those
    rounds fell simply isn't recoverable.
    """
    p = _MATCH_PROGRESS
    total = ally + enemy

    if p["match_id"] != match_id:
        seeded = (
            [{"n": 0, "won": True, "known": False, "side": ""} for _ in range(ally)] +
            [{"n": 0, "won": False, "known": False, "side": ""} for _ in range(enemy)]
        )
        for idx, entry in enumerate(seeded):
            entry["n"] = idx + 1
        p.update({
            "match_id": match_id, "ally": ally, "enemy": enemy,
            "rounds": seeded, "started_at": time.time(),
        })
        return p["rounds"]

    # A transient empty presence can report 0-0 in the middle of a match.
    # Never rewind the ledger for the same match; wait for a monotonic score.
    if ally < p["ally"] or enemy < p["enemy"]:
        return p["rounds"]

    ally_delta = ally - p["ally"]
    enemy_delta = enemy - p["enemy"]
    delta_total = ally_delta + enemy_delta
    played = len(p["rounds"])

    # Only a one-round delta has a knowable winner/order.  If the app slept
    # through several rounds, retain the score but mark those pips unknown
    # instead of inventing a win/loss order and a false streak.
    for won, count in ((True, ally_delta), (False, enemy_delta)):
        for _ in range(count):
            played += 1
            p["rounds"].append({
                "n": played,
                "won": won,
                "known": delta_total == 1,
                "side": _side_for_round(starting_side, played - 1, queue_id) if delta_total == 1 else "",
            })

    p["ally"], p["enemy"] = ally, enemy

    # A ledger that drifted out of step with the score (a poll missed while
    # the app was asleep) is trimmed back rather than left lying.
    if len(p["rounds"]) > total:
        p["rounds"] = p["rounds"][:total]
    return p["rounds"]


def _round_streak(rounds: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Length and kind of the run of rounds ending the ledger."""
    if not rounds:
        return {"count": 0, "won": False}
    if not rounds[-1].get("known"):
        return {"count": 0, "won": False}
    won = rounds[-1]["won"]
    count = 0
    for entry in reversed(rounds):
        if not entry.get("known") or entry["won"] != won:
            break
        count += 1
    return {"count": count, "won": won}


def _build_progress(match_id: str, ally: int, enemy: int, starting_side: str,
                    current_side: str, queue_id: str) -> Dict[str, Any]:
    """The rounds-won/lost header block for a match that's running."""
    rounds = _track_rounds(match_id, ally, enemy, starting_side, queue_id)
    played = ally + enemy
    target = ROUNDS_TO_WIN.get((queue_id or "").lower(), 0)

    half_len = _half_length(queue_id)
    if played < half_len:
        half = "1st Half"
    elif played < half_len * 2:
        half = "2nd Half"
    else:
        half = f"Overtime {(played - half_len * 2) + 1}"
    if target and target < 13:
        half = ""

    return {
        "rounds_won": ally,
        "rounds_lost": enemy,
        "rounds_played": played,
        "round_number": played + 1,
        "rounds_to_win": target,
        "match_point": bool(target and ally == target - 1 and ally > enemy),
        "elim_point": bool(target and enemy == target - 1 and enemy > ally),
        "diff": ally - enemy,
        "half": half,
        "streak": _round_streak(rounds),
        "history": rounds[-30:],
        "watched_for": int(time.time() - (_MATCH_PROGRESS["started_at"] or time.time())),
        "current_side": current_side,
        "starting_side": starting_side,
    }


def _live_probe(client, match_id: str, rounds_played: int = -1) -> Optional[Dict[str, Any]]:
    """
    Your own scoreline for the match in progress, re-read as the match runs.

    Modes that publish mid-match (deathmatch, custom, practice) answer every
    time, so this keeps asking rather than freezing on the first answer - that
    freeze is what made the "live" numbers stop moving after the first round.
    Ranked and unrated only publish once the match ends, so a miss is normal;
    the last good answer is kept so the panel doesn't flicker back to empty,
    and a fresh read is forced the moment the round score moves.
    """
    p = _LIVE_PROBE
    if p["match_id"] != match_id:
        p.update({"match_id": match_id, "next_at": 0.0, "data": None, "at_rounds": -1})

    # A completed round is the only moment the numbers can actually have
    # changed, so it always earns a read regardless of the interval.
    round_changed = rounds_played >= 0 and rounds_played != p["at_rounds"]
    if not round_changed and time.time() < p["next_at"]:
        return p["data"]

    p["next_at"] = time.time() + _LIVE_PROBE_INTERVAL
    fresh = valorant_client.personal_match_summary(client, match_id, live=True)
    # Record the attempted score even on the expected ranked/unrated miss.
    # Otherwise every 1.2s snapshot sees the same round as "changed" and
    # defeats the six-second backoff above.
    p["at_rounds"] = rounds_played
    if fresh:
        p["data"] = fresh
    return p["data"]


def _self_block(client, match_id: str, me: Optional[Dict[str, Any]],
                queue_id: str, progress: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    The "you, right now" card: agent and rank straight from the match, plus two
    strictly separated combat lines.

    `current` is THIS match and nothing else. It is only populated from a real
    read of this match's details - when Riot hasn't published them yet the
    numbers stay None and `current.available` is false, so the UI can say so
    instead of quietly showing a rolling average under a "current match" label,
    which is what made the old panel look live without being live.

    `recent` is the rolling last-5-matches average, always labelled as such.
    """
    if not me:
        return None

    progress = progress or {}
    rounds_played = int(progress.get("rounds_played", -1) or 0) if progress else -1
    live = _live_probe(client, match_id, rounds_played) if match_id else None

    # What the round ledger alone can tell us about this match. This part is
    # live every poll, with no dependency on Riot publishing match details.
    rounds_won = int(progress.get("rounds_won", 0) or 0)
    rounds_lost = int(progress.get("rounds_lost", 0) or 0)
    played = rounds_won + rounds_lost
    history = progress.get("history") or []
    attack_won = sum(1 for r in history if r.get("known") and r.get("side") == "Attacker" and r.get("won"))
    attack_played = sum(1 for r in history if r.get("known") and r.get("side") == "Attacker")
    defense_won = sum(1 for r in history if r.get("known") and r.get("side") == "Defender" and r.get("won"))
    defense_played = sum(1 for r in history if r.get("known") and r.get("side") == "Defender")

    current: Dict[str, Any] = {
        "available": False,
        "reason": "Riot publishes this match's combat stats when it ends.",
        "kills": None,
        "deaths": None,
        "assists": None,
        "kda_line": None,
        "kd": None,
        "kda": None,
        "hs_pct": None,
        "adr": None,
        "acs": None,
        "headshots": 0,
        "bodyshots": 0,
        "legshots": 0,
        "shots": 0,
        "damage": 0,
        # Round-derived - live every poll, whatever Riot is or isn't publishing.
        "rounds_played": played,
        "rounds_won": rounds_won,
        "rounds_lost": rounds_lost,
        "round_number": progress.get("round_number", played + 1),
        "round_winrate": round(rounds_won / played * 100, 1) if played else 0.0,
        "streak": progress.get("streak", {"count": 0, "won": False}),
        "attack_record": {"won": attack_won, "played": attack_played},
        "defense_record": {"won": defense_won, "played": defense_played},
    }

    if live:
        kills = int(live.get("kills", 0) or 0)
        deaths = int(live.get("deaths", 0) or 0)
        assists = int(live.get("assists", 0) or 0)
        head = int(live.get("headshots", 0) or 0)
        body = int(live.get("bodyshots", 0) or 0)
        leg = int(live.get("legshots", 0) or 0)
        shots = head + body + leg
        live_rounds = int(live.get("rounds", 0) or 0) or played

        current.update({
            "available": True,
            "reason": "",
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "kda_line": f"{kills}/{deaths}/{assists}",
            "kd": round(kills / max(1, deaths), 2),
            "kda": round((kills + assists) / max(1, deaths), 2),
            "hs_pct": round(head / shots * 100, 1) if shots else 0.0,
            "adr": live.get("adr", 0),
            "acs": live.get("acs", 0),
            "headshots": head,
            "bodyshots": body,
            "legshots": leg,
            "shots": shots,
            "damage": int(live.get("total_damage", 0) or 0),
            "kills_per_round": round(kills / max(1, live_rounds), 2),
        })

    recent = {
        "kd": me.get("kd", 0.0),
        "kda": me.get("kda", 0.0),
        "hs_pct": me.get("hs_pct", 0),
        "adr": me.get("adr", 0),
        "acs": me.get("acs", 0),
        "games": me.get("last5_games", 0) or me.get("games", 0),
        "winrate": me.get("winrate_last5", me.get("winrate", 0)),
    }

    block = {
        "name": me.get("name", ""),
        "agent": me.get("agent", ""),
        "agent_icon": me.get("agent_icon", ""),
        "level": me.get("level", 0),
        "tier": me.get("tier", 0),
        "tier_label": me.get("tier_label", "Unranked"),
        "tier_icon": me.get("tier_icon", ""),
        "rr": me.get("rr", 0),
        "peak_tier_label": me.get("peak_tier_label", ""),
        "peak_tier_icon": me.get("peak_tier_icon", ""),
        "winrate": me.get("winrate", 0),
        "wins": me.get("wins", 0),
        "games": me.get("games", 0),
        "winrate_last5": me.get("winrate_last5", 0),
        "last5_wins": me.get("last5_wins", 0),
        "last5_losses": me.get("last5_losses", 0),
        "last5_games": me.get("last5_games", 0),
        "last5_form": me.get("last5_form", []),
        "queue_id": queue_id,

        "current": current,
        "recent": recent,

        # Provenance, kept unambiguous: "live" only ever means this match.
        "source": "live" if current["available"] else "recent",
        "is_live_match": current["available"],
        "recent_kd": recent["kd"],
        "recent_hs_pct": recent["hs_pct"],
        "recent_adr": recent["adr"],
        "recent_acs": recent["acs"],
    }

    # Flat mirrors of the current-match figures. These are None (not an
    # average) when this match hasn't published, so nothing downstream can
    # accidentally present last-5 numbers as this match's.
    block.update({
        "kills": current["kills"],
        "deaths": current["deaths"],
        "assists": current["assists"],
        "kd": current["kd"],
        "kda": current["kda"],
        "hs_pct": current["hs_pct"],
        "adr": current["adr"],
        "acs": current["acs"],
        "headshots": current["headshots"],
        "bodyshots": current["bodyshots"],
        "legshots": current["legshots"],
        "damage": current["damage"],
        "rounds": current["rounds_played"],
        "current_match_kd": current["kd"],
        "current_match_hs": current["hs_pct"],
        "current_match_kda": current["kda_line"],
    })
    return block


def _record_session_match(puuid: str, summary: Dict[str, Any]) -> None:
    """Adds a finished match to this app-session's running tally, once."""
    if not summary:
        return
    if _SESSION["puuid"] != puuid:
        _SESSION.update({"puuid": puuid, "ids": [], "matches": [], "started_at": time.time()})
    mid = summary.get("match_id") or ""
    if mid and mid in _SESSION["ids"]:
        return
    _SESSION["ids"].append(mid)
    _SESSION["matches"].append(summary)
    if len(_SESSION["matches"]) > 25:
        _SESSION["ids"] = _SESSION["ids"][-25:]
        _SESSION["matches"] = _SESSION["matches"][-25:]


def _reset_live_state_for_player(puuid: str) -> None:
    """Partition all process-local match state by the signed-in player."""
    global _LIVE_OWNER_PUUID
    puuid = (puuid or "").strip()
    if not puuid or puuid == _LIVE_OWNER_PUUID:
        return

    _LIVE_OWNER_PUUID = puuid
    _MATCH_PROGRESS.update({
        "match_id": "", "ally": 0, "enemy": 0,
        "rounds": [], "started_at": 0.0,
    })
    _LIVE_PROBE.update({
        "match_id": "", "next_at": 0.0, "data": None, "at_rounds": -1,
    })
    _LAST_MATCH.update({
        "watch_id": "", "match_id": "", "data": None,
        "next_at": 0.0, "tries": 0,
    })
    _SESSION.update({"puuid": puuid, "ids": [], "matches": [], "started_at": time.time()})
    _MY_PARTY.update({"at": 0.0, "puuid": puuid, "members": []})
    _NAME_CACHE.clear()


def _session_block() -> Dict[str, Any]:
    """Aggregate of every match finished since the app started."""
    matches = _SESSION["matches"]
    if not matches:
        return {"matches": 0}

    kills = sum(m.get("kills", 0) for m in matches)
    deaths = sum(m.get("deaths", 0) for m in matches)
    assists = sum(m.get("assists", 0) for m in matches)
    rounds = sum(m.get("rounds", 0) for m in matches) or 1
    damage = sum(m.get("total_damage", 0) for m in matches)
    shots = sum(m.get("shots", 0) for m in matches)
    heads = sum(m.get("headshots", 0) for m in matches)

    return {
        "matches": len(matches),
        "wins": sum(1 for m in matches if m.get("result") == "Win"),
        "losses": sum(1 for m in matches if m.get("result") == "Loss"),
        "draws": sum(1 for m in matches if m.get("result") == "Draw"),
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kd": round(kills / max(1, deaths), 2),
        "kda": round((kills + assists) / max(1, deaths), 2),
        "hs_pct": round(heads / shots * 100, 1) if shots else 0.0,
        "adr": round(damage / rounds),
        "acs": round(sum(m.get("acs", 0) for m in matches) / len(matches)),
        "form": [m.get("result", "") for m in matches[-6:]],
    }


def _resolve_finished_match(client, in_match: bool, active_id: str) -> Optional[Dict[str, Any]]:
    """
    Turns the match that just ended into a full scoreline. Details are only
    published a few seconds after the last round, so the id is remembered and
    retried on a backoff until it lands or the tries run out.
    """
    lm = _LAST_MATCH

    if in_match and active_id:
        if lm["watch_id"] != active_id:
            lm.update({"watch_id": active_id, "next_at": 0.0, "tries": 0})
        return lm["data"]

    watch = lm["watch_id"]
    if watch and watch != lm["match_id"]:
        if time.time() >= lm["next_at"] and lm["tries"] < _LAST_MATCH_MAX_TRIES:
            lm["tries"] += 1
            lm["next_at"] = time.time() + min(4.0 * lm["tries"], 20.0)
            summary = valorant_client.personal_match_summary(client, watch)
            if summary:
                lm.update({"match_id": watch, "data": summary, "watch_id": ""})
                _record_session_match(client.puuid, summary)
                # RR and rolling Last-5 values can change now; do not keep the
                # pre-match roster snapshot for the rest of the process.
                _PLAYER_MMR_CACHE.pop(client.puuid, None)
                valorant_client.invalidate_player_stats()
        elif lm["tries"] >= _LAST_MATCH_MAX_TRIES:
            lm["watch_id"] = ""

    return lm["data"]


def _warm_player_stats(client, players: List[Dict[str, Any]]) -> None:
    """
    Rank + combat lookups are the slow half of a snapshot: ten players in
    sequence is twenty-odd Riot round trips. They're independent, so the ones
    that aren't cached yet are fetched together instead.
    """
    todo = []
    for p in players:
        subject = p.get("Subject", "")
        if subject and not _player_stats_cache_fresh(subject):
            tier = (p.get("SeasonalBadgeInfo") or {}).get("Rank") or p.get("CompetitiveTier") or 0
            todo.append((subject, tier))

    if len(todo) < 2:
        return
    try:
        with ThreadPoolExecutor(max_workers=min(10, len(todo))) as pool:
            list(pool.map(lambda t: _get_player_stats(client, t[0], t[1]), todo))
    except Exception:
        pass


def _apply_parties(roster: List[Dict[str, Any]], my_party: List[str]) -> None:
    """
    Marks who queued together, in place.

    Your own party is exact - it comes straight from the party endpoint.
    Everyone else is inferred from shared party ids and party partner sets in recent
    matches across teammates and enemy team players.
    """
    parent: Dict[str, str] = {p["puuid"]: p["puuid"] for p in roster if p.get("puuid")}
    if not parent:
        return

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # 1. Your own party - known for certain.
    confirmed = {m for m in my_party if m in parent}
    known = sorted(confirmed)
    for other in known[1:]:
        union(known[0], other)

    # 2. Everyone else, inferred from shared party ids and party partner sets in recent matches.
    by_team: Dict[str, List[str]] = {}
    for p in roster:
        if p.get("puuid"):
            by_team.setdefault(p.get("team", ""), []).append(p["puuid"])

    for team_puuids in by_team.values():
        for i, a in enumerate(team_puuids):
            pa = (_PLAYER_MMR_CACHE.get(a) or {}).get("parties") or {}
            partners_a = (_PLAYER_MMR_CACHE.get(a) or {}).get("party_partners") or []
            for b in team_puuids[i + 1:]:
                pb = (_PLAYER_MMR_CACHE.get(b) or {}).get("parties") or {}
                partners_b = (_PLAYER_MMR_CACHE.get(b) or {}).get("party_partners") or []

                # Check direct party partner co-occurrence
                if b in partners_a or a in partners_b:
                    union(a, b)
                    continue

                # Check shared match + party ID
                if any(pid and pb.get(mid) == pid for mid, pid in pa.items()):
                    union(a, b)

    groups: Dict[str, List[str]] = {}
    for puuid in parent:
        groups.setdefault(find(puuid), []).append(puuid)

    numbered: Dict[str, int] = {}
    next_id = 0
    for root, members in groups.items():
        if len(members) < 2:
            continue
        next_id += 1
        for m in members:
            numbered[m] = next_id

    # Create mapping of PUUID to player metadata for partner names
    player_by_puuid = {p["puuid"]: p for p in roster if p.get("puuid")}

    for p in roster:
        puuid = p.get("puuid", "")
        gid = numbered.get(puuid, 0)
        group_members = groups.get(find(puuid), []) if gid else []
        size = len(group_members)
        is_confirmed = bool(puuid in confirmed and len(confirmed) > 1)

        p["party_group"] = gid
        p["party_size"] = size
        p["party_confirmed"] = is_confirmed
        if size >= 2:
            p["party_tag"] = "DUO" if size == 2 else ("TRIO" if size == 3 else f"{size}-STACK")
            partner_names = []
            for m in group_members:
                if m != puuid and m in player_by_puuid:
                    partner_names.append(player_by_puuid[m].get("name") or player_by_puuid[m].get("agent") or "Teammate")
            p["party_partners"] = partner_names
        else:
            p["party_tag"] = ""
            p["party_partners"] = []


def _summarize_parties(roster: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Groups roster players by their party_group to produce a clean stack summary."""
    stacks = []
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for p in roster:
        gid = p.get("party_group", 0)
        if gid:
            groups.setdefault(gid, []).append(p)

    for gid, members in groups.items():
        if len(members) < 2:
            continue
        tag = "DUO" if len(members) == 2 else ("TRIO" if len(members) == 3 else f"{len(members)}-STACK")
        names = [p.get("name") or p.get("agent") or "Player" for p in members]
        agents = [p.get("agent") or "Agent" for p in members]
        confirmed = any(p.get("party_confirmed") for p in members)
        stacks.append({
            "group_id": gid,
            "tag": tag,
            "size": len(members),
            "confirmed": confirmed,
            "names": names,
            "agents": agents,
            "summary": f"{tag}: {' + '.join(names)}"
        })
    return stacks


def _build_pregame_block(client, presence: Dict[str, Any], match_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    match_id = match_id or client.pregame_match_id()
    if not match_id:
        return None

    data = client.pregame_match(match_id)
    if not data:
        return None

    ally_team = data.get("AllyTeam") or {}
    ally = ally_team.get("Players", []) or []
    team_id = (ally_team.get("TeamID") or "Blue").strip()
    starting_side = "Defender" if team_id.lower() == "blue" else "Attacker"

    # Enemy team in pregame (if available, e.g. custom games)
    enemy_team = data.get("EnemyTeam") or {}
    enemy = enemy_team.get("Players", []) or []

    puuids = [p.get("Subject", "") for p in ally + enemy if p.get("Subject")]
    names = _cached_names(client, match_id, puuids)
    map_info = valorant_client.resolve_map(data.get("MapID", ""))

    remaining_ns = data.get("PhaseTimeRemainingNS", 0) or 0
    queue_id = (presence.get("queueId", "") or "").lower()

    _warm_player_stats(client, ally + enemy)
    team = [_roster_entry(client, p, names, client.puuid) for p in ally]
    enemy_roster = [_roster_entry(client, p, names, client.puuid) for p in enemy]
    _apply_parties(team + enemy_roster, _my_party_members(client))
    me = next((r for r in team if r.get("is_self")), None)

    stacks = {
        "ally": _summarize_parties(team),
        "enemy": _summarize_parties(enemy_roster)
    }

    return {
        "phase": "agent_select",
        "match_id": match_id,
        "map": map_info,
        "mode": valorant_client.resolve_mode(data.get("Mode", ""), presence.get("queueId", "")),
        "time_remaining": round(remaining_ns / 1_000_000_000, 1),
        "team": team,
        "enemy": enemy_roster,
        "stacks": stacks,
        "me": _self_block(client, "", me, queue_id),
        "progress": None,
        "score": {"ally": 0, "enemy": 0},
        "round": 0,
        "starting_side": starting_side,
        "current_side": starting_side,
        "side": starting_side,
    }


def _build_coregame_block(client, presence: Dict[str, Any], match_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    match_id = match_id or client.coregame_match_id()
    if not match_id:
        return None

    data = client.coregame_match(match_id)
    if not data:
        return None

    players = data.get("Players", []) or []
    puuids = [p.get("Subject", "") for p in players if p.get("Subject")]
    names = _cached_names(client, match_id, puuids)

    self_team = ""
    for p in players:
        if p.get("Subject") == client.puuid:
            self_team = p.get("TeamID", "")
            break
    if not self_team:
        self_team = "Blue"

    _warm_player_stats(client, players)
    roster = [_roster_entry(client, p, names, client.puuid) for p in players]
    ally = [r for r in roster if r["team"] == self_team]
    enemy = [r for r in roster if r["team"] != self_team]

    ally_score = int(presence.get("partyOwnerMatchScoreAllyTeam", 0) or 0)
    enemy_score = int(presence.get("partyOwnerMatchScoreEnemyTeam", 0) or 0)
    if _MATCH_PROGRESS.get("match_id") == match_id:
        # Presence briefly disappears/returns 0-0 during reconnects and phase
        # transitions.  Scores in a running match are monotonic, so preserve
        # the last good values instead of resetting the tracker.
        ally_score = max(ally_score, int(_MATCH_PROGRESS.get("ally") or 0))
        enemy_score = max(enemy_score, int(_MATCH_PROGRESS.get("enemy") or 0))
    map_id = data.get("MapID") or presence.get("matchMap", "")
    total_rounds = ally_score + enemy_score

    starting_side = "Defender" if self_team.lower() == "blue" else "Attacker"
    queue_id = (presence.get("queueId", "") or "").lower()

    # Only explicit attack/defence presence values are sides.  Blue/Red is a
    # persistent TeamID and must not override the halftime calculation.
    pres_team = (presence.get("partyOwnerMatchCurrentTeam", "") or "").lower()
    if "defend" in pres_team or pres_team == "blue":
        current_side = "Defender" if "defend" in pres_team else _side_for_round(starting_side, total_rounds, queue_id)
    elif "attack" in pres_team or pres_team == "red":
        current_side = "Attacker" if "attack" in pres_team else _side_for_round(starting_side, total_rounds, queue_id)
    else:
        current_side = _side_for_round(starting_side, total_rounds, queue_id)
    _apply_parties(ally + enemy, _my_party_members(client))
    me = next((r for r in ally if r.get("is_self")), None)

    stacks = {
        "ally": _summarize_parties(ally),
        "enemy": _summarize_parties(enemy)
    }

    progress = _build_progress(
        match_id, ally_score, enemy_score, starting_side, current_side, queue_id
    )

    return {
        "phase": "in_match",
        "match_id": match_id,
        "map": valorant_client.resolve_map(map_id),
        "mode": valorant_client.resolve_mode(data.get("ModeID", ""), presence.get("queueId", "")),
        "time_remaining": 0,
        "team": ally,
        "enemy": enemy,
        "stacks": stacks,
        "me": _self_block(client, match_id, me, queue_id, progress),
        "progress": progress,
        "score": {"ally": ally_score, "enemy": enemy_score},
        "round": total_rounds + 1,
        "starting_side": starting_side,
        "current_side": current_side,
        "side": current_side,
    }


def build_live_snapshot() -> Dict[str, Any]:
    """
    One complete picture of the signed-in session: which stored account it is,
    what the client is doing right now, party/queue state, and the live match
    if one is running. Never raises - an unreachable client just comes back
    as available: false.
    """
    snapshot: Dict[str, Any] = {
        "available": False,
        "valorant_running": False,
        "account_id": None,
        "banned_account_id": None,
        "account_banned": False,
        "username": "",
        "display_name": "",
        "region": "",
        "level": 0,
        "rank_label": "",
        "rank_icon_url": "",
        "state": "OFFLINE",
        "queue_id": "",
        "queue_label": "",
        "party": {},
        "match": None,
        "last_match": None,
        "session": {"matches": 0},
        "queue_elapsed": 0,
        "launch": valorant_client.launch_state(),
        "message": "No Riot Client session detected.",
    }

    # Identity is read from the local Riot Client.  Rank/XP remote calls do
    # not belong in a one-second match poll and are handled by the slower sync
    # worker instead.
    info = launcher.get_active_riot_session()
    if not info or not info.get("found"):
        return snapshot

    snapshot.update({
        "username": info.get("username", ""),
        "display_name": info.get("display_name", ""),
        "region": info.get("region", ""),
        "level": info.get("level", 0),
        "rank_label": f"{info.get('rank_tier', 'UNRANKED').title()} {info.get('rank_division', '')}".strip(),
        "rank_icon_url": info.get("rank_icon_url", ""),
        "status": info.get("status", "PLAYABLE"),
        "available": True,
        "message": "Signed in - VALORANT isn't running yet.",
    })

    matched = _match_account_to_session(
        info.get("username", ""), info.get("display_name", ""), info.get("puuid", "")
    )
    if matched:
        snapshot["account_id"] = matched["id"]
        if not snapshot["display_name"]:
            snapshot["display_name"] = matched.get("display_name", "")
        snapshot["level"] = int(matched.get("level", 0) or snapshot["level"] or 0)
        stored_rank = f"{matched.get('rank_tier', 'UNRANKED').title()} {matched.get('rank_division', '')}".strip()
        snapshot["rank_label"] = stored_rank or snapshot["rank_label"]
        snapshot["rank_icon_url"] = matched.get("rank_icon_url", "") or snapshot["rank_icon_url"]
        snapshot["region"] = matched.get("region", "") or snapshot["region"]
        # Learn this account's puuid the first time we ever see it signed in.
        # It's the key to its local settings folder, so recording it here is
        # what lets crosshair/keybind copying find the account later.
        session_puuid = (info.get("puuid") or "").strip()
        if session_puuid and (matched.get("puuid") or "") != session_puuid:
            try:
                db.update_account(matched["id"], {"puuid": session_puuid})
            except Exception:
                pass
    else:
        # The signed-in account may be one that was flagged and moved to the
        # banned store. It's still the live session, so it still owns the
        # "currently logged in" card - it just has to be addressed by its
        # banned-store id, or the card ends up with nothing to act on.
        banned_match = _match_banned_to_session(
            info.get("username", ""), info.get("display_name", "")
        )
        if banned_match:
            snapshot["banned_account_id"] = banned_match["id"]
            snapshot["account_banned"] = True
            if not snapshot["display_name"]:
                snapshot["display_name"] = banned_match.get("display_name", "")

        # A session Riot itself reports as banned/suspended is never
        # auto-added to the roster: it would reappear the instant the user
        # deleted it, which is exactly the loop that made the card unshakeable.
        riot_status = (info.get("status") or "PLAYABLE").upper()
        if riot_status in ("BANNED", "SUSPENDED"):
            snapshot["account_banned"] = True

        uname = (info.get("username") or "").strip()
        display = (info.get("display_name") or "").strip()
        if uname and riot_status not in ("BANNED", "SUSPENDED") and not db.account_exists(uname):
            # A brand new Riot Client session can report a stale or half-empty
            # identity for the first tick or two after it restarts - the same
            # race that used to write a wrong region onto a new row and stamp
            # one account's Riot ID onto another's during a fast account
            # switch. Requiring the SAME (username, display_name) on back to
            # back polls before ever creating a row costs one extra ~1s tick
            # and closes both.
            seen = _PENDING_AUTO_ADD.get(uname)
            identity = (uname, display)
            stable = bool(seen and seen[0] == identity and (time.time() - seen[1]) >= 0.8)
            _PENDING_AUTO_ADD[uname] = (identity, time.time())

            if display and stable:
                try:
                    new_acc_id = db.add_account({
                        "username": uname,
                        "password": "",
                        "display_name": display,
                        "region": info.get("region", "") or "",
                        "level": int(info.get("level", 0) or 0),
                        "rank_tier": info.get("rank_tier", "UNRANKED"),
                        "rank_division": info.get("rank_division", ""),
                        "lp": int(info.get("lp", 0) or 0),
                        "rank_icon_url": info.get("rank_icon_url", ""),
                        "peak_rank_tier": info.get("peak_rank_tier", ""),
                        "peak_rank_division": info.get("peak_rank_division", ""),
                        "peak_rank_icon_url": info.get("peak_rank_icon_url", ""),
                        "tag": "Ranked" if int(info.get("level", 0) or 0) >= 20 else "Unrated",
                        "status": "PLAYABLE",
                        "notes": "Auto-detected active session"
                    })
                    snapshot["account_id"] = new_acc_id
                    matched = db.get_account_by_id(new_acc_id)
                    _PENDING_AUTO_ADD.pop(uname, None)
                except Exception:
                    pass

    snapshot["valorant_running"] = launcher.is_valorant_running()
    if not snapshot["valorant_running"]:
        return snapshot

    client = valorant_client.ValorantLiveClient()
    if not client.connect():
        snapshot["message"] = "Waiting for the game's session to come up..."
        return snapshot

    snapshot["puuid"] = client.puuid
    _reset_live_state_for_player(client.puuid)
    if snapshot.get("account_id") and client.puuid:
        try:
            stored = db.get_account_by_id(snapshot["account_id"])
            if stored and (stored.get("puuid") or "") != client.puuid:
                db.update_account(snapshot["account_id"], {"puuid": client.puuid})
        except Exception:
            pass
    if not snapshot.get("account_id") and snapshot.get("puuid"):
        matched = _match_account_to_session(info.get("username", ""), info.get("display_name", ""), snapshot["puuid"])
        if matched:
            snapshot["account_id"] = matched["id"]
            if not snapshot["display_name"]:
                snapshot["display_name"] = matched.get("display_name", "")
    presence = client.presence()
    presence_loop_state = (presence.get("sessionLoopState") or "").upper()

    # Authoritative game check: check Coregame first, then Pregame
    core_match_id = None
    pregame_match_id = None

    try:
        core_match_id = client.coregame_match_id()
    except Exception:
        core_match_id = None

    if not core_match_id:
        try:
            pregame_match_id = client.pregame_match_id()
        except Exception:
            pregame_match_id = None

    if core_match_id:
        loop_state = "INGAME"
    elif pregame_match_id:
        loop_state = "PREGAME"
    elif presence_loop_state in ("INGAME", "PREGAME"):
        loop_state = presence_loop_state
    else:
        loop_state = "MENUS"

    snapshot["state"] = loop_state
    snapshot["queue_id"] = presence.get("queueId", "") or ""
    snapshot["queue_label"] = valorant_client.MODE_LABELS.get(snapshot["queue_id"], snapshot["queue_id"])

    try:
        party = client.party()
    except valorant_client.LiveClientError:
        party = {}

    if party:
        party_state = (party.get("State") or "DEFAULT").upper()
        members = party.get("Members", []) or []
        snapshot["party"] = {
            "id": party.get("ID", ""),
            "size": len(members),
            "max": party.get("MaxPartySize", 5),
            "state": party_state,
            "in_queue": party_state == "MATCHMAKING",
            "queue_id": (party.get("MatchmakingData") or {}).get("QueueID", "") or snapshot["queue_id"],
        }
        if snapshot["party"]["queue_id"]:
            snapshot["queue_id"] = snapshot["party"]["queue_id"]
            snapshot["queue_label"] = valorant_client.MODE_LABELS.get(
                snapshot["queue_id"], snapshot["queue_id"]
            )
        snapshot["queue_elapsed"] = _queue_elapsed(party, snapshot["party"]["in_queue"])
    else:
        _queue_elapsed({}, False)

    try:
        if loop_state == "PREGAME":
            snapshot["match"] = _build_pregame_block(client, presence, pregame_match_id)
        elif loop_state == "INGAME":
            snapshot["match"] = _build_coregame_block(client, presence, core_match_id)
    except valorant_client.LiveClientError as e:
        snapshot["message"] = str(e)

    # The scoreline for whatever finished most recently plus this session's
    # running tally. Both outlive the match itself so the panel has something
    # real to show between games.
    try:
        snapshot["last_match"] = _resolve_finished_match(
            client, loop_state == "INGAME", core_match_id or ""
        )
    except Exception:
        snapshot["last_match"] = None
    snapshot["session"] = _session_block()

    if snapshot["match"]:
        snapshot["message"] = ""
    elif snapshot["party"].get("in_queue"):
        snapshot["message"] = f"Matchmaking (In Queue) - {snapshot['queue_label'] or 'a match'}"
    else:
        snapshot["message"] = "In the menus - pick a mode and start a match."

    return snapshot


def invalidate_live_snapshot() -> None:
    """Forces the next poll to rebuild instead of serving the cached view."""
    with _LIVE_SNAPSHOT_LOCK:
        _LIVE_SNAPSHOT["built_at"] = 0.0


def get_live_snapshot(force: bool = False) -> Dict[str, Any]:
    now = time.monotonic()
    if not force and _LIVE_SNAPSHOT["data"] and (now - _LIVE_SNAPSHOT["built_at"]) < _LIVE_SNAPSHOT_TTL:
        return _LIVE_SNAPSHOT["data"]

    # Main UI, overlay and manual refreshes can arrive together.  Only one
    # caller pays for the Riot request fan-out; everyone else re-checks the
    # freshly populated cache after acquiring the lock.
    with _LIVE_SNAPSHOT_LOCK:
        now = time.monotonic()
        if not force and _LIVE_SNAPSHOT["data"] and (now - _LIVE_SNAPSHOT["built_at"]) < _LIVE_SNAPSHOT_TTL:
            return _LIVE_SNAPSHOT["data"]

        data = build_live_snapshot()
        _LIVE_SNAPSHOT["data"] = data
        # Stamp completion, not start.  A slow build should still receive its
        # full TTL instead of being stale the instant it returns.
        _LIVE_SNAPSHOT["built_at"] = time.monotonic()
        return data


def _connected_client():
    """Connected live client, or a user-facing error explaining why not."""
    client = valorant_client.ValorantLiveClient()
    if not client.connect():
        raise valorant_client.LiveClientError(
            "VALORANT isn't running. Press Play first, then try again."
        )
    return client


def _current_puuid() -> str:
    """Best-effort puuid of whoever's signed into the Riot Client right now.
    Only needs the Riot Client's lockfile, not the game itself running."""
    try:
        client = valorant_client.ValorantLiveClient()
        if client.connect():
            return client.puuid or ""
    except Exception:
        pass
    return ""


# Set while the in-lobby borderless watcher is running, so a second launch
# doesn't stack another one on top of it.
_BORDERLESS_WATCH: Dict[str, Any] = {"running": False, "applied_for": ""}


def _borderless_when_in_lobby(puuid: str) -> None:
    """
    Forces windowed borderless once the game is actually up and sitting in
    the menus, rather than before it launches.

    VALORANT reads its video config at startup and writes it back from memory
    afterwards, so a pre-launch write is racing the game's own save and gets
    silently undone. Waiting until the client reports MENUS means the game has
    finished its startup read and settled, so the value written is the one
    still on disk when it next starts.

    Runs on its own thread and gives up quietly - a launch the user cancels,
    or a game that never reaches the menus, must not leave anything behind.
    """
    if not puuid or _BORDERLESS_WATCH["running"]:
        return

    def watch() -> None:
        _BORDERLESS_WATCH["running"] = True
        try:
            deadline = time.time() + 300  # five minutes covers a slow cold start
            while time.time() < deadline:
                time.sleep(3.0)
                if not launcher.is_valorant_running():
                    continue
                try:
                    client = valorant_client.ValorantLiveClient()
                    if not client.connect():
                        continue
                    state = (client.presence().get("sessionLoopState") or "").upper()
                except Exception:
                    continue

                # MENUS is "in the lobby" - past the startup read, not in a match.
                if state != "MENUS":
                    continue

                result = game_config.force_borderless(puuid)
                _BORDERLESS_WATCH["applied_for"] = puuid
                client_launcher.login_logger.info(
                    "forced borderless for %s once in the lobby: %s", puuid[:8], result
                )
                return
        finally:
            _BORDERLESS_WATCH["running"] = False

    threading.Thread(target=watch, daemon=True).start()


async def _apply_launch_prefs(puuid: str) -> None:
    """
    Applies the settings preset to the account that is about to play, when
    auto-apply is armed.

    Runs synchronously when the account's local config folder already exists
    (a returning account - this is a couple of small file writes, well under
    a launch's normal latency). When it doesn't - a first-ever login for this
    account on this PC, where Riot hasn't created the folder yet - the launch
    is never blocked on it; a background watcher applies it the moment the
    folder shows up instead.

    Forced borderless is handled separately by _borderless_when_in_lobby().
    """
    if not puuid:
        return

    settings = db.get_settings()
    autoapply = settings.get("settings_autoapply", "0") == "1"

    # Forced borderless deliberately does NOT happen here any more. VALORANT
    # reads its video config at startup and writes it back out from memory
    # afterwards, so anything set before launch is liable to be overwritten by
    # the game's own idea of the settings. It's applied once the game is up
    # and sitting in the menus instead - see _borderless_when_in_lobby().
    if not autoapply:
        return

    def apply_now() -> None:
        if game_config.describe_preset().get("exists"):
            game_config.apply_preset(puuid)

    if game_config.account_dir(puuid):
        await asyncio.to_thread(apply_now)
        return

    def watch():
        if game_config.wait_for_account(puuid, timeout=90.0):
            apply_now()

    threading.Thread(target=watch, daemon=True).start()


async def _arm_launch_prefs(puuid: str) -> None:
    """Everything that should happen around a launch: preset first, then the
    in-lobby borderless pass."""
    await _apply_launch_prefs(puuid)
    if db.get_settings().get("force_borderless", "1") != "0":
        _borderless_when_in_lobby(puuid)


# --------------------------------------------------------------------------
# LOCAL GAME CONFIG - forced borderless + copying settings between accounts
#
# Riot doesn't expose crosshair/sensitivity/keybinds/video through any API,
# so these act directly on the per-account config files under
# %LOCALAPPDATA%\VALORANT\Saved\Config - see backend/game_config.py.
# --------------------------------------------------------------------------

@app.get("/api/game-config/settings")
async def get_game_config_settings():
    """
    Current borderless/profile preferences, plus which stored accounts have
    actually signed into VALORANT on this PC - the only ones that can serve
    as a settings source or receive a copy right now.
    """
    settings = db.get_settings()
    accounts = db.get_all_accounts()

    def has_config(puuid: str) -> bool:
        try:
            return bool(puuid) and game_config.has_config(puuid)
        except Exception:
            return False

    def build_status() -> List[Dict[str, Any]]:
        out = []
        for acc in accounts:
            puuid = (acc.get("puuid") or "").strip()
            ready = has_config(puuid)
            # Two genuinely different reasons an account can't be used, which
            # the old UI collapsed into one unexplained greyed-out row.
            if ready:
                reason = ""
            elif not puuid:
                reason = "not identified yet - log in once with Vortex open"
            else:
                reason = "no settings on this PC yet - play one match on it"
            out.append({
                "id": acc["id"],
                "display_name": acc.get("display_name") or acc.get("username", ""),
                "username": acc.get("username", ""),
                "has_config": ready,
                "has_puuid": bool(puuid),
                "reason": reason,
            })
        return out

    account_status = await asyncio.to_thread(build_status)
    profile_id = settings.get("settings_profile_account_id", "") or ""

    # Exactly what the chosen profile has on disk, so the UI can spell out
    # what a copy would actually carry across instead of leaving it to guesswork.
    profile_detail = None
    if profile_id.isdigit():
        prof = db.get_account_by_id(int(profile_id))
        if prof and (prof.get("puuid") or "").strip():
            profile_detail = await asyncio.to_thread(game_config.describe, prof["puuid"].strip())

    return {
        "force_borderless": settings.get("force_borderless", "1") != "0",
        "autoapply": settings.get("settings_autoapply", "0") == "1",
        "stay_signed_in": settings.get("stay_signed_in", "1") != "0",
        "auto_launch_after_login": settings.get("auto_launch_after_login", "0") == "1",
        "profile_account_id": int(profile_id) if profile_id.isdigit() else None,
        "accounts": account_status,
        "ready_count": sum(1 for a in account_status if a["has_config"]),
        "total_count": len(account_status),
        "profile_detail": profile_detail,
    }


@app.post("/api/game-config/settings")
async def update_game_config_settings(req: GameConfigSettingsRequest):
    updates: Dict[str, str] = {}
    if req.force_borderless is not None:
        updates["force_borderless"] = "1" if req.force_borderless else "0"
    if req.autoapply is not None:
        updates["settings_autoapply"] = "1" if req.autoapply else "0"
    if req.profile_account_id is not None:
        updates["settings_profile_account_id"] = str(req.profile_account_id) if req.profile_account_id else ""
    if req.stay_signed_in is not None:
        updates["stay_signed_in"] = "1" if req.stay_signed_in else "0"
    if req.auto_launch_after_login is not None:
        updates["auto_launch_after_login"] = "1" if req.auto_launch_after_login else "0"
    if updates:
        db.update_settings(updates)
    return await get_game_config_settings()


@app.post("/api/game-config/copy")
async def copy_game_config(req: GameConfigCopyRequest):
    """Copies crosshair/sensitivity/keybinds and/or video settings between two
    stored accounts' local config, right now."""
    src = db.get_account_by_id(req.source_account_id)
    if not src or not src.get("puuid"):
        return {"success": False, "message": "Source account not found or has no known PUUID yet - check it in once first."}

    if req.target_account_id:
        dst = db.get_account_by_id(req.target_account_id)
        if not dst or not dst.get("puuid"):
            return {"success": False, "message": "Target account not found or has no known PUUID yet - check it in once first."}
        dst_puuid = dst["puuid"]
    else:
        dst_puuid = await asyncio.to_thread(_current_puuid)
        if not dst_puuid:
            return {"success": False, "message": "No account is signed into the Riot Client right now."}

    result = await asyncio.to_thread(
        game_config.copy_settings, src["puuid"], dst_puuid, req.gameplay, req.video
    )
    return result


@app.get("/api/game-config/preset")
async def get_settings_preset():
    """What's currently saved as the settings preset."""
    return await asyncio.to_thread(game_config.describe_preset)


@app.post("/api/game-config/preset/capture")
async def capture_settings_preset(req: PresetCaptureRequest):
    """
    Saves the signed-in account's settings as the preset.

    Capturing from the live session rather than a stored account is what makes
    this usable at all: the puuid comes from the Riot Client directly, so an
    account Vortex has never identified can still be used as the source. Most
    accounts are in exactly that state - they have real settings sitting on
    this PC, but no stored puuid to find them by.
    """
    puuid = ""
    label = ""

    if req.account_id:
        acc = db.get_account_by_id(req.account_id)
        if not acc:
            return {"success": False, "message": "Account not found."}
        puuid = (acc.get("puuid") or "").strip()
        label = acc.get("display_name") or acc.get("username", "")
        if not puuid:
            return {"success": False, "message":
                    f"Vortex hasn't identified {label} yet - sign into it and capture from the live session."}
    else:
        puuid = await asyncio.to_thread(_current_puuid)
        info = await asyncio.to_thread(launcher.get_active_riot_account)
        label = (info or {}).get("display_name") or (info or {}).get("username") or ""
        if not puuid:
            return {"success": False, "message":
                    "No account is signed into the Riot Client right now."}
        # Learn this account's puuid while we have it, so it can be a copy
        # target later without needing another sign-in.
        matched = _match_account_to_session((info or {}).get("username", ""), label)
        if matched and (matched.get("puuid") or "") != puuid:
            try:
                db.update_account(matched["id"], {"puuid": puuid})
            except Exception:
                pass

    result = await asyncio.to_thread(game_config.capture_preset, puuid, label)
    if result.get("success") and req.set_as_profile:
        matched = db.get_account_by_puuid(puuid)
        if matched:
            db.update_settings({"settings_profile_account_id": str(matched["id"])})
    return result


@app.post("/api/game-config/preset/apply")
async def apply_settings_preset(req: PresetApplyRequest):
    """Writes the saved preset onto one account, or onto every account that can take it."""
    if req.all_accounts:
        def run_all() -> Dict[str, Any]:
            applied, skipped = [], []
            for acc in db.get_all_accounts():
                name = acc.get("display_name") or acc.get("username", "")
                pu = (acc.get("puuid") or "").strip()
                if not pu:
                    skipped.append({"name": name, "why": "not identified on this PC yet"})
                    continue
                res = game_config.apply_preset(pu, name)
                if res.get("success"):
                    applied.append({"name": name, "files": res.get("applied", [])})
                else:
                    skipped.append({"name": name, "why": res.get("message", "failed")})
            return {"applied": applied, "skipped": skipped}

        res = await asyncio.to_thread(run_all)
        applied, skipped = res["applied"], res["skipped"]
        if not applied:
            return {"success": False, "message":
                    "No account was ready to receive the preset yet.", **res}
        msg = f"Applied the preset to {len(applied)} account{'s' if len(applied) != 1 else ''}."
        if skipped:
            msg += f" {len(skipped)} skipped."
        return {"success": True, "message": msg, **res}

    if req.account_id:
        acc = db.get_account_by_id(req.account_id)
        if not acc:
            return {"success": False, "message": "Account not found."}
        puuid = (acc.get("puuid") or "").strip()
        label = acc.get("display_name") or acc.get("username", "")
        if not puuid:
            return {"success": False, "message":
                    f"Vortex hasn't identified {label} yet - sign into it once, then apply."}
    else:
        puuid = await asyncio.to_thread(_current_puuid)
        info = await asyncio.to_thread(launcher.get_active_riot_account)
        label = (info or {}).get("display_name") or (info or {}).get("username") or ""
        if not puuid:
            return {"success": False, "message": "No account is signed into the Riot Client right now."}

    return await asyncio.to_thread(game_config.apply_preset, puuid, label)


@app.post("/api/game-config/copy-all")
async def copy_game_config_to_all(req: GameConfigCopyAllRequest):
    """
    Copies the profile account's whole local setup onto every other account
    that has settings on this PC, in one go.

    This is the "make all my accounts identical" button - doing it one target
    at a time through the single-target copy was the only way before, which
    is not an obvious way to say "apply this everywhere".
    """
    src = db.get_account_by_id(req.source_account_id)
    if not src:
        return {"success": False, "message": "Profile account not found."}
    src_puuid = (src.get("puuid") or "").strip()
    if not src_puuid:
        return {"success": False, "message":
                "That account hasn't been identified yet - sign into it once with Vortex open, then try again."}

    def run() -> Dict[str, Any]:
        if not game_config.has_config(src_puuid):
            return {"success": False, "message":
                    "The profile account has no VALORANT settings on this PC yet - "
                    "play one match on it, then copy."}

        applied, skipped = [], []
        for acc in db.get_all_accounts():
            if acc["id"] == src["id"]:
                continue
            name = acc.get("display_name") or acc.get("username", "")
            puuid = (acc.get("puuid") or "").strip()
            if not puuid:
                skipped.append({"name": name, "why": "not identified on this PC yet"})
                continue
            if puuid == src_puuid:
                continue
            if not game_config.has_config(puuid):
                skipped.append({"name": name, "why": "has never played on this PC"})
                continue
            res = game_config.copy_settings(src_puuid, puuid, req.gameplay, req.video)
            if res.get("success"):
                applied.append(name)
            else:
                skipped.append({"name": name, "why": res.get("message", "copy failed")})
        return {"applied": applied, "skipped": skipped}

    result = await asyncio.to_thread(run)
    if "success" in result:
        return result

    applied, skipped = result["applied"], result["skipped"]
    src_name = src.get("display_name") or src.get("username", "")
    if not applied:
        return {
            "success": False,
            "message": "No account was ready to receive the settings yet.",
            "applied": [], "skipped": skipped,
        }

    msg = f"Copied {src_name}'s settings onto {len(applied)} account{'s' if len(applied) != 1 else ''}."
    if skipped:
        msg += f" {len(skipped)} skipped."
    return {"success": True, "message": msg, "applied": applied, "skipped": skipped}


@app.post("/api/game-config/force-borderless")
async def force_borderless_now(req: GameConfigBorderlessRequest):
    """Applies windowed-borderless immediately, without waiting for the next launch."""
    if req.all_accounts:
        def run_all() -> Dict[str, Any]:
            done, skipped = [], []
            for acc in db.get_all_accounts():
                name = acc.get("display_name") or acc.get("username", "")
                pu = (acc.get("puuid") or "").strip()
                if not pu or game_config.force_borderless(pu) is not True:
                    skipped.append(name)
                else:
                    done.append(name)
            return {"done": done, "skipped": skipped}

        res = await asyncio.to_thread(run_all)
        done, skipped = res["done"], res["skipped"]
        if not done:
            return {"success": False, "message":
                    "No account has VALORANT settings on this PC yet, so there's nothing to set."}
        msg = f"Set {len(done)} account{'s' if len(done) != 1 else ''} to windowed borderless."
        if skipped:
            msg += f" {len(skipped)} skipped (never played on this PC)."
        return {"success": True, "message": msg, "done": done, "skipped": skipped}

    if req.account_id:
        acc = db.get_account_by_id(req.account_id)
        if not acc or not acc.get("puuid"):
            return {"success": False, "message": "Account not found or has no known PUUID yet - check it in once first."}
        puuid = acc["puuid"]
    else:
        puuid = await asyncio.to_thread(_current_puuid)
        if not puuid:
            return {"success": False, "message": "No account is signed into the Riot Client right now."}

    result = await asyncio.to_thread(game_config.force_borderless, puuid)
    if result is None:
        return {"success": False, "message": "This account hasn't signed into VALORANT on this PC yet - log in and reach the main menu once first."}
    if result is False:
        return {"success": False, "message": "Couldn't write the settings file - is VALORANT currently running for this account?"}
    return {"success": True, "message": "Set to windowed borderless."}


@app.get("/api/live/session")
async def live_session(force: bool = False):
    """Live snapshot of the signed-in session, polled by the dashboard."""
    data = await asyncio.to_thread(get_live_snapshot, force)
    return data


@app.get("/api/live/agents")
async def live_agents():
    """Playable agent roster, for the insta-lock picker."""
    agents = await asyncio.to_thread(valorant_client.get_agents)
    return {"agents": agents, "modes": valorant_client.GAME_MODES}


@app.post("/api/live/mode")
async def live_change_mode(req: ModeRequest):
    """Switches the party's queue without starting matchmaking."""
    def _run():
        client = _connected_client()
        client.change_queue(req.queue_id)
        return valorant_client.MODE_LABELS.get(req.queue_id, req.queue_id)

    try:
        label = await asyncio.to_thread(_run)
    except valorant_client.LiveClientError as e:
        return {"success": False, "message": str(e)}

    invalidate_live_snapshot()
    return {"success": True, "queue_id": req.queue_id, "message": f"Mode set to {label}."}


@app.post("/api/live/queue/start")
async def live_start_queue(req: QueueStartRequest):
    """
    Starts matchmaking, optionally switching the queue first - that pairing is
    what the dashboard's one-click "Start Ranked Match" button uses.
    """
    def _run():
        client = _connected_client()
        queue_id = req.queue_id or ""
        if queue_id:
            client.change_queue(queue_id)
            # The party needs a beat to settle on the new queue before it will
            # accept a matchmaking join for it.
            time.sleep(0.5)
        else:
            queue_id = (client.party().get("MatchmakingData") or {}).get("QueueID", "") or ""
        client.start_queue()
        return valorant_client.MODE_LABELS.get(queue_id, "") or "the selected mode"

    try:
        label = await asyncio.to_thread(_run)
    except valorant_client.LiveClientError as e:
        return {"success": False, "message": str(e)}

    _QUEUE_TIMER.update({"key": "", "started_at": time.time()})
    invalidate_live_snapshot()
    return {"success": True, "message": f"Matchmaking for {label}..."}


@app.post("/api/live/queue/stop")
async def live_stop_queue():
    def _run():
        client = _connected_client()
        client.stop_queue()

    try:
        await asyncio.to_thread(_run)
    except valorant_client.LiveClientError as e:
        return {"success": False, "message": str(e)}

    invalidate_live_snapshot()
    return {"success": True, "message": "Left the queue."}


@app.get("/api/live/instalock")
async def live_instalock_status():
    return valorant_client.instalock_status()


@app.post("/api/live/instalock")
async def live_set_instalock(req: InstalockRequest):
    """Arms or disarms the agent-select auto-lock."""
    if not req.enabled or not req.agent_id:
        state = await asyncio.to_thread(valorant_client.disarm_instalock)
        return {"success": True, "message": "Insta-lock turned off.", "instalock": state}

    agent = await asyncio.to_thread(valorant_client.agent_by_id, req.agent_id)
    if not agent.get("name"):
        return {"success": False, "message": "Unknown agent."}

    state = await asyncio.to_thread(valorant_client.arm_instalock, req.agent_id, agent["name"])
    return {
        "success": True,
        "message": f"Insta-lock armed for {agent['name']}.",
        "instalock": state
    }


@app.post("/api/live/lock-now")
async def live_lock_now(req: LockNowRequest):
    """Locks an agent immediately - only works while agent select is open."""
    def _run():
        client = _connected_client()
        agent = valorant_client.agent_by_id(req.agent_id)
        # Same verified select -> settle -> lock path the watcher uses, minus
        # the wait for the phase to open: this is only pressed once it is.
        return valorant_client.lock_agent_flow(
            client, req.agent_id, agent.get("name", ""), wait_for_open=False
        )

    try:
        locked, message = await asyncio.to_thread(_run)
    except valorant_client.LiveClientError as e:
        return {"success": False, "message": str(e)}

    invalidate_live_snapshot()
    return {"success": locked, "message": message}


@app.get("/api/live/stats")
async def live_player_stats(force: bool = False):
    """
    Tracker-style profile for the signed-in account: rank and RR, peak rank,
    win/loss form and streak, combat averages, top agents, recent matches and
    the skin collection. Served from cache and refreshed in the background,
    so this returns instantly even on the very first call.
    """
    if not await asyncio.to_thread(valorant_client.is_game_running):
        return {"available": False, "loading": False,
                "message": "Start VALORANT to load your live profile."}

    return await asyncio.to_thread(valorant_client.get_player_stats, force)


@app.post("/api/live/launch")
async def live_launch():
    """
    Force-starts VALORANT for whoever is signed into the Riot Client. Unlike
    the per-account Play, this never switches accounts - it just makes sure
    the game actually comes up for the current session.
    """
    settings = db.get_settings()
    client_path = settings.get("riot_client_path", "") or ""

    await _arm_launch_prefs(await asyncio.to_thread(_current_puuid))
    result = await asyncio.to_thread(valorant_client.launch_valorant, client_path)
    invalidate_live_snapshot()
    return {**result, "launch": valorant_client.launch_state()}


@app.get("/api/live/launch-state")
async def live_launch_state():
    return valorant_client.launch_state()


async def _launch_game_for_current_session() -> None:
    """
    Starts VALORANT for whoever just signed in, applying the launch
    preferences (forced borderless, settings profile) first.

    Used by "start the game after a plain Login". Never raises - it runs
    detached from any request, so a failure here must not take down the
    login flow that scheduled it.
    """
    try:
        if await asyncio.to_thread(launcher.is_valorant_running):
            return

        # The Riot Client needs a moment after auth before it will accept a
        # launch request for the new session.
        await asyncio.sleep(1.5)

        puuid = await asyncio.to_thread(_current_puuid)
        await _arm_launch_prefs(puuid)

        settings = db.get_settings()
        client_path = settings.get("riot_client_path", "") or             await asyncio.to_thread(launcher.detect_riot_client_path)
        await asyncio.to_thread(valorant_client.launch_valorant, client_path)
    except Exception:
        client_launcher.login_logger.exception("auto-launch after login failed")


async def background_login_then_play(account_id: int):
    """
    Waits for a freshly started login to land, then launches VALORANT for it.
    Used by Play on an account that isn't the current session.
    """
    acc = db.get_account_by_id(account_id)
    if not acc:
        client_launcher._set_login_stage("error", "The account was removed before login finished.")
        return

    settings = db.get_settings()
    client_path = settings.get("riot_client_path", "") or launcher.detect_riot_client_path()

    for _ in range(40):
        await asyncio.sleep(1.0)
        info = await asyncio.to_thread(launcher.get_active_riot_session, acc["username"])
        if info and info.get("found"):
            # Pay for rank/XP only once, after the lightweight local identity
            # proves the new session has landed.
            full_info = await asyncio.to_thread(launcher.get_active_riot_account, acc["username"])
            resolved = full_info if full_info and full_info.get("found") else info
            update_payload = {k: v for k, v in resolved.items() if k not in ("found", "username")}
            update_payload["last_updated"] = datetime.now().isoformat()
            if apply_account_update(account_id, update_payload):
                client_launcher._set_login_stage(
                    "error", "This account is banned or suspended, so VALORANT was not started.", acc["username"]
                )
                return  # banned/suspended - don't launch
            await asyncio.sleep(1.5)
            await _arm_launch_prefs(await asyncio.to_thread(_current_puuid))
            launch = await asyncio.to_thread(valorant_client.launch_valorant, client_path)
            if launch.get("success"):
                client_launcher._set_login_stage(
                    "done", f"Signed in as {resolved.get('display_name') or acc['username']} and started VALORANT.", acc["username"]
                )
            else:
                client_launcher._set_login_stage(
                    "error", launch.get("message") or "Signed in, but VALORANT could not be started.", acc["username"]
                )
            return

    client_launcher._set_login_stage(
        "error", "Login timed out before Riot confirmed the new session.", acc["username"]
    )


@app.post("/api/accounts/{account_id}/play")
async def play_account(account_id: int, background_tasks: BackgroundTasks):
    """
    Launches VALORANT for an account. If it's already the signed-in session
    the game starts straight away; otherwise the account is logged in first
    and the game is launched once that lands.
    """
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    settings = db.get_settings()
    client_path = settings.get("riot_client_path", "") or await asyncio.to_thread(launcher.detect_riot_client_path)

    info = await asyncio.to_thread(launcher.get_active_riot_session)
    is_active = bool(
        info and info.get("found")
        and (info.get("username") or "").strip().lower() == account["username"].strip().lower()
    )

    if is_active:
        if await asyncio.to_thread(launcher.is_valorant_running):
            return {"success": True, "already_running": True, "switched": False,
                    "message": "VALORANT is already running for this account."}

        await _arm_launch_prefs(await asyncio.to_thread(_current_puuid))
        result = await asyncio.to_thread(valorant_client.launch_valorant, client_path)
        if not result.get("success"):
            return {"success": False, "message": result.get("message") or
                    "Couldn't start VALORANT - check the Riot Client path in Settings."}
        return {"success": True, "switched": False,
                "message": f"Starting VALORANT as {account.get('display_name') or account['username']}..."}

    # Different account signed in (or none) - log in first, then launch.
    result = await asyncio.to_thread(
        launcher.login_account, account["username"], account["password"], client_path or None,
        _stay_signed_in_pref()
    )
    if result.get("success"):
        db.update_account(account_id, {"last_login": datetime.now().isoformat()})
        note_account_login(account_id)
        background_tasks.add_task(background_login_then_play, account_id)
    return {
        "success": bool(result.get("success")),
        "switched": bool(result.get("success")),
        "message": result["message"] if not result["success"] else f"Switching to {account['username']}, then starting VALORANT...",
    }


@app.post("/api/accounts/{account_id}/check")
async def check_single_account(account_id: int):
    """
    Verifies one account on demand: logs in, confirms the credentials work,
    and pulls the real Riot ID, region, level, rank, peak rank and ban status
    off Riot's servers. Unlike the batch checker this leaves the account
    signed in, so it flows straight into Play / the live dashboard.
    """
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if CHECK_PROGRESS["running"]:
        return {"success": False, "message": "A full roster check is already running."}

    settings = db.get_settings()
    custom_path = settings.get("riot_client_path", "")

    await asyncio.to_thread(launcher.login_account, account["username"], account["password"],
                            custom_path if custom_path else None, _stay_signed_in_pref())

    detected_info = None
    for _ in range(40):
        await asyncio.sleep(0.5)
        info = await asyncio.to_thread(launcher.get_active_riot_account, account["username"])
        if info and info.get("found") and info.get("username", "").strip().lower() == account["username"].strip().lower():
            detected_info = info
            break

    if not detected_info:
        return {
            "success": False,
            "verified": False,
            "message": f"Couldn't verify {account['username']} - the login didn't go through. Check the username and password."
        }

    update_payload = {k: v for k, v in detected_info.items() if k not in ("found", "username")}
    update_payload["last_updated"] = datetime.now().isoformat()

    lvl = int(detected_info.get("level", 1) or 1)
    if account.get("tag") in ("Smurf", "Ranked", "Unrated", "", None):
        update_payload["tag"] = "Ranked" if lvl >= 20 else "Unrated"

    status = (detected_info.get("status") or "").upper()
    if status in ("BANNED", "SUSPENDED"):
        apply_account_update(account_id, update_payload)
        return {
            "success": True,
            "verified": True,
            "moved_to_banned": True,
            "message": f"{account['username']} is {status.lower()} - moved to Banned Accounts."
        }

    db.update_account(account_id, update_payload)

    # Fill in match history too, so the card is complete after one check.
    if detected_info.get("display_name"):
        scraper = StatScraper(riot_api_key=settings.get("riot_api_key"))
        stats = await scraper.fetch_account_stats(
            detected_info["display_name"], detected_info.get("region", "NA")
        )
        if stats.get("match_history"):
            db.update_account(account_id, {"match_history": stats["match_history"]})

    updated = db.get_account_by_id(account_id)
    return {
        "success": True,
        "verified": True,
        "account": updated,
        "message": f"Verified {detected_info.get('display_name') or account['username']} - Riot ID, level and rank are up to date."
    }


# When frozen by PyInstaller (onefile build), bundled data files live under
# sys._MEIPASS (a temp extraction dir), not next to this source file.
import sys as _sys
if getattr(_sys, "frozen", False):
    _APP_ROOT = getattr(_sys, "_MEIPASS", os.path.dirname(_sys.executable))
else:
    _APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FRONTEND_DIR = os.path.join(_APP_ROOT, "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
