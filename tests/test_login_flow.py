import threading
import time
import unittest
from unittest.mock import patch

from backend import client_launcher as cl


class LoginWatchdogTests(unittest.TestCase):
    """The watchdog is the safety net that stops a hung login from spinning
    the progress modal forever with no error and no way back."""

    def setUp(self):
        self._orig = dict(cl.LOGIN_PROGRESS)

    def tearDown(self):
        cl.LOGIN_PROGRESS.clear()
        cl.LOGIN_PROGRESS.update(self._orig)

    def test_stalled_stage_is_forced_to_error(self):
        now = time.time()
        cl.LOGIN_PROGRESS.update(
            active=True, stage="waiting_window", message="Loading the sign-in page...",
            username="acc", started_at=now - 400, stage_at=now - 400,
        )
        # One watchdog iteration's worth of logic, without the sleep loop.
        p = cl.LOGIN_PROGRESS
        stalled = (time.time() - p["stage_at"]) > cl._LOGIN_STAGE_STALL_LIMIT
        self.assertTrue(stalled)
        cl._set_login_stage("error", "Login timed out - the Riot Client stopped responding. Try again.", "acc")
        self.assertEqual(cl.LOGIN_PROGRESS["stage"], "error")
        self.assertFalse(cl.LOGIN_PROGRESS["active"])
        self.assertTrue(cl.LOGIN_PROGRESS["can_retry"])

    def test_fresh_stage_is_left_alone(self):
        now = time.time()
        cl.LOGIN_PROGRESS.update(
            active=True, stage="typing", message="Entering username...",
            username="acc", started_at=now - 5, stage_at=now - 2,
        )
        p = cl.LOGIN_PROGRESS
        stalled = (time.time() - p["stage_at"]) > cl._LOGIN_STAGE_STALL_LIMIT
        self.assertFalse(stalled)

    def test_set_login_stage_stamps_stage_at(self):
        before = time.time()
        cl._set_login_stage("typing", "Entering password...", "acc")
        self.assertGreaterEqual(cl.LOGIN_PROGRESS["stage_at"], before)

    def test_watchdog_thread_is_running(self):
        names = {t.name for t in threading.enumerate()}
        self.assertIn("vortex-login-watchdog", names)


class LoginThreadingTests(unittest.TestCase):
    """Warm and cold logins must return to the caller immediately and do all
    of their UI Automation work on one background thread - never on the
    request thread that called login_account."""

    def setUp(self):
        self._orig = dict(cl.LOGIN_PROGRESS)
        cl.LOGIN_PROGRESS.update(active=False, stage="idle", started_at=0.0)

    def tearDown(self):
        cl.LOGIN_PROGRESS.clear()
        cl.LOGIN_PROGRESS.update(self._orig)

    def test_warm_login_returns_without_touching_uia_on_caller(self):
        done = threading.Event()

        def fake_restart(*a, **k):
            done.set()

        with patch.object(cl.ClientLauncher, "detect_riot_client_path", return_value=__file__), \
             patch("os.path.exists", return_value=True), \
             patch.object(cl.ClientLauncher, "find_riot_window", return_value=1234), \
             patch.object(cl.ClientLauncher, "is_valorant_running", return_value=False), \
             patch.object(cl.ClientLauncher, "get_lockfile_auth", return_value=None), \
             patch.object(cl.ClientLauncher, "wait_for_login_form", return_value=None) as wff, \
             patch.object(cl.ClientLauncher, "_full_restart_login", side_effect=fake_restart):
            res = cl.ClientLauncher.login_account("acc", "pw", client_path=__file__)
            # Returned straight away - the UIA call has not happened yet.
            self.assertTrue(res["success"])
            self.assertEqual(wff.call_count, 0)
            # The worker eventually runs the fallback (no form -> restart).
            self.assertTrue(done.wait(5))
            self.assertGreaterEqual(wff.call_count, 1)

    def test_cold_login_spawns_full_restart_worker(self):
        done = threading.Event()
        with patch.object(cl.ClientLauncher, "detect_riot_client_path", return_value=__file__), \
             patch("os.path.exists", return_value=True), \
             patch.object(cl.ClientLauncher, "find_riot_window", return_value=None), \
             patch.object(cl.ClientLauncher, "_full_restart_login", side_effect=lambda *a, **k: done.set()):
            res = cl.ClientLauncher.login_account("acc", "pw", client_path=__file__)
            self.assertTrue(res["success"])
            self.assertTrue(done.wait(5))


if __name__ == "__main__":
    unittest.main()
