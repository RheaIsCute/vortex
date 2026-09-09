import os

from backend.database import Database


def test_blank_update_cannot_erase_password(tmp_path):
    db = Database(str(tmp_path / "data.sqlite"))
    account_id = db.add_account({"username": "player", "password": "secret"})

    db.update_account(account_id, {"password": ""})

    assert db.get_account_by_id(account_id)["password"] == "secret"


def test_unavailable_profile_values_cannot_erase_verified_rank(tmp_path):
    db = Database(str(tmp_path / "data.sqlite"))
    account_id = db.add_account({
        "username": "player",
        "rank_tier": "DIAMOND",
        "rank_division": "2",
        "lp": 37,
        "rank_icon_url": "https://example.test/diamond.png",
    })

    db.update_account(account_id, {
        "rank_tier": None,
        "rank_division": None,
        "lp": None,
        "rank_icon_url": None,
    })

    account = db.get_account_by_id(account_id)
    assert account["rank_tier"] == "DIAMOND"
    assert account["rank_division"] == "2"
    assert account["lp"] == 37
    assert account["rank_icon_url"] == "https://example.test/diamond.png"


def test_active_backup_round_trip_excludes_banned_accounts_and_repairs_blank_password(tmp_path):
    source = Database(str(tmp_path / "source.sqlite"))
    source.add_account({"username": "active", "password": "one"})
    banned_id = source.add_account({"username": "banned", "password": "two"})
    source.update_account(banned_id, {"status": "BANNED"})
    backup = source.export_all()
    assert "settings" not in backup
    assert backup["banned_accounts"] == []
    # Legacy backups may contain this field; modern imports must ignore it.
    backup["settings"] = {"theme": "crimson", "overwolf_enabled": "1"}

    target = Database(str(tmp_path / "target.sqlite"))
    target.update_settings({"theme": "purple", "overwolf_enabled": "0"})
    existing_id = target.add_account({"username": "active", "password": "temporary"})
    conn = target.get_connection()
    conn.execute("UPDATE accounts SET password='' WHERE id=?", (existing_id,))
    conn.commit()
    conn.close()

    result = target.import_backup(backup)

    assert result["repaired_passwords"] == 1
    assert target.get_account_by_id(existing_id)["password"] == "one"
    assert target.account_exists("banned") is None
    assert target.get_settings()["theme"] == "purple"
    assert target.get_settings()["overwolf_enabled"] == "0"
    assert os.path.isdir(tmp_path / "backups")
