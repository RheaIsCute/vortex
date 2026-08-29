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
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    status = (acc.get("status") or "").upper()
    return not (has_riot_id and was_synced and status not in ("UNVERIFIED", "BANNED", "SUSPENDED"))


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
            custom_path if custom_path else None
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


@app.delete("/api/banned-accounts/{account_id}")
async def delete_banned_account(account_id: int):
    """Permanently deletes one banned account record (explicit action, not automatic)."""
    success = db.delete_banned_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Banned account not found")
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
        custom_path if custom_path else None
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
async def launch_account(account_id: int, background_tasks: BackgroundTasks):
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    settings = db.get_settings()
    custom_path = settings.get("riot_client_path", "")

    result = await asyncio.to_thread(
        launcher.login_account,
        account["username"],
        account["password"],
        custom_path if custom_path else None
    )

    # Automatically watch, sync Level, Region, Rank, Peak Rank, and link Riot ID
    db.update_account(account_id, {"last_login": datetime.now().isoformat()})
    note_account_login(account_id)
    background_tasks.add_task(background_auto_detect_and_link, account_id)
    
    return {
        "success": result["success"],
        "message": result["message"],
        "account": account,
        "copied": "password"
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


class GameConfigCopyRequest(BaseModel):
    source_account_id: int
    target_account_id: Optional[int] = None  # omitted = whoever's signed in now
    gameplay: bool = True
    video: bool = True


class GameConfigBorderlessRequest(BaseModel):
    account_id: Optional[int] = None  # omitted = whoever's signed in now


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


_PLAYER_MMR_CACHE: Dict[str, Dict[str, Any]] = {}


def _get_player_stats(client, puuid: str, fallback_tier: int = 0) -> Dict[str, Any]:
    if not puuid:
        return valorant_client.parse_player_mmr({})
    if puuid in _PLAYER_MMR_CACHE:
        return _PLAYER_MMR_CACHE[puuid]

    try:
        raw_mmr = client.player_mmr(puuid)
        stats = valorant_client.parse_player_mmr(raw_mmr)
    except Exception:
        stats = valorant_client.parse_player_mmr({})

    try:
        combat = client.player_combat_summary(puuid, max_matches=5)
    except Exception:
        combat = {}

    # Store combat & form metrics from the last 5 matches
    stats["kd_last5"] = combat.get("kd", 0.0)
    stats["kda_last5"] = combat.get("kda", 0.0)
    stats["hs_pct_last5"] = combat.get("hs_pct", 0)
    stats["adr_last5"] = combat.get("adr", 0)
    stats["acs_last5"] = combat.get("acs", 0)
    stats["wins_last5"] = combat.get("wins", 0)
    stats["losses_last5"] = combat.get("losses", 0)
    stats["draws_last5"] = combat.get("draws", 0)
    stats["winrate_last5"] = combat.get("winrate", 0)
    stats["form_last5"] = combat.get("form", [])
    stats["matches_analyzed"] = combat.get("matches_analyzed", 0)

    # Use 5-match combat metrics for recent performance indicators
    stats["kd"] = stats["kd_last5"]
    stats["kda"] = stats["kda_last5"]
    stats["hs_pct"] = stats["hs_pct_last5"]
    stats["adr"] = stats["adr_last5"]
    stats["acs"] = stats["acs_last5"]

    # Party data across all analyzed matches
    stats["parties"] = combat.get("parties") or {}
    stats["match_parties"] = combat.get("match_parties") or {}

    if stats["tier"] == 0 and fallback_tier > 0:
        stats["tier"] = fallback_tier
        stats["tier_label"] = valorant_client.tier_label(fallback_tier)
        stats["tier_icon"] = valorant_client.tier_icon(fallback_tier)
        if stats["peak_tier"] < fallback_tier:
            stats["peak_tier"] = fallback_tier
            stats["peak_tier_label"] = stats["tier_label"]
            stats["peak_tier_icon"] = stats["tier_icon"]

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
        "winrate_lifetime": stats.get("winrate", 0),
        "winrate": stats.get("winrate_last5", 0),
        "winrate_last5": stats.get("winrate_last5", 0),
        "wins_last5": stats.get("wins_last5", 0),
        "losses_last5": stats.get("losses_last5", 0),
        "draws_last5": stats.get("draws_last5", 0),
        "form_last5": stats.get("form_last5", []),
        "matches_analyzed": stats.get("matches_analyzed", 0),
        "kd": stats.get("kd", 0.0),
        "kda": stats.get("kda", 0.0),
        "hs_pct": stats.get("hs_pct", 0),
        "adr": stats.get("adr", 0),
        "acs": stats.get("acs", 0),
        "is_self": subject == self_puuid,
        "locked": (player.get("CharacterSelectionState", "") == "locked"),
    }


