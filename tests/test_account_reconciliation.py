from backend.database import Database


def test_reconciliation_hides_puuid_duplicates_without_deleting_credentials(tmp_path):
    db = Database(str(tmp_path / "data.sqlite"))
    first_id = db.add_account({
        "username": "old-login", "password": "first-secret", "puuid": "same-puuid",
        "display_name": "Player#NA1",
    })
    second_id = db.add_account({
        "username": "new-login", "password": "second-secret", "puuid": "same-puuid",
        "display_name": "Player#NA1",
    })

    result = db.reconcile_accounts()

    assert result["visible_accounts"] == 1
    assert result["duplicate_records"] == 1
    assert [account["id"] for account in db.get_all_accounts()] == [first_id]
    # Both records stay in SQLite; reconciliation is deliberately non-destructive.
    assert db.get_account_by_id(first_id)["password"] == "first-secret"
    assert db.get_account_by_id(second_id)["password"] == "second-secret"


def test_reconciliation_does_not_merge_conflicting_puuids(tmp_path):
    db = Database(str(tmp_path / "data.sqlite"))
    db.add_account({
        "username": "one", "password": "one", "puuid": "puuid-one",
        "display_name": "SharedName#NA1",
    })
    db.add_account({
        "username": "two", "password": "two", "puuid": "puuid-two",
        "display_name": "SharedName#NA1",
    })

    result = db.reconcile_accounts()

    assert result["visible_accounts"] == 2
    assert result["duplicate_records"] == 0
    assert len(db.get_all_accounts()) == 2


def test_reconciliation_uses_riot_id_only_for_unknown_puuid_records(tmp_path):
    db = Database(str(tmp_path / "data.sqlite"))
    original_id = db.add_account({
        "username": "first", "password": "", "display_name": "Player#NA1",
    })
    db.add_account({
        "username": "second", "password": "preserved-secret", "display_name": "Player#NA1",
    })

    result = db.reconcile_accounts()

    assert result["visible_accounts"] == 1
    # Filling an empty credential is safe; no nonempty credential is replaced.
    assert db.get_account_by_id(original_id)["password"] == "preserved-secret"
