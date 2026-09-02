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
from webview_diagnostics import (
    REQUESTED_BACKEND,
    initialize_and_instrument,
    log_system_diagnostics,
    prepare_user_data_dir,
    show_webview2_error,
)

# When frozen by PyInstaller (onefile build), bundled data files live under
# sys._MEIPASS (a temp extraction dir), not next to this script.
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, BASE_DIR)

from backend.server import app, db, in_match_now
from backend.client_launcher import is_valorant_foreground
from backend.version import APP_VERSION

ICON_PATH = os.path.join(BASE_DIR, "frontend", "assets", "logo.ico")

HUD_MARGIN = 24
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
WEBVIEW2_USER_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.dirname(os.path.abspath(__file__)),
    "Vortex",
    "WebView2",
)


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


def _create_live_hud_window():
    """Small passive upper-right HUD for the live aim trace.

    This is intentionally a normal desktop window, not an injected game
    overlay.  Its native style makes it click-through and non-activating, so
    it never captures the VALORANT cursor or opens the Windows taskbar.
    """
    try:
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        x = max(0, screen_w - LIVE_HUD_WIDTH - HUD_MARGIN)
    except Exception:
        x = None
    return webview.create_window(
        title=LIVE_HUD_TITLE,
        url=f"{URL}/static/live_overlay.html",
        width=LIVE_HUD_WIDTH,
        height=LIVE_HUD_HEIGHT,
        x=x,
        y=HUD_MARGIN,
        min_size=(260, 150),
        background_color="#0b0a15",
        frameless=True,
        easy_drag=False,
        on_top=True,
        hidden=True,
    )


def _make_live_hud_controller(hud_window):
    """Returns the desktop bridge used by Settings to show/hide the aim HUD."""
    state = {"hwnd": 0, "visible": False, "fg_applied": None, "fade_out_at": 0.0}

    # How long live_overlay.css takes to fade .aim-hud out. The native window
    # is only hidden once that has finished, so the fade is actually seen.
    HUD_FADE_SECONDS = 0.32

    def _set_hud_dormant(dormant: bool):
        """Toggle the CSS fade class on the HUD page.

        The HUD should only be visible while VALORANT owns the foreground -
        not while the player is in a browser, Discord, or the Vortex window.
        A real native alpha fade needs WS_EX_LAYERED, which is what turned the
        HUD into a black rectangle before, so the fade lives in CSS. The keeper
        loop hides the native window entirely once the fade-out has run, so a
        dormant HUD leaves nothing on screen at all.
        """
        js = "document.body&&document.body.classList.toggle('hud-dormant',%s)" % (
            "true" if dormant else "false"
        )
        try:
            runner = getattr(hud_window, "run_js", None) or hud_window.evaluate_js
            runner(js)
        except Exception:
            pass

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
        # Whether the HUD is actually on screen is decided by the keeper loop
        # from VALORANT's foreground state - enabling here just arms it. Force a
        # fresh evaluation either way.
        state["fg_applied"] = None
        state["fade_out_at"] = 0.0
        try:
            hwnd = _prepare()
            if enabled:
                # Keep it hidden until the keeper confirms VALORANT is in front;
                # showing it here would flash an empty panel on the desktop.
                if hwnd:
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            else:
                if hwnd:
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                else:
                    hud_window.hide()
            return {"success": True, "enabled": enabled}
        except Exception:
            _startup_log("setLiveHudEnabled failed:\n" + traceback.format_exc())
            return {"success": False, "enabled": enabled}

    # Persistent daemon: keeps the HUD pinned above VALORANT and gates its
    # presence on being in an actual match with VALORANT in front. In the
    # menus, alt-tabbed, or with no match, the HUD fades out (CSS) and then
    # the native window is hidden - nothing is left on screen. When the game
    # comes back to a live match it is shown again and fades in.
    def _topmost_keeper():
        while True:
            time.sleep(0.3)
            if not state["visible"]:
                continue
            try:
                fg = is_valorant_foreground() and in_match_now()

                hwnd = state["hwnd"] or win32gui.FindWindow(None, LIVE_HUD_TITLE)
                if not (hwnd and win32gui.IsWindow(hwnd)):
                    # pywebview may not realise the native window until its
                    # first show(); only pay that cost once the game is in front.
                    if fg:
                        try:
                            hud_window.show()
                        except Exception:
                            pass
                        hwnd = win32gui.FindWindow(None, LIVE_HUD_TITLE)
                    if not (hwnd and win32gui.IsWindow(hwnd)):
                        continue
                state["hwnd"] = hwnd

                if fg != state["fg_applied"]:
                    if fg:
                        # Coming back in-game: show the window, then fade in.
                        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
                        _apply_all_children(hwnd)
                        win32gui.SetWindowPos(
                            hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                            | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
                        )
                        _set_hud_dormant(False)
                    else:
                        # Left the game: start the CSS fade-out now; the window
                        # itself is hidden a beat later, once the fade has run.
                        _set_hud_dormant(True)
                        state["fade_out_at"] = time.time()
                    state["fg_applied"] = fg

                if fg:
                    # Re-assert topmost only while actually visible in-game.
                    _apply_all_children(hwnd)
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                        | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
                    )
                elif (
                    state["fade_out_at"]
                    and time.time() - state["fade_out_at"] > HUD_FADE_SECONDS
                    and win32gui.IsWindowVisible(hwnd)
                ):
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            except Exception:
                pass

    threading.Thread(target=_topmost_keeper, daemon=True).start()

    return setLiveHudEnabled


