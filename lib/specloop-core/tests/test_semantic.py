#!/usr/bin/env python3
"""Semantic-layer unit tests — pure helpers only, no network.

The actual :meth:`semantic.Chatter.complete` HTTP call needs a live API key and
is exercised manually via ``mem recap``; these tests cover the prompt-building
and JSON-parsing logic that surrounds it by injecting a fake Chatter.
Run: python3 test_semantic.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import semantic  # noqa: E402


class ParseHelperTests(unittest.TestCase):
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


class FakeChatter:
    """Returns canned JSON; records the (system, user) of each call."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, system, user, **kw):
        self.calls.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class ExtractLessonsTests(unittest.TestCase):
    def test_normal_extraction_schema(self):
        ch = FakeChatter(
            '{"status":"done","lessons":['
            '{"when":"deploying jekyll to github pages","then":["resolve dist/CNAME first"]},'
            '{"when":"booting a pi from usb","then":["set program_usb_boot_timeout=1"]}]}')
        out = semantic.extract_lessons(ch, "deploy the site", '{"prompts":[],"errors":[]}')
        self.assertEqual(out["status"], "done")
        self.assertEqual(len(out["lessons"]), 2)
        self.assertEqual(out["lessons"][0]["when"], "deploying jekyll to github pages")
        self.assertEqual(out["lessons"][0]["then"], ["resolve dist/CNAME first"])
        # initial prompt is passed through; system prompt mentions lessons
        self.assertIn("deploy the site", ch.calls[0][1])
        self.assertIn("lessons", ch.calls[0][0])

    def test_then_string_from_model_is_coerced_to_one_item_list(self):
        # the schema asks for a list; a model that returns a bare string (a
        # formatting slip, not a contract violation) shouldn't lose the lesson
        ch = FakeChatter(
            '{"status":"done","lessons":['
            '{"when":"a situation","then":"a single takeaway"}]}')
        out = semantic.extract_lessons(ch, "p", "{}")
        self.assertEqual(out["lessons"][0]["then"], ["a single takeaway"])

    def test_void_returns_empty_lessons(self):
        ch = FakeChatter('{"status":"void","lessons":[]}')
        out = semantic.extract_lessons(ch, "chat about weather", "{}")
        self.assertEqual(out["status"], "void")
        self.assertEqual(out["lessons"], [])

    def test_cap_enforced_at_five(self):
        many = [{"when": f"situation {i}", "then": [f"takeaway {i}"]} for i in range(8)]
        ch = FakeChatter('{"status":"partial","lessons":' + semantic.json.dumps(many) + '}')
        out = semantic.extract_lessons(ch, "p", "{}")
        self.assertLessEqual(len(out["lessons"]), semantic.MAX_LESSONS)
        self.assertEqual(len(out["lessons"]), 5)

    def test_garbage_json_raises(self):
        # the contract: an unparseable reply is a hard failure (write path → error)
        ch = FakeChatter("totally not json at all {{{")
        with self.assertRaises(ValueError):
            semantic.extract_lessons(ch, "p", "{}")

    def test_missing_status_raises(self):
        # well-formed JSON but contract-violating (no status) → raise
        ch = FakeChatter('{"lessons":[]}')  # no status field
        with self.assertRaises(ValueError):
            semantic.extract_lessons(ch, "p", "{}")

    def test_lessons_not_a_list_raises(self):
        ch = FakeChatter('{"status":"done","lessons":"not a list"}')
        with self.assertRaises(ValueError):
            semantic.extract_lessons(ch, "p", "{}")

    def test_empty_lessons_list_is_not_an_error(self):
        # a well-formed {status, lessons:[]} is the model's own verdict, not a failure
        ch = FakeChatter('{"status":"partial","lessons":[]}')
        out = semantic.extract_lessons(ch, "p", "{}")
        self.assertEqual(out, {"status": "partial", "lessons": []})


