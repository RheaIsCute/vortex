"""
Safety tests for the login input lock.

The real ``BlockInput`` is never called here - a test that genuinely froze the
mouse and keyboard would be indistinguishable from a hung machine. ``_user32``
is replaced with a fake that records the calls instead, so every assertion is
about the release paths that keep a user from being locked out.
"""

import threading
import time
import unittest
from unittest.mock import patch

from backend import input_lock


class FakeUser32:
    """Stand-in for user32 that records BlockInput calls."""

    def __init__(self, allow: bool = True):
        self.allow = allow
        self.calls = []
        self.blocked = False
        self.esc_down = False
        self.unblock_raises = False

    def BlockInput(self, flag):
        self.calls.append(bool(flag))
        if flag:
            if not self.allow:
                return 0
            self.blocked = True
            return 1
        if self.unblock_raises:
            raise OSError("simulated failure")
        self.blocked = False
        return 1

    def GetAsyncKeyState(self, _vk):
        # Win32 returns the high bit set for a physically-down key; as a signed
        # short that is -32768.
        return -32768 if self.esc_down else 0


class InputLockTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeUser32()
        self._patches = [
            patch.object(input_lock, "_user32", self.fake),
            patch.object(input_lock, "_IS_WINDOWS", True),
        ]
        for p in self._patches:
            p.start()
        input_lock.set_enabled(True)

    def tearDown(self):
        input_lock.release("test teardown")
        for p in reversed(self._patches):
            p.stop()
        input_lock.set_enabled(True)

    def _wait_until(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def test_arm_blocks_and_release_unblocks(self):
        self.assertTrue(input_lock.arm("test"))
        self.assertTrue(input_lock.is_locked())
        self.assertTrue(self.fake.blocked)

        input_lock.release("test done")
        self.assertFalse(input_lock.is_locked())
        self.assertFalse(self.fake.blocked)
        # Exactly one block and one matching unblock.
        self.assertEqual(self.fake.calls, [True, False])

    def test_disabled_preference_never_blocks(self):
        input_lock.set_enabled(False)
        self.assertFalse(input_lock.arm("test"))
        self.assertFalse(input_lock.is_locked())
        self.assertEqual(self.fake.calls, [])

    def test_refused_block_reports_unlocked(self):
        """An unelevated / already-blocked refusal must not claim a lock."""
        self.fake.allow = False
        self.assertFalse(input_lock.arm("test"))
        self.assertFalse(input_lock.is_locked())
        self.assertIn("refused", input_lock.status()["last_error"])

    def test_timeout_releases_without_any_caller(self):
        """The ceiling is the backstop for a caller that never releases."""
        self.assertTrue(input_lock.arm("test", timeout=1.0))
        self.assertTrue(
            self._wait_until(lambda: not input_lock.is_locked(), timeout=5.0),
            "input lock outlived its timeout ceiling",
        )
        self.assertFalse(self.fake.blocked)
        self.assertEqual(input_lock.status()["released_by"], "timeout")

    def test_holding_escape_releases_early(self):
        self.assertTrue(input_lock.arm("test", timeout=60.0))
        self.fake.esc_down = True
        self.assertTrue(
            self._wait_until(lambda: not input_lock.is_locked(), timeout=5.0),
            "ESC did not lift the input lock",
        )
        self.assertFalse(self.fake.blocked)
        self.assertEqual(input_lock.status()["released_by"], "escape key")

    def test_unblock_exception_still_clears_locked_state(self):
        """A throwing BlockInput(False) must not leave us believing we're locked."""
        self.assertTrue(input_lock.arm("test"))
        self.fake.unblock_raises = True
        input_lock.release("test done")
        self.assertFalse(input_lock.is_locked())

    def test_release_without_arm_is_safe(self):
        input_lock.release("nothing held")
        self.assertFalse(input_lock.is_locked())
        self.assertEqual(self.fake.calls, [])

    def test_double_arm_does_not_stack_blocks(self):
        self.assertTrue(input_lock.arm("first"))
        self.assertTrue(input_lock.arm("second"))
        self.assertEqual(self.fake.calls.count(True), 1)
        input_lock.release("done")
        self.assertEqual(self.fake.calls, [True, False])
        self.assertFalse(self.fake.blocked)

    def test_release_is_idempotent(self):
        input_lock.arm("test")
        input_lock.release("once")
        input_lock.release("twice")
        self.assertEqual(self.fake.calls, [True, False])

    def test_release_from_another_thread(self):
        """Release is called from the request thread, not the holder thread."""
        input_lock.arm("test", timeout=60.0)
        done = threading.Event()

        def worker():
            input_lock.release("from another thread")
            done.set()

        threading.Thread(target=worker, daemon=True).start()
        self.assertTrue(done.wait(5.0))
        self.assertFalse(input_lock.is_locked())
        self.assertFalse(self.fake.blocked)


class LoginWorkerIntegrationTests(unittest.TestCase):
    """The lock must follow a login attempt's real lifecycle."""

    def setUp(self):
        self.fake = FakeUser32()
        self._patches = [
            patch.object(input_lock, "_user32", self.fake),
            patch.object(input_lock, "_IS_WINDOWS", True),
        ]
        for p in self._patches:
            p.start()
        input_lock.set_enabled(True)

    def tearDown(self):
        input_lock.release("test teardown")
        for p in reversed(self._patches):
            p.stop()

    def test_worker_releases_even_when_the_target_raises(self):
        from backend import client_launcher as cl

        cl.LOGIN_PROGRESS["attempt"] = 7
        locked_during_run = []

        def boom():
            locked_during_run.append(input_lock.is_locked())
            raise RuntimeError("automation blew up")

        with self.assertRaises(RuntimeError):
            cl._run_login_worker(7, threading.Event(), boom)

        self.assertEqual(locked_during_run, [True], "login ran without the lock")
        self.assertFalse(input_lock.is_locked(), "a crashed login left input blocked")
        self.assertFalse(self.fake.blocked)

    def test_superseded_worker_does_not_release_the_newer_attempt(self):
        """
        A stale worker finishing late must leave the replacing attempt's lock
        alone - otherwise the new login types with input unblocked.
        """
        from backend import client_launcher as cl

        cl.LOGIN_PROGRESS["attempt"] = 9      # attempt 9 is the live one

        def stale_target():
            pass

        cl._run_login_worker(8, threading.Event(), stale_target)   # older attempt

        self.assertTrue(input_lock.is_locked(),
                        "a superseded worker released the active attempt's lock")
        input_lock.release("cleanup")


if __name__ == "__main__":
    unittest.main()
