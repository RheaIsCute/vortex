from backend.database import Database


def test_raw_combo_import_preserves_password_after_first_colon(tmp_path):
    db = Database(str(tmp_path / "accounts.sqlite"))

    result = db.import_from_text("  user@example.com:p:ass:word!  \n\nother:secret\n")

    assert result["malformed_lines"] == []
    assert len(result["created"]) == 2
    saved = db.get_all_accounts(sort_by="name")
    assert next(a for a in saved if a["username"] == "user@example.com")["password"] == "p:ass:word!"


def test_raw_combo_import_reports_bad_rows_and_skips_duplicates(tmp_path):
    db = Database(str(tmp_path / "accounts.sqlite"))

    result = db.import_from_text("good:one\nmissing-separator\n:no-user\ngood:two\nempty:\n")

    assert len(result["created"]) == 1
    assert result["skipped_existing"] == 1
    assert [item["line"] for item in result["malformed_lines"]] == [2, 3, 5]


def test_confirmed_low_level_competitive_access_is_ranked_capable(tmp_path):
    db = Database(str(tmp_path / "accounts.sqlite"))
    account_id = db.add_account({
        "username": "legacy", "password": "pw", "level": 9,
        "competitive_queue_eligible": True,
        "ranked_eligibility_source": "party_eligible_queues",
    })

    account = db.get_account_by_id(account_id)
    assert account["tag"] == "Ranked"
    assert account["ranked_capable"] is True
    assert account["is_legacy_ranked_eligible"] is True
    assert [a["id"] for a in db.get_all_accounts(tag="Unrated")] == []
    assert [a["id"] for a in db.get_all_accounts(tag="Ranked")] == [account_id]


def test_normal_sub_level_20_account_is_not_assumed_eligible(tmp_path):
    db = Database(str(tmp_path / "accounts.sqlite"))
    account_id = db.add_account({"username": "new", "password": "pw", "level": 9})

    account = db.get_account_by_id(account_id)
    assert account["tag"] == "Unrated"
    assert account["competitive_queue_eligible"] is None
    assert account["is_legacy_ranked_eligible"] is False
    assert account["ranked_capable"] is False


def test_unknown_refresh_does_not_erase_confirmed_queue_eligibility(tmp_path):
    db = Database(str(tmp_path / "accounts.sqlite"))
    account_id = db.add_account({
        "username": "legacy", "password": "pw", "level": 9,
        "competitive_queue_eligible": True,
        "ranked_eligibility_source": "party_eligible_queues",
    })

    db.update_account(account_id, {
        "competitive_queue_eligible": None,
        "ranked_eligibility_source": "",
    })

    account = db.get_account_by_id(account_id)
    assert account["competitive_queue_eligible"] is True
    assert account["ranked_eligibility_source"] == "party_eligible_queues"
    assert account["ranked_capable"] is True


def test_stats_count_confirmed_low_level_ranked_account(tmp_path):
    db = Database(str(tmp_path / "accounts.sqlite"))
    db.add_account({
        "username": "legacy", "password": "pw", "level": 9,
        "competitive_queue_eligible": True,
    })
    db.add_account({"username": "normal", "password": "pw", "level": 9})

    stats = db.get_stats_summary()
    assert stats["ranked_accounts"] == 1
    assert stats["unrated_accounts"] == 1
