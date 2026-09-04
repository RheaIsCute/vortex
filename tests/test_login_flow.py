import threading
import time
import unittest
from unittest.mock import MagicMock, patch

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


class CredentialInputTests(unittest.TestCase):
    class Control:
        def __init__(self, name="", control_type="EditControl", automation_id="",
                     is_password=False, children=None):
            self.Name = name
            self.ControlTypeName = control_type
            self.AutomationId = automation_id
            self.IsPassword = is_password
            self.IsOffscreen = False
            self.IsEnabled = True
            self._children = children or []

        def GetChildren(self):
            return self._children

    def test_fields_survive_riot_accessibility_name_changes(self):
        username = self.Control(name="Username or email", automation_id="login-user")
        password = self.Control(name="", automation_id="password-input", is_password=True)
        window = self.Control(control_type="WindowControl", children=[username, password])

        found_user, found_password = cl.ClientLauncher._find_login_fields(window)

        self.assertIs(found_user, username)
        self.assertIs(found_password, password)

    def test_value_pattern_enters_without_foreground_focus(self):
        field = MagicMock()
        pattern = MagicMock(IsReadOnly=False)
        current = {"value": ""}
        pattern.SetValue.side_effect = lambda value: current.update(value=value)
        field.GetValuePattern.return_value = pattern
        with patch.object(cl.ClientLauncher, "_field_text", side_effect=lambda _field: current["value"]), \
             patch.object(cl.time, "sleep"):
            self.assertTrue(cl.ClientLauncher.fill_field_verified(field, "secret", "username"))

        pattern.SetValue.assert_called_once_with("secret")
        field.SetFocus.assert_not_called()

    def test_progress_wait_wakes_on_stage_event(self):
        revision, _ = cl.wait_for_login_progress_change(-1, 0)
        result = []
        waiter = threading.Thread(
            target=lambda: result.append(cl.wait_for_login_progress_change(revision, 1.0))
        )
        waiter.start()
        cl._set_login_stage("typing", "Entering username...", "acc")
        waiter.join(1.0)
        self.assertTrue(result)
        self.assertEqual(result[0][1]["stage"], "typing")


