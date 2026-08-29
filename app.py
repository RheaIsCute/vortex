"""
Vortex Valorant Account Manager - Desktop Application Launcher.
Starts the local backend server cleanly and opens the native desktop window with custom branding & taskbar icon.
"""

import sys
import os
import io
import ctypes
import atexit

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
from backend import fps_monitor

ICON_PATH = os.path.join(BASE_DIR, "frontend", "assets", "logo.ico")

OVERLAY_WIDTH = 400
OVERLAY_HEIGHT = 600
OVERLAY_MARGIN = 24

FPS_HUD_WIDTH = 120
FPS_HUD_HEIGHT = 56
FPS_MARGIN = 24


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

# Backstop for the PresentMon subprocess: it's a normal child process, not
# one Windows tears down automatically when this one exits, so anything that
# skips the main window's own closing handler (Ctrl+C, task kill) still needs
# this to avoid leaving it running.
atexit.register(fps_monitor.ensure_stopped)


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


def _fps_start_position(settings):
    """Wherever the HUD was last dragged to, else the top-right corner."""
    x_raw, y_raw = settings.get("fps_x", ""), settings.get("fps_y", "")
    if x_raw and y_raw:
        try:
            return int(float(x_raw)), int(float(y_raw))
        except ValueError:
            pass
    try:
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        return max(0, screen_w - FPS_HUD_WIDTH - FPS_MARGIN), FPS_MARGIN
    except Exception:
        return None, None


def _create_fps_window(settings):
    """
    The FPS HUD: a tiny always-on-top window that only ever shows a number.
    Like the Quick Panel, this is an ordinary second webview window - nothing
    here is drawn inside VALORANT or reads its memory. That also means it can
    only visually sit on top of the game while VALORANT renders through the
    desktop compositor (Borderless / Windowed Fullscreen), not in exclusive
    Fullscreen - the same tradeoff every non-injected overlay has.
    """
    x, y = _fps_start_position(settings)
    return webview.create_window(
        title="Vortex FPS",
        url=f"{URL}/static/fps_hud.html",
        width=FPS_HUD_WIDTH,
        height=FPS_HUD_HEIGHT,
        x=x, y=y,
        min_size=(FPS_HUD_WIDTH, FPS_HUD_HEIGHT),
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
        background_color="#0c0a14",
        hidden=(settings.get("fps_enabled", "1") == "0"),
    )


def _wire_fps_window(fps_window):
    """
    Starts frame capture if the setting is already on, and keeps the HUD's
    dragged position saved so it reopens where it was left.

    The `moved` event fires on every pixel of a live drag, so writing to the
    database from inside the handler would hammer it mid-drag. The handler
    only updates an in-memory position; a slow periodic thread flushes it to
    the database when it's actually changed.
    """
    pending = {"x": None, "y": None}

    def on_moved(x, y):
        pending["x"], pending["y"] = x, y

    fps_window.events.moved += on_moved

    def flush_loop():
        last = (None, None)
        while True:
            time.sleep(1.5)
            x, y = pending["x"], pending["y"]
            if x is None or (x, y) == last:
                continue
            last = (x, y)
            try:
                db.update_settings({"fps_x": str(x), "fps_y": str(y)})
            except Exception:
                pass

    threading.Thread(target=flush_loop, daemon=True, name="vortex-fps-position").start()

    if db.get_settings().get("fps_enabled", "1") != "0":
        error = fps_monitor.ensure_started()
        if error:
            print(f"[Vortex] FPS counter not armed: {error}")


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
        fps_window = _create_fps_window(db.get_settings())
        _wire_fps_window(fps_window)

        def _on_main_closing():
            # pywebview keeps running as long as any window - including the
            # hidden Quick Panel and the FPS HUD - still exists, so closing
            # just the main window would otherwise leave the app alive with
            # nothing visible to bring it back with. Closing the main window
            # is "quit Vortex" - everything else has to go down with it.
            fps_monitor.ensure_stopped()
            for w in (overlay_window, fps_window):
                try:
                    w.destroy()
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
