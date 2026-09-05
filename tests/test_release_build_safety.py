import os
import re
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(relative_path):
    with open(os.path.join(ROOT, relative_path), encoding="utf-8") as handle:
        return handle.read()


class ReleaseBuildSafetyTests(unittest.TestCase):
    def test_release_dependencies_are_exactly_pinned(self):
        requirements = _read("requirements.txt")
        entries = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(entries)
        self.assertTrue(all("==" in entry for entry in entries))
        self.assertIn("uvicorn[standard]==", requirements)
        self.assertRegex(requirements, r"(?m)^pyinstaller==")

    def test_spec_builds_smoke_twin_and_collects_uia_data(self):
        spec = _read("build_exe.spec")
        self.assertIn('collect_data_files("uiautomation")', spec)
        self.assertIn('collect_dynamic_libs("uiautomation")', spec)
        self.assertIn('collect_submodules("uvicorn")', spec)
        self.assertIn('collect_submodules("websockets")', spec)
        self.assertIn('name="VortexSmoke"', spec)
        self.assertIn("smoke_exe,", spec)
        self.assertIn("uac_admin=False", spec)

    def test_build_runs_frozen_and_installer_smoke_gates(self):
        build = _read("build.bat")
        self.assertIn('"dist\\Vortex\\VortexSmoke.exe" --smoke-test', build)
        self.assertIn("for /L %%n in (1,1,3)", build)
        self.assertIn("/api/app-version", _read("app.py"))
        self.assertIn("VORTEX_SMOKE_OK", _read("app.py"))
        self.assertIn("asyncio.SelectorEventLoop()", _read("app.py"))
        self.assertIn("/VORTEXBUILDSMOKE", build)
        self.assertLess(
            build.index("Running installer integrity test"),
            build.index('move /y "%VORTEX_INSTALLER_OUTPUT_DIR%\\VortexSetup.exe"'),
        )

    def test_windowless_tracebacks_are_file_backed_before_optional_imports(self):
        app = _read("app.py")
        stream_open = app.index('STARTUP_LOG, "a", encoding="utf-8"')
        self.assertLess(stream_open, app.index("import uvicorn"))
        self.assertNotIn("sys.stderr = io.StringIO()", app)
        self.assertIn('backend server failed:\\n', app)
        self.assertIn("_launch_server_and_wait()", app)

    def test_installer_probe_has_no_real_install_side_effects(self):
        installer = _read("installer/vortex_setup.iss")
        self.assertIn("Uninstallable=not IsBuildSmoke", installer)
        self.assertIn("CreateUninstallRegKey=not IsBuildSmoke", installer)
        self.assertGreaterEqual(len(re.findall(r"Check: not IsBuildSmoke", installer)), 3)
        prepare = installer.split("function PrepareToInstall", 1)[1]
        self.assertLess(prepare.index("if IsBuildSmoke then"), prepare.index("taskkill"))


if __name__ == "__main__":
    unittest.main()