def main():
    _startup_log("main entered")
    log_system_diagnostics(
        BASE_DIR, sys.executable, WEBVIEW2_USER_DATA_DIR, APP_VERSION, _startup_log
    )
    if not prepare_user_data_dir(WEBVIEW2_USER_DATA_DIR, _startup_log):
        show_webview2_error(STARTUP_LOG)
        return

    if "--browser" not in sys.argv:
        try:
            initialize_and_instrument(_startup_log, STARTUP_LOG)
        except Exception:
            _startup_log("WebView2 preflight failure:\n" + traceback.format_exc())
            show_webview2_error(STARTUP_LOG)
            return

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

        def saveBackup(contents, filename):
            """Save a locally generated backup through WebView2's native dialog."""
            if not isinstance(contents, str):
                return {"success": False}
            safe_name = os.path.basename(filename or "vortex_backup.json")
            if not safe_name.lower().endswith(".json"):
                safe_name += ".json"
            try:
                destination = window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=safe_name,
                    file_types=("JSON files (*.json)",),
                )
                if not destination:
                    return {"success": False, "cancelled": True}
                # pywebview returns a path for SAVE_DIALOG; tolerate a one-item
                # sequence for older backends without ever logging its content.
                if isinstance(destination, (tuple, list)):
                    destination = destination[0] if destination else ""
                if not destination:
                    return {"success": False, "cancelled": True}
                temp_path = str(destination) + ".tmp"
                with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(contents)
                os.replace(temp_path, destination)
                return {"success": True}
            except OSError:
                return {"success": False}

        window.expose(saveBackup)
        hud_enabled_at_start = db.get_settings().get("live_hud_enabled", "0") != "0"
        live_hud_window = _create_live_hud_window() if hud_enabled_at_start else None
        _startup_log("Live Aim HUD WebView " + ("created" if live_hud_window else "skipped (disabled)"))
        if live_hud_window:
            set_live_hud_enabled = _make_live_hud_controller(live_hud_window)
        else:
            def set_live_hud_enabled(enabled):
                # Avoid keeping a full WebView2 renderer alive for an opt-in
                # HUD. Enabling persists immediately and takes effect after a
                # restart, when the HUD window will actually be constructed.
                return {"success": not bool(enabled), "enabled": False,
                        "restart_required": bool(enabled)}
        window.expose(set_live_hud_enabled)

        if live_hud_window:
            def _restore_live_hud_after_load(*_args):
                set_live_hud_enabled(True)
            live_hud_window.events.loaded += _restore_live_hud_after_load
        _startup_log("Live Aim HUD initialized")

        def _on_main_closing():
            # pywebview keeps running as long as any window - including the
            # hidden Live Aim HUD - still exists, so closing just the main
            # window would otherwise leave the app alive with nothing visible
            # to bring it back with. Closing the main window is "quit Vortex"
            # - everything else has to go down with it.
            if live_hud_window:
                try:
                    live_hud_window.destroy()
                except Exception:
                    pass

        window.events.closing += _on_main_closing
        _startup_log("entering WebView event loop")
        webview.start(
            gui=REQUESTED_BACKEND,
            debug=False,
            private_mode=False,
            storage_path=WEBVIEW2_USER_DATA_DIR,
        )
        _startup_log("WebView event loop exited")
    except Exception:
        _startup_log("desktop startup failed:\n" + traceback.format_exc())
        show_webview2_error(STARTUP_LOG)


if __name__ == "__main__":
    main()
