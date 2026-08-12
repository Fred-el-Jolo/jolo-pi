#!/usr/bin/env python3
"""Audit-log unit tests — temp file, env-driven. Run: python3 test_audit.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import audit  # noqa: E402


class AuditTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._td.name, "audit.jsonl")
        self._old = {k: os.environ.get(k) for k in ("SPECLOOP_AUDIT", "SPECLOOP_SESSION", "SPECLOOP_PROJECT")}
        os.environ["SPECLOOP_AUDIT"] = self.path
        os.environ["SPECLOOP_SESSION"] = "sess-123"
        os.environ.pop("SPECLOOP_PROJECT", None)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    def test_log_read_roundtrip(self):
        audit.log({"event": "write", "type": "prompt", "id": "abc"})
        rows = audit.read(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "write")
        self.assertEqual(rows[0]["session"], "sess-123")  # stamped
        self.assertIn("ts", rows[0])

    def test_filter_by_event_and_tail(self):
        for i in range(5):
            audit.log({"event": "write", "type": "prompt", "id": str(i)})
        audit.log({"event": "recall", "phase": "m0", "hits": []})
        self.assertEqual(len(audit.read(self.path, event="write")), 5)
        self.assertEqual(len(audit.read(self.path, event="recall")), 1)
        self.assertEqual(len(audit.read(self.path, tail=2)), 2)

    def test_disabled_is_noop(self):
        os.environ["SPECLOOP_AUDIT"] = "0"
        self.assertIsNone(audit.path())
        audit.log({"event": "write"})  # must not raise, must not write
        os.environ["SPECLOOP_AUDIT"] = self.path
        self.assertEqual(audit.read(self.path), [])

    def test_missing_file_reads_empty(self):
        os.environ["SPECLOOP_AUDIT"] = self.path + ".does-not-exist"
        self.assertEqual(audit.read(os.environ["SPECLOOP_AUDIT"]), [])

    def test_malformed_line_skipped(self):
        with open(self.path, "w") as f:
            f.write('{"event":"write","id":"a"}\n')
            f.write("not json\n")
            f.write('{"event":"write","id":"b"}\n')
        rows = audit.read(self.path)
        self.assertEqual([r["id"] for r in rows], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
