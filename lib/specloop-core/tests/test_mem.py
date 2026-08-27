#!/usr/bin/env python3
"""Write-path (cmd_recap / run_recap) tests — unit 05.

Drives ``run_recap`` against an in-memory store + HashEmbedder. A single fake
Chatter serves both ``extract_lessons`` (first call) and ``merge_thens`` (later
calls via LessonPolicy), so no functions are monkeypatched and no network is
used. Asserts: node count = len(lessons) − merges; void/error ⇒ 0 nodes + audit;
per-lesson skip ⇒ partial write + audit; JSON output shape.
Run: python3 test_mem.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from engine import HashEmbedder, Memory  # noqa: E402
import mem  # noqa: E402


class ScriptedChatter:
    """Returns canned JSON replies in order; raises if exhausted."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, user, **kw):
        self.calls.append(system)
        if not self.replies:
            raise AssertionError("ScriptedChatter: unexpected extra call")
        return self.replies.pop(0)


def lesson_json(when, then):
    """``then`` is what extract_lessons would return post-coercion: list[str].
    Accepts a bare string too (wrapped to a 1-item list) for terser call sites."""
    return {"when": when, "then": [then] if isinstance(then, str) else list(then)}


class RunRecapTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        os.environ["SPECLOOP_AUDIT"] = "0"  # audit off — we assert via the store
        self.mem = Memory(self.db_path, embedder=HashEmbedder(), current_project="proj")

    def tearDown(self):
        self.mem.close()
        os.unlink(self.db_path)
        os.environ.pop("SPECLOOP_AUDIT", None)

    def _run(self, chatter, digest=None, ip="do the thing", session="sess-1"):
        return mem.run_recap(self.mem, chatter, ip,
                             json.dumps(digest or {}), session)

    # -- happy path: 2 distinct lessons ⇒ 2 nodes --------------------------
    def test_two_distinct_lessons_two_nodes(self):
        ch = ScriptedChatter([
            json.dumps({"status": "done", "lessons": [
                lesson_json("deploying jekyll to github pages", "resolve dist cname first"),
                lesson_json("booting a pi from usb", "set program_usb_boot_timeout one"),
            ]}),
        ])
        out = self._run(ch)
        self.assertEqual(out["session_status"], "done")
        self.assertEqual(len(out["lessons"]), 2)
        self.assertEqual(self.mem.count(type="lesson"), 2)
        # each lesson reports outcome new; status stays tentative — a "done"
        # session no longer grants confirmed (evidence-only confirmation)
        self.assertEqual(sorted(l["outcome"] for l in out["lessons"]), ["new", "new"])
        self.assertTrue(all(l["status"] == "tentative" for l in out["lessons"]))

    # -- void ⇒ 0 nodes ----------------------------------------------------
    def test_void_writes_nothing(self):
        ch = ScriptedChatter([json.dumps({"status": "void", "lessons": []})])
        out = self._run(ch)
        self.assertEqual(out["session_status"], "void")
        self.assertEqual(out["lessons"], [])
        self.assertEqual(self.mem.count(), 0)

    # -- empty lessons list (partial) ⇒ 0 nodes ---------------------------
    def test_empty_lessons_writes_nothing(self):
        ch = ScriptedChatter([json.dumps({"status": "partial", "lessons": []})])
        out = self._run(ch)
        self.assertEqual(out["session_status"], "partial")
        self.assertEqual(self.mem.count(), 0)

    # -- extractor raises (garbage JSON) ⇒ error, 0 nodes ------------------
    def test_extractor_failure_is_error_no_nodes(self):
        class RaisingChatter:
            def complete(self, s, u, **kw):
                return "totally not json {{{"

        out = self._run(RaisingChatter())
        self.assertEqual(out["session_status"], "error")
        self.assertEqual(out["lessons"], [])
        self.assertEqual(self.mem.count(), 0)
        self.assertTrue(out["warnings"])  # the failure is surfaced

    # -- same trigger recurs ⇒ fast-path merge, node count stable ---------
    def test_repeated_trigger_merges_not_duplicates(self):
        when = "cloning the raspberry pi sd card"
        then = "use rpi-clone to clone the sd card"
        # session 1: new
        ch1 = ScriptedChatter([json.dumps(
            {"status": "partial", "lessons": [lesson_json(when, then)]})])
        out1 = self._run(ch1, session="s1")
        self.assertEqual(len(out1["lessons"]), 1)
        self.assertEqual(out1["lessons"][0]["outcome"], "new")
        self.assertEqual(self.mem.count(), 1)
        # session 2: SAME when+then ⇒ fast-path merge (no merge_thens call)
        ch2 = ScriptedChatter([json.dumps(
            {"status": "partial", "lessons": [lesson_json(when, then)]})])
        out2 = self._run(ch2, session="s2")
        self.assertEqual(self.mem.count(), 1)  # still one node — merged
        self.assertEqual(out2["lessons"][0]["outcome"], "merged:fast")
        self.assertEqual(len(ch2.calls), 1)    # only extract_lessons; no merge_thens

    # -- same trigger, different THEN ⇒ LLM merge (2 chatter calls) -------
    def test_different_then_triggers_llm_merge(self):
        when = "tuning the recall threshold"
        ch1 = ScriptedChatter([json.dumps({"status": "done", "lessons": [
            lesson_json(when, "start at zero point four zero")]})])
        self._run(ch1, session="s1")
        self.assertEqual(self.mem.count(), 1)
        # 2nd call: extract returns a different THEN; merge_thens canned after
        ch2 = ScriptedChatter([
            json.dumps({"status": "done", "lessons": [
                lesson_json(when, "raise it to zero point six eight instead")]}),
            json.dumps({"same_trigger": True, "then": "start around zero point six eight",
                        "status": "confirmed", "dropped": []}),
        ])
        out2 = self._run(ch2, session="s2")
        self.assertEqual(self.mem.count(), 1)  # merged in place, not duplicated
        self.assertEqual(out2["lessons"][0]["outcome"], "merged:llm")
        self.assertEqual(len(ch2.calls), 2)    # extract + merge_thens

    # -- partial session ⇒ lessons start tentative ------------------------
    def test_partial_session_lessons_are_tentative(self):
        ch = ScriptedChatter([json.dumps({"status": "partial", "lessons": [
            lesson_json("some situation here", "some takeaway action")]})])
        out = self._run(ch)
        self.assertEqual(out["lessons"][0]["status"], "tentative")

    # -- JSON output shape --------------------------------------------------
    def test_output_shape(self):
        ch = ScriptedChatter([json.dumps({"status": "done", "lessons": [
            lesson_json("situation alpha", "takeaway beta")]})])
        out = self._run(ch)
        self.assertIn("session_status", out)
        self.assertIn("lessons", out)
        self.assertIn("warnings", out)
        for l in out["lessons"]:
            self.assertEqual(set(l.keys()), {"id", "status", "outcome", "when"})

    # -- per-lesson failure skips that lesson, keeps the rest -------------
    def test_per_lesson_skip_continues_others(self):
        # force the SECOND lesson's index to fail by monkeypatching the store
        when_a = "first distinct situation alpha"
        when_b = "second distinct situation beta"
        ch = ScriptedChatter([json.dumps({"status": "done", "lessons": [
            lesson_json(when_a, "takeaway a"), lesson_json(when_b, "takeaway b")]})])
        original_index = self.mem.index
        calls = {"n": 0}

        def flaky_index(node):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom on second lesson")
            return original_index(node)

        self.mem.index = flaky_index
        try:
            out = self._run(ch)
        finally:
            self.mem.index = original_index
        # first lesson written; second skipped
        self.assertEqual(self.mem.count(), 1)
        self.assertEqual(len(out["lessons"]), 1)
        self.assertTrue(any("boom" in w for w in out["warnings"]))