_MY_PARTY: Dict[str, Any] = {"at": 0.0, "members": []}


def _my_party_members(client) -> List[str]:
    """
    PUUIDs in your current party. This is the one grouping Riot will state
    outright, so it anchors the premade detection. Cached briefly - party
    membership can't change mid-match and the snapshot already calls it.
    """
    if time.time() - _MY_PARTY["at"] < 8.0:
        return _MY_PARTY["members"]
    try:
        members = [
            (m.get("Subject") or "")
            for m in (client.party().get("Members") or [])
            if m.get("Subject")
        ]
    except Exception:
        members = []
    _MY_PARTY.update({"at": time.time(), "members": members})
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
_LIVE_PROBE: Dict[str, Any] = {"match_id": "", "next_at": 0.0, "data": None}
_LIVE_PROBE_INTERVAL = 20.0

# The match that just finished, resolved after the fact. Details take a few
# seconds to appear, so the lookup is retried on a backoff before giving up.
_LAST_MATCH: Dict[str, Any] = {
    "watch_id": "", "match_id": "", "data": None, "next_at": 0.0, "tries": 0,
}
_LAST_MATCH_MAX_TRIES = 12

# Everything played while this app has been running, for the session strip.
_SESSION: Dict[str, Any] = {"puuid": "", "ids": [], "matches": [], "started_at": 0.0}


