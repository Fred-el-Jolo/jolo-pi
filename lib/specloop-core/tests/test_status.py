#!/usr/bin/env python3
"""status.py unit tests — pure taxonomy, no DB/model.  Run: python3 test_status.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import status  # noqa: E402


class StatusTests(unittest.TestCase):
    # -- initial_lesson_status ------------------------------------------------
    def test_initial_is_always_tentative(self):
        # evidence-only confirmation: even a "done" session starts tentative;
        # promotion happens when ≥2 distinct sessions re-learn the lesson
        for s in ("done", "partial", "failed", "void", "nonsense"):
            self.assertEqual(status.initial_lesson_status(s), "tentative")

    def test_initial_unknown_defaults_tentative(self):
        # void never reaches here in the flow, but the function stays defensive
        self.assertEqual(status.initial_lesson_status("void"), "tentative")
        self.assertEqual(status.initial_lesson_status("nonsense"), "tentative")

    # -- promote --------------------------------------------------------------
    def test_promote_tentative_at_threshold(self):
        # CONFIRM_TO_CONFIRMED == 2: at exactly 2 distinct sessions it promotes
        self.assertEqual(status.promote("tentative", 2), "confirmed")
        self.assertEqual(status.promote("tentative", 3), "confirmed")
        # below threshold stays tentative
        self.assertEqual(status.promote("tentative", 1), "tentative")
        self.assertEqual(status.promote("tentative", 0), "tentative")

    def test_promote_tentative_by_distinct_days(self):
        # the resumed-session escape hatch: same session, re-learned on
        # CONFIRM_DAYS (3) distinct calendar days ⇒ confirmed
        self.assertEqual(status.promote("tentative", 1, 3), "confirmed")
        self.assertEqual(status.promote("tentative", 0, 4), "confirmed")
        # fewer days (and only one session) is not enough
        self.assertEqual(status.promote("tentative", 1, 2), "tentative")
        self.assertEqual(status.promote("tentative", 1, 0), "tentative")
        # days never downgrade a 2-session confirmation
        self.assertEqual(status.promote("tentative", 2, 0), "confirmed")

    def test_promote_confirmed_stays_confirmed(self):
        self.assertEqual(status.promote("confirmed", 5), "confirmed")
        self.assertEqual(status.promote("confirmed", 0), "confirmed")

    def test_promote_contested_untouched(self):
        # a contested merge is not silently cleared by re-confirmation
        self.assertEqual(status.promote("contested", 10), "contested")

    def test_void_never_promotes(self):
        # void never reaches promote (no nodes), but if it did it wouldn't confirm
        self.assertNotEqual(status.promote("void", 99), "confirmed")

    # -- merged_status table --------------------------------------------------
    def test_merged_all_confirmed(self):
        self.assertEqual(status.merged_status(["confirmed", "confirmed"]), "confirmed")
        self.assertEqual(status.merged_status(["confirmed"]), "confirmed")

    def test_merged_mixed_no_contradiction(self):
        self.assertEqual(status.merged_status(["confirmed", "tentative"]), "tentative")
        self.assertEqual(status.merged_status(["tentative", "tentative"]), "tentative")
        self.assertEqual(status.merged_status(["tentative"]), "tentative")

    def test_merged_contested_is_not_produced_here(self):
        # contested comes from the merger (merge_thens), not this pure rule
        self.assertEqual(status.merged_status(["contested", "confirmed"]), "tentative")
        self.assertNotEqual(status.merged_status(["contested"]), "contested")

    # -- authority_rank ordering ---------------------------------------------
    def test_authority_rank_status_beats_count_beats_recency(self):
        # confirmed outranks tentative regardless of count/recency
        a = status.authority_rank("confirmed", 1, 1.0)
        b = status.authority_rank("tentative", 99, 99.0)
        self.assertGreater(a, b)

    def test_authority_rank_count_breaks_status_tie(self):
        t0 = 1.0
        a = status.authority_rank("tentative", 3, t0)
        b = status.authority_rank("tentative", 1, t0)
        self.assertGreater(a, b)  # more confirmations wins

    def test_authority_rank_recency_breaks_count_tie(self):
        # equal rank+count → newer (larger created) ranks higher
        older = status.authority_rank("tentative", 2, 100.0)
        newer = status.authority_rank("tentative", 2, 200.0)
        self.assertGreater(newer, older)
        # max() picks the newest on a full tie except recency
        winner = max([older, newer])
        self.assertEqual(winner, newer)

    def test_authority_rank_max_picks_highest(self):
        items = [
            ("A", status.authority_rank("contested", 1, 50.0)),
            ("B", status.authority_rank("confirmed", 5, 10.0)),
            ("C", status.authority_rank("tentative", 2, 999.0)),
        ]
        name = max(items, key=lambda t: t[1])[0]
        self.assertEqual(name, "B")  # confirmed beats the others outright


if __name__ == "__main__":
    unittest.main()
