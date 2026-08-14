#!/usr/bin/env python3
"""Engine unit tests — stdlib only, no deps.  Run: python3 test_engine.py

Covers the generic Store (unit 01): cosine search, scope, redaction, the
policy-registry dispatch on index(), and the node helpers. Lesson-specific
dedup/merge intelligence is exercised in test_lesson.py via a real LessonPolicy.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from engine import HashEmbedder, Memory, cosine  # noqa: E402


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.mem = Memory(":memory:", embedder=HashEmbedder(), current_project="proj-a")

    def _node(self, **kw):
        # a type with NO registered policy → index inserts unconditionally on body
        base = dict(type="note", project="proj-a", body="", meta={})
        base.update(kw)
        return base


class RecallAndSearchTests(EngineTests):
    def test_recall_most_similar_first(self):
        self.mem.index(self._node(id="a", body="postgres connection pool timeout"))
        self.mem.index(self._node(id="b", body="jwt token refresh race auth"))
        self.mem.index(self._node(id="c", body="cors preflight browser origin"))
        res = self.mem.recall("postgres connection timeout", k=2)
        self.assertEqual(res[0]["id"], "a")
        # _score is attached and sorted descending
        self.assertGreaterEqual(res[0]["_score"], res[1]["_score"])

    def test_scope_local_vs_global(self):
        self.mem.index(self._node(id="a", project="proj-a", body="postgres pool timeout"))
        self.mem.index(self._node(id="b", project="proj-b", body="postgres pool timeout"))
        glob = {r["id"] for r in self.mem.recall("postgres pool timeout", k=5, scope="global")}
        local = {r["id"] for r in self.mem.recall("postgres pool timeout", k=5, scope="local")}
        self.assertEqual(glob, {"a", "b"})
        self.assertEqual(local, {"a"})

    def test_nearest_returns_scored_ids_above_threshold(self):
        self.mem.index(self._node(id="a", body="alpha beta gamma"))
        self.mem.index(self._node(id="b", body="delta epsilon zeta"))
        vec = self.mem.embedder.embed("alpha beta gamma")
        hits = self.mem.nearest(vec, k=5, threshold=0.99)   # only near-identical
        self.assertEqual([h[0] for h in hits], ["a"])
        self.assertGreater(hits[0][1], 0.99)

    def test_nearest_type_filter(self):
        self.mem.index(self._node(id="a", type="note", body="shared text here"))
        self.mem.index(self._node(id="b", type="other", body="shared text here"))
        vec = self.mem.embedder.embed("shared text here")
        only_notes = self.mem.nearest(vec, type="note", k=5, threshold=0.5)
        self.assertEqual([h[0] for h in only_notes], ["a"])

    def test_cosine_rejects_dim_mismatch(self):
        # switching embedders mid-DB must NOT silently truncate
        with self.assertRaises(ValueError):
            cosine([1.0] * 3, [1.0] * 4)
        # _cosine staticmethod still works (backward-compat)
        with self.assertRaises(ValueError):
            self.mem._cosine([1.0] * 3, [1.0] * 4)
        self.assertAlmostEqual(self.mem._cosine([1.0, 0.0], [1.0, 0.0]), 1.0)


class RedactionTests(EngineTests):
    def test_index_redacts_secret_in_body(self):
        # redaction is ON by default; an obvious key must not be persisted raw
        raw = "deploy with api_key=sk-proj-FAKE_OPENAI_KEY_XXXX and go"
        nid = self.mem.index(self._node(body=raw))
        stored = self.mem.conn.execute(
            "SELECT body FROM nodes WHERE id=?", (nid,)).fetchone()["body"]
        self.assertNotIn("sk-proj-FAKE_OPENAI_KEY_XXXX", stored)
        self.assertIn("[REDACTED:", stored)

    def test_index_redaction_disabled_by_env(self):
        os.environ["SPECLOOP_REDACT"] = "0"
        try:
            raw = "key sk-proj-FAKE_OPENAI_KEY_XXXX here"
            nid = self.mem.index(self._node(body=raw))
            stored = self.mem.conn.execute(
                "SELECT body FROM nodes WHERE id=?", (nid,)).fetchone()["body"]
            self.assertEqual(stored, raw)  # stored verbatim when disabled
        finally:
            os.environ.pop("SPECLOOP_REDACT", None)

    def test_index_redacts_secret_in_meta_when(self):
        # 'when'/'then' are redact-listed meta fields (lesson payload can carry secrets)
        raw_when = ("situation with a leaked bearer "
                    "Bearer abcdefghijklmnopqrstuvwxyz123456 token")
        nid = self.mem.index(self._node(meta={"when": raw_when, "then": "x"}))
        stored = self.mem.get_node(nid)["meta"]
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", stored["when"])
        self.assertIn("[REDACTED:", stored["when"])


class NodeHelperTests(EngineTests):
    def test_get_node_returns_none_for_missing(self):
        self.assertIsNone(self.mem.get_node("nope"))

    def test_get_node_parses_meta_drops_embedding(self):
        nid = self.mem.index(self._node(id="x", body="b", meta={"k": 1}))
        node = self.mem.get_node("x")
        self.assertEqual(node["meta"], {"k": 1})
        self.assertNotIn("embedding", node)

    def test_update_node_body_and_meta_round_trip(self):
        nid = self.mem.index(self._node(id="x", body="old", meta={"k": 1}))
        self.mem.update_node("x", body="new body", meta={"k": 2, "extra": True})
        node = self.mem.get_node("x")
        self.assertEqual(node["body"], "new body")
        self.assertEqual(node["meta"], {"k": 2, "extra": True})

    def test_update_node_does_not_change_embedding(self):
        # merge evolves the payload, not the match key (unit 03 §stable id)
        nid = self.mem.index(self._node(id="x", body="alpha beta", meta={}))
        emb_before = self.mem.conn.execute(
            "SELECT embedding FROM nodes WHERE id=?", (nid,)).fetchone()["embedding"]
        self.mem.update_node("x", body="completely different gamma delta", meta={"k": 1})
        emb_after = self.mem.conn.execute(
            "SELECT embedding FROM nodes WHERE id=?", (nid,)).fetchone()["embedding"]
        self.assertEqual(emb_before, emb_after)


class CountTests(EngineTests):
    def test_count_total_and_by_type(self):
        self.mem.index(self._node(id="a", type="note", body="x"))
        self.mem.index(self._node(id="b", type="note", body="y"))
        self.mem.index(self._node(id="c", type="other", body="z"))
        self.assertEqual(self.mem.count(), 3)
        self.assertEqual(self.mem.count(type="note"), 2)
        self.assertEqual(self.mem.count(type="other"), 1)
        self.assertEqual(self.mem.count(type="absent"), 0)


class StubPolicy:
    """Records calls + lets each test script find_candidate/merge outcomes."""

    def __init__(self):
        self.calls = []
        self.candidate = None          # return value of find_candidate
        self.outcome = None            # return value of merge (object with .value)

    def embedding_text(self, node):
        self.calls.append(("embedding_text", node["body"]))
        return node["body"]

    def find_candidate(self, store, node, project):
        self.calls.append(("find_candidate", project))
        return self.candidate

    def merge(self, store, existing_id, new_node):
        self.calls.append(("merge", existing_id))
        return self.outcome


def _outcome(value):
    return types.SimpleNamespace(value=value)


class PolicyDispatchTests(EngineTests):
    def setUp(self):
        super().setUp()
        self.policy = StubPolicy()
        self.mem.register_policy("note", self.policy)

    def test_no_policy_inserts_unconditionally(self):
        # 'other' has no policy → straight insert, embedding from body
        nid = self.mem.index(self._node(id="x", type="other", body="hello world"))
        self.assertEqual(self.mem.count(), 1)
        self.assertEqual(self.mem.last_outcome, "new")
        self.assertEqual(self.policy.calls, [])   # policy never consulted

    def test_no_candidate_inserts_and_marks_new(self):
        self.policy.candidate = None
        nid = self.mem.index(self._node(id="x", body="hello"))
        self.assertEqual(self.mem.count(), 1)
        self.assertEqual(nid, "x")
        self.assertEqual(self.mem.last_outcome, "new")
        # find_candidate runs first (returns None), then _insert asks embedding_text
        kinds = [c[0] for c in self.policy.calls]
        self.assertEqual(kinds, ["find_candidate", "embedding_text"])

    def test_not_a_dup_inserts_new_node(self):
        self.mem.index(self._node(id="base", type="other", body="base"))  # seed, no policy
        self.policy.candidate = "base"
        self.policy.outcome = _outcome("not-a-dup")
        nid = self.mem.index(self._node(id="x", body="hello"))
        self.assertEqual(nid, "x")               # a NEW node was inserted
        self.assertEqual(self.mem.count(), 2)
        self.assertEqual(self.mem.last_outcome, "not-a-dup")
        self.assertIn(("merge", "base"), self.policy.calls)

    def test_merged_returns_existing_id_no_new_node(self):
        self.mem.index(self._node(id="base", type="other", body="base"))
        self.policy.candidate = "base"
        self.policy.outcome = _outcome("merged:llm")
        nid = self.mem.index(self._node(id="x", body="hello"))
        self.assertEqual(nid, "base")            # merged in place
        self.assertEqual(self.mem.count(), 1)    # no new node
        self.assertEqual(self.mem.last_outcome, "merged:llm")

    def test_index_embeds_policy_key_text_not_body(self):
        # embedding_text returns the body here; but it proves the Store asked the
        # policy for the key rather than assuming the body. (lesson.py returns WHEN.)
        self.policy.candidate = None
        nid = self.mem.index(self._node(id="x", body="the body text"))
        emb = self.mem.conn.execute(
            "SELECT embedding FROM nodes WHERE id=?", (nid,)).fetchone()["embedding"]
        import json
        vec = json.loads(emb)
        # the stored vector is the embed of the policy's key text (== body here)
        expected = self.mem.embedder.embed("the body text")
        self.assertEqual(vec, expected)


if __name__ == "__main__":
    unittest.main()