class RiotTransientLoginPopupTests(unittest.TestCase):
    def setUp(self):
        self._orig = dict(cl.LOGIN_PROGRESS)
        cl.LOGIN_PROGRESS.update(
            active=True, stage="submitted", username="acc", message="Signing in...",
        )

    def tearDown(self):
        cl.LOGIN_PROGRESS.clear()
        cl.LOGIN_PROGRESS.update(self._orig)

    @staticmethod
    def _control(name, control_type="TextControl", children=None):
        control = MagicMock()
        control.Name = name
        control.ControlTypeName = control_type
        control.GetChildren.return_value = children or []
        return control

    def test_popup_detection_requires_failure_copy_and_sign_out_button(self):
        failure = self._control("Sorry, we're having trouble signing you in")
        failure_tail = self._control("right now.")
        sign_out = self._control("Sign out", "ButtonControl")
        root = self._control("Riot Client", children=[failure, failure_tail, sign_out])
        auto = MagicMock()
        auto.ControlFromHandle.return_value = root

        with patch.object(cl, "_uia", return_value=auto), \
             patch.object(cl.ClientLauncher, "find_riot_window", return_value=123):
            self.assertIs(cl.ClientLauncher.find_transient_login_popup(), sign_out)

        root = self._control("Riot Client", children=[self._control("Sign out", "ButtonControl")])
        auto.ControlFromHandle.return_value = root
        with patch.object(cl, "_uia", return_value=auto), \
             patch.object(cl.ClientLauncher, "find_riot_window", return_value=123):
            self.assertIsNone(cl.ClientLauncher.find_transient_login_popup())

    def test_popup_retries_same_account_and_then_succeeds(self):
        with patch.object(cl.ClientLauncher, "get_active_riot_session", side_effect=[
                None, {"found": True, "username": "acc", "display_name": "Player#NA1"}]), \
             patch.object(cl.ClientLauncher, "find_transient_login_popup", side_effect=[object(), None]), \
             patch.object(cl.ClientLauncher, "click_transient_login_sign_out", return_value=True) as click, \
             patch.object(cl.ClientLauncher, "wait_for_transient_login_popup_gone", return_value=True), \
             patch.object(cl.ClientLauncher, "wait_for_signed_out", return_value=True), \
             patch.object(cl.ClientLauncher, "wait_for_login_form", return_value=object()), \
             patch.object(cl.ClientLauncher, "_attempt_login_fill", return_value=True) as fill, \
             patch.object(cl.ClientLauncher, "check_login_error", return_value=None), \
             patch.object(cl.time, "sleep"):
            result = cl.ClientLauncher._monitor_login_result("acc", "pw", True, timeout=1)

        self.assertTrue(result)
        click.assert_called_once_with()
        fill.assert_called_once_with("acc", "pw", True, tries=3, form_timeout=20.0)
        self.assertEqual(cl.LOGIN_PROGRESS["stage"], "done")

    def test_popup_stops_after_three_total_attempts(self):
        with patch.object(cl.ClientLauncher, "get_active_riot_session", return_value=None), \
             patch.object(cl.ClientLauncher, "find_transient_login_popup", return_value=object()), \
             patch.object(cl.ClientLauncher, "click_transient_login_sign_out", return_value=True) as click, \
             patch.object(cl.ClientLauncher, "wait_for_transient_login_popup_gone", return_value=True), \
             patch.object(cl.ClientLauncher, "wait_for_signed_out", return_value=True), \
             patch.object(cl.ClientLauncher, "wait_for_login_form", return_value=object()), \
             patch.object(cl.ClientLauncher, "_attempt_login_fill", return_value=True) as fill, \
             patch.object(cl.time, "sleep"):
            result = cl.ClientLauncher._monitor_login_result("acc", "pw", True, timeout=1)

        self.assertFalse(result)
        self.assertEqual(click.call_count, 2)
        self.assertEqual(fill.call_count, 2)
        self.assertEqual(
            cl.LOGIN_PROGRESS["message"],
            "Riot login temporarily unavailable after 3 attempts.",
        )
        self.assertFalse(cl.LOGIN_PROGRESS["active"])

    def test_two_popups_allow_the_third_attempt_to_succeed(self):
        with patch.object(cl.ClientLauncher, "get_active_riot_session", side_effect=[
                None, None, None, {"found": True, "username": "acc"}]), \
             patch.object(cl.ClientLauncher, "find_transient_login_popup", side_effect=[
                 object(), object(), None]), \
             patch.object(cl.ClientLauncher, "click_transient_login_sign_out", return_value=True) as click, \
             patch.object(cl.ClientLauncher, "wait_for_transient_login_popup_gone", return_value=True), \
             patch.object(cl.ClientLauncher, "wait_for_signed_out", return_value=True), \
             patch.object(cl.ClientLauncher, "wait_for_login_form", return_value=object()), \
             patch.object(cl.ClientLauncher, "_attempt_login_fill", return_value=True) as fill, \
             patch.object(cl.ClientLauncher, "check_login_error", return_value=None), \
             patch.object(cl.time, "sleep"):
            result = cl.ClientLauncher._monitor_login_result("acc", "pw", True, timeout=1)

        self.assertTrue(result)
        self.assertEqual(click.call_count, 2)
        self.assertEqual(fill.call_count, 2)

    def test_result_monitor_timeout_releases_the_attempt(self):
        with patch.object(cl.ClientLauncher, "get_active_riot_session", return_value=None), \
             patch.object(cl.ClientLauncher, "find_transient_login_popup", return_value=None), \
             patch.object(cl.ClientLauncher, "find_login_validation_error", return_value=None), \
             patch.object(cl.ClientLauncher, "check_login_error", return_value=None), \
             patch.object(cl.time, "monotonic", side_effect=[0.0, 1.0]), \
             patch.object(cl.time, "sleep"):
            result = cl.ClientLauncher._monitor_login_result("acc", "pw", True, timeout=0.5)

        self.assertFalse(result)
        self.assertEqual(cl.LOGIN_PROGRESS["stage"], "error")
        self.assertFalse(cl.LOGIN_PROGRESS["active"])
        self.assertTrue(cl.LOGIN_PROGRESS["can_retry"])

    def test_client_validation_releases_the_attempt(self):
        with patch.object(cl.ClientLauncher, "get_active_riot_session", return_value=None), \
             patch.object(cl.ClientLauncher, "find_transient_login_popup", return_value=None), \
             patch.object(cl.ClientLauncher, "find_login_validation_error", return_value="unsupported special characters"):
            result = cl.ClientLauncher._monitor_login_result("acc", "pw", True, timeout=1)

        self.assertFalse(result)
        self.assertIn("Remove unsupported characters", cl.LOGIN_PROGRESS["message"])
        self.assertFalse(cl.LOGIN_PROGRESS["active"])


if __name__ == "__main__":
    unittest.main()
