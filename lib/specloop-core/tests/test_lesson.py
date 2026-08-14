#!/usr/bin/env python3
"""LessonPolicy unit tests — every merge branch + multi-session integration.

No network: a fake Chatter returns canned merge_thens JSON; HashEmbedder gives
deterministic cosine (identical text ⇒ 1.0; disjoint vocab ⇒ ~0). The Store is a
real in-memory Memory. Run: python3 test_lesson.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from engine import HashEmbedder, Memory  # noqa: E402
from lesson import LessonPolicy, MergeOutcome  # noqa: E402


class FakeChatter:
    """Returns canned JSON for merge_thens; raises if unexpected call."""

    def __init__(self, replies=None):
        # replies: list consumed in order, or a single string used for every call
        if isinstance(replies, str):
            self._queue = [replies]
            self._repeat = replies
        else:
            self._queue = list(replies or [])
            self._repeat = None
        self.calls = []

    def complete(self, system, user, **kw):
        self.calls.append((system, user))
        if self._queue:
            return self._queue.pop(0)
        if self._repeat is not None:
            return self._repeat
        raise AssertionError("FakeChatter.complete called with no canned reply")


def lesson(when, then, session="s1", lstatus="tentative", created=None):
    """Build a lesson node the way the write path (mem.py) would."""
    return {
        "type": "lesson",
        "body": f"WHEN {when} THEN {then}",
        "meta": {
            "when": when, "then": then, "status": lstatus,
            "session": session,
            "confirmed_by": [session],
            "merge_count": 0,
        },
        "created": created if created is not None else time.time(),
    }


class LessonPolicyTests(unittest.TestCase):
    def setUp(self):
        self.chatter = FakeChatter()
        self.mem = Memory(":memory:", embedder=HashEmbedder(), current_project="proj")
        self.policy = LessonPolicy(self.mem.embedder, self.chatter)
        self.mem.register_policy("lesson", self.policy)

    def _index(self, **kw):
        nid = self.mem.index(lesson(**kw))
        return nid

    def tearDown(self):
        self.mem.close()

    # -- 1. no candidate → insert ------------------------------------------
    def test_no_candidate_inserts_new(self):
        nid = self._index(when="alpha beta gamma situation", then="takeaway one")
        self.assertEqual(self.mem.count(), 1)
        self.assertEqual(self.mem.last_outcome, "new")
        self.assertEqual(self.chatter.calls, [])   # no LLM on a fresh insert

    # -- 2. fast path ------------------------------------------------------
    def test_fast_path_bumps_confirmed_by_and_promotes(self):
        WHEN = "deploying a jekyll site to github pages"
        THEN = "resolve dist cname and robots txt before the action runs"
        a = self._index(when=WHEN, then=THEN, session="s1", lstatus="tentative")
        # re-learn the SAME lesson from a 2nd session ⇒ fast path (THEN identical)
        b = self._index(when=WHEN, then=THEN, session="s2", lstatus="tentative")
        self.assertEqual(a, b)                     # merged onto the same node
        self.assertEqual(self.mem.count(), 1)
        self.assertEqual(self.mem.last_outcome, "merged:fast")
        meta = self.mem.get_node(a)["meta"]
        self.assertEqual(set(meta["confirmed_by"]), {"s1", "s2"})
        self.assertEqual(meta["merge_count"], 1)
        # tentative promoted to confirmed at ≥2 distinct sessions
        self.assertEqual(meta["status"], "confirmed")
        self.assertEqual(self.chatter.calls, [])   # no LLM on fast path

    def test_fast_path_below_confirm_threshold_stays_tentative(self):
        # a single re-confirm from the SAME session does not inflate confirmed_by
        WHEN = "configuring wifi on a raspberry pi"
        THEN = "set the wifi country code before connecting"
        a = self._index(when=WHEN, then=THEN, session="s1", lstatus="tentative")
        self._index(when=WHEN, then=THEN, session="s1")  # same session again
        meta = self.mem.get_node(a)["meta"]
        self.assertEqual(meta["confirmed_by"], ["s1"])  # deduped
        self.assertEqual(meta["status"], "tentative")   # still <2 distinct

    # -- 3. arbiter: same_trigger False ⇒ NOT_A_DUP ------------------------
    def test_same_trigger_false_inserts_separate_node(self):
        WHEN = "working with the memory database"
        self._index(when=WHEN, then="use sqlite for storage", session="s1")
        self.chatter = FakeChatter(
            '{"same_trigger":false,"then":"","status":"tentative","dropped":[]}')
        self.policy.chatter = self.chatter
        # different THEN ⇒ arbiter says different trigger ⇒ new node
        nid = self._index(when=WHEN, then="a totally different concern here",
                          session="s2")
        self.assertEqual(self.mem.count(), 2)
        self.assertEqual(self.mem.last_outcome, "not-a-dup")
        self.assertIsNotNone(nid)

    # -- 4. reconcile: same trigger, THENs differ ⇒ update in place --------
    def test_reconcile_updates_existing_in_place(self):
        WHEN = "cloning the raspberry pi sd card"
        a = self._index(when=WHEN, then="use rpi-clone tool to clone sd",
                        session="s1", lstatus="tentative")
        self.chatter = FakeChatter(
            '{"same_trigger":true,"then":"prefer piclone because rpi-clone is unreliable",'
            '"status":"confirmed",'
            '"dropped":[{"item":"use rpi-clone","reason":"superseded by piclone"}]}')
        self.policy.chatter = self.chatter
        b = self._index(when=WHEN,
                        then="rpi-clone broke so switch to the piclone utility",
                        session="s2", lstatus="tentative")
        self.assertEqual(a, b)                     # stable id — updated in place
        self.assertEqual(self.mem.count(), 1)
        self.assertEqual(self.mem.last_outcome, "merged:llm")
        node = self.mem.get_node(a)
        # body + then reflect the merged THEN; WHEN unchanged
        self.assertIn("prefer piclone", node["body"])
        self.assertIn("prefer piclone", node["meta"]["then"])
        self.assertEqual(node["meta"]["when"], WHEN)
        # status from the merger; confirmations unioned; merge_count advanced
        self.assertEqual(node["meta"]["status"], "confirmed")
        self.assertEqual(set(node["meta"]["confirmed_by"]), {"s1", "s2"})
        self.assertEqual(node["meta"]["merge_count"], 1)
        # provenance preserves the dropped-then for recovery
        prov = node["meta"]["provenance"]
        self.assertEqual(len(prov), 1)
        self.assertIn("piclone utility", prov[0]["then"])
        # dropped honoured in the audit detail
        self.assertEqual(self.policy.last_merge["dropped"][0]["item"], "use rpi-clone")

    def test_reconcile_provenance_accumulates_across_merges(self):
        WHEN = "tuning the recall score threshold"
        a = self._index(when=WHEN, then="start at zero point four zero", session="s1")
        # 2nd merge
        self.chatter = FakeChatter(
            '{"same_trigger":true,"then":"v2 merged takeaway","status":"tentative","dropped":[]}')
        self.policy.chatter = self.chatter
        self._index(when=WHEN, then="second distinct approach two", session="s2")
        # 3rd merge
        self.chatter = FakeChatter(
            '{"same_trigger":true,"then":"v3 merged takeaway","status":"tentative","dropped":[]}')
        self.policy.chatter = self.chatter
        self._index(when=WHEN, then="third distinct approach three", session="s3")
        node = self.mem.get_node(a)
        self.assertEqual(len(node["meta"]["provenance"]), 2)  # s2 + s3 appended
        self.assertEqual(node["meta"]["merge_count"], 2)

    def test_authority_uses_merged_status_and_then(self):
        # the merger (canned) resolves the contradiction by authority; the policy
        # trusts res["then"]/res["status"]. Higher-authority side wins.
        WHEN = "choosing an embedding provider"
        self._index(when=WHEN, then="the old broken recommendation here",
                    session="s1", lstatus="contested")
        self.chatter = FakeChatter(
            '{"same_trigger":true,"then":"use mistral-embed it is confirmed working",'
            '"status":"confirmed","dropped":[]}')
        self.policy.chatter = self.chatter
        self._index(when=WHEN, then="a contradictory different option text",
                    session="s2", lstatus="tentative")
        node = self.mem.get_node(
            self.mem.conn.execute("SELECT id FROM nodes").fetchone()[0])
        self.assertEqual(node["meta"]["status"], "confirmed")
        self.assertIn("mistral-embed", node["meta"]["then"])


class MultiSessionIntegrationTest(unittest.TestCase):
    """unit 07 §Test plan: same trigger recurs (fast), then a different THEN
    (LLM merge), then a different trigger (separate node)."""

    def test_sequence(self):
        chatter = FakeChatter(
            '{"same_trigger":true,"then":"prefer piclone it is more reliable",'
            '"status":"confirmed","dropped":[]}')
        mem = Memory(":memory:", embedder=HashEmbedder(), current_project="proj")
        policy = LessonPolicy(mem.embedder, chatter)
        mem.register_policy("lesson", policy)

        WHEN = "cloning the raspberry pi sd card"
        # s1: first write — new node (session partial ⇒ lesson tentative)
        s1 = mem.index(lesson(when=WHEN, then="use rpi-clone to clone the sd card",
                              session="s1", lstatus="tentative"))
        self.assertEqual(mem.count(), 1)
        self.assertEqual(mem.last_outcome, "new")

        # s2: SAME trigger + THEN ⇒ fast-path merge (no LLM)
        s2 = mem.index(lesson(when=WHEN, then="use rpi-clone to clone the sd card",
                              session="s2", lstatus="tentative"))
        self.assertEqual(s2, s1)
        self.assertEqual(mem.count(), 1)
        self.assertEqual(mem.last_outcome, "merged:fast")
        node = mem.get_node(s1)
        self.assertEqual(set(node["meta"]["confirmed_by"]), {"s1", "s2"})
        self.assertEqual(node["meta"]["status"], "confirmed")  # promoted at 2

        # s3: SAME trigger, DIFFERENT THEN ⇒ LLM merge in place
        s3 = mem.index(lesson(when=WHEN,
                              then="rpi-clone failed so use the piclone tool instead",
                              session="s3", lstatus="confirmed"))
        self.assertEqual(s3, s1)
        self.assertEqual(mem.count(), 1)
        self.assertEqual(mem.last_outcome, "merged:llm")
        node = mem.get_node(s1)
        self.assertIn("prefer piclone", node["meta"]["then"])
        self.assertEqual(set(node["meta"]["confirmed_by"]), {"s1", "s2", "s3"})
        self.assertEqual(node["meta"]["merge_count"], 2)
        self.assertEqual(len(node["meta"]["provenance"]), 1)

        # s4: DIFFERENT trigger ⇒ separate node, no merge
        s4 = mem.index(lesson(when="configuring wifi on a raspberry pi board",
                              then="set the wifi country code first",
                              session="s4", lstatus="confirmed"))
        self.assertNotEqual(s4, s1)
        self.assertEqual(mem.count(), 2)
        self.assertEqual(mem.last_outcome, "new")

        # the LLM (merge_thens) was called exactly once (only the s3 reconcile)
        self.assertEqual(len(chatter.calls), 1)
        mem.close()


if __name__ == "__main__":
    unittest.main()