class MergeThensTests(unittest.TestCase):
    def _ab(self):
        return ({"then": ["use rpi-clone for sd cloning"], "status": "confirmed",
                 "confirmed_by": ["s1", "s2"], "date": 100.0},
                {"then": ["rpi-clone broke", "use piclone instead"], "status": "tentative",
                 "confirmed_by": ["s3"], "date": 200.0})

    def test_same_trigger_true_returns_merged(self):
        ch = FakeChatter(
            '{"same_trigger":true,"then":["prefer piclone (rpi-clone unreliable on this setup)"],'
            '"status":"contested","dropped":[{"item":"use rpi-clone","reason":"superseded by piclone"}]}')
        out = semantic.merge_thens(ch, "cloning the pi sd card", *self._ab())
        self.assertTrue(out["same_trigger"])
        self.assertIn("piclone", out["then"][0])
        self.assertEqual(out["status"], "contested")
        self.assertEqual(len(out["dropped"]), 1)
        self.assertEqual(out["dropped"][0]["item"], "use rpi-clone")

    def test_same_trigger_false_signals_not_a_dup(self):
        ch = FakeChatter('{"same_trigger":false,"then":[],"status":"tentative","dropped":[]}')
        out = semantic.merge_thens(ch, "cloning the pi sd card", *self._ab())
        self.assertFalse(out["same_trigger"])
        # the other fields are present but the caller ignores them
        self.assertEqual(out["then"], [])

    def test_union_and_dedupe_preserved(self):
        # two non-overlapping items → merged then unions them
        ch = FakeChatter(
            '{"same_trigger":true,"then":["install X first","then run Y"],'
            '"status":"confirmed","dropped":[]}')
        out = semantic.merge_thens(ch, "w", *self._ab())
        self.assertTrue(out["same_trigger"])
        self.assertIn("install X first", out["then"])
        self.assertIn("then run Y", out["then"])

    def test_authority_status_returned(self):
        # the merger returns the resolved status per the authority rules
        ch = FakeChatter('{"same_trigger":true,"then":["x"],"status":"confirmed","dropped":[]}')
        out = semantic.merge_thens(ch, "w", *self._ab())
        self.assertEqual(out["status"], "confirmed")

    def test_dropped_populated_with_reasons(self):
        ch = FakeChatter(
            '{"same_trigger":true,"then":["keep a","keep b"],'
            '"status":"tentative",'
            '"dropped":[{"item":"c","reason":"duplicate of a"},{"item":"d","reason":"lowest value"}]}')
        out = semantic.merge_thens(ch, "w", *self._ab())
        self.assertEqual(len(out["dropped"]), 2)
        self.assertEqual({d["item"] for d in out["dropped"]}, {"c", "d"})
        self.assertTrue(all("reason" in d for d in out["dropped"]))

    def test_garbage_json_raises(self):
        ch = FakeChatter("nope not json")
        with self.assertRaises(ValueError):
            semantic.merge_thens(ch, "w", *self._ab())

    def test_missing_same_trigger_raises(self):
        ch = FakeChatter('{"then":["x"],"status":"tentative"}')  # no same_trigger
        with self.assertRaises(ValueError):
            semantic.merge_thens(ch, "w", *self._ab())

    def test_overflow_items_truncated_and_recorded_as_dropped(self):
        # the model ignores the cap and returns 8 items ⇒ code truncates to
        # MAX_THEN_ITEMS and records the overflow in 'dropped' (never silent)
        items = [f"item {i}" for i in range(8)]
        ch = FakeChatter(semantic.json.dumps(
            {"same_trigger": True, "then": items, "status": "tentative", "dropped": []}))
        out = semantic.merge_thens(ch, "w", *self._ab())
        self.assertEqual(len(out["then"]), semantic.MAX_THEN_ITEMS)
        self.assertEqual(out["then"], items[:semantic.MAX_THEN_ITEMS])
        overflow_dropped = [d for d in out["dropped"] if d["item"] in items[semantic.MAX_THEN_ITEMS:]]
        self.assertEqual(len(overflow_dropped), 2)

    def test_bare_string_then_from_model_is_coerced_to_list(self):
        ch = FakeChatter(
            '{"same_trigger":true,"then":"a single merged takeaway",'
            '"status":"confirmed","dropped":[]}')
        out = semantic.merge_thens(ch, "w", *self._ab())
        self.assertEqual(out["then"], ["a single merged takeaway"])


class ChatterRoutesTests(unittest.TestCase):
    def test_chatter_complete_routes_through_post_json(self):
        # the retry seam lives in httputil.post_json; complete just indexes the payload
        from unittest.mock import patch
        seen = {}

        def fake_post(url, headers, body, **kw):
            seen.update(url=url, headers=headers, body=body, kw=kw)
            return {"choices": [{"message": {"content": '{"ok":1}'}}]}

        ch = semantic.Chatter(name="mistral", key_env="MISTRAL_API_KEY",
                              url="http://u", model="m", api_key="k")
        os.environ["SPECLOOP_USAGE"] = "0"   # don't pollute the real usage log in tests
        try:
            with patch("semantic.post_json", fake_post):
                out = ch.complete("sys", "usr", purpose="extract")
        finally:
            os.environ.pop("SPECLOOP_USAGE", None)
        self.assertEqual(out, '{"ok":1}')
        self.assertEqual(seen["url"], "http://u")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer k")
        self.assertEqual(seen["body"]["model"], "m")
        self.assertEqual(seen["body"]["messages"][0]["content"], "sys")
        self.assertIn("response_format", seen["body"])  # json_mode default on


if __name__ == "__main__":
    unittest.main()
