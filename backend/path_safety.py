r"""Centralized write/delete path safety for Vortex.

Vortex is an *external* account manager: it observes and automates the Riot
Client through supported local APIs and normal UI/input automation, and it
never modifies Riot Games / VALORANT / Riot Vanguard installation files,
configuration, or processes.

To keep it that way even as the code changes, every filesystem write or delete
that Vortex performs on a computed path should pass through :func:`guard_path`
first. The guard:

* normalizes and fully resolves the target path,
* rejects it if it lands inside a known Riot / VALORANT / Vanguard location,
* optionally emits an audit-log line for every write/delete Vortex makes, so it
  is obvious from the log that Vortex only ever writes inside its own
  app / data / temp directories.

The guard deliberately does not try to *repair* or *delete* anything itself.
It raises :class:`ProtectedPathError` and lets the caller decide (callers here
simply skip the operation).
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile

logger = logging.getLogger("vortex.path_safety")

# Opt-in via env var so normal runs stay quiet. Set VORTEX_AUDIT_FS=1 to log
# every guarded write/delete (path + operation, never file contents).
_AUDIT_ENABLED = (os.getenv("VORTEX_AUDIT_FS") or "").strip().lower() in {"1", "true", "yes", "on"}


class ProtectedPathError(RuntimeError):
    """Raised when a write/delete targets a Riot/VALORANT/Vanguard location."""


def _norm(path: str) -> str:
    """Absolute, real, case-folded path for comparison."""
    try:
        resolved = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
    except OSError:
        resolved = os.path.abspath(os.path.expanduser(str(path)))
    return os.path.normcase(resolved)


def _first_existing_parent(path: str) -> str:
    """The nearest existing ancestor of ``path`` (for realpath on new files)."""
    cur = os.path.abspath(os.path.expanduser(str(path)))
    while cur and not os.path.exists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return cur


def _protected_roots() -> list[str]:
    """Directories Vortex must never write into or delete from."""
    roots: list[str] = []

    def add(*parts: str) -> None:
        if all(parts):
            roots.append(_norm(os.path.join(*parts)))

    localappdata = os.getenv("LOCALAPPDATA") or ""
    programdata = os.getenv("PROGRAMDATA") or r"C:\ProgramData"
    programfiles = os.getenv("ProgramFiles") or r"C:\Program Files"
    programfiles_x86 = os.getenv("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    systemroot = os.getenv("SystemRoot") or r"C:\Windows"

    # Riot Client + VALORANT install / config trees.
    for base in (
        r"C:\Riot Games",
        r"D:\Riot Games",
        r"E:\Riot Games",
        r"F:\Riot Games",
        os.path.join(programfiles, "Riot Games"),
        os.path.join(programfiles_x86, "Riot Games"),
        os.path.join(programfiles, "Riot Client"),
        os.path.join(programfiles_x86, "Riot Client"),
    ):
        add(base)
    add(localappdata, "Riot Games")
    add(localappdata, "VALORANT")

    # Riot Vanguard (anti-cheat). Never touched.
    add(programfiles, "Riot Vanguard")
    add(programfiles_x86, "Riot Vanguard")
    add(programdata, "Riot Games", "Metadata")
    add(systemroot, "System32", "drivers", "vgk.sys")
    add(systemroot, "System32", "drivers", "vgc.sys")

    return [r for r in roots if r]


_PROTECTED_ROOTS = _protected_roots()


def _vortex_owned_roots() -> list[str]:
    """Directories Vortex legitimately writes to (for audit context only)."""
    roots: list[str] = []
    localappdata = os.getenv("LOCALAPPDATA") or ""
    if localappdata:
        roots.append(_norm(os.path.join(localappdata, "Vortex")))
        roots.append(_norm(os.path.join(localappdata, "Programs", "Vortex")))
    roots.append(_norm(tempfile.gettempdir()))
    if not getattr(sys, "frozen", False):
        # Source runs write the dev database/log beside the repo.
        roots.append(_norm(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return roots


_VORTEX_ROOTS = _vortex_owned_roots()


def _is_within(path: str, root: str) -> bool:
    if not root:
        return False
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        # Different drives.
        return False


def is_protected(path: str) -> bool:
    """True if ``path`` is inside a Riot/VALORANT/Vanguard location."""
    target = _norm(_first_existing_parent(path) if not os.path.exists(path) else path)
    # Re-append the leaf so an exact-file root (vgk.sys) still matches.
    leaf = _norm(path)
    return any(
        _is_within(target, root) or _is_within(leaf, root) or leaf == root
        for root in _PROTECTED_ROOTS
    )


def is_vortex_owned(path: str) -> bool:
    leaf = _norm(path)
    return any(_is_within(leaf, root) or leaf == root for root in _VORTEX_ROOTS)


def guard_path(path: str, operation: str = "write") -> str:
    """Validate a write/delete target.

    Returns the normalized absolute path on success. Raises
    :class:`ProtectedPathError` if the path is a Riot/VALORANT/Vanguard
    location. Emits an audit line when ``VORTEX_AUDIT_FS`` is set.
    """
    resolved = os.path.abspath(os.path.expanduser(str(path)))
    if is_protected(path):
        logger.error("BLOCKED %s into protected location: %s", operation, resolved)
        raise ProtectedPathError(
            f"Refusing to {operation} inside a Riot/VALORANT/Vanguard location: {resolved}"
        )
    if _AUDIT_ENABLED:
        where = "vortex-owned" if is_vortex_owned(path) else "OUTSIDE vortex dirs"
        logger.info("fs %s [%s]: %s", operation, where, resolved)
    return resolved


def safe_remove(path: str) -> bool:
    """``os.remove`` guarded by :func:`guard_path`. True if a file was removed."""
    guard_path(path, "delete")
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
