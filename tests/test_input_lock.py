"""
Safety tests for the login input lock.

No real hook is ever installed and no real input is ever suppressed - a test
that genuinely froze the mouse and keyboard would be indistinguishable from a
hung machine. ``_user32``/``_kernel32`` are replaced with fakes that record
calls instead.

The load-bearing tests are the passthrough ones. v5.6.4 shipped a lock built on
``BlockInput`` which, held on a dedicated thread, silently swallowed Vortex's
*own* synthetic keystrokes: the login form filled (UI Automation, an API call)
but could never submit. Anything that suppresses injected input is that bug.
"""

import ctypes
import threading
import time
import unittest
from unittest.mock import patch

from backend import input_lock


class FakeUser32:
    """Records hook installs/removals; never touches the real input stream."""

    def __init__(self, can_hook: bool = True):
        self.can_hook = can_hook
        self.installed = []          # hook ids installed, in order
        self.unhooked = []           # hook handles removed
        self.next_hook_handle = 1000
        self.call_next_calls = 0
        self._events = {}            # handle -> signalled?

    # -- hook management ----------------------------------------------------
    def SetWindowsHookExW(self, hook_id, proc, hmod, tid):
        if not self.can_hook:
            return 0
        self.next_hook_handle += 1
        self.installed.append(hook_id)
        return self.next_hook_handle

    def UnhookWindowsHookEx(self, handle):
        self.unhooked.append(handle)
        return 1

    def CallNextHookEx(self, handle, code, w_param, l_param):
        self.call_next_calls += 1
        return 0

    # -- message pump -------------------------------------------------------
    def MsgWaitForMultipleObjects(self, count, handles, wait_all, ms, mask):
        handle = handles[0]
        deadline = time.monotonic() + min(ms / 1000.0, 0.05)
        while time.monotonic() < deadline:
            if self._events.get(handle):
                return input_lock.WAIT_OBJECT_0
            time.sleep(0.002)
        if self._events.get(handle):
            return input_lock.WAIT_OBJECT_0
        return 1                      # woke for messages / timed out

    def PeekMessageW(self, *_args):
        return 0

    # -- event objects (kernel32 side, kept here for one shared store) ------
    def signal(self, handle):
        self._events[handle] = True


class FakeKernel32:
    def __init__(self, user32: FakeUser32):
        self.user32 = user32
        self.next_handle = 500
        self.closed = []

    def CreateEventW(self, attrs, manual, initial, name):
        self.next_handle += 1
        self.user32._events[self.next_handle] = False
        return self.next_handle

    def SetEvent(self, handle):
        self.user32.signal(handle)
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


def _kb_lparam(vk: int, injected: bool) -> int:
    """A real KBDLLHOOKSTRUCT, addressed the way Windows passes it."""
    s = input_lock.KBDLLHOOKSTRUCT(
        vkCode=vk, scanCode=0,
        flags=(input_lock.LLKHF_INJECTED if injected else 0),
        time=0, dwExtraInfo=None,
    )
    _KEEPALIVE.append(s)
    return ctypes.cast(ctypes.byref(s), ctypes.c_void_p).value


def _ms_lparam(injected: bool) -> int:
    s = input_lock.MSLLHOOKSTRUCT(
        pt=ctypes.wintypes.POINT(0, 0), mouseData=0,
        flags=(input_lock.LLMHF_INJECTED if injected else 0),
        time=0, dwExtraInfo=None,
    )
    _KEEPALIVE.append(s)
    return ctypes.cast(ctypes.byref(s), ctypes.c_void_p).value


_KEEPALIVE = []      # structs must outlive the pointers handed to callbacks


