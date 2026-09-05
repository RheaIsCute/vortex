import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import elevation


class ElevationTests(unittest.TestCase):
    def test_riot_check_short_circuits_when_self_elevated(self):
        # If Vortex is already elevated there is no mismatch to act on, and the
        # process scan is skipped entirely.
        with patch.object(elevation, "is_self_elevated", return_value=True), \
             patch.object(elevation, "_iter_processes", side_effect=AssertionError("should not scan")):
            self.assertFalse(elevation.riot_client_is_elevated())

    def test_riot_check_true_when_a_riot_process_reads_elevated(self):
        with patch.object(elevation, "is_self_elevated", return_value=False), \
             patch.object(elevation, "_iter_processes",
                          return_value=[("chrome.exe", 10), ("riotclientservices.exe", 20)]), \
             patch.object(elevation, "_process_elevation", lambda pid: pid == 20):
            self.assertTrue(elevation.riot_client_is_elevated())

    def test_riot_check_treats_unreadable_token_as_elevated(self):
        # OpenProcessToken failing on a process we can otherwise see means it
        # outranks us - which is the case we care about.
        with patch.object(elevation, "is_self_elevated", return_value=False), \
             patch.object(elevation, "_iter_processes",
                          return_value=[("riot client.exe", 30)]), \
             patch.object(elevation, "_process_elevation", lambda pid: None):
            self.assertTrue(elevation.riot_client_is_elevated())

    def test_riot_check_false_when_no_riot_process(self):
        with patch.object(elevation, "is_self_elevated", return_value=False), \
             patch.object(elevation, "_iter_processes",
                          return_value=[("chrome.exe", 1), ("explorer.exe", 2)]), \
             patch.object(elevation, "_process_elevation", lambda pid: True):
            self.assertFalse(elevation.riot_client_is_elevated())

    def test_relaunch_command_points_at_a_real_script_from_source(self):
        exe, params = elevation.relaunch_command()
        self.assertTrue(exe)
        self.assertIn(os.path.abspath(elevation._source_script_path()), params)
        self.assertIn(elevation._ELEVATION_SENTINEL, params)

    def test_relaunch_command_quotes_spaced_arguments_and_forwards_them(self):
        with patch.object(sys, "argv", ["app.py", "--profile", "path with spaces"]):
            _exe, params = elevation.relaunch_command()
        self.assertIn('"path with spaces"', params)
        self.assertIn(elevation._ELEVATION_SENTINEL, params)

    def test_startup_elevation_handoff_and_denial_never_continue(self):
        with patch.object(elevation.os, "name", "nt"), \
             patch.object(elevation, "is_self_elevated", return_value=False), \
             patch.object(elevation, "relaunch_elevated", return_value=True):
            self.assertEqual(elevation.startup_elevation_action(), "relaunched")
            self.assertFalse(elevation.ensure_elevated_startup())

        with patch.object(elevation.os, "name", "nt"), \
             patch.object(elevation, "is_self_elevated", return_value=False), \
             patch.object(elevation, "relaunch_elevated", return_value=False):
            self.assertEqual(elevation.startup_elevation_action(), "failed")

    def test_elevation_sentinel_prevents_relaunch_loop(self):
        with patch.object(elevation.os, "name", "nt"), \
             patch.object(elevation, "is_self_elevated", return_value=False), \
             patch.object(sys, "argv", ["app.py", elevation._ELEVATION_SENTINEL]), \
             patch.object(elevation, "relaunch_elevated") as relaunch:
            self.assertEqual(elevation.startup_elevation_action(), "failed")
        relaunch.assert_not_called()

    def test_manifest_and_app_bootstrap_require_early_elevation(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "vortex.manifest"), encoding="utf-8") as handle:
            manifest = handle.read()
        with open(os.path.join(root, "app.py"), encoding="utf-8") as handle:
            app_source = handle.read()
        with open(os.path.join(root, "build_exe.spec"), encoding="utf-8") as handle:
            spec_source = handle.read()
        self.assertIn('level="requireAdministrator"', manifest)
        self.assertIn('uiAccess="false"', manifest)
        self.assertIn('manifest="vortex.manifest"', spec_source)
        self.assertIn("uac_admin=True", spec_source)
        self.assertIn("uac_uiaccess=False", spec_source)
        self.assertLess(
            app_source.index("startup_elevation_action()"),
            app_source.index("import uvicorn"),
        )

    def test_relaunch_elevated_noop_when_already_elevated(self):
        with patch.object(elevation, "is_self_elevated", return_value=True):
            self.assertFalse(elevation.relaunch_elevated())


if __name__ == "__main__":
    unittest.main()
