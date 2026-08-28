"""T8: patterns must survive deterministic challenges; prevention is
labeled ESTIMATED; hidden ground truth never enters production logic."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.audit import AuditChain
from app.counterparty import CounterpartySim
from app.decision import decide
from app.executor import Executor
from app.portfolio import (MIN_MEMBERS, ai_pattern_hypothesis,
                           build_clusters, kpis)
from app.recon import reconcile
from app.world import generate

SUP = {"result": "SUPPORTED", "checks": []}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        generate(seed=42, out_dir=cls.tmp.name)
        cls.world = json.loads(Path(cls.tmp.name, "world.json").read_text())
        cls.gt = json.loads(Path(cls.tmp.name,
                                 "ground_truth.json").read_text())["labels"]
        cls.now = json.loads(Path(cls.tmp.name,
                                  "split.json").read_text())["sim_now"]
        cls.exceptions = reconcile(cls.tmp.name)["exceptions"]
        cp = CounterpartySim(cls.world, cls.gt, cls.now)
        ex = Executor(cls.world, cls.now, cp, AuditChain())
        for e in cls.exceptions:
            d = decide(e, SUP, cls.world, cls.now)
            if "action_package" in d:
                ex.execute(d["action_package"],
                           approval=d["action_package"]
                           .get("required_approval", False))
        cls.recoveries = ex.recoveries
        cls.clusters = build_clusters(cls.exceptions, cls.world, cls.now,
                                      cls.recoveries)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cluster(self, cid):
        return next(c for c in self.clusters if c["cluster_id"] == cid)


class TestClustering(Base):
    def test_real_systemic_clusters_confirmed(self):
        confirmed = {c["cluster_id"] for c in self.clusters
                     if c["status"] == "CONFIRMED"}
        for cid in ("cl_fee_overcharge_GatewayA",
                    "cl_fee_overcharge_GatewayB",
                    "cl_missing_settlement_GatewayA",
                    "cl_double_refund_GatewayA",
                    "cl_rounding_drift_GatewayA"):
            self.assertIn(cid, confirmed)

    def test_membership_matches_ground_truth_eval_only(self):
        # gt used ONLY here, in evaluation — never inside build_clusters
        for c in self.clusters:
            if c["status"] != "CONFIRMED":
                continue
            for eid in c["affected_exception_ids"]:
                oid = next(e["order_id"] for e in self.exceptions
                           if e["exception_id"] == eid)
                self.assertEqual(self.gt[oid]["leak_type"],
                                 c["cluster_type"], eid)

    def test_no_hidden_ground_truth_in_cluster_objects(self):
        s = json.dumps(self.clusters)
        for forbidden in ("outcome_if_claimed", "gt_", "true_leak_paise",
                          "rejection_reason"):
            self.assertNotIn(forbidden, s)

    def test_ai_overcount_is_corrected_deterministically(self):
        c = self.cluster("cl_fee_overcharge_GatewayA")
        hyp = c["ai_hypothesis"]
        self.assertIn("UNVERIFIED", hyp["label"])
        self.assertNotEqual(hyp["claimed_affected_count"],
                            c["affected_transaction_count"])
        self.assertTrue(c["ai_claimed_count_corrected"])
        self.assertEqual(c["affected_transaction_count"],
                         len(c["affected_exception_ids"]))

    def test_false_pattern_valid_reversals_rejected(self):
        # craft pseudo-exceptions from BENIGN reversal pairs: an apparent
        # "refund synchronization bug" that is legitimate
        refs = {}
        for r in self.world["refunds"]:
            refs.setdefault(r["gateway_txn_id"], []).append(r)
        pseudo = []
        for t in self.world["gateway_txns"]:
            rs = refs.get(t["id"], [])
            if any(r["kind"] == "reversal" for r in rs):
                pseudo.append({"exception_id": f"exc_adv_{t['id']}",
                               "discrepancy_type": "double_refund",
                               "order_id": t["order_id"],
                               "affected_records":
                                   {"gateway_txns": [t["id"]]},
                               "delta_paise": rs[0]["amount_paise"],
                               "created_at": t["created_at"]})
            if len(pseudo) >= MIN_MEMBERS + 2:
                break
        cs = build_clusters(pseudo, self.world, self.now)
        self.assertTrue(cs)
        self.assertEqual(cs[0]["status"], "FALSE_PATTERN")
        # either deterministic kill is valid: the recompute-count
        # challenge fires first (0 members recompute), the refund-kind
        # challenge would catch it second
        reason = cs[0]["validation_reason"]
        self.assertTrue("reversal" in reason or "recompute" in reason,
                        reason)

    def test_false_pattern_intl_surcharge_not_pricing_drift(self):
        pseudo = []
        for t in self.world["gateway_txns"]:
            o = next(x for x in self.world["orders"]
                     if x["id"] == t["order_id"])
            if o["international"] and t["order_id"] not in self.gt:
                pseudo.append({"exception_id": f"exc_adv_{t['id']}",
                               "discrepancy_type": "fee_overcharge",
                               "order_id": t["order_id"],
                               "affected_records":
                                   {"gateway_txns": [t["id"]]},
                               "delta_paise": 500,
                               "created_at": t["created_at"]})
            if len(pseudo) >= MIN_MEMBERS + 3:
                break
        cs = build_clusters(pseudo, self.world, self.now)
        for c in cs:
            self.assertEqual(c["status"], "FALSE_PATTERN", c)

    def test_reproducible(self):
        again = build_clusters(self.exceptions, self.world, self.now,
                               self.recoveries)
        self.assertEqual(json.dumps(self.clusters, sort_keys=True),
                         json.dumps(again, sort_keys=True))


class TestPrevention(Base):
    def test_prevention_labeled_estimated_with_assumptions(self):
        c = self.cluster("cl_fee_overcharge_GatewayA")
        p = c["prevention"]
        self.assertEqual(p["label"], "ESTIMATED PREVENTABLE LOSS")
        for k in ("observed_weekly_leak_paise", "horizon_weeks",
                  "mitigation_effectiveness", "implementation_cost_paise"):
            self.assertIn(k, p["assumptions"])
        a = p["assumptions"]
        self.assertEqual(p["estimated_preventable_paise"],
                         round(a["observed_weekly_leak_paise"]
                               * a["horizon_weeks"]
                               * a["mitigation_effectiveness"]))
        self.assertEqual(p["expected_net_prevention_paise"],
                         p["estimated_preventable_paise"]
                         - a["implementation_cost_paise"])
        self.assertIn(p["priority"],
                      ("CRITICAL", "HIGH", "MEDIUM", "LOW"))

    def test_actual_and_estimated_never_merged(self):
        k = kpis(self.clusters, self.recoveries)
        self.assertEqual(k["labels"]["recovered"], "ACTUAL")
        self.assertEqual(k["labels"]["preventable"], "ESTIMATED")
        self.assertGreater(k["active_root_causes"], 3)
        self.assertNotIn("combined", json.dumps(k))

    def test_consolidated_recovery_is_candidate_not_execution(self):
        c = self.cluster("cl_fee_overcharge_GatewayA")
        cr = c["consolidated_recovery"]
        self.assertEqual(cr["total_recoverable_paise"],
                         c["gross_leakage_paise"])
        self.assertEqual(cr["claim_count_reduction"],
                         c["affected_transaction_count"] - 1)
        self.assertTrue(cr["required_approval"])
        self.assertNotIn("package_hash", json.dumps(cr))   # no package
        self.assertIn("T6", cr["note"])

    def test_trend_and_bundle(self):
        for c in self.clusters:
            self.assertIn(c["trend"], ("NEW", "GROWING", "STABLE",
                                       "DECLINING"))
            self.assertEqual(len(c["evidence_bundle_hash"]), 64)
