import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend import server


class BatchAccountCheckTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.progress = dict(server.CHECK_PROGRESS)
        self.login_progress = dict(server.client_launcher.LOGIN_PROGRESS)
        server.CHECK_PROGRESS.update(running=True, current=0, total=1,
                                     account="", message="", verified=0, failed=0)

    def tearDown(self):
        server.CHECK_PROGRESS.clear()
        server.CHECK_PROGRESS.update(self.progress)
        server.client_launcher.LOGIN_PROGRESS.clear()
        server.client_launcher.LOGIN_PROGRESS.update(self.login_progress)

    async def test_window_failure_is_retryable_not_invalid(self):
        server.client_launcher.LOGIN_PROGRESS.update(
            username="example", stage="error",
            message="Could not focus the Riot Client window.", active=False,
        )
        with patch.object(server.launcher, "get_active_riot_account", return_value=None):
            result = await server._wait_for_checked_account("example", timeout=1)

        self.assertFalse(result["invalid_credentials"])
        self.assertIn("focus", result["message"])

    async def test_riot_credential_rejection_is_identified_but_retained(self):
        server.client_launcher.LOGIN_PROGRESS.update(
            username="example", stage="submitted",
            message="Signing in...", active=True,
        )
        with patch.object(server.launcher, "get_active_riot_account", return_value=None), \
             patch.object(server.launcher, "check_login_error", return_value="invalid_credentials"):
            result = await server._wait_for_checked_account("example", timeout=1)

        self.assertTrue(result["invalid_credentials"])
        self.assertIsNone(result["info"])

    @patch.object(server.db, "is_globally_banned", return_value=False)
    async def test_batch_failure_never_deletes_the_account(self, _global_banned):
        account = {"id": 7, "username": "example", "password": "saved", "tag": ""}
        retryable = {
            "info": None, "cancelled": False, "invalid_credentials": False,
            "message": "Could not focus the Riot Client window.",
        }
        with patch.object(server.db, "get_all_accounts", return_value=[account]), \
             patch.object(server, "account_needs_check", return_value=True), \
             patch.object(server.db, "get_settings", return_value={}), \
             patch.object(server.launcher, "kill_valorant", return_value=True), \
             patch.object(server.launcher, "force_kill_riot_client", return_value=True), \
             patch.object(server.launcher, "wait_for_processes_gone", return_value=True), \
             patch.object(server.launcher, "login_account", return_value={"success": True}), \
             patch.object(server.launcher, "api_sign_out", return_value=True), \
             patch.object(server.launcher, "wait_for_signed_out", return_value=True), \
             patch.object(server, "_wait_for_checked_account", new=AsyncMock(return_value=retryable)), \
             patch.object(server.asyncio, "sleep", new=AsyncMock()), \
             patch.object(server.db, "delete_account", new=MagicMock()) as delete_account:
            await server.run_batch_account_check()

        delete_account.assert_not_called()
        self.assertEqual(server.CHECK_PROGRESS["failed"], 1)
        self.assertIn("kept for retry", server.CHECK_PROGRESS["message"])

    async def test_single_check_uses_shared_waiter_and_releases_failed_attempt(self):
        account = {"id": 7, "username": "bad-then-good", "password": "saved"}
        server.CHECK_PROGRESS["running"] = False
        failed = {
            "info": None, "cancelled": False, "invalid_credentials": False,
            "message": "Riot rejected the sign-in form.",
        }
        with patch.object(server.db, "get_account_by_id", return_value=account), \
             patch.object(server.db, "get_settings", return_value={}), \
             patch.object(server.launcher, "login_account", return_value={"success": True}), \
             patch.object(server, "_wait_for_checked_account", new=AsyncMock(return_value=failed)) as waiter:
            result = await server.check_single_account(7)

        self.assertFalse(result["success"])
        self.assertIn("sign-in form", result["message"])
        waiter.assert_awaited_once_with("bad-then-good", timeout=120.0, cancel_with_batch=False)

    @patch.object(server.db, "is_globally_banned", return_value=False)
    async def test_batch_finally_releases_a_leftover_login_attempt(self, _global_banned):
        account = {"id": 7, "username": "example", "password": "saved", "tag": ""}
        server.client_launcher.LOGIN_PROGRESS.update(
            active=True, stage="submitted", username="example", message="Signing in..."
        )
        with patch.object(server.db, "get_all_accounts", return_value=[account]), \
             patch.object(server, "account_needs_check", return_value=True), \
             patch.object(server.db, "get_settings", return_value={}), \
             patch.object(server.launcher, "force_kill_riot_client", return_value=True), \
             patch.object(server.launcher, "wait_for_processes_gone", return_value=True), \
             patch.object(server.launcher, "kill_valorant", return_value=True), \
             patch.object(server.launcher, "login_account", return_value={"success": False, "message": "busy"}), \
             patch.object(server.launcher, "api_sign_out", return_value=True), \
             patch.object(server.launcher, "wait_for_signed_out", return_value=True), \
             patch.object(server.asyncio, "sleep", new=AsyncMock()):
            await server.run_batch_account_check()

        self.assertFalse(server.client_launcher.LOGIN_PROGRESS["active"])
        self.assertEqual(server.client_launcher.LOGIN_PROGRESS["stage"], "error")

    @patch.object(server.db, "is_globally_banned", return_value=False)
    async def test_sequential_transition_waits_for_state_then_uses_short_cooldown(self, _global_banned):
        accounts = [
            {"id": 7, "username": "first", "password": "saved", "tag": ""},
            {"id": 8, "username": "second", "password": "saved", "tag": ""},
        ]
        sleep = AsyncMock()
        with patch.object(server.db, "get_all_accounts", return_value=accounts), \
             patch.object(server, "account_needs_check", return_value=True), \
             patch.object(server.db, "get_settings", return_value={}), \
             patch.object(server.launcher, "kill_valorant", return_value=True), \
             patch.object(server.launcher, "force_kill_riot_client", return_value=True), \
             patch.object(server.launcher, "wait_for_processes_gone", return_value=True) as process_wait, \
             patch.object(server.launcher, "login_account", return_value={"success": False, "message": "busy"}), \
             patch.object(server.launcher, "api_sign_out", return_value=True), \
             patch.object(server.launcher, "wait_for_signed_out", return_value=True) as signout_wait, \
             patch.object(server.asyncio, "sleep", new=sleep):
            await server.run_batch_account_check()

        process_wait.assert_called_once()
        self.assertEqual(signout_wait.call_count, 2)
        sleep.assert_awaited_once_with(0.25)

    async def test_batch_skips_and_moves_globally_known_banned_username(self):
        account = {"id": 7, "username": "known-ban", "password": "saved", "tag": ""}
        with patch.object(server.db, "get_all_accounts", return_value=[account]), patch.object(
                server.db, "is_globally_banned", return_value=True), patch.object(
                server.db, "move_to_banned", return_value=True) as move, patch.object(
                server.launcher, "login_account") as login:
            await server.run_batch_account_check()

        move.assert_called_once_with(7)
        login.assert_not_called()


if __name__ == "__main__":
    unittest.main()
