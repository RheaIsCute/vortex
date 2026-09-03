import importlib
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RuntimeAuditTests(unittest.TestCase):
    def _fresh(self, enabled: bool):
        os.environ["VORTEX_AUDIT_RUNTIME"] = "1" if enabled else "0"
        import backend.runtime_audit as ra
        importlib.reload(ra)
        records = []
        ra._logger.handlers = [_ListHandler(records)]
        ra._configured = True  # skip file handler setup
        return ra, records

    def test_disabled_by_default_is_noop(self):
        ra, records = self._fresh(enabled=False)
        ra.process_open(0x1000, "pid=123", "test")
        ra.riot_api("DELETE", "https://127.0.0.1:1234/rso-auth/v1/session?x=y")
        self.assertEqual(records, [])

    def test_enabled_records_and_flags_invasive(self):
        ra, records = self._fresh(enabled=True)
        ra.process_open(0x1000, "pid=1", "safe")
        ra.process_open(0x0010 | 0x0020, "pid=2", "bad")  # VM_WRITE | VM_OPERATION
        joined = "\n".join(records)
        self.assertIn("PROCESS_QUERY_LIMITED_INFORMATION", joined)
        self.assertIn("INVASIVE", joined)
        self.assertNotIn("INVASIVE", records[0])  # the query-only one is not flagged

    def test_secrets_are_scrubbed(self):
        ra, records = self._fresh(enabled=True)
        ra.riot_api("GET", "https://riot:supersecret@127.0.0.1:9/foo?token=abc")
        line = records[0]
        self.assertNotIn("supersecret", line)
        self.assertNotIn("token=abc", line)
        self.assertIn("<redacted>", line)

    def tearDown(self):
        os.environ.pop("VORTEX_AUDIT_RUNTIME", None)


class _ListHandler(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        self.sink.append(record.getMessage())


if __name__ == "__main__":
    unittest.main()
