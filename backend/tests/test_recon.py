"""T2: the matcher earns perfect precision on a world built to trick it."""
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from app.recon import (
    AMBIGUOUS, EXCEPTION, MATCHED, MATCHED_WITH_TOLERANCE,
    ReconciliationEngine, reconcile,
)
from app.world import generate


class TestRecon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        generate(seed=42, out_dir=cls.tmp.name)
        cls.gt = json.loads(Path(cls.tmp.name,
                                 "ground_truth.json").read_text())["labels"]
        out = reconcile(cls.tmp.name)
        cls.results, cls.exceptions = out["results"], out["exceptions"]
        cls.states = out["states"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def by_type(self, t):
        return {e["order_id"] for e in self.exceptions
                if e["discrepancy_type"] == t}

    def gt_type(self, t):
        return {o for o, g in self.gt.items() if g["leak_type"] == t}

    def test_exact_detection_per_leak_type(self):
        """Recall AND precision 1.0 per type — the set matches ground truth
        exactly; every benign trap (valid reversals, in-tolerance rounding,
        T+3 postings) stays silent."""
        for t in ("fee_overcharge", "missing_settlement", "double_refund",
                  "refund_marked_success_not_settled",
                  "partial_capture_mismatch", "duplicate_capture",
                  "rounding_drift"):
            self.assertEqual(self.by_type(t), self.gt_type(t), t)

    def test_no_exception_outside_ground_truth(self):
        flagged = {e["order_id"] for e in self.exceptions}
        self.assertEqual(flagged, set(self.gt))
        self.assertGreater(self.states.get(MATCHED, 0), 4000)
        self.assertGreater(self.states.get(MATCHED_WITH_TOLERANCE, 0), 50)

    def test_deltas_recompute_to_ground_truth_paise(self):
        for e in self.exceptions:
            g = self.gt[e["order_id"]]
            if g["true_leak_paise"] is None or g["leak_type"] == \
                    "refund_marked_success_not_settled":
                continue
            if g["leak_type"] == "double_refund":
                self.assertEqual(e["actual_paise"] - e["expected_paise"],
                                 g["true_leak_paise"], e["order_id"])
            elif g["leak_type"] in ("fee_overcharge", "duplicate_capture"):
                self.assertEqual(abs(e["delta_paise"]),
                                 g["true_leak_paise"], e["order_id"])
            else:
                self.assertEqual(e["delta_paise"], g["true_leak_paise"],
                                 e["order_id"])

    def test_discrepancy_object_schema_and_evidence_hashes(self):
        e = self.exceptions[0]
        for k in ("exception_id", "discrepancy_type", "expected_paise",
                  "actual_paise", "delta_paise", "rule_violated",
                  "affected_records", "evidence_hashes",
                  "deterministic_confidence", "counterparty",
                  "claim_deadline", "created_at", "discrepancy_hash"):
            self.assertIn(k, e)
        self.assertTrue(all(len(h) == 64
                            for h in e["evidence_hashes"].values()))

    def test_deterministic_double_run(self):
        again = reconcile(self.tmp.name)
        self.assertEqual(self.exceptions, again["exceptions"])

    def test_ambiguous_state_on_unequal_refund_pair(self):
        world = json.loads(Path(self.tmp.name, "world.json").read_text())
        clean = next(t for t in world["gateway_txns"]
                     if t["order_id"] not in self.gt
                     and not any(r["gateway_txn_id"] == t["id"]
                                 for r in world["refunds"]))
        for suf, amt in (("x", 5000), ("y", 7000)):
            world["refunds"].append({
                "id": f"ref_amb_{suf}", "order_id": clean["order_id"],
                "gateway_txn_id": clean["id"], "amount_paise": amt,
                "created_at": clean["created_at"], "status": "processed",
                "kind": "refund", "record_hash": "0" * 64})
        split = json.loads(Path(self.tmp.name, "split.json").read_text())
        res = ReconciliationEngine(world, split["sim_now"]).run()
        r = next(x for x in res if x.txn_id == clean["id"])
        self.assertEqual(r.state, AMBIGUOUS)
