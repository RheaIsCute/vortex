"""Windows WebView2 startup diagnostics for the Vortex desktop host.

This module deliberately contains no account/backend imports.  It may run before
the desktop renderer exists and must never inspect or log application data.
"""

from __future__ import annotations

import ctypes
import importlib
import importlib.metadata
import importlib.util
import os
import platform
import struct
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable


REQUESTED_BACKEND = "edgechromium"


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def find_webview2_files(base_dir: str) -> dict[str, str]:
    """Return the packaged WebView2 interop paths without searching user data."""
    roots = [Path(base_dir) / "webview"]
    spec = importlib.util.find_spec("webview")
    if spec and spec.submodule_search_locations:
        roots.extend(Path(item) for item in spec.submodule_search_locations)
    names = (
        "WebView2Loader.dll",
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
    )
    result: dict[str, str] = {}
    for name in names:
        matches = [match for root in roots if root.exists() for match in root.glob(f"**/{name}")]
        architecture = "win-x64" if struct.calcsize("P") * 8 == 64 else "win-x86"
        preferred = next((item for item in matches if architecture in str(item)), None)
        result[name] = str(preferred or (matches[0] if matches else "not found"))
    return result


def prepare_user_data_dir(path: str, log: Callable[[str], None]) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".vortex-write-test-", dir=path)
        os.close(fd)
        os.unlink(probe)
        log(f"WebView2 user-data directory writable: yes ({path})")
        return True
    except Exception:
        log(f"WebView2 user-data directory writable: no ({path})\n{traceback.format_exc()}")
        return False


def log_system_diagnostics(base_dir: str, executable: str, user_data_dir: str,
                           app_version: str, log: Callable[[str], None]) -> None:
    log(f"application version: {app_version}")
    log(f"Python version: {sys.version.replace(os.linesep, ' ')}")
    log(f"Python architecture: {struct.calcsize('P') * 8}-bit ({platform.machine()})")
    log(
        "frozen/PyInstaller state: "
        f"frozen={bool(getattr(sys, 'frozen', False))}, _MEIPASS={getattr(sys, '_MEIPASS', 'not set')}"
    )
    log(f"pywebview version: {package_version('pywebview')}")
    log(f"pythonnet version: {package_version('pythonnet')}")
    log(f"clr-loader version: {package_version('clr-loader')}")
    log(f"requested backend: {REQUESTED_BACKEND}")
    log(f"executable path: {executable}")
    log(f"BASE_DIR: {base_dir}")
    log(f"Windows version/build: {platform.platform()} / {platform.version()}")
    for name, path in find_webview2_files(base_dir).items():
        log(f"{name} path: {path}")
    log(f"WebView2 user-data directory: {user_data_dir}")


def show_webview2_error(log_path: str) -> None:
    message = (
        "Vortex could not initialize Microsoft Edge WebView2.\n\n"
        "The WebView2 Runtime appears to be installed, but the embedded browser could not start.\n\n"
        f"Diagnostic log:\n{log_path}"
    )
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "Vortex startup error", 0x10)
    except Exception:
        pass


def initialize_and_instrument(log: Callable[[str], None], log_path: str) -> str:
    """Initialize pywebview's requested GUI and instrument its async WebView2 result.

    pywebview 6.2.1 only writes an async initialization failure to its logger and
    leaves the WinForms window alive.  The callback wrapper below makes that
    otherwise-swallowed failure visible and closes the GUI loop.
    """
    try:
        log(".NET/CLR initialization start")
        import clr  # noqa: F401
        log(".NET/CLR initialization result: success")
    except Exception:
        log(".NET/CLR initialization result: failure\n" + traceback.format_exc())
        raise

    log("WebView2 backend selection start")
    guilib_module = importlib.import_module("webview.guilib")
    gui = guilib_module.initialize(REQUESTED_BACKEND)
    selected = str(getattr(gui, "renderer", "unknown"))
    log(f"selected backend: {selected}")
    if selected != REQUESTED_BACKEND:
        raise RuntimeError(
            f"Requested {REQUESTED_BACKEND}, but pywebview selected unsupported backend {selected}"
        )

    edge = importlib.import_module("webview.platforms.edgechromium")
    environment = getattr(importlib.import_module("Microsoft.Web.WebView2.Core"),
                          "CoreWebView2Environment")
    try:
        runtime_version = str(environment.GetAvailableBrowserVersionString())
        log(f"WebView2 runtime discovery result: success; version={runtime_version}")
    except Exception:
        log("WebView2 runtime discovery result: failure\n" + traceback.format_exc())
        raise

    if getattr(edge.EdgeChrome, "_vortex_instrumented", False):
        return selected

    original_init = edge.EdgeChrome.__init__
    original_ready = edge.EdgeChrome.on_webview_ready

    def instrumented_init(self, form, window, cache_dir):
        log(f"WebView2 environment creation start; user-data directory={cache_dir}")
        try:
            original_init(self, form, window, cache_dir)
            log("WebView2 WinForms control creation success; EnsureCoreWebView2Async started")
        except Exception:
            log("WebView2 environment/control creation failure\n" + traceback.format_exc())
            raise

    def instrumented_ready(self, sender, args):
        if not args.IsSuccess:
            error = str(args.InitializationException)
            log(f"WebView2 environment/controller creation failure: {error}")
            try:
                raise RuntimeError(error)
            except RuntimeError:
                log("WebView2 initialization traceback:\n" + traceback.format_exc())
            show_webview2_error(log_path)
            try:
                import System.Windows.Forms as WinForms
                WinForms.Application.Exit()
            except Exception:
                log("Failed to close WebView event loop:\n" + traceback.format_exc())
            return

        log("WebView2 environment creation success")
        log("WebView2 controller creation success")
        try:
            original_ready(self, sender, args)
        except Exception:
            log("WebView2 post-controller initialization failure\n" + traceback.format_exc())
            show_webview2_error(log_path)
            try:
                import System.Windows.Forms as WinForms
                WinForms.Application.Exit()
            except Exception:
                pass

    instrumented_init._vortex_instrumented = True
    edge.EdgeChrome.__init__ = instrumented_init
    edge.EdgeChrome.on_webview_ready = instrumented_ready
    edge.EdgeChrome._vortex_instrumented = True
    return selected
