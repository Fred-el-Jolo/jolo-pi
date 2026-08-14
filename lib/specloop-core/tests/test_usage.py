#!/usr/bin/env python3
"""Usage-log unit tests — log/read + the pure rollups. No network, no DB.
Run: python3 test_usage.py
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import usage  # noqa: E402


class UsageLogTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.unlink(self.path)               # log() creates it
        os.environ["SPECLOOP_USAGE"] = self.path

    def tearDown(self):
        os.environ.pop("SPECLOOP_USAGE", None)
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_log_writes_stamped_line(self):
        usage.log({"kind": "chat", "purpose": "extract", "total_tokens": 100,
                   "prompt_tokens": 80, "completion_tokens": 20})
        rows = usage.read(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_tokens"], 100)
        self.assertIn("ts", rows[0])         # auto-stamped
        self.assertEqual(rows[0]["purpose"], "extract")

    def test_disabled_is_noop(self):
        os.environ["SPECLOOP_USAGE"] = "0"
        usage.log({"kind": "chat", "purpose": "x", "total_tokens": 1})
        self.assertEqual(usage.read(self.path), [])   # nothing written

    def test_read_filters(self):
        usage.log({"kind": "chat", "purpose": "extract", "total_tokens": 100})
        usage.log({"kind": "embed", "purpose": "index", "total_tokens": 50})
        usage.log({"kind": "embed", "purpose": "recall", "total_tokens": 30})
        self.assertEqual(len(usage.read(self.path, kind="chat")), 1)
        self.assertEqual(len(usage.read(self.path, kind="embed")), 2)
        self.assertEqual(len(usage.read(self.path, purpose="index")), 1)
        # since/until on ts
        cut = time.time()
        usage.log({"kind": "chat", "purpose": "m", "total_tokens": 5})
        self.assertEqual(len(usage.read(self.path, since=cut)), 1)   # only the new one


class RollupTests(unittest.TestCase):
    def _rows(self):
        today = time.time()
        yesterday = today - 86400
        return [
            {"ts": today, "kind": "chat", "purpose": "extract", "total_tokens": 120},
            {"ts": today, "kind": "embed", "purpose": "index", "total_tokens": 40},
            {"ts": today, "kind": "embed", "purpose": "dedup", "total_tokens": 20},
            {"ts": today, "kind": "chat", "purpose": "merge", "total_tokens": 60},
            {"ts": today, "kind": "embed", "purpose": "recall", "total_tokens": 500},  # read-side
            {"ts": yesterday, "kind": "chat", "purpose": "extract", "total_tokens": 90},
        ]

    def test_rollup_by_day_splits_chat_embed(self):
        out = usage.rollup_by_day(self._rows())
        self.assertEqual(len(out), 2)                  # two distinct days
        today_key = usage.day_key(time.time())
        today = next(d for d in out if d["day"] == today_key)
        # chat = extract(120) + merge(60) = 180; embed = index(40)+dedup(20)+recall(500) = 560
        self.assertEqual(today["chat"], 180)
        self.assertEqual(today["embed"], 560)
        self.assertEqual(today["calls"], 5)

    def test_rollup_by_session_excludes_recall(self):
        rows = self._rows()
        # tag two sessions
        for r in rows[:4]:
            r["session"] = "s1"
        rows[4]["session"] = "s2"   # recall → read-side, excluded
        rows[5]["session"] = "s1"
        out = usage.rollup_by_session(rows)
        s1 = next(s for s in out if s["session"] == "s1")
        # extract = 120 (today) + 90 (yesterday) = 210; write = index40+dedup20+merge60 = 120
        self.assertEqual(s1["extract"], 210)
        self.assertEqual(s1["write"], 120)
        # the read-side recall (s2) is not present at all
        self.assertFalse(any(s["session"] == "s2" for s in out))

    def test_rollup_by_session_uses_none_when_unset(self):
        out = usage.rollup_by_session([{"purpose": "extract", "total_tokens": 10}])
        self.assertEqual(out[0]["session"], "(none)")

    def test_day_key_format(self):
        # yields a YYYY-MM-DD shape regardless of timezone
        self.assertRegex(usage.day_key(time.time()), r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
