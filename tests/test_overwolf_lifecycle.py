import unittest
import unittest
from unittest.mock import patch

from backend import overwolf
from backend import server


def _process(name, pid, parent=0, command="", path=""):
    return {
        "Name": name,
        "ProcessId": pid,
        "ParentProcessId": parent,
        "CommandLine": command,
        "ExecutablePath": path,
    }


class OverwolfProcessSelectionTests(unittest.TestCase):
    ROOT = r'"C:\Program Files (x86)\Overwolf\Overwolf.exe"'
    TRACKER_UID = overwolf._TRACKER_UID

    def _tracker(self, pid=22128, parent=15400):
        return _process(
            "OverwolfBrowser.exe",
            pid,
            parent,
            f'{self.ROOT} --owapp="Valorant Tracker - background" --uid={self.TRACKER_UID}',
            r"C:\Program Files (x86)\Overwolf\0.309.0.14\OverwolfBrowser.exe",
        )

    def test_selects_tracker_by_uid_and_shared_overwolf_root(self):
        infos = [
            _process("Overwolf.exe", 15400, path=r"C:\Program Files (x86)\Overwolf\Overwolf.exe"),
            self._tracker(),
            _process(
                "OverwolfBrowser.exe",
                11844,
                15400,
                f'{self.ROOT} --owapp="Overwolf General GameEvents Provider - index.html"',
                r"C:\Program Files (x86)\Overwolf\0.309.0.14\OverwolfBrowser.exe",
            ),
            _process("OverwolfHelper.exe", 17572, 15400),
            _process("OverwolfHelper64.exe", 17652, 15400),
            _process("OverwolfSetup-vortex.exe", 30003, 15400),
        ]

        selected = overwolf._select_shutdown_targets(infos)

        self.assertEqual([22128], selected["tracker"])
        self.assertEqual([30003], selected["installers"])
        self.assertEqual([15400], selected["roots"])
        self.assertEqual([], selected["blocked_labels"])

    def test_unknown_overwolf_app_blocks_shared_root_but_not_tracker(self):
        infos = [
            _process("Overwolf.exe", 15400),
            self._tracker(),
            _process(
                "OverwolfBrowser.exe",
                30000,
                15400,
                f'{self.ROOT} --owapp="Some unrelated Overwolf app"',
            ),
        ]

        selected = overwolf._select_shutdown_targets(infos)

        self.assertEqual([22128], selected["tracker"])
        self.assertEqual([], selected["roots"])
        self.assertEqual([15400], selected["root_candidates"])
        self.assertEqual(["Some unrelated Overwolf app"], selected["blocked_labels"])

    def test_unrelated_process_names_and_tracker_like_labels_are_not_targets(self):
        infos = [
            _process("Overwolf.exe", 15400),
            _process("OverwolfBrowser.exe", 30001, 15400,
                     f'{self.ROOT} --owapp="Unrelated Tracker Dashboard"'),
            _process("Chrome.exe", 30002, command="Valorant Tracker"),
        ]

        selected = overwolf._select_shutdown_targets(infos)

        self.assertEqual([], selected["tracker"])
        self.assertEqual(["Unrelated Tracker Dashboard"], selected["blocked_labels"])


