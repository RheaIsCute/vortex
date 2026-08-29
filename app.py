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

OVERLAY_WIDTH = 400
OVERLAY_HEIGHT = 600
OVERLAY_MARGIN = 24


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
        title="Vortex Quick Panel",
        url=f"{URL}/static/overlay.html",
        width=OVERLAY_WIDTH,
        height=OVERLAY_HEIGHT,
        x=x, y=y,
        min_size=(360, 480),
        background_color="#06040b",
        frameless=True,
        easy_drag=True,
        on_top=True,
        hidden=True,
    )


def _start_overlay_hotkey(overlay_window):
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
    state = {"visible": False}

    def toggle():
        state["visible"] = not state["visible"]
        try:
            if state["visible"]:
                overlay_window.show()
            else:
                overlay_window.hide()
        except Exception:
            pass

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
        _start_overlay_hotkey(overlay_window)
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