def _side_for_round(starting_side: str, rounds_played: int) -> str:
    """Which side you are on for the round after `rounds_played` completed ones."""
    other = "Attacker" if starting_side == "Defender" else "Defender"
    if rounds_played < 12:
        return starting_side
    if rounds_played < 24:
        return other
    # Overtime runs in pairs, alternating from the second half's side.
    return other if ((rounds_played - 24) // 2) % 2 == 0 else starting_side


def _track_rounds(match_id: str, ally: int, enemy: int, starting_side: str) -> List[Dict[str, Any]]:
    """
    Appends whatever rounds have completed since the last poll and returns the
    full ledger. A match the dashboard joined late is seeded from the score
    with the entries flagged `known: false`, because the order in which those
    rounds fell simply isn't recoverable.
    """
    p = _MATCH_PROGRESS
    total = ally + enemy

    if p["match_id"] != match_id or ally < p["ally"] or enemy < p["enemy"]:
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

    played = len(p["rounds"])
    for _ in range(ally - p["ally"]):
        played += 1
        p["rounds"].append({
            "n": played, "won": True, "known": True,
            "side": _side_for_round(starting_side, played - 1),
        })
    for _ in range(enemy - p["enemy"]):
        played += 1
        p["rounds"].append({
            "n": played, "won": False, "known": True,
            "side": _side_for_round(starting_side, played - 1),
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
    won = rounds[-1]["won"]
    count = 0
    for entry in reversed(rounds):
        if entry["won"] != won:
            break
        count += 1
    return {"count": count, "won": won}


def _build_progress(match_id: str, ally: int, enemy: int, starting_side: str,
                    current_side: str, queue_id: str) -> Dict[str, Any]:
    """The rounds-won/lost header block for a match that's running."""
    rounds = _track_rounds(match_id, ally, enemy, starting_side)
    played = ally + enemy
    target = ROUNDS_TO_WIN.get((queue_id or "").lower(), 0)

    if played < 12:
        half = "1st Half"
    elif played < 24:
        half = "2nd Half"
    else:
        half = f"Overtime {((played - 24) // 2) + 1}"
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


def _live_probe(client, match_id: str) -> Optional[Dict[str, Any]]:
    """
    Your own scoreline for the match in progress, when Riot will give it up.
    Custom games answer live; ranked and unrated only once the match ends, so
    a miss is normal and simply retried on a slow cadence.
    """
    p = _LIVE_PROBE
    if p["match_id"] != match_id:
        p.update({"match_id": match_id, "next_at": 0.0, "data": None})
    if p["data"]:
        return p["data"]
    if time.time() < p["next_at"]:
        return None

    p["next_at"] = time.time() + _LIVE_PROBE_INTERVAL
    p["data"] = valorant_client.personal_match_summary(client, match_id)
    return p["data"]


def _self_block(client, match_id: str, me: Optional[Dict[str, Any]],
                queue_id: str) -> Optional[Dict[str, Any]]:
    """
    The "you, right now" card: agent and rank straight from the match, plus
    your combat line. `source` says where the numbers came from - "live" when
    they belong to this match, "recent" when they're your rolling average and
    this match hasn't been published yet.
    """
    if not me:
        return None

    live = _live_probe(client, match_id) if match_id else None
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
        "winrate_lifetime": me.get("winrate_lifetime", 0),
        "winrate": me.get("winrate_last5", me.get("winrate", 0)),
        "winrate_last5": me.get("winrate_last5", 0),
        "wins_last5": me.get("wins_last5", 0),
        "losses_last5": me.get("losses_last5", 0),
        "form_last5": me.get("form_last5", []),
        "matches_analyzed": me.get("matches_analyzed", 0),
        "wins": me.get("wins", 0),
        "games": me.get("games", 0),
        "queue_id": queue_id,
        "is_live": bool(live),
    }

    if live:
        block.update({
            "source": "live",
            "kills": live.get("kills", 0),
            "deaths": live.get("deaths", 0),
            "assists": live.get("assists", 0),
            "kd": live.get("kd", 0.0),
            "kda": round((live.get("kills", 0) + live.get("assists", 0)) /
                         max(1, live.get("deaths", 0)), 2),
            "hs_pct": live.get("hs_pct", 0),
            "adr": live.get("adr", 0),
            "acs": live.get("acs", 0),
            "headshots": live.get("headshots", 0),
            "bodyshots": live.get("bodyshots", 0),
            "legshots": live.get("legshots", 0),
            "damage": live.get("total_damage", 0),
            "rounds": live.get("rounds", 0),
            "current_match_kd": live.get("kd", 0.0),
            "current_match_hs_pct": live.get("hs_pct", 0),
        })
    else:
        block.update({
            "source": "recent",
            "kills": me.get("kills", 0),
            "deaths": me.get("deaths", 0),
            "assists": me.get("assists", 0),
            "kd": me.get("kd", 0.0),
            "kda": me.get("kda", 0.0),
            "hs_pct": me.get("hs_pct", 0),
            "adr": me.get("adr", 0),
            "acs": me.get("acs", 0),
            "headshots": 0,
            "bodyshots": 0,
            "legshots": 0,
            "damage": 0,
            "rounds": 0,
            "current_match_kd": me.get("kd", 0.0),
            "current_match_hs_pct": me.get("hs_pct", 0),
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
        if subject and subject not in _PLAYER_MMR_CACHE:
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
    Everyone else is inferred from shared party ids in recent matches across
    both teams (teammates and enemies).
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

    # 2. Everyone else, inferred from shared party ids in recent matches.
    by_team: Dict[str, List[str]] = {}
    for p in roster:
        if p.get("puuid"):
            by_team.setdefault(p.get("team", ""), []).append(p["puuid"])

    # Aggregate all match party maps across the cached players
    all_match_party_maps: List[Dict[str, str]] = []
    for p in roster:
        puuid = p.get("puuid", "")
        if puuid and puuid in _PLAYER_MMR_CACHE:
            mp = _PLAYER_MMR_CACHE[puuid].get("match_parties") or {}
            for m_id, p_map in mp.items():
                if isinstance(p_map, dict) and p_map not in all_match_party_maps:
                    all_match_party_maps.append(p_map)

    for team_puuids in by_team.values():
        for i, a in enumerate(team_puuids):
            pa = (_PLAYER_MMR_CACHE.get(a) or {}).get("parties") or {}
            for b in team_puuids[i + 1:]:
                pb = (_PLAYER_MMR_CACHE.get(b) or {}).get("parties") or {}
                # Direct match party ID match
                if any(pid and pb.get(mid) == pid for mid, pid in pa.items()):
                    union(a, b)
                    continue
                # Lobby-wide match details party map match
                for p_map in all_match_party_maps:
                    if a in p_map and b in p_map and p_map[a] and p_map[a] == p_map[b]:
                        union(a, b)
                        break

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

    self_puuid = next((p.get("puuid") for p in roster if p.get("is_self")), "")
    self_team = next((p.get("team") for p in roster if p.get("is_self")), "")

    for p in roster:
        puuid = p.get("puuid", "")
        gid = numbered.get(puuid, 0)
        group_members = groups.get(find(puuid), []) if gid else []
        g_size = len(group_members)
        is_self_party = puuid in confirmed and len(confirmed) > 1

        p_type = "Duo" if g_size == 2 else ("Trio" if g_size == 3 else f"{g_size}-Stack") if gid else ""
        if is_self_party:
            badge = f"YOUR {p_type.upper()}"
        elif gid:
            is_ally = (p.get("team") == self_team) if self_team else (p.get("team", "").lower() in ("blue", "team_1"))
            badge = f"{'TEAM' if is_ally else 'ENEMY'} {p_type.upper()}"
        else:
            badge = ""

        p["party_group"] = gid
        p["party_size"] = g_size if gid else 1
        p["party_type"] = p_type
        p["party_badge"] = badge
        p["party_confirmed"] = is_self_party


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

    return {
        "phase": "agent_select",
        "match_id": match_id,
        "map": map_info,
        "mode": valorant_client.resolve_mode(data.get("Mode", ""), presence.get("queueId", "")),
        "time_remaining": round(remaining_ns / 1_000_000_000, 1),
        "team": team,
        "enemy": enemy_roster,
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
    map_id = data.get("MapID") or presence.get("matchMap", "")
    total_rounds = ally_score + enemy_score

    starting_side = "Defender" if self_team.lower() == "blue" else "Attacker"

    # Determine current side based on round/half switch & presence hint
    pres_team = (presence.get("partyOwnerMatchCurrentTeam", "") or "").lower()
    if "defend" in pres_team or pres_team == "blue":
        current_side = "Defender"
    elif "attack" in pres_team or pres_team == "red":
        current_side = "Attacker"
    else:
        # Standard Valorant regulation: 12 rounds per half
        if total_rounds < 12:
            current_side = starting_side
        elif total_rounds < 24:
            current_side = "Attacker" if starting_side == "Defender" else "Defender"
        else:
            # Overtime (rounds 25+): switches every 2 rounds
            ot_round = total_rounds - 24
            switches = ot_round // 2
            current_side = ("Attacker" if starting_side == "Defender" else "Defender") if (switches % 2 == 1) else starting_side

    queue_id = (presence.get("queueId", "") or "").lower()
    _apply_parties(ally + enemy, _my_party_members(client))
    me = next((r for r in ally if r.get("is_self")), None)

    return {
        "phase": "in_match",
        "match_id": match_id,
        "map": valorant_client.resolve_map(map_id),
        "mode": valorant_client.resolve_mode(data.get("ModeID", ""), presence.get("queueId", "")),
        "time_remaining": 0,
        "team": ally,
        "enemy": enemy,
        "me": _self_block(client, match_id, me, queue_id),
        "progress": _build_progress(
            match_id, ally_score, enemy_score, starting_side, current_side, queue_id
        ),
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

    info = launcher.get_active_riot_account()
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

    matched = _match_account_to_session(info.get("username", ""), info.get("display_name", ""))
    if matched:
        snapshot["account_id"] = matched["id"]
        if not snapshot["display_name"]:
            snapshot["display_name"] = matched.get("display_name", "")
    else:
        uname = (info.get("username") or "").strip()
        if uname and not db.account_exists(uname):
            try:
                new_acc_id = db.add_account({
                    "username": uname,
                    "password": "",
                    "display_name": info.get("display_name", uname),
                    "region": info.get("region", "NA"),
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
    _LIVE_SNAPSHOT["built_at"] = 0.0


def get_live_snapshot(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and _LIVE_SNAPSHOT["data"] and (now - _LIVE_SNAPSHOT["built_at"]) < _LIVE_SNAPSHOT_TTL:
        return _LIVE_SNAPSHOT["data"]

    data = build_live_snapshot()
    _LIVE_SNAPSHOT["data"] = data
    _LIVE_SNAPSHOT["built_at"] = now
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


async def _apply_launch_prefs(puuid: str) -> None:
    """
    Applies this app's local-launch preferences - forced borderless display,
    and (if armed) copying a chosen "profile" account's settings onto this
    one - before the game reads its config on startup.

    Runs synchronously when the account's local config folder already exists
    (a returning account - this is a couple of small file writes, well under
    a launch's normal latency). When it doesn't - a first-ever login for this
    account on this PC, where Riot hasn't created the folder yet - the launch
    is never blocked on it; a background watcher applies the preference the
    moment the folder shows up instead.
    """
    if not puuid:
        return

    settings = db.get_settings()
    force_border = settings.get("force_borderless", "1") != "0"
    autoapply = settings.get("settings_autoapply", "0") == "1"
    profile_id = settings.get("settings_profile_account_id", "") or ""

    profile_puuid = ""
    if autoapply and profile_id.isdigit():
        prof = db.get_account_by_id(int(profile_id))
        profile_puuid = (prof or {}).get("puuid", "") or ""

    if not (force_border or profile_puuid):
        return

    def apply_now() -> None:
        if profile_puuid and profile_puuid != puuid:
            game_config.copy_settings(profile_puuid, puuid)
        if force_border:
            game_config.force_borderless(puuid)

    if game_config.account_dir(puuid):
        await asyncio.to_thread(apply_now)
        return

    def watch():
        if game_config.wait_for_account(puuid, timeout=90.0):
            apply_now()

    threading.Thread(target=watch, daemon=True).start()


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
        return [{
            "id": acc["id"],
            "display_name": acc.get("display_name") or acc.get("username", ""),
            "has_config": has_config(acc.get("puuid", "") or ""),
        } for acc in accounts]

    account_status = await asyncio.to_thread(build_status)
    profile_id = settings.get("settings_profile_account_id", "") or ""

    return {
        "force_borderless": settings.get("force_borderless", "1") != "0",
        "autoapply": settings.get("settings_autoapply", "0") == "1",
        "profile_account_id": int(profile_id) if profile_id.isdigit() else None,
        "accounts": account_status,
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


@app.post("/api/game-config/force-borderless")
async def force_borderless_now(req: GameConfigBorderlessRequest):
    """Applies windowed-borderless immediately, without waiting for the next launch."""
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

    await _apply_launch_prefs(await asyncio.to_thread(_current_puuid))
    result = await asyncio.to_thread(valorant_client.launch_valorant, client_path)
    invalidate_live_snapshot()
    return {**result, "launch": valorant_client.launch_state()}


@app.get("/api/live/launch-state")
async def live_launch_state():
    return valorant_client.launch_state()


async def background_login_then_play(account_id: int):
    """
    Waits for a freshly started login to land, then launches VALORANT for it.
    Used by Play on an account that isn't the current session.
    """
    acc = db.get_account_by_id(account_id)
    if not acc:
        return

    settings = db.get_settings()
    client_path = settings.get("riot_client_path", "") or launcher.detect_riot_client_path()

    for _ in range(40):
        await asyncio.sleep(1.0)
        info = await asyncio.to_thread(launcher.get_active_riot_account, acc["username"])
        if info and info.get("found"):
            update_payload = {k: v for k, v in info.items() if k not in ("found", "username")}
            update_payload["last_updated"] = datetime.now().isoformat()
            if apply_account_update(account_id, update_payload):
                return  # banned/suspended - don't launch
            await asyncio.sleep(1.5)
            await _apply_launch_prefs(await asyncio.to_thread(_current_puuid))
            await asyncio.to_thread(valorant_client.launch_valorant, client_path)
            return


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

    info = await asyncio.to_thread(launcher.get_active_riot_account)
    is_active = bool(
        info and info.get("found")
        and (info.get("username") or "").strip().lower() == account["username"].strip().lower()
    )

    if is_active:
        if await asyncio.to_thread(launcher.is_valorant_running):
            return {"success": True, "already_running": True, "switched": False,
                    "message": "VALORANT is already running for this account."}

        await _apply_launch_prefs(await asyncio.to_thread(_current_puuid))
        result = await asyncio.to_thread(valorant_client.launch_valorant, client_path)
        if not result.get("success"):
            return {"success": False, "message": result.get("message") or
                    "Couldn't start VALORANT - check the Riot Client path in Settings."}
        return {"success": True, "switched": False,
                "message": f"Starting VALORANT as {account.get('display_name') or account['username']}..."}

    db.update_account(account_id, {"last_login": datetime.now().isoformat()})
    note_account_login(account_id)

    # Different account signed in (or none) - log in first, then launch.
    result = await asyncio.to_thread(
        launcher.login_account, account["username"], account["password"], client_path or None
    )
    background_tasks.add_task(background_login_then_play, account_id)
    return {
        "success": result["success"],
        "switched": True,
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
                            custom_path if custom_path else None)

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
