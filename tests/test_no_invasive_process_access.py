import unittest
from pathlib import Path


class NoInvasiveProcessAccessTests(unittest.TestCase):
    def test_memory_access_and_injection_subsystem_is_absent(self):
        root = Path(__file__).parent.parent
        forbidden_files = {
            "backend/memory_reader.py",
            "backend/injector.py",
            "backend/valorant_internal.cpp",
            "backend/build_internal_dll.bat",
            "backend/live_memory.py",
        }
        for relative in forbidden_files:
            self.assertFalse((root / relative).exists(), relative)

    def test_source_does_not_reference_invasive_win32_apis(self):
        root = Path(__file__).parent.parent
        source = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for directory in (root / "backend", root / "frontend")
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in {".py", ".js", ".html", ".css", ".cpp", ".bat"}
        )
        for api in ("ReadProcessMemory", "WriteProcessMemory", "VirtualAllocEx", "CreateRemoteThread"):
            self.assertNotIn(api, source)


if __name__ == "__main__":
    unittest.main()
