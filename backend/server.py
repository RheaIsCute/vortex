"""
FastAPI Backend Server for Valorant Account Manager.
Serves REST API endpoints for accounts, live rank stats, match histories,
batch text combo imports, status detection (PLAYABLE/BANNED/SUSPENDED),
and automated full-roster account checker ("Check Accounts").
"""

import os
import time
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
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

    for _ in range(15):
        await asyncio.sleep(2.0)
        info = await asyncio.to_thread(launcher.get_active_riot_account, target_username)
        if info and info.get("found") and (info.get("display_name") or info.get("username")):
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
    
    # Auto-fill from active Riot Client if fields were empty
    if not account_dict.get("display_name"):
        info = await asyncio.to_thread(launcher.get_active_riot_account)
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



@app.post("/api/accounts/refresh-all")
async def refresh_all_accounts():
    accounts = db.get_all_accounts()

    # Auto-sync active account in Riot Client
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

    # Fetch up to date accounts
    accounts = db.get_all_accounts()
    tasks = [process_acc(acc) for acc in accounts if acc.get("display_name")]
    if tasks:
        await asyncio.gather(*tasks)

    return {"success": True, "refreshed_count": len(tasks)}


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
    Downloads the latest installer and opens Explorer with it selected so
    the user can run it themselves.

    The app deliberately doesn't launch the installer directly: some
    security software blocks an app from spawning an installer and shows an
    alarming "Security validation failure" dialog. Handing off to Explorer
    avoids that entirely.
    """
    update_info = await asyncio.to_thread(updater.check_for_update)
    if not update_info:
        return {"success": False, "message": "No update available."}

    installer_path = await asyncio.to_thread(updater.download_installer, update_info["url"], update_info["version"])
    if not installer_path:
        return {"success": False, "message": "Failed to download the update. Check your connection and try again."}

    await asyncio.to_thread(updater.reveal_installer, installer_path)
    return {
        "success": True,
        "installer_path": installer_path,
        "message": f"Version {update_info['version']} downloaded. Close Vortex, then run VortexSetup to finish updating."
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


def _match_account_to_session(username: str) -> Optional[Dict[str, Any]]:
    """Finds the stored account matching the signed-in Riot Client username."""
    if not username:
        return None
    target = username.strip().lower()
    for acc in db.get_all_accounts():
        if acc["username"].strip().lower() == target:
            return acc
    return None


def _roster_entry(player: Dict[str, Any], names: Dict[str, str], self_puuid: str) -> Dict[str, Any]:
    agent = valorant_client.agent_by_id(player.get("CharacterID", ""))
    tier = (player.get("SeasonalBadgeInfo") or {}).get("Rank") or player.get("CompetitiveTier") or 0
    subject = player.get("Subject", "")
    identity = player.get("PlayerIdentity", {}) or {}

    return {
        "puuid": subject,
        "name": names.get(subject, "") or ("Hidden" if identity.get("Incognito") else ""),
        "agent": agent.get("name", ""),
        "agent_icon": agent.get("icon", ""),
        "team": player.get("TeamID", ""),
        "level": identity.get("AccountLevel", 0),
        "tier": tier,
        "tier_label": valorant_client.tier_label(tier),
        "tier_icon": valorant_client.tier_icon(tier),
        "is_self": subject == self_puuid,
        "locked": (player.get("CharacterSelectionState", "") == "locked"),
    }


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


def _build_pregame_block(client, presence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    match_id = client.pregame_match_id()
    if not match_id:
        return None

    data = client.pregame_match(match_id)
    if not data:
        return None

    ally = (data.get("AllyTeam") or {}).get("Players", []) or []
    puuids = [p.get("Subject", "") for p in ally if p.get("Subject")]
    names = _cached_names(client, match_id, puuids)
    map_info = valorant_client.resolve_map(data.get("MapID", ""))

    remaining_ns = data.get("PhaseTimeRemainingNS", 0) or 0

    return {
        "phase": "agent_select",
        "match_id": match_id,
        "map": map_info,
        "mode": valorant_client.resolve_mode(data.get("Mode", ""), presence.get("queueId", "")),
        "time_remaining": round(remaining_ns / 1_000_000_000, 1),
        "team": [_roster_entry(p, names, client.puuid) for p in ally],
        "enemy": [],
        "score": {"ally": 0, "enemy": 0},
        "round": 0,
    }


def _build_coregame_block(client, presence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    match_id = client.coregame_match_id()
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

    roster = [_roster_entry(p, names, client.puuid) for p in players]
    ally = [r for r in roster if r["team"] == self_team]
    enemy = [r for r in roster if r["team"] != self_team]

    ally_score = int(presence.get("partyOwnerMatchScoreAllyTeam", 0) or 0)
    enemy_score = int(presence.get("partyOwnerMatchScoreEnemyTeam", 0) or 0)
    map_id = data.get("MapID") or presence.get("matchMap", "")

    return {
        "phase": "in_match",
        "match_id": match_id,
        "map": valorant_client.resolve_map(map_id),
        "mode": valorant_client.resolve_mode(data.get("ModeID", ""), presence.get("queueId", "")),
        "time_remaining": 0,
        "team": ally,
        "enemy": enemy,
        "score": {"ally": ally_score, "enemy": enemy_score},
        "round": ally_score + enemy_score + 1,
        "side": presence.get("partyOwnerMatchCurrentTeam", "") or self_team,
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

    matched = _match_account_to_session(info.get("username", ""))
    if matched:
        snapshot["account_id"] = matched["id"]
        if not snapshot["display_name"]:
            snapshot["display_name"] = matched.get("display_name", "")

    snapshot["valorant_running"] = launcher.is_valorant_running()
    if not snapshot["valorant_running"]:
        return snapshot

    client = valorant_client.ValorantLiveClient()
    if not client.connect():
        snapshot["message"] = "Waiting for the game's session to come up..."
        return snapshot

    snapshot["puuid"] = client.puuid
    presence = client.presence()
    loop_state = (presence.get("sessionLoopState") or "MENUS").upper()
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

    try:
        if loop_state == "PREGAME":
            snapshot["match"] = _build_pregame_block(client, presence)
        elif loop_state == "INGAME":
            snapshot["match"] = _build_coregame_block(client, presence)
    except valorant_client.LiveClientError as e:
        snapshot["message"] = str(e)

    if snapshot["match"]:
        snapshot["message"] = ""
    elif snapshot["party"].get("in_queue"):
        snapshot["message"] = f"In queue for {snapshot['queue_label'] or 'a match'}..."
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
        if req.queue_id:
            client.change_queue(req.queue_id)
            time.sleep(0.4)
        client.start_queue()
        return valorant_client.MODE_LABELS.get(req.queue_id or "", "") or "the selected mode"

    try:
        label = await asyncio.to_thread(_run)
    except valorant_client.LiveClientError as e:
        return {"success": False, "message": str(e)}

    invalidate_live_snapshot()
    return {"success": True, "message": f"Searching for a {label} match..."}


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
        match_id = client.pregame_match_id()
        if not match_id:
            raise valorant_client.LiveClientError("You're not in agent select right now.")
        client.select_agent(req.agent_id, match_id)
        return client.lock_agent(req.agent_id, match_id)

    try:
        locked = await asyncio.to_thread(_run)
    except valorant_client.LiveClientError as e:
        return {"success": False, "message": str(e)}

    agent = valorant_client.agent_by_id(req.agent_id)
    if not locked:
        return {"success": False, "message": f"Couldn't lock {agent.get('name') or 'that agent'} - it may be taken."}
    return {"success": True, "message": f"Locked {agent['name']}."}


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

        launched = await asyncio.to_thread(valorant_client.launch_valorant, client_path)
        if not launched:
            return {"success": False, "message": "Couldn't start VALORANT - check the Riot Client path in Settings."}
        return {"success": True, "switched": False, "message": f"Starting VALORANT as {account.get('display_name') or account['username']}..."}

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
