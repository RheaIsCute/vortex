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
        # params is a quoted path to an existing .py file
        self.assertTrue(params.startswith('"') and params.endswith('"'))
        self.assertTrue(os.path.exists(params.strip('"')))

    def test_relaunch_elevated_noop_when_already_elevated(self):
        with patch.object(elevation, "is_self_elevated", return_value=True):
            self.assertFalse(elevation.relaunch_elevated())


if __name__ == "__main__":
    unittest.main()
