"""
Vortex Valorant Account Manager - Desktop Application Launcher.
Starts the local backend server cleanly and opens the native desktop window with custom branding & taskbar icon.
"""

import sys
import os
import io
import ctypes
import traceback


def _enable_per_monitor_dpi_awareness():
    """Render WebView2 at the native DPI of whichever monitor owns it.

    This must run before pywebview, WinForms, or any other UI library is
    imported.  If Windows sees the process as merely system-DPI-aware it may
    bitmap-scale the whole window after a monitor/DPI change, which makes
    otherwise hardware-accelerated text look soft or pixelated.
    """
    if sys.platform != "win32":
        return

    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except (AttributeError, OSError):
        pass

    try:
        # Windows 8.1 fallback: PROCESS_PER_MONITOR_DPI_AWARE.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


_enable_per_monitor_dpi_awareness()

# Set Windows AppUserModelID for custom Taskbar icon & grouping
try:
    myappid = "vortex.valorant.accountmanager.v2"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

# Ensure streams are valid under pythonw (windowless)
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import time
import socket
import threading
import webbrowser
import uvicorn
import webview
import win32gui
import win32con
import win32api

# When frozen by PyInstaller (onefile build), bundled data files live under
# sys._MEIPASS (a temp extraction dir), not next to this script.
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, BASE_DIR)

from backend.server import app, db
from backend.overlay_hotkey import OverlayHotkey

ICON_PATH = os.path.join(BASE_DIR, "frontend", "assets", "logo.ico")

OVERLAY_WIDTH = 430
OVERLAY_HEIGHT = 640
OVERLAY_MARGIN = 24
OVERLAY_TITLE = "Vortex Quick Panel"
LIVE_HUD_WIDTH = 300
LIVE_HUD_HEIGHT = 188
LIVE_HUD_TITLE = "Vortex Live Aim HUD"
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000


def find_available_port(default_port: int = 8765) -> int:
    """Finds an available TCP port starting from default_port."""
    for port in range(default_port, default_port + 50):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return default_port


PORT = find_available_port(8765)
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"
STARTUP_LOG = os.path.join(os.environ.get("TEMP") or BASE_DIR, "vortex_startup.log")


def _startup_log(message):
    """Small persistent trace for failures that happen before the UI exists."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(STARTUP_LOG, "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] pid={os.getpid()} {message}\n")
    except OSError:
        pass


def start_server():
    """Runs the Uvicorn ASGI server in a dedicated daemon thread."""
    config = uvicorn.Config(
        app=app,
        host=HOST,
        port=PORT,
        log_config=None,
        access_log=False
    )
    server = uvicorn.Server(config)
    server.run()


def apply_window_icon_loop():
    """Applies the custom icon to the taskbar and titlebar of the app window."""
    if not os.path.exists(ICON_PATH):
        return

    for _ in range(40):
        time.sleep(0.15)
        hwnd = win32gui.FindWindow(None, "Vortex | Valorant Account Manager")
        if hwnd:
            try:
                icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
                hicon = win32gui.LoadImage(0, ICON_PATH, win32con.IMAGE_ICON, 0, 0, icon_flags)
                if hicon:
                    win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, hicon)
                    win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, hicon)
                break
            except Exception:
                pass


def _overlay_start_position():
    """Top-right corner of the primary monitor, with a small margin - the
    usual spot for a quick-access panel that shouldn't sit on top of
    whatever's centered on screen (the game, a browser, etc)."""
    try:
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        return max(0, screen_w - OVERLAY_WIDTH - OVERLAY_MARGIN), OVERLAY_MARGIN
    except Exception:
        return None, None


