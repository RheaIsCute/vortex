from datetime import datetime, timedelta, timezone

from backend.client_launcher import _timed_penalty
from backend.database import Database


def test_timed_queue_penalty_normalizes_riot_milliseconds():
    expiry = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp() * 1000)

    penalty = _timed_penalty("TEMP_BANNED", [{
        "type": "QUEUE_BAN",
        "expiration": expiry,
    }])

    assert penalty["penalty_type"] == "Queue ban"
    assert datetime.fromisoformat(penalty["penalty_expires_at"]) > datetime.now(timezone.utc)


def test_expired_restriction_is_not_an_active_penalty():
    expiry = int((datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp())

    assert _timed_penalty("SUSPENDED", [{"type": "SUSPENDED", "expiresAt": expiry}]) == {}


def test_penalty_metadata_round_trips_through_account_storage(tmp_path):
    db = Database(str(tmp_path / "penalties.sqlite"))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    account_id = db.add_account({
        "username": "penalty-user",
        "password": "secret",
        "penalty_type": "Matchmaking suspended",
        "penalty_expires_at": expires,
    })

    account = db.get_account_by_id(account_id)
    assert account["penalty_type"] == "Matchmaking suspended"
    assert account["penalty_expires_at"] == expires
