#!/usr/bin/env python3
"""Semantic-layer unit tests — pure helpers only, no network.

The actual :meth:`semantic.Chatter.complete` HTTP call needs a live API key and
is exercised manually via ``mem finish``; these tests cover the prompt-building
and JSON-parsing logic that surrounds it.  Run: python3 test_semantic.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import semantic  # noqa: E402


class SemanticTests(unittest.TestCase):
    def test_parse_json_clean(self):
        self.assertEqual(semantic.parse_json('{"a": 1}', {}), {"a": 1})

    def test_parse_json_fenced(self):
        raw = "```json\n{\"a\": 1}\n```"
        self.assertEqual(semantic.parse_json(raw, {}), {"a": 1})

    def test_parse_json_with_prose(self):
        raw = "Here you go: {\"result\": \"ok\", \"status\": \"done\"} — hope it helps"
        self.assertEqual(semantic.parse_json(raw, {}),
                         {"result": "ok", "status": "done"})

    def test_parse_json_garbage_returns_default_copy(self):
        default = {"result": "", "status": "partial"}
        out = semantic.parse_json("not json at all", default)
        self.assertEqual(out, default)
        # default is copied, not shared
        out["result"] = "x"
        self.assertEqual(default["result"], "")

    def test_truncate_short_unchanged(self):
        self.assertEqual(semantic.truncate("abc", 10), "abc")

    def test_truncate_long_marked(self):
        out = semantic.truncate("abcdefghij", 4)
        self.assertTrue(out.startswith("abcd"))
        self.assertIn("[truncated]", out)

    def test_summarize_session_uses_chatter(self):
        # monkeypatch Chatter.complete to avoid any network
        calls = {}

        class FakeChatter:
            def complete(self, system, user, **kw):
                calls["system"] = system
                calls["user"] = user
                return '{"summary":"added a test, subject drifted to Y","status":"done"}'

        out = semantic.summarize_session(FakeChatter(), "do the thing",
                                         '{"prompts":[],"errors":[]}')
        self.assertEqual(out, {"summary": "added a test, subject drifted to Y",
                               "status": "done"})
        self.assertIn("recap", calls["system"])
        self.assertIn("do the thing", calls["user"])  # initial prompt passed through

    def test_chatter_complete_routes_through_post_json(self):
        # the retry seam lives in httputil.post_json; complete just indexes the payload
        from unittest.mock import patch
        seen = {}

        def fake_post(url, headers, body, **kw):
            seen.update(url=url, headers=headers, body=body, kw=kw)
            return {"choices": [{"message": {"content": '{"ok":1}'}}]}

        ch = semantic.Chatter(name="mistral", key_env="MISTRAL_API_KEY",
                              url="http://u", model="m", api_key="k")
        with patch("semantic.post_json", fake_post):
            out = ch.complete("sys", "usr")
        self.assertEqual(out, '{"ok":1}')
        self.assertEqual(seen["url"], "http://u")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer k")
        self.assertEqual(seen["body"]["model"], "m")
        self.assertEqual(seen["body"]["messages"][0]["content"], "sys")
        self.assertIn("response_format", seen["body"])  # json_mode default on

if __name__ == "__main__":
    unittest.main()