class DedupCommandTests(unittest.TestCase):
    """`mem dedup` repair pass (unit: maintenance). HashEmbedder + identical
    WHEN/THEN fragments ⇒ fast-path merge, no chatter/LLM needed."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        os.environ["SPECLOOP_AUDIT"] = "0"
        self.mem = Memory(self.db_path, embedder=HashEmbedder(), current_project="proj")

    def tearDown(self):
        self.mem.close()
        os.unlink(self.db_path)
        os.environ.pop("SPECLOOP_AUDIT", None)

    def _node(self, nid, when, then, session):
        return {"type": "lesson", "id": nid, "project": "proj",
                "body": mem.render_body(when, [then]),
                "meta": {"when": when, "then": [then], "status": "tentative",
                         "confirmed_by": [session], "learned_days": ["2026-08-01"],
                         "merge_count": 0}}

    def _args(self, apply):
        import argparse
        return argparse.Namespace(threshold=None, apply=apply, json=False,
                                  chat_provider=None, chat_model=None)

    def test_dedup_dry_run_then_apply(self):
        W = "editing a file with exact text matching whitespace sensitive"
        T = "verify the exact text and whitespace before replacing"
        self.mem.index(self._node("dup1", W, T, "s1"))
        self.mem.index(self._node("dup2", W, T, "s2"))
        # a THIRD fragment: its dry-run pair targets dup2, but dup2 is consumed
        # by the first merge — the cascade round must re-find dup3~dup1
        self.mem.index(self._node("dup3", W, T, "s3"))
        self.mem.index(self._node("other", "exploring app ideas for a new playground",
                                  "prototype fast and throw it away", "s4"))
        self.assertEqual(self.mem.count(type="lesson"), 4)
        # dry-run: reports pairs, changes nothing
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mem.cmd_dedup(self.mem, self._args(apply=False))
        self.assertIn("candidate pair", buf.getvalue())
        self.assertEqual(self.mem.count(type="lesson"), 4)
        # apply: all three fragments collapse onto one node (cascade rounds)
        with contextlib.redirect_stdout(buf):
            mem.cmd_dedup(self.mem, self._args(apply=True))
        self.assertEqual(self.mem.count(type="lesson"), 2)  # one dup + other
        kept = next(n for n in (self.mem.get_node(x) for x in ("dup1", "dup2", "dup3"))
                    if n is not None)
        self.assertIsNotNone(kept)
        self.assertEqual(set(kept["meta"]["confirmed_by"]), {"s1", "s2", "s3"})


if __name__ == "__main__":
    unittest.main()