def _create_overlay_window():
    """
    The Quick Panel: a small, frameless, always-on-top window for fast
    account switching without going through the full app window. Created
    hidden - the global hotkey below is what shows it.

    This is a second ordinary webview window, not an in-game overlay: nothing
    here touches VALORANT's process, injects into it, or draws over its
    surface. It floats above whatever else is on screen the same way any
    always-on-top desktop app does.
    """
    x, y = _overlay_start_position()
    return webview.create_window(
        title=OVERLAY_TITLE,
        url=f"{URL}/static/overlay.html",
        width=OVERLAY_WIDTH,
        height=OVERLAY_HEIGHT,
        x=x, y=y,
        min_size=(390, 520),
        background_color="#06040b",
        frameless=True,
        easy_drag=True,
        on_top=True,
        hidden=True,
    )


def _create_live_hud_window():
    """Small passive upper-right HUD for the live aim trace.

    This is intentionally a normal desktop window, not an injected game
    overlay.  Its native style makes it click-through and non-activating, so
    it never captures the VALORANT cursor or opens the Windows taskbar.
    """
    try:
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        x = max(0, screen_w - LIVE_HUD_WIDTH - OVERLAY_MARGIN)
    except Exception:
        x = None
    return webview.create_window(
        title=LIVE_HUD_TITLE,
        url=f"{URL}/static/live_overlay.html",
        width=LIVE_HUD_WIDTH,
        height=LIVE_HUD_HEIGHT,
        x=x,
        y=OVERLAY_MARGIN,
        min_size=(260, 150),
        background_color="#0b0a15",
        frameless=True,
        easy_drag=False,
        on_top=True,
        hidden=True,
    )


def _make_live_hud_controller(hud_window):
    """Returns the desktop bridge used by Settings to show/hide the aim HUD."""
    state = {"hwnd": 0, "visible": False}

    def _set_ex_style(h: int, add_transparent: bool):
        try:
            ex_style = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE)
            # WS_EX_LAYERED is NOT needed for click-through and is actively
            # harmful: a layered window with no SetLayeredWindowAttributes call
            # composites as an opaque black rectangle on many GPUs once WebView2
            # re-lays out - exactly how the HUD went solid black. Always clear
            # it. WS_EX_TRANSPARENT (mouse pass-through) goes on the top-level
            # window only; forcing it onto the WebView2 render child can stop
            # that child painting on some runtime versions.
            new_ex = (ex_style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW & ~WS_EX_LAYERED
            if add_transparent:
                new_ex |= WS_EX_TRANSPARENT
            if ex_style != new_ex:
                win32gui.SetWindowLong(h, win32con.GWL_EXSTYLE, new_ex)
        except Exception:
            pass

    def _apply_clickthrough(h: int):
        _set_ex_style(h, add_transparent=True)

    def _apply_all_children(parent_hwnd: int):
        if not parent_hwnd or not win32gui.IsWindow(parent_hwnd):
            return
        _apply_clickthrough(parent_hwnd)
        try:
            def _child_cb(chwnd, _):
                _set_ex_style(chwnd, add_transparent=False)
                return True
            win32gui.EnumChildWindows(parent_hwnd, _child_cb, None)
        except Exception:
            pass

    def _prepare() -> int:
        hwnd = state["hwnd"] or win32gui.FindWindow(None, LIVE_HUD_TITLE)
        if not hwnd:
            return 0
        state["hwnd"] = hwnd
        try:
            _apply_all_children(hwnd)
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_FRAMECHANGED | win32con.SWP_NOACTIVATE,
            )
            return hwnd
        except Exception:
            _startup_log("prepare_live_hud failed:\n" + traceback.format_exc())
            return 0

    def setLiveHudEnabled(enabled: bool):
        enabled = bool(enabled)
        state["visible"] = enabled
        try:
            hwnd = _prepare()
            if enabled:
                if hwnd:
                    _apply_all_children(hwnd)
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE,
                    )
                else:
                    hud_window.show()
                    hwnd = _prepare()
                    if hwnd:
                        _apply_all_children(hwnd)
                        win32gui.SetWindowPos(
                            hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE,
                        )
            else:
                if hwnd:
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                else:
                    hud_window.hide()
            return {"success": True, "enabled": enabled}
        except Exception:
            _startup_log("setLiveHudEnabled failed:\n" + traceback.format_exc())
            return {"success": False, "enabled": enabled}

    # Persistent topmost-keeper daemon to maintain HUD overlay position above VALORANT
    def _topmost_keeper():
        while True:
            time.sleep(0.3)
            if not state["visible"]:
                continue
            try:
                hwnd = state["hwnd"] or win32gui.FindWindow(None, LIVE_HUD_TITLE)
                if hwnd and win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                    state["hwnd"] = hwnd
                    _apply_all_children(hwnd)
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
                    )
            except Exception:
                pass

    threading.Thread(target=_topmost_keeper, daemon=True).start()

    return setLiveHudEnabled


