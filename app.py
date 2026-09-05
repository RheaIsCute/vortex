"""
Vortex Valorant Account Manager - Desktop Application Launcher.
Starts the local backend server cleanly and opens the native desktop window with custom branding & taskbar icon.
"""

import sys
import os
import io
import ctypes
import traceback

# Resolve the application root before importing any optional runtime. Frozen
# builds are elevated by the embedded manifest before this code runs; source
# launches perform the same handoff here, before FastAPI, WebView2, Riot
# discovery, or any optional integration can initialize.
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, BASE_DIR)

# A windowed PyInstaller executable has no console streams.  Keep them backed
# by a real file before importing any third-party package so import failures and
# background-thread tracebacks cannot disappear into an in-memory StringIO.
STARTUP_LOG = os.environ.get("VORTEX_STARTUP_LOG") or os.path.join(
    os.environ.get("TEMP") or BASE_DIR, "vortex_startup.log"
)
if sys.stdout is None or sys.stderr is None:
    try:
        _windowless_stream = open(
            STARTUP_LOG, "a", encoding="utf-8", buffering=1
        )
    except OSError:
        _windowless_stream = io.StringIO()
    if sys.stdout is None:
        sys.stdout = _windowless_stream
    if sys.stderr is None:
        sys.stderr = _windowless_stream

_SMOKE_TEST = "--smoke-test" in sys.argv[1:]

from backend import elevation as _elevation


if __name__ == "__main__" and not _SMOKE_TEST:
    _elevation_action = _elevation.startup_elevation_action()
    if _elevation_action != "continue":
        if _elevation_action == "failed":
            try:
                ctypes.windll.user32.MessageBoxW(
                    None,
                    "Vortex requires Administrator privileges and cannot continue "
                    "without them.",
                    "Vortex",
                    0x10,
                )
            except Exception:
                pass
        raise SystemExit(0 if _elevation_action == "relaunched" else 1)


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

import time
import socket
import threading
import webbrowser
import http.client
import json
import asyncio
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

from backend.server import app, db, in_match_now
from backend.client_launcher import is_valorant_foreground, _uia
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


def start_server(state):
    """Run Uvicorn and preserve every outcome for the launch/readiness gate."""
    try:
        def _new_server_event_loop():
            # Proactor intermittently fails localhost accept() with WinError
            # 64 when Uvicorn runs in this background thread. Vortex needs no
            # subprocess pipes in its ASGI loop, so Selector is the stable fit.
            if sys.platform == "win32":
                return asyncio.SelectorEventLoop()
            return asyncio.new_event_loop()

        _startup_log(
            f"backend server initialization started on {URL}; "
            f"loop={'SelectorEventLoop' if sys.platform == 'win32' else 'default'}"
        )
        config = uvicorn.Config(
            app=app,
            host=HOST,
            port=PORT,
            log_config=None,
            access_log=False,
            # A build smoke test must not run startup workers that inspect or
            # stop optional external integrations on the build machine.
            lifespan="off" if _SMOKE_TEST else "auto",
        )
        server = uvicorn.Server(config)
        state["server"] = server
        with asyncio.Runner(loop_factory=_new_server_event_loop) as runner:
            runner.run(server.serve())
        if not server.started and not state.get("error"):
            state["error"] = "Uvicorn exited before reporting a successful bind."
            _startup_log(state["error"])
    except BaseException:
        state["error"] = traceback.format_exc()
        _startup_log("backend server failed:\n" + state["error"])


def _wait_for_server(state, thread, timeout=15.0):
    """Wait until the frozen backend answers its version endpoint."""
    deadline = time.monotonic() + timeout
    last_error = "backend did not answer"
    while time.monotonic() < deadline:
        if state.get("error"):
            return False, state["error"]
        if not thread.is_alive():
            return False, "Backend server thread exited before becoming ready."
        connection = http.client.HTTPConnection(HOST, PORT, timeout=1.0)
        try:
            connection.request("GET", "/api/app-version")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            if response.status == 200 and payload.get("version") == APP_VERSION:
                _startup_log(
                    f"backend ready on {URL}; version={payload['version']}"
                )
                return True, ""
            last_error = (
                f"version probe returned HTTP {response.status}: {payload!r}"
            )
        except (OSError, ValueError, http.client.HTTPException) as exc:
            last_error = str(exc)
        finally:
            connection.close()
        time.sleep(0.1)
    return False, f"Backend readiness timed out after {timeout:.1f}s: {last_error}"


def _launch_server_and_wait(timeout=15.0):
    state = {"server": None, "error": None}
    thread = threading.Thread(
        target=start_server, args=(state,), name="vortex-backend", daemon=True
    )
    thread.start()
    ready, error = _wait_for_server(state, thread, timeout)
    return state, thread, ready, error


def _show_backend_startup_error(error):
    _startup_log("desktop launch stopped because the backend is unavailable:\n" + error)
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "Vortex's local backend could not start. The app was not opened "
            f"with stale data.\n\nDiagnostics: {STARTUP_LOG}",
            "Vortex startup failed",
            0x10,
        )
    except Exception:
        pass


def _verify_frozen_uiautomation():
    """Exercise the UI Automation dependency used by Riot login."""
    uia = _uia()
    if uia is None:
        raise RuntimeError("uiautomation could not be imported")

    # Constructing the COM client forces comtypes to load/generate the
    # UIAutomationCore typelib now instead of discovering a broken bundle only
    # when a user next attempts a login.
    client = uia.uiautomation._AutomationClient.instance()
    if not getattr(client, "IUIAutomation", None):
        raise RuntimeError("UIAutomationCore client initialization failed")

    if getattr(sys, "frozen", False):
        package_dir = os.path.join(BASE_DIR, "uiautomation", "bin")
        expected = (
            "UIAutomationClient_VC140_X64.dll",
            "UIAutomationClient_VC140_X86.dll",
        )
        missing = [
            name
            for name in expected
            if not os.path.isfile(os.path.join(package_dir, name))
        ]
        if missing:
            raise RuntimeError("missing uiautomation package data: " + ", ".join(missing))


def _run_packaged_smoke_test():
    """Validate frozen imports, UIA, Uvicorn bind, and the version API."""
    _startup_log("packaged smoke test started")
    try:
        _verify_frozen_uiautomation()
    except Exception:
        _startup_log("UI Automation smoke test failed:\n" + traceback.format_exc())
        return 1

    state, thread, ready, error = _launch_server_and_wait(timeout=20.0)
    if not ready:
        _startup_log("packaged smoke test failed:\n" + error)
        return 1

    _startup_log("packaged smoke test passed")
    print(f"VORTEX_SMOKE_OK version={APP_VERSION} url={URL}", flush=True)
    server = state.get("server")
    if server is not None:
        server.should_exit = True
    thread.join(timeout=5.0)
    return 0


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
    if _SMOKE_TEST:
        return _run_packaged_smoke_test()

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

    # Do not create WebView2 until the backend is proven reachable. Otherwise
    # its persistent cache can render an old UI against a dead server and make
    # intact local account data look empty.
    _server_state, _server_thread, ready, error = _launch_server_and_wait()
    if not ready:
        _show_backend_startup_error(error)
        return 1

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
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
