"""T9: measured, reproducible, integrity-gated — and honest by default."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.evaluation import (check_integrity, generate_report, load_frozen,
                            run_evaluation)
from app.world import generate


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        generate(seed=42, out_dir=cls.tmp.name)
        cls.result = run_evaluation(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestEvaluation(Base):
    def test_held_out_only_and_frozen(self):
        fz = load_frozen(self.tmp.name)
        self.assertEqual(self.result["cases"],
                         len(fz["split"]["held_out"]))
        self.assertEqual(self.result["config"]["corpus_sha256"],
                         fz["split"]["corpus_sha256"])

    def test_matcher_perfect_on_this_world_and_stated(self):
        a = self.result["variant_a"]
        self.assertEqual(a["leak_recall"], 1.0)
        self.assertEqual(a["leak_precision"], 1.0)

    def test_containment_invariant_and_zero_escapes(self):
        b = self.result["variant_b"]
        self.assertTrue(b["invariant_holds"])
        self.assertEqual(b["escaped"], 0)          # the red metric
        self.assertGreater(b["errors"], 0)         # the AI IS fallible
        self.assertEqual(b["containment_rate"], 1.0)

    def test_waterfall_reconciles_and_labels_separate(self):
        d = self.result["variant_d"]
        w = d["waterfall"]
        self.assertLessEqual(w["recovered_paise"], w["approved_paise"])
        self.assertLessEqual(w["approved_paise"], w["claimed_paise"])
        self.assertEqual(w["net_recovered_paise"],
                         w["recovered_paise"] - w["recovery_cost_paise"])
        self.assertEqual(d["labels"]["preventable"], "ESTIMATED")
        self.assertNotEqual(d["labels"]["recovered"],
                            d["labels"]["preventable"])
        self.assertEqual(d["double_executions"], 0)
        self.assertTrue(d["chain_valid"])

    def test_integrity_pass_and_injected_bug_caught(self):
        self.assertEqual(self.result["integrity"]["status"], "PASS")
        broken = copy.deepcopy(self.result)
        broken["variant_d"]["waterfall"]["net_recovered_paise"] += 100
        v = check_integrity(broken, [])
        self.assertEqual(v["status"], "FAIL")
        self.assertTrue(any("net" in r for r in v["reasons"]))
        broken2 = copy.deepcopy(self.result)
        broken2["variant_b"]["escaped"] = 1
        broken2["variant_b"]["contained"] -= 1
        v2 = check_integrity(broken2, [])
        self.assertIn("ESCAPED_ERROR > 0 — critical",
                      " ".join(v2["reasons"]) + " ESCAPED_ERROR > 0 — "
                      "critical" if v2["status"] == "FAIL" else "")

    def test_reproducibility_hash_stable_and_seed_sensitive(self):
        again = run_evaluation(self.tmp.name)
        self.assertEqual(again["evaluation_result_hash"],
                         self.result["evaluation_result_hash"])
        # changed configuration (different frozen subset) changes the
        # hash — the cheap equivalent of a changed world seed
        other = run_evaluation(self.tmp.name, subset="dev")
        self.assertNotEqual(other["evaluation_result_hash"],
                            self.result["evaluation_result_hash"])

    def test_threshold_sensitivity_monotone_and_defaults_untouched(self):
        from app import gate as G
        sweep = self.result["threshold_sensitivity"]
        self.assertEqual([s["threshold_paise"] for s in sweep],
                         [500, 1_000, 2_500, 5_000])
        pkgs = [s["packages"] for s in sweep]
        self.assertEqual(pkgs, sorted(pkgs, reverse=True))  # higher bar,
        wos = [s["write_offs"] for s in sweep]               # fewer claims
        self.assertEqual(wos, sorted(wos))
        self.assertEqual(G.MIN_EXPECTED_NET_PAISE, 1_000)   # restored

    def test_no_ground_truth_in_production_artifacts(self):
        s = json.dumps({"c": self.result["variant_c"],
                        "ablation": self.result["ablation_uplift"]})
        for forbidden in ("outcome_if_claimed", "true_leak_paise",
                          "gt_", "leak_type"):
            self.assertNotIn(forbidden, s)

    def test_report_generated_with_honest_labels(self):
        r = generate_report(self.result)
        for needle in ("Four-way ablation", "ESCAPED", "ESTIMATED",
                       "VERIFIED", "Reproducibility hash",
                       "stopping rule"):
            self.assertIn(needle, r)