class OverwolfCleanupMatchingTests(unittest.TestCase):
    def test_startup_matching_is_exact_enough_to_leave_other_apps_alone(self):
        self.assertEqual("overwolf", overwolf._startup_entry_kind(
            "Overwolf", r"C:\Program Files (x86)\Overwolf\OverwolfLauncher.exe -overwolfsilent"
        ))
        self.assertEqual("valorant_tracker", overwolf._startup_entry_kind(
            "TrackerNetwork", f"overwolf-extension-{overwolf._TRACKER_UID}"
        ))
        self.assertEqual("", overwolf._startup_entry_kind(
            "RiotClient", r"C:\Riot Games\Riot Client\RiotClientServices.exe --launch-background-mode"
        ))
        self.assertEqual("", overwolf._startup_entry_kind(
            "Steam", r"C:\Program Files (x86)\Steam\steam.exe -silent"
        ))
        self.assertEqual("", overwolf._startup_entry_kind(
            "OtherApp", r"C:\Tools\Valorant Tracker Dashboard.exe"
        ))

    def test_clean_shutdown_escalates_only_remaining_pids(self):
        killed = []
        with patch.object(overwolf, "_taskkill", side_effect=lambda pid, force=False: killed.append((pid, force))), \
             patch.object(overwolf, "_wait_for_pids_gone", side_effect=[[7], []]):
            remaining = overwolf._terminate_pids([7], "VAL Tracker")

        self.assertEqual([], remaining)
        self.assertEqual([(7, False), (7, True)], killed)

    def test_disabled_gate_prevents_provider_launch(self):
        overwolf.enable_live_match_integration()
        with patch.object(overwolf, "is_installed", side_effect=AssertionError("must not probe install")):
            overwolf._integration_enabled = False
            try:
                self.assertFalse(overwolf.ensure_available())
                self.assertFalse(overwolf.ensure_running())
                self.assertEqual(
                    {"success": False, "message": "Live Match Features are disabled."},
                    overwolf.start_install(),
                )
            finally:
                overwolf.enable_live_match_integration()

    def test_restore_uses_only_recorded_registry_entries(self):
        item = {
            "kind": "Overwolf",
            "mechanism": "registry",
            "name": "Overwolf",
            "location": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
            "restore": {
                "command": r"C:\Program Files (x86)\Overwolf\OverwolfLauncher.exe -overwolfsilent",
                "value_type": "1",
                "registry_view": "0",
            },
        }
        with patch.object(overwolf, "_restore_registry_startup_item", return_value=None) as restore:
            result = overwolf.restore_startup_entries([item])

        restore.assert_called_once_with(item)
        self.assertEqual([item], result["restored"])
        self.assertEqual([], result["remaining"])

    def test_restore_preserves_user_replacement_and_retries_failures(self):
        item = {"kind": "Overwolf", "mechanism": "registry", "name": "Overwolf"}
        with patch.object(
            overwolf,
            "_restore_registry_startup_item",
            return_value="startup entry now exists; leaving the current value unchanged",
        ):
            skipped = overwolf.restore_startup_entries([item])
        self.assertEqual([], skipped["remaining"])
        self.assertEqual(1, len(skipped["skipped"]))

        with patch.object(overwolf, "_restore_registry_startup_item", return_value="access denied"):
            failed = overwolf.restore_startup_entries([item])
        self.assertEqual([item], failed["remaining"])
        self.assertEqual(1, len(failed["failed"]))


class SettingsLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_turning_live_match_off_runs_cleanup_after_persist(self):
        previous = {
            "live_hud_enabled": "1",
        }
        current = {
            **previous,
            "live_hud_enabled": "0",
        }
        cleanup = {
            "success": True,
            "processes": {"failed": []},
            "startup": {
                "removed": [{"kind": "Overwolf", "mechanism": "registry"}],
                "disabled": [],
                "failed": [],
            },
        }
        calls = []

        def update_settings(values):
            calls.append(values)

        with patch.object(server.db, "get_settings", side_effect=[previous, current, current]), \
             patch.object(server.db, "update_settings", side_effect=update_settings), \
             patch.object(server, "_disable_live_match_features", return_value=cleanup) as disable:
            result = await server.update_settings(server.SettingsUpdate(settings={
                "live_hud_enabled": "0",
            }))

        disable.assert_called_once()
        self.assertTrue(result["success"])
        self.assertIn("live_match_cleanup", result)
        self.assertIn("live_match_startup_cleanup", calls[-1])

    async def test_turning_live_match_on_restores_recorded_startup_then_rearms(self):
        previous = {
            "live_hud_enabled": "0",
        }
        current = {
            "live_hud_enabled": "1",
        }
        with patch.object(server.db, "get_settings", side_effect=[previous, current, current]), \
             patch.object(server.db, "update_settings"), \
             patch.object(server.overwolf, "enable_live_match_integration") as enable, \
             patch.object(server, "_restore_live_match_startup", return_value={"restored": [{"name": "Overwolf"}], "skipped": [], "failed": []}) as restore, \
             patch.object(server, "_disable_live_match_features") as disable:
            result = await server.update_settings(server.SettingsUpdate(settings={
                "live_hud_enabled": "1",
            }))

        self.assertTrue(result["success"])
        enable.assert_called_once()
        restore.assert_called_once()
        self.assertIn("live_match_startup_restore", result)
        disable.assert_not_called()

    def test_canonical_setting_wins_over_stale_legacy_aliases(self):
        self.assertFalse(server._live_match_features_enabled({
            "live_hud_enabled": "0", "overwolf_enabled": "1", "valorant_tracker_enabled": "1",
        }))
        normalized = server._normalize_live_match_settings({"live_hud_enabled": "1"})
        self.assertEqual("1", normalized["overwolf_enabled"])
        self.assertEqual("1", normalized["valorant_tracker_enabled"])

    async def test_direct_overwolf_install_honors_canonical_setting(self):
        stale = {"live_hud_enabled": "0", "overwolf_enabled": "1"}
        with patch.object(server.db, "get_settings", return_value=stale), \
             patch.object(server.overwolf, "start_install") as install:
            result = await server.overwolf_install()

        self.assertFalse(result["success"])
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
