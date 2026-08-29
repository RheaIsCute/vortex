"""
Database module for Valorant Account Manager.
Handles SQLite storage, migrations, and CRUD operations for accounts, settings,
rank icons, peak rank, account statuses (PLAYABLE, BANNED, SUSPENDED), and recent match histories.
"""

import sqlite3
import json
import os
import re
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional

if getattr(sys, "frozen", False):
    # Packaged .exe: store the DB in a writable per-user location, since
    # the install directory (e.g. Program Files) is typically read-only
    # for standard users.
    _DATA_DIR = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "Vortex")
    os.makedirs(_DATA_DIR, exist_ok=True)
    DB_FILE = os.path.join(_DATA_DIR, "database.sqlite")
else:
    DB_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database.sqlite")

VALORANT_TIER_ORDER = """
CASE UPPER(rank_tier)
    WHEN 'RADIANT' THEN 1
    WHEN 'IMMORTAL' THEN 2
    WHEN 'ASCENDANT' THEN 3
    WHEN 'DIAMOND' THEN 4
    WHEN 'PLATINUM' THEN 5
    WHEN 'GOLD' THEN 6
    WHEN 'SILVER' THEN 7
    WHEN 'BRONZE' THEN 8
    WHEN 'IRON' THEN 9
    ELSE 10
END, lp DESC
"""