def _make_overlay_controller(overlay_window, main_window):
    """
    Wires the Quick Panel's own Close button / Escape key and its "Full app"
    button, and returns the toggle callback for the global hotkey.

    All three routes into showing/hiding the panel - the hotkey, the in-panel
    Close button, and Escape - have to agree on whether it's currently open.
    Before this they didn't: the hotkey tracked its own visible/hidden flag,
    while the panel's Close button and Escape key called into a JS bridge
    (window.pywebview.api.hideOverlay) that nothing on the Python side ever
    exposed, so both silently did nothing and the panel could only be
    dismissed by pressing the hotkey again. Routing all three through the
    same state here is what keeps them in sync.
    """
    state = {"visible": False, "hwnd": 0}

    def prepare_native_window():
        """Keep the panel topmost while allowing it to receive mouse input."""
        hwnd = state["hwnd"] or win32gui.FindWindow(None, OVERLAY_TITLE)
        if not hwnd:
            return 0
        state["hwnd"] = hwnd
        try:
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            # NOACTIVATE kept VALORANT focused and trapped its cursor. Opening
            # the quick panel is an intentional focus change, so it must be a
            # normal interactive window for buttons and inputs to work.
            # The quick panel is the interactive exception to the desktop HUD.
            # Explicitly clear every click-through/non-activating flag so a
            # previous HUD style or WebView recreation can never make its
            # buttons and inputs swallow mouse events.
            ex_style = (
                (ex_style | WS_EX_TOOLWINDOW)
                & ~WS_EX_NOACTIVATE
                & ~WS_EX_TRANSPARENT
                & ~WS_EX_LAYERED
                & ~WS_EX_APPWINDOW
            )
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_FRAMECHANGED,
            )
        except Exception:
            _startup_log("prepare_native_window failed:\n" + traceback.format_exc())
            return 0
        return hwnd

    def focus_overlay(hwnd):
        """Focus only the panel, without activating the shell/taskbar."""
        user32 = ctypes.windll.user32
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        overlay_thread = user32.GetWindowThreadProcessId(hwnd, None)
        attached = []
        try:
            # The hotkey callback has its own Win32 message thread. Attach it
            # briefly to both the game's foreground queue and WebView's UI
            # queue so Windows permits a direct focus transfer to the panel.
            for thread_id in {foreground_thread, overlay_thread}:
                if thread_id and thread_id != current_thread:
                    if user32.AttachThreadInput(current_thread, thread_id, True):
                        attached.append(thread_id)
            user32.AllowSetForegroundWindow(-1)
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
            )
            win32gui.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            for thread_id in reversed(attached):
                user32.AttachThreadInput(current_thread, thread_id, False)

    def showOverlay():
        state["visible"] = True
        try:
            hwnd = prepare_native_window()
            if hwnd:
                focus_overlay(hwnd)
            else:
                overlay_window.show()
                hwnd = prepare_native_window()
                if hwnd:
                    focus_overlay(hwnd)
        except Exception:
            _startup_log("showOverlay failed:\n" + traceback.format_exc())

    def hideOverlay():
        state["visible"] = False
        try:
            overlay_window.hide()
        except Exception:
            pass

    def showMainApp():
        # Restore and show the main window, then bring it to the foreground natively
        try:
            main_window.restore()
        except Exception:
            pass
        try:
            main_window.show()
        except Exception:
            pass
        try:
            main_hwnd = win32gui.FindWindow(None, "Vortex | Valorant Account Manager")
            if main_hwnd and win32gui.IsWindow(main_hwnd):
                # Main WebView must never inherit overlay click-through flags.
                ex_style = win32gui.GetWindowLong(main_hwnd, win32con.GWL_EXSTYLE)
                ex_style = (
                    (ex_style | WS_EX_APPWINDOW)
                    & ~WS_EX_TRANSPARENT
                    & ~WS_EX_LAYERED
                    & ~WS_EX_NOACTIVATE
                )
                win32gui.SetWindowLong(main_hwnd, win32con.GWL_EXSTYLE, ex_style)
                win32gui.ShowWindow(main_hwnd, win32con.SW_RESTORE)
                win32gui.SetWindowPos(
                    main_hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                )
                win32gui.BringWindowToTop(main_hwnd)
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
                ctypes.windll.user32.SetForegroundWindow(main_hwnd)
        except Exception:
            pass

    overlay_window.expose(hideOverlay, showMainApp)

    def toggle():
        hideOverlay() if state["visible"] else showOverlay()

    return toggle


