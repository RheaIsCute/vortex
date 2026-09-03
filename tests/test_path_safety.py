import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import path_safety
from backend.path_safety import ProtectedPathError, guard_path, is_protected


class PathSafetyTests(unittest.TestCase):
    def _reload_roots(self):
        # Recompute roots against the currently-patched environment.
        path_safety._PROTECTED_ROOTS = path_safety._protected_roots()
        path_safety._VORTEX_ROOTS = path_safety._vortex_owned_roots()

    def test_blocks_riot_games_install_dir(self):
        with patch.dict(os.environ, {"ProgramFiles": r"C:\Program Files"}, clear=False):
            self._reload_roots()
            for target in (
                r"C:\Riot Games\VALORANT\live\ShooterGame\Binaries\Win64\VALORANT.exe",
                r"C:\Riot Games\Riot Client\RiotClientServices.exe",
                r"C:\Program Files\Riot Vanguard\vgc.exe",
            ):
                self.assertTrue(is_protected(target), target)
                with self.assertRaises(ProtectedPathError):
                    guard_path(target, "write")

    def test_blocks_localappdata_valorant_and_riot(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\me\AppData\Local"}, clear=False):
            self._reload_roots()
            for target in (
                r"C:\Users\me\AppData\Local\VALORANT\Saved\Config\Windows\GameUserSettings.ini",
                r"C:\Users\me\AppData\Local\Riot Games\Riot Client\Config\lockfile",
            ):
                with self.assertRaises(ProtectedPathError):
                    guard_path(target, "delete")

    def test_allows_vortex_owned_paths(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\me\AppData\Local"}, clear=False):
            self._reload_roots()
            for target in (
                r"C:\Users\me\AppData\Local\Vortex\database.sqlite",
                r"C:\Users\me\AppData\Local\Vortex\backups\vortex-20260101.sqlite",
                os.path.join(path_safety.tempfile.gettempdir(), "VortexUpdateSetup-1.0.0.exe"),
            ):
                self.assertFalse(is_protected(target), target)
                self.assertEqual(
                    guard_path(target, "write"),
                    os.path.abspath(os.path.expanduser(target)),
                )

    def test_safe_remove_refuses_protected(self):
        with patch.dict(os.environ, {"ProgramFiles": r"C:\Program Files"}, clear=False):
            self._reload_roots()
            with self.assertRaises(ProtectedPathError):
                path_safety.safe_remove(r"C:\Riot Games\VALORANT\live\Engine\Binaries\ThirdParty\x.dll")


if __name__ == "__main__":
    unittest.main()