class _LockTestBase(unittest.TestCase):
    def setUp(self):
        _KEEPALIVE.clear()
        self.user32 = FakeUser32()
        self.kernel32 = FakeKernel32(self.user32)
        self._patches = [
            patch.object(input_lock, "_user32", self.user32),
            patch.object(input_lock, "_kernel32", self.kernel32),
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


class PassthroughTests(_LockTestBase):
    """Vortex's own automation must never be suppressed. This is the v5.6.4 bug."""

    def test_injected_keystroke_passes_through(self):
        input_lock._blocked.set()
        result = input_lock._keyboard_callback(0, 0x0100, _kb_lparam(0x41, injected=True))
        self.assertNotEqual(result, 1, "an injected keystroke was suppressed")
        self.assertEqual(self.user32.call_next_calls, 1)

    def test_injected_enter_passes_through(self):
        """The submit fallback is pyautogui.press('enter') - it must survive."""
        input_lock._blocked.set()
        result = input_lock._keyboard_callback(0, 0x0100, _kb_lparam(0x0D, injected=True))
        self.assertNotEqual(result, 1, "the submit keystroke was suppressed")

    def test_injected_click_passes_through(self):
        input_lock._blocked.set()
        result = input_lock._mouse_callback(0, 0x0201, _ms_lparam(injected=True))
        self.assertNotEqual(result, 1, "an injected click was suppressed")

    def test_physical_keystroke_is_suppressed(self):
        input_lock._blocked.set()
        result = input_lock._keyboard_callback(0, 0x0100, _kb_lparam(0x41, injected=False))
        self.assertEqual(result, 1, "a real keystroke reached the application")

    def test_physical_click_is_suppressed(self):
        input_lock._blocked.set()
        result = input_lock._mouse_callback(0, 0x0201, _ms_lparam(injected=False))
        self.assertEqual(result, 1, "a real click reached the application")

    def test_mouse_movement_passes_through(self):
        """Movement cannot steal focus; a frozen cursor reads as a hang."""
        input_lock._blocked.set()
        result = input_lock._mouse_callback(0, input_lock.WM_MOUSEMOVE, _ms_lparam(injected=False))
        self.assertNotEqual(result, 1)

    def test_nothing_is_suppressed_when_not_locked(self):
        input_lock._blocked.clear()
        self.assertNotEqual(
            input_lock._keyboard_callback(0, 0x0100, _kb_lparam(0x41, injected=False)), 1)
        self.assertNotEqual(
            input_lock._mouse_callback(0, 0x0201, _ms_lparam(injected=False)), 1)

    def test_negative_ncode_is_always_passed_on(self):
        """Win32 requires nCode < 0 to go straight to CallNextHookEx."""
        input_lock._blocked.set()
        self.assertNotEqual(
            input_lock._keyboard_callback(-1, 0x0100, _kb_lparam(0x41, injected=False)), 1)


class LifecycleTests(_LockTestBase):
    def test_arm_installs_both_hooks_and_release_removes_them(self):
        self.assertTrue(input_lock.arm("test"))
        self.assertTrue(input_lock.is_locked())
        self.assertCountEqual(
            self.user32.installed, [input_lock.WH_KEYBOARD_LL, input_lock.WH_MOUSE_LL])

        input_lock.release("test done")
        self.assertFalse(input_lock.is_locked())
        self.assertEqual(len(self.user32.unhooked), 2, "a hook was left installed")

    def test_failed_hook_install_reports_unlocked(self):
        self.user32.can_hook = False
        self.assertFalse(input_lock.arm("test"))
        self.assertFalse(input_lock.is_locked())
        self.assertIn("hooks", input_lock.status()["last_error"])

    def test_disabled_preference_never_locks(self):
        input_lock.set_enabled(False)
        self.assertFalse(input_lock.arm("test"))
        self.assertFalse(input_lock.is_locked())
        self.assertEqual(self.user32.installed, [])

    def test_timeout_releases_without_any_caller(self):
        self.assertTrue(input_lock.arm("test", timeout=1.0))
        self.assertTrue(
            self._wait_until(lambda: not input_lock.is_locked(), timeout=6.0),
            "input lock outlived its timeout ceiling",
        )
        self.assertEqual(input_lock.status()["released_by"], "timeout")
        self.assertEqual(len(self.user32.unhooked), 2)

    def test_escape_releases_early(self):
        self.assertTrue(input_lock.arm("test", timeout=60.0))
        # A real ESC press arrives through the hook.
        input_lock._keyboard_callback(0, 0x0100, _kb_lparam(input_lock.VK_ESCAPE, injected=False))
        self.assertTrue(
            self._wait_until(lambda: not input_lock.is_locked(), timeout=6.0),
            "ESC did not lift the input lock",
        )
        self.assertEqual(input_lock.status()["released_by"], "escape key")

    def test_injected_escape_does_not_release(self):
        """Vortex sending ESC to the Riot Client must not drop the lock."""
        self.assertTrue(input_lock.arm("test", timeout=60.0))
        input_lock._keyboard_callback(0, 0x0100, _kb_lparam(input_lock.VK_ESCAPE, injected=True))
        time.sleep(0.3)
        self.assertTrue(input_lock.is_locked(), "an injected ESC released the lock")

    def test_release_without_arm_is_safe(self):
        input_lock.release("nothing held")
        self.assertFalse(input_lock.is_locked())
        self.assertEqual(self.user32.installed, [])

    def test_double_arm_does_not_stack_hooks(self):
        self.assertTrue(input_lock.arm("first"))
        self.assertTrue(input_lock.arm("second"))
        self.assertEqual(len(self.user32.installed), 2, "a second pair of hooks was installed")
        input_lock.release("done")
        self.assertEqual(len(self.user32.unhooked), 2)

    def test_release_is_idempotent(self):
        input_lock.arm("test")
        input_lock.release("once")
        input_lock.release("twice")
        self.assertEqual(len(self.user32.unhooked), 2)

    def test_release_from_another_thread(self):
        input_lock.arm("test", timeout=60.0)
        done = threading.Event()
        threading.Thread(
            target=lambda: (input_lock.release("other thread"), done.set()), daemon=True).start()
        self.assertTrue(done.wait(5.0))
        self.assertFalse(input_lock.is_locked())


class LoginWorkerIntegrationTests(_LockTestBase):
    """The lock must follow a login attempt's real lifecycle."""

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
        self.assertFalse(input_lock.is_locked(), "a crashed login left input locked")

    def test_superseded_worker_does_not_release_the_newer_attempt(self):
        from backend import client_launcher as cl

        cl.LOGIN_PROGRESS["attempt"] = 9          # attempt 9 is the live one
        cl._run_login_worker(8, threading.Event(), lambda: None)   # stale attempt

        self.assertTrue(input_lock.is_locked(),
                        "a superseded worker released the active attempt's lock")
        input_lock.release("cleanup")


if __name__ == "__main__":
    unittest.main()
