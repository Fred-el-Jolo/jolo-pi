#!/usr/bin/env python3
"""Engine unit tests — stdlib only, no deps.  Run: python3 test_engine.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from engine import HashEmbedder, Memory  # noqa: E402


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.mem = Memory(":memory:", embedder=HashEmbedder(), current_project="proj-a")

    def _node(self, **kw):
        base = dict(type="recap", project="proj-a", body="", meta={})
        base.update(kw)
        return base

    def test_recall_most_similar_first(self):
        self.mem.index(self._node(id="a", body="postgres connection pool timeout"))
        self.mem.index(self._node(id="b", body="jwt token refresh race auth"))
        self.mem.index(self._node(id="c", body="cors preflight browser origin"))
        res = self.mem.recall("postgres connection timeout", k=2)
        self.assertEqual(res[0]["id"], "a")

    def test_recap_dedup_on_write(self):
        # recap dedup is on the initial-PROMPT vector; with no prompt in meta
        # it falls back to the body, so re-indexing near-identical bodies merges
        first = self.mem.index(self._node(body="migrate rest api from express to fastify"))
        self.assertEqual(self.mem.count(), 1)
        again = self.mem.index(self._node(body="migrate rest api from express to fastify"))
        self.assertEqual(first, again)
        self.assertEqual(self.mem.count(), 1)
        # unrelated body → new node
        self.mem.index(self._node(body="something totally unrelated xyzzy"))
        self.assertEqual(self.mem.count(), 2)

    def test_recap_dedup_on_prompt_across_statuses(self):
        # same initial prompt, DIFFERENT summaries + statuses → merge on prompt,
        # regardless of status. The higher-status summary survives.
        a = self.mem.index(self._node(
            body="migration failed: rpi-clone not installed",
            meta={"status": "failed",
                  "initial_prompt": "migrate sd card to external usb hard drive"}))
        b = self.mem.index(self._node(
            body="migration partial: cloned via rpi-clone, smartd alerts pending",
            meta={"status": "partial",
                  "initial_prompt": "migrate sd card to external usb hard drive"}))
        self.assertEqual(a, b)            # merged onto the same node
        self.assertEqual(self.mem.count(), 1)
        # the partial (higher rank) body won
        stored = self.mem.conn.execute(
            "SELECT body FROM nodes WHERE id=?", (a,)).fetchone()["body"]
        self.assertIn("cloned via rpi-clone", stored)

    def test_recap_promotion_not_downgrade(self):
        # a later LOWER-status recap on the same prompt must NOT clobber a done one
        done = self.mem.index(self._node(
            body="deployed to github pages via bun, verified",
            meta={"status": "done",
                  "initial_prompt": "deploy this repo to github pages"}))
        self.mem.index(self._node(
            body="deploy failed: bun missing",
            meta={"status": "failed",
                  "initial_prompt": "deploy this repo to github pages"}))
        self.assertEqual(self.mem.count(), 1)
        stored = self.mem.conn.execute(
            "SELECT body FROM nodes WHERE id=?", (done,)).fetchone()["body"]
        self.assertIn("verified", stored)  # done body kept, not overwritten

    def test_scope_local_vs_global(self):
        self.mem.index(self._node(id="a", project="proj-a", body="postgres pool timeout"))
        self.mem.index(self._node(id="b", project="proj-b", body="postgres pool timeout"))
        glob = {r["id"] for r in self.mem.recall("postgres pool timeout", k=5, scope="global")}
        local = {r["id"] for r in self.mem.recall("postgres pool timeout", k=5, scope="local")}
        self.assertEqual(glob, {"a", "b"})
        self.assertEqual(local, {"a"})

    def test_link_sets_provenance(self):
        root = self.mem.index(self._node(id="root", body="build the invoicing feature"))
        self.mem.index(dict(type="spec", id="spec1", project="proj-a",
                            body="generate monthly pdf invoice", meta={}))
        self.mem.link("spec1", root)
        hit = next(r for r in self.mem.recall("invoice", k=5) if r["id"] == "spec1")
        self.assertEqual(hit["root_prompt_id"], root)

    def test_cosine_rejects_dim_mismatch(self):
        # switching embedders mid-DB must NOT silently truncate
        with self.assertRaises(ValueError):
            self.mem._cosine([1.0] * 3, [1.0] * 4)
        # equal lengths still work
        self.assertAlmostEqual(self.mem._cosine([1.0, 0.0], [1.0, 0.0]), 1.0)

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

    def test_recall_redacts_query_to_match_redacted_body(self):
        # query + stored body both scrubbed to the same placeholder space, so a
        # secret-bearing query still recalls the secret-bearing original.
        self.mem.index(self._node(
            body="db url postgres://app:FAKE_DB_PASSWORD@host/db conn string"))
        hits = self.mem.recall("postgres://app:FAKE_DB_PASSWORD@host/db", k=3)
        self.assertTrue(hits, "expected a hit with redacted query+body")
        self.assertNotIn("FAKE_DB_PASSWORD", hits[0]["body"])

    def test_history_returns_linked_children(self):
        root = self.mem.index(self._node(id="r", body="build feature X"))
        self.mem.index(dict(type="spec", id="s1", project="proj-a",
                            body="the spec for feature X", meta={},
                            root_prompt_id=root))
        ids = [n["id"] for n in self.mem.history(root)]
        self.assertIn(root, ids)
        self.assertIn("s1", ids)


if __name__ == "__main__":
    unittest.main()