def _start_overlay_hotkey(toggle):
    """
    Arms the global shortcut that shows/hides the Quick Panel, reading the
    combination from Settings (default CTRL+SHIFT+F8). Disabled entirely
    when the user has turned the overlay off.

    A hotkey that's already claimed by something else on the system fails to
    register - that's logged and left off rather than fought over or retried,
    since there's nothing productive to do about a conflicting global binding
    from inside this app.
    """
    settings = db.get_settings()
    if settings.get("overlay_enabled", "1") == "0":
        return None

    spec = settings.get("overlay_hotkey", "SHIFT+5") or "SHIFT+5"
    hotkey = OverlayHotkey()
    error = hotkey.start(spec, toggle)
    if error:
        print(f"[Vortex] Overlay hotkey not armed: {error}")
        return None
    return hotkey


def main():
    _startup_log("main entered")
    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    _startup_log(f"server thread started on {URL}")

    # Start taskbar icon applicator thread
    threading.Thread(target=apply_window_icon_loop, daemon=True).start()

    if "--browser" in sys.argv:
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)

    try:
        window = webview.create_window(
            title="Vortex | Valorant Account Manager",
            url=URL,
            width=1320,
            height=850,
            min_size=(1020, 680),
            background_color="#06040b",
            text_select=True,
            easy_drag=True
        )
        _startup_log("main WebView created")
        overlay_window = _create_overlay_window()
        _startup_log("hidden Quick Panel WebView created")
        live_hud_window = _create_live_hud_window()
        _startup_log("hidden Live Aim HUD WebView created")
        toggle_overlay = _make_overlay_controller(overlay_window, window)
        set_live_hud_enabled = _make_live_hud_controller(live_hud_window)
        window.expose(set_live_hud_enabled)

        def _restore_live_hud_after_load(*_args):
            enabled = db.get_settings().get("live_hud_enabled", "0") != "0"
            set_live_hud_enabled(enabled)

        live_hud_window.events.loaded += _restore_live_hud_after_load
        _start_overlay_hotkey(toggle_overlay)
        _startup_log("overlay controller, Live Aim HUD, and hotkey initialized")

        def _on_main_closing():
            # pywebview keeps running as long as any window - including the
            # hidden Quick Panel - still exists, so closing just the main
            # window would otherwise leave the app alive with nothing visible
            # to bring it back with. Closing the main window is "quit Vortex"
            # - everything else has to go down with it.
            try:
                overlay_window.destroy()
            except Exception:
                pass
            try:
                live_hud_window.destroy()
            except Exception:
                pass

        window.events.closing += _on_main_closing
        _startup_log("entering WebView event loop")
        webview.start(debug=False)
        _startup_log("WebView event loop exited")
    except Exception:
        _startup_log("desktop startup failed:\n" + traceback.format_exc())
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
