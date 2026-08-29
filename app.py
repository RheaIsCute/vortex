"""
Vortex Valorant Account Manager - Desktop Application Launcher.
Starts the local backend server cleanly and opens the native desktop window with custom branding & taskbar icon.
"""

import sys
import os
import io
import ctypes

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
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOWNOACTIVATE = 4


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
        """Keep the overlay above apps without ever becoming the active app."""
        hwnd = state["hwnd"] or win32gui.FindWindow(None, OVERLAY_TITLE)
        if not hwnd:
            return 0
        state["hwnd"] = hwnd
        try:
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED,
            )
        except Exception:
            return 0
        return hwnd

    def prepare_native_window_loop():
        for _ in range(80):
            if prepare_native_window():
                return
            time.sleep(0.1)

    threading.Thread(target=prepare_native_window_loop, daemon=True).start()

    def showOverlay():
        state["visible"] = True
        foreground = win32gui.GetForegroundWindow()
        try:
            hwnd = prepare_native_window()
            if hwnd:
                win32gui.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
            else:
                overlay_window.show()
                hwnd = prepare_native_window()
                if hwnd:
                    win32gui.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            if foreground and win32gui.GetForegroundWindow() != foreground:
                win32gui.SetForegroundWindow(foreground)
        except Exception:
            pass

    def hideOverlay():
        state["visible"] = False
        try:
            overlay_window.hide()
        except Exception:
            pass

    def showMainApp():
        # The panel's "Full app" button used to fall back to opening a
        # browser tab, because this bridge function didn't exist either -
        # restore() first so a minimized main window actually reappears,
        # not just repaints somewhere off in the taskbar.
        try:
            main_window.restore()
        except Exception:
            pass
        try:
            main_window.show()
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

    spec = settings.get("overlay_hotkey", "CTRL+SHIFT+F8") or "CTRL+SHIFT+F8"
    hotkey = OverlayHotkey()
    error = hotkey.start(spec, toggle)
    if error:
        print(f"[Vortex] Overlay hotkey not armed: {error}")
        return None
    return hotkey


def main():
    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

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
        overlay_window = _create_overlay_window()
        toggle_overlay = _make_overlay_controller(overlay_window, window)
        _start_overlay_hotkey(toggle_overlay)

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

        window.events.closing += _on_main_closing
        webview.start(debug=False)
    except Exception:
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