class Database:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def init_db(self):
        """Initializes database tables and runs non-destructive migrations."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            
            # Accounts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL,
                    region TEXT NOT NULL DEFAULT 'NA',
                    display_name TEXT DEFAULT '',
                    tag TEXT DEFAULT 'Main',
                    notes TEXT DEFAULT '',
                    rank_tier TEXT DEFAULT 'UNRANKED',
                    rank_division TEXT DEFAULT '',
                    lp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    winrate REAL DEFAULT 0.0,
                    games_played INTEGER DEFAULT 0,
                    top_champs TEXT DEFAULT '[]',
                    rank_icon_url TEXT DEFAULT '',
                    peak_rank_tier TEXT DEFAULT '',
                    peak_rank_division TEXT DEFAULT '',
                    peak_rank_icon_url TEXT DEFAULT '',
                    peak_rank_season TEXT DEFAULT '',
                    card_small_url TEXT DEFAULT '',
                    match_history TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'PLAYABLE',
                    favorite INTEGER DEFAULT 0,
                    puuid TEXT DEFAULT '',
                    last_login TEXT DEFAULT '',
                    last_updated TEXT DEFAULT '',
                    created_at TEXT DEFAULT ''
                )
            """)

            # Run dynamic column migrations for existing SQLite databases
            cursor.execute("PRAGMA table_info(accounts)")
            existing_cols = [col["name"] for col in cursor.fetchall()]

            new_columns = [
                ("rank_icon_url", "TEXT DEFAULT ''"),
                ("peak_rank_tier", "TEXT DEFAULT ''"),
                ("peak_rank_division", "TEXT DEFAULT ''"),
                ("peak_rank_icon_url", "TEXT DEFAULT ''"),
                ("peak_rank_season", "TEXT DEFAULT ''"),
                ("card_small_url", "TEXT DEFAULT ''"),
                ("match_history", "TEXT DEFAULT '[]'"),
                ("status", "TEXT DEFAULT 'PLAYABLE'"),
                ("last_login", "TEXT DEFAULT ''"),
                # Riot's stable per-account id. Everything that reads an
                # account's local VALORANT settings folder is keyed on this -
                # without it, crosshair/keybind copying can never find a
                # source or a target.
                ("puuid", "TEXT DEFAULT ''")
            ]

            for col_name, col_def in new_columns:
                if col_name not in existing_cols:
                    try:
                        cursor.execute(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_def}")
                    except Exception:
                        pass

            # Banned/suspended accounts, kept separately from the main roster
            # so they don't clutter normal listings/filters, but the data
            # (credentials, last known rank, etc.) isn't thrown away - just
            # moved here. Mirrors the accounts table's columns plus banned_at.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS banned_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL,
                    region TEXT NOT NULL DEFAULT 'NA',
                    display_name TEXT DEFAULT '',
                    tag TEXT DEFAULT 'Main',
                    notes TEXT DEFAULT '',
                    rank_tier TEXT DEFAULT 'UNRANKED',
                    rank_division TEXT DEFAULT '',
                    lp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    winrate REAL DEFAULT 0.0,
                    games_played INTEGER DEFAULT 0,
                    top_champs TEXT DEFAULT '[]',
                    rank_icon_url TEXT DEFAULT '',
                    peak_rank_tier TEXT DEFAULT '',
                    peak_rank_division TEXT DEFAULT '',
                    peak_rank_icon_url TEXT DEFAULT '',
                    peak_rank_season TEXT DEFAULT '',
                    card_small_url TEXT DEFAULT '',
                    match_history TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'BANNED',
                    favorite INTEGER DEFAULT 0,
                    puuid TEXT DEFAULT '',
                    last_login TEXT DEFAULT '',
                    last_updated TEXT DEFAULT '',
                    created_at TEXT DEFAULT '',
                    banned_at TEXT DEFAULT ''
                )
            """)

            cursor.execute("PRAGMA table_info(banned_accounts)")
            existing_banned_cols = [col["name"] for col in cursor.fetchall()]
            for col_name, col_def in (("last_login", "TEXT DEFAULT ''"),
                                      ("puuid", "TEXT DEFAULT ''")):
                if col_name not in existing_banned_cols:
                    try:
                        cursor.execute(f"ALTER TABLE banned_accounts ADD COLUMN {col_name} {col_def}")
                    except Exception:
                        pass

            # App Settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            # Default settings
            defaults = [
                ("riot_client_path", r"C:\Riot Games\Riot Client\RiotClientServices.exe"),
                ("riot_api_key", "HDEV-259b6c27-0a83-4445-9f36-f66a3147f24c"),
                ("theme", "blue"),
                ("auto_minimize_on_launch", "true"),
                # Tick Riot's "Stay signed in" during automated logins, so a
                # relaunch of the Riot Client doesn't ask for the password again.
                ("stay_signed_in", "1"),
                # Start VALORANT by itself once a plain Login lands. Off by
                # default - Login and Play stay distinct actions unless asked.
                ("auto_launch_after_login", "0"),
                # Native quick panel, summoned globally by the hotkey below.
                ("overlay_enabled", "1"),
                ("overlay_hotkey", "SHIFT+5"),
            ]
            for k, v in defaults:
                cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

            # Migrate any legacy 'Smurf' tags to 'Ranked' (if level >= 20) or 'Unrated'
            cursor.execute("UPDATE accounts SET tag = 'Ranked' WHERE UPPER(tag) = 'SMURF' AND level >= 20")
            cursor.execute("UPDATE accounts SET tag = 'Unrated' WHERE UPPER(tag) = 'SMURF'")

            # Migrate auto-applied legacy 'Main' tags to 'Ranked' / 'Unrated' unless user explicitly sets it
            cursor.execute("UPDATE accounts SET tag = CASE WHEN level >= 20 THEN 'Ranked' ELSE 'Unrated' END WHERE UPPER(tag) = 'MAIN'")

            # Repair "ghost" accounts: rows whose status ended up NULL or blank
            # (e.g. added while no Riot Client session was detected, so the
            # status default never got applied). SQLite treats
            # `UPPER(NULL) NOT IN (...)` as NULL, so these rows silently drop
            # out of every listing without being moved to the banned table.
            cursor.execute(
                "UPDATE accounts SET status = 'PLAYABLE' "
                "WHERE status IS NULL OR TRIM(status) = ''"
            )

            # Auto-migrate any banned/suspended accounts currently lingering in the accounts table
            cursor.execute("SELECT id FROM accounts WHERE UPPER(status) IN ('BANNED', 'SUSPENDED')")
            lingering_rows = cursor.fetchall()
            for l_row in lingering_rows:
                b_id = l_row["id"]
                cursor.execute("SELECT * FROM accounts WHERE id = ?", (b_id,))
                acc_row = cursor.fetchone()
                if acc_row:
                    acc_dict = dict(acc_row)
                    cols = self._ACCOUNT_COLUMNS
                    placeholders = ", ".join(["?"] * (len(cols) + 1))
                    cursor.execute("DELETE FROM banned_accounts WHERE LOWER(TRIM(username)) = LOWER(?)", (acc_dict.get("username", "").strip(),))
                    cursor.execute(
                        f"INSERT INTO banned_accounts ({', '.join(cols)}, banned_at) VALUES ({placeholders})",
                        [acc_dict.get(c) for c in cols] + [acc_dict.get("last_updated") or datetime.now().isoformat()]
                    )
                    cursor.execute("DELETE FROM accounts WHERE id = ?", (b_id,))

            conn.commit()
        finally:
            conn.close()

    def repair_ghost_accounts(self) -> int:
        """
        Fixes rows whose status is NULL or blank by setting it to 'PLAYABLE'.
        Such rows are present in the database but silently excluded from every
        listing (SQLite evaluates `UPPER(NULL) NOT IN (...)` as NULL, not
        true) and are never moved to the banned table either. Returns the
        number of rows repaired.
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE accounts SET status = 'PLAYABLE' "
                "WHERE status IS NULL OR TRIM(status) = ''"
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def get_all_accounts(
        self,
        search: str = "",
        region: str = "",
        tag: str = "",
        status: str = "",
        sort_by: str = "level"
    ) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            # Sweep any lingering banned accounts from accounts table into banned_accounts
            cursor.execute("SELECT id FROM accounts WHERE UPPER(status) IN ('BANNED', 'SUSPENDED')")
            lingering_rows = cursor.fetchall()
            if lingering_rows:
                for l_row in lingering_rows:
                    b_id = l_row["id"]
                    cursor.execute("SELECT * FROM accounts WHERE id = ?", (b_id,))
                    acc_row = cursor.fetchone()
                    if acc_row:
                        acc_dict = dict(acc_row)
                        cols = self._ACCOUNT_COLUMNS
                        placeholders = ", ".join(["?"] * (len(cols) + 1))
                        cursor.execute("DELETE FROM banned_accounts WHERE LOWER(TRIM(username)) = LOWER(?)", (acc_dict.get("username", "").strip(),))
                        cursor.execute(
                            f"INSERT INTO banned_accounts ({', '.join(cols)}, banned_at) VALUES ({placeholders})",
                            [acc_dict.get(c) for c in cols] + [acc_dict.get("last_updated") or datetime.now().isoformat()]
                        )
                        cursor.execute("DELETE FROM accounts WHERE id = ?", (b_id,))
                conn.commit()

            # NULL-safe: a row with a NULL/blank status is still an active
            # account, not a hidden one.
            query = (
                "SELECT * FROM accounts "
                "WHERE (status IS NULL OR UPPER(status) NOT IN ('BANNED', 'SUSPENDED'))"
            )
            params = []

            if search:
                query += " AND (username LIKE ? OR display_name LIKE ? OR notes LIKE ?)"
                like_str = f"%{search}%"
                params.extend([like_str, like_str, like_str])

            if region and region.upper() != "ALL":
                query += " AND UPPER(region) = ?"
                params.append(region.upper())

            if tag and tag.upper() != "ALL":
                if tag.upper() == "RANKED":
                    query += " AND (level >= 20 OR UPPER(tag) = 'RANKED')"
                elif tag.upper() == "UNRATED":
                    query += " AND (level < 20 OR UPPER(tag) = 'UNRATED')"
                else:
                    query += " AND UPPER(tag) = ?"
                    params.append(tag.upper())

            if status and status.upper() != "ALL":
                if status.upper() == "BANNED":
                    query += " AND UPPER(status) IN ('BANNED', 'SUSPENDED')"
                elif status.upper() == "PLAYABLE":
                    # Treat NULL/blank status as playable too.
                    query += " AND (status IS NULL OR TRIM(status) = '' OR UPPER(status) = 'PLAYABLE')"
                else:
                    query += " AND UPPER(status) = ?"
                    params.append(status.upper())

            if sort_by == "rank":
                query += f" ORDER BY favorite DESC, {VALORANT_TIER_ORDER}"
            elif sort_by == "favorite":
                query += " ORDER BY favorite DESC, level DESC"
            elif sort_by == "winrate":
                query += " ORDER BY favorite DESC, winrate DESC"
            elif sort_by == "name":
                query += " ORDER BY favorite DESC, username COLLATE NOCASE ASC"
            elif sort_by == "last_updated":
                query += " ORDER BY favorite DESC, last_updated DESC"
            else:  # "level" or default
                query += " ORDER BY favorite DESC, level DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def get_account_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def get_account_by_puuid(self, puuid: str) -> Optional[Dict[str, Any]]:
        """The stored account for a Riot puuid, or None."""
        if not (puuid or "").strip():
            return None
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE puuid = ? LIMIT 1", (puuid.strip(),))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def account_exists(self, username: str) -> Optional[str]:
        """
        Checks whether a username already exists, in either the main roster
        or the banned list. Returns "active", "banned", or None.

        Matching is case-insensitive and whitespace-trimmed, since the same
        account typed/imported twice often differs only by those.
        """
        uname = (username or "").strip()
        if not uname:
            return None

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM accounts WHERE LOWER(TRIM(username)) = LOWER(?) LIMIT 1",
                (uname,)
            )
            if cursor.fetchone():
                return "active"

            cursor.execute(
                "SELECT 1 FROM banned_accounts WHERE LOWER(TRIM(username)) = LOWER(?) LIMIT 1",
                (uname,)
            )
            if cursor.fetchone():
                return "banned"

            return None
        finally:
            conn.close()

    def add_account(self, account: Dict[str, Any]) -> int:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            top_champs_json = json.dumps(account.get("top_champs", []))
            match_history_json = json.dumps(account.get("match_history", []))
            now = datetime.now().isoformat()

            lvl_val = int(account.get("level", 1) or 1)
            raw_tag = (account.get("tag") or "").strip()
            if not raw_tag or raw_tag.lower() == "smurf":
                tag_val = "Ranked" if lvl_val >= 20 else "Unrated"
            else:
                tag_val = raw_tag

            cursor.execute("""
                INSERT INTO accounts (
                    username, password, region, display_name, tag, notes,
                    rank_tier, rank_division, lp, level, winrate, games_played,
                    top_champs, rank_icon_url, peak_rank_tier, peak_rank_division,
                    peak_rank_icon_url, peak_rank_season, card_small_url,
                    match_history, status, favorite, puuid, last_updated, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                account.get("username", "").strip(),
                account.get("password", "").strip(),
                account.get("region", "NA").strip().upper(),
                account.get("display_name", "").strip(),
                tag_val,
                account.get("notes", "").strip(),
                account.get("rank_tier", "UNRANKED").strip().upper(),
                account.get("rank_division", "").strip(),
                account.get("lp", 0),
                lvl_val,
                account.get("winrate", 0.0),
                account.get("games_played", 0),
                top_champs_json,
                account.get("rank_icon_url", ""),
                account.get("peak_rank_tier", ""),
                account.get("peak_rank_division", ""),
                account.get("peak_rank_icon_url", ""),
                account.get("peak_rank_season", ""),
                account.get("card_small_url", ""),
                match_history_json,
                (account.get("status") or "PLAYABLE"),
                1 if account.get("favorite") else 0,
                (account.get("puuid") or "").strip(),
                now,
                now
            ))
            new_id = cursor.lastrowid
            conn.commit()

            if (account.get("status") or "").upper() in ("BANNED", "SUSPENDED"):
                self.move_to_banned(new_id)

            return new_id
        finally:
            conn.close()

    # Fields that should never be overwritten with a blank/empty value.
    # Riot's live-sync APIs (esp. peak rank, which needs an extra
    # entitlements+MMR round trip) are flaky under frequent polling
    # (rate limits, transient timeouts) and quietly fall back to "" on
    # failure. Without this guard, a single failed background sync would
    # wipe out a peak rank that was correctly fetched moments earlier.
    STICKY_NON_EMPTY_FIELDS = {
        "peak_rank_tier", "peak_rank_division", "peak_rank_icon_url", "peak_rank_season",
        "match_history", "top_champs", "puuid"
    }

    def update_account(self, account_id: int, updates: Dict[str, Any]) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            fields = []
            values = []

            for key, val in updates.items():
                if key in ("id", "created_at"):
                    continue
                if key in self.STICKY_NON_EMPTY_FIELDS and not val:
                    # Don't blank out a previously-synced value with an
                    # empty result from a failed/partial fetch.
                    continue
                if key == "status" and not val:
                    # Never write a NULL/blank status - it would make the row
                    # vanish from every listing (see the ghost-account repair
                    # in init_db).
                    continue
                if key in ("winrate", "games_played") and not val:
                    # A wiped winrate / match count is always a failed lookup,
                    # never a real result - an account with games played can't
                    # drop back to zero of them.
                    continue
                if key == "level" and (not isinstance(val, int) or val < 1):
                    # Level 0/None/garbage only ever comes from a failed
                    # lookup. The producers already omit "level" entirely
                    # when they have no data; this is a backstop so a bad
                    # value can't overwrite a good stored level.
                    continue
                if key in ("top_champs", "match_history") and isinstance(val, (list, dict)):
                    val = json.dumps(val)
                elif key == "favorite":
                    val = 1 if val else 0
                fields.append(f"{key} = ?")
                values.append(val)

            if not fields:
                return False

            values.append(account_id)
            query = f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()

            # If updated status is banned or suspended, automatically move out of active roster
            new_status = (updates.get("status") or "").upper()
            if new_status in ("BANNED", "SUSPENDED"):
                self.move_to_banned(account_id)

            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_account(self, account_id: int) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    _ACCOUNT_COLUMNS = [
        "username", "password", "region", "display_name", "tag", "notes",
        "rank_tier", "rank_division", "lp", "level", "winrate", "games_played",
        "top_champs", "rank_icon_url", "peak_rank_tier", "peak_rank_division",
        "peak_rank_icon_url", "peak_rank_season", "card_small_url",
        "match_history", "status", "favorite", "puuid", "last_login",
        "last_updated", "created_at"
    ]

    def move_to_banned(self, account_id: int) -> bool:
        """
        Moves an account from the main roster into the separate
        banned_accounts table - the data (credentials, last known rank,
        match history, etc.) is preserved, not deleted, just kept out of
        the normal account list/filters.
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            if not row:
                return False

            data = dict(row)
            cols = self._ACCOUNT_COLUMNS
            placeholders = ", ".join(["?"] * (len(cols) + 1))
            # Delete any duplicate in banned_accounts with same username first
            cursor.execute("DELETE FROM banned_accounts WHERE LOWER(TRIM(username)) = LOWER(?)", (data.get("username", "").strip(),))
            cursor.execute(
                f"INSERT INTO banned_accounts ({', '.join(cols)}, banned_at) VALUES ({placeholders})",
                [data.get(c) for c in cols] + [datetime.now().isoformat()]
            )
            cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def get_banned_accounts(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM banned_accounts ORDER BY banned_at DESC")
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def get_banned_account_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM banned_accounts WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def update_banned_account(self, account_id: int, updates: Dict[str, Any]) -> bool:
        """Same field-update logic as update_account, but for banned_accounts (used when rechecking a banned account's status)."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            fields = []
            values = []
            for key, val in updates.items():
                if key in ("id", "created_at", "banned_at"):
                    continue
                if key in self.STICKY_NON_EMPTY_FIELDS and not val:
                    continue
                if key == "level" and (not isinstance(val, int) or val < 1):
                    continue
                if key in ("top_champs", "match_history") and isinstance(val, (list, dict)):
                    val = json.dumps(val)
                elif key == "favorite":
                    val = 1 if val else 0
                fields.append(f"{key} = ?")
                values.append(val)
            if not fields:
                return False
            values.append(account_id)
            cursor.execute(f"UPDATE banned_accounts SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def restore_from_banned(self, account_id: int) -> Optional[int]:
        """
        Moves an account back from banned_accounts into the main accounts
        table (used when a recheck finds it's actually playable again) and
        returns its new id in the accounts table, or None if not found.
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM banned_accounts WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            if not row:
                return None

            data = dict(row)
            if (data.get("status") or "").upper() in ("BANNED", "SUSPENDED"):
                data["status"] = "PLAYABLE"

            cols = self._ACCOUNT_COLUMNS
            placeholders = ", ".join(["?"] * len(cols))
            # Delete any duplicate in accounts with same username first
            cursor.execute("DELETE FROM accounts WHERE LOWER(TRIM(username)) = LOWER(?)", (data.get("username", "").strip(),))
            cursor.execute(
                f"INSERT INTO accounts ({', '.join(cols)}) VALUES ({placeholders})",
                [data.get(c) for c in cols]
            )
            new_id = cursor.lastrowid
            cursor.execute("DELETE FROM banned_accounts WHERE id = ?", (account_id,))
            conn.commit()
            return new_id
        finally:
            conn.close()

    def delete_banned_account(self, account_id: int) -> bool:
        """Permanently deletes one banned account record (explicit user action, not automatic)."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM banned_accounts WHERE id = ?", (account_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def toggle_favorite(self, account_id: int) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE accounts SET favorite = CASE WHEN favorite = 1 THEN 0 ELSE 1 END WHERE id = ?", (account_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_stats_summary(self) -> Dict[str, Any]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM accounts")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as mains FROM accounts WHERE UPPER(tag) = 'MAIN'")
            mains = cursor.fetchone()["mains"]

            cursor.execute("SELECT COUNT(*) as ranked FROM accounts WHERE level >= 20 OR UPPER(tag) = 'RANKED'")
            ranked = cursor.fetchone()["ranked"]

            cursor.execute("SELECT COUNT(*) as unrated FROM accounts WHERE level < 20 AND UPPER(tag) NOT IN ('MAIN', 'ALT', 'RANKED')")
            unrated = cursor.fetchone()["unrated"]

            cursor.execute("SELECT region, COUNT(*) as count FROM accounts GROUP BY region")
            regions = {row["region"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) as banned FROM banned_accounts")
            banned = cursor.fetchone()["banned"]

            return {
                "total_accounts": total,
                "main_accounts": mains,
                "ranked_accounts": ranked,
                "unrated_accounts": unrated,
                "banned_accounts": banned,
                "regions": regions
            }
        finally:
            conn.close()

    def get_settings(self) -> Dict[str, str]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            return {row["key"]: row["value"] for row in cursor.fetchall()}
        finally:
            conn.close()

    def update_settings(self, settings_dict: Dict[str, str]):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            for k, v in settings_dict.items():
                cursor.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, str(v))
                )
            conn.commit()
        finally:
            conn.close()

    def export_all(self) -> List[Dict[str, Any]]:
        return self.get_all_accounts(sort_by="name")

    def import_all(self, accounts_list: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Restores accounts from a JSON backup, skipping any that already
        exist in the main roster or the banned list.
        """
        count = 0
        skipped_existing = 0
        skipped_banned = 0
        seen_in_batch = set()

        for acc in accounts_list:
            if "username" not in acc or "password" not in acc:
                continue

            uname_key = (acc.get("username") or "").strip().lower()
            if not uname_key or uname_key in seen_in_batch:
                skipped_existing += 1
                continue

            existing = self.account_exists(acc["username"])
            if existing == "banned":
                skipped_banned += 1
                continue
            if existing == "active":
                skipped_existing += 1
                continue

            seen_in_batch.add(uname_key)
            self.add_account(acc)
            count += 1

        return {
            "imported": count,
            "skipped_existing": skipped_existing,
            "skipped_banned": skipped_banned
        }

    def import_from_text(self, raw_text: str) -> Dict[str, Any]:
        """
        Parses text files or raw combo lists into account entries:
        Formats supported:
        - username:password
        - username:password:region
        - username:password:region:tag
        - username:password:RiotID#TAG
        - username,password
        - username | password

        Accounts already present - in the main roster OR the banned list -
        are skipped rather than duplicated, as are repeats within the pasted
        text itself. Returns the created accounts plus skip counts.
        """
        created_accounts = []
        skipped_existing = 0
        skipped_banned = 0
        seen_in_batch = set()
        lines = raw_text.strip().splitlines()

        for line in lines:
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#") or cleaned.startswith("//"):
                continue

            parts = []
            if ":" in cleaned:
                parts = cleaned.split(":")
            elif "|" in cleaned:
                parts = [p.strip() for p in cleaned.split("|")]
            elif "," in cleaned:
                parts = [p.strip() for p in cleaned.split(",")]
            elif "\t" in cleaned:
                parts = [p.strip() for p in cleaned.split("\t")]

            if len(parts) >= 2:
                username = parts[0].strip()
                password = parts[1].strip()
                region = "NA"
                tag = ""
                display_name = ""

                if len(parts) >= 3:
                    p3 = parts[2].strip()
                    if "#" in p3:
                        display_name = p3
                    elif p3.upper() in ("NA", "EU", "AP", "KR", "BR", "LATAM"):
                        region = p3.upper()
                    else:
                        tag = p3

                if len(parts) >= 4:
                    p4 = parts[3].strip()
                    if "#" in p4:
                        display_name = p4
                    elif p4.upper() in ("NA", "EU", "AP", "KR", "BR", "LATAM"):
                        region = p4.upper()
                    else:
                        tag = p4

                # Skip anything we already have, including repeats inside
                # this same paste.
                uname_key = username.strip().lower()
                if not uname_key or uname_key in seen_in_batch:
                    skipped_existing += 1
                    continue

                existing = self.account_exists(username)
                if existing == "banned":
                    skipped_banned += 1
                    continue
                if existing == "active":
                    skipped_existing += 1
                    continue

                seen_in_batch.add(uname_key)

                acc_data = {
                    "username": username,
                    "password": password,
                    "region": region,
                    "tag": tag if tag else "Unrated",
                    "display_name": display_name,
                    "rank_tier": "UNRANKED",
                    "level": 1,
                    "status": "UNVERIFIED"
                }
                acc_id = self.add_account(acc_data)
                acc_data["id"] = acc_id
                created_accounts.append(acc_data)

        return {
            "created": created_accounts,
            "skipped_existing": skipped_existing,
            "skipped_banned": skipped_banned
        }

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        if "top_champs" in d and d["top_champs"]:
            try:
                d["top_champs"] = json.loads(d["top_champs"])
            except Exception:
                d["top_champs"] = []
        else:
            d["top_champs"] = []

        if "match_history" in d and d["match_history"]:
            try:
                d["match_history"] = json.loads(d["match_history"])
            except Exception:
                d["match_history"] = []
        else:
            d["match_history"] = []

        d["favorite"] = bool(d.get("favorite", 0))
        d["status"] = d.get("status") or "PLAYABLE"
        return d
