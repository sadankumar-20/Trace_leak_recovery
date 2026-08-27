"""T5: tools are read-only and bounded; the AI errs; containment catches
every error before it can become financial truth."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.audit import AuditChain
from app.investigator import (
    HYPOTHESIS_TYPES, Hypothesis, investigate, report, validate,
)
from app.recon import reconcile
from app.tools import ToolError, ToolRegistry
from app.world import generate

NOW = datetime(2026, 7, 5, 12, 0)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        generate(seed=42, out_dir=cls.tmp.name)
        cls.world = json.loads(Path(cls.tmp.name, "world.json").read_text())
        cls.gt = json.loads(Path(cls.tmp.name,
                                 "ground_truth.json").read_text())["labels"]
        cls.split = json.loads(Path(cls.tmp.name, "split.json").read_text())
        cls.exceptions = reconcile(cls.tmp.name)["exceptions"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def pseudo_exc(self, txn_id, dtype):
        """Adversarial pseudo-exception over a BENIGN record: what a
        careless upstream might hand the investigator."""
        tx = next(t for t in self.world["gateway_txns"]
                  if t["id"] == txn_id)
        return {"exception_id": f"exc_adv_{txn_id}",
                "discrepancy_type": dtype, "order_id": tx["order_id"],
                "affected_records": {"gateway_txns": [txn_id]},
                "delta_paise": 0, "counterparty": "gateway",
                "claim_deadline": "2026-12-31T00:00:00"}


class TestTools(Base):
    def test_read_only_and_errors(self):
        reg = ToolRegistry(self.world)
        o = reg.get_order(self.world["orders"][0]["id"])
        o["amount_paise"] = 1                       # mutate the COPY
        self.assertNotEqual(self.world["orders"][0]["amount_paise"], 1)
        with self.assertRaises(ToolError):
            reg.get_order("ord_nope")
        with self.assertRaises(ToolError):
            reg.get_gateway_txn("")                 # invalid argument
        self.assertFalse(reg.trace[-1]["ok"])

    def test_budget_bounds_the_loop(self):
        reg = ToolRegistry(self.world, budget=3)
        oid = self.world["orders"][0]["id"]
        for _ in range(3):
            reg.get_order(oid)
        with self.assertRaises(ToolError) as cm:
            reg.get_order(oid)
        self.assertIn("budget", str(cm.exception))

    def test_knowledge_base_structured(self):
        docs = ToolRegistry(self.world).search_knowledge("fee_schedule")
        self.assertEqual(len(docs), 2)
        for d in docs:
            for k in ("document_id", "title", "category", "effective_from",
                      "relevant_rule", "source_reference", "confidence",
                      "matching_reason"):
                self.assertIn(k, d)


class TestRealExceptions(Base):
    def test_ai_correct_and_supported_on_real_leaks(self):
        chain = AuditChain()
        results = {}
        overstated_contained = 0
        for exc in self.exceptions:
            hyp = investigate(exc, self.world, chain, NOW)
            v = validate(hyp, self.world, self.split["sim_now"], chain, NOW)
            results.setdefault(v["result"], []).append(exc)
            if v["result"] == "SUPPORTED":
                continue
            # A real leak may still be CONTAINED — but ONLY when the naive
            # AI overstated the amount (e.g. international surcharge
            # ignored). Containment policing inflated claims on TRUE leaks
            # is the architecture working, never a silent pass-through.
            self.assertEqual(v["result"], "CONTAINED",
                             (exc["order_id"], v["checks"]))
            # naive AI may overstate the amount OR mistype entirely
            # (international orders): both must be contained, never
            # silently passed through
            overstated_contained += 1
        self.assertGreaterEqual(len(results.get("SUPPORTED", [])), 190)
        self.assertLessEqual(overstated_contained, 15)
        self.assertGreaterEqual(overstated_contained, 1)   # intl cases exist
        self.assertTrue(chain.verify(NOW)["valid"])
        r = report(self.exceptions[0],
                   investigate(self.exceptions[0], self.world,
                               AuditChain(), NOW),
                   {"result": "SUPPORTED", "checks": [],
                    "hypothesis_id": "h"})
        for k in ("appeared_to_be", "evidence_inspected", "tools_used",
                  "hypothesis", "validation", "verdict",
                  "ready_for_admissibility_gate"):
            self.assertIn(k, r)
        self.assertIn("UNVERIFIED", r["hypothesis"]["label"])

    def test_reproducible_traces(self):
        exc = self.exceptions[0]
        h1 = investigate(exc, self.world, AuditChain(), NOW)
        h2 = investigate(exc, self.world, AuditChain(), NOW)
        self.assertEqual(h1.tool_trace, h2.tool_trace)
        self.assertEqual((h1.hypothesis_type, h1.suspected_leak_paise),
                         (h2.hypothesis_type, h2.suspected_leak_paise))


class TestContainment(Base):
    def adversarial_cases(self):
        w = self.world
        gtx = w["gateway_txns"]
        refs = w["refunds"]
        rev_txn = next(r["gateway_txn_id"] for r in refs
                       if r["kind"] == "reversal")
        intl = next(t for t in gtx if t["order_id"] not in self.gt
                    and next(o for o in w["orders"]
                             if o["id"] == t["order_id"])["international"])
        lines = {l["gateway_txn_id"]: l for l in w["settlement_lines"]}
        tol_txn = next(t["id"] for t in gtx if t["order_id"] not in self.gt
                       and t["id"] in lines
                       and 0 < (t["amount_paise"] - t["fee_paise"]
                                - t["gst_paise"])
                       - lines[t["id"]]["net_paise"] <= 50)
        return [("valid_reversal_pair", rev_txn, "double_refund"),
                ("intl_surcharge_looks_like_overcharge", intl["id"],
                 "fee_overcharge"),
                ("in_tolerance_rounding", tol_txn, "rounding_drift")]

    def test_ai_errs_and_containment_catches_100pct(self):
        chain = AuditChain()
        metrics = {"adversarial": 0, "ai_wrong": 0, "contained": 0,
                   "unsupported_claims_passed": 0}
        for name, txn_id, dtype in self.adversarial_cases():
            exc = self.pseudo_exc(txn_id, dtype)
            hyp = investigate(exc, self.world, chain, NOW)
            v = validate(hyp, self.world, self.split["sim_now"], chain, NOW)
            metrics["adversarial"] += 1
            wrong = hyp.hypothesis_type != "legitimate_difference"
            if wrong:
                metrics["ai_wrong"] += 1
                if v["result"] == "CONTAINED":
                    metrics["contained"] += 1
                elif v["result"] == "SUPPORTED":
                    metrics["unsupported_claims_passed"] += 1
            self.assertNotEqual(v["result"], "SUPPORTED", name)
        self.assertGreaterEqual(metrics["ai_wrong"], 3)     # naive by design
        self.assertEqual(metrics["contained"], metrics["ai_wrong"])
        self.assertEqual(metrics["unsupported_claims_passed"], 0)
        self.assertTrue(chain.verify(NOW)["valid"])

    def test_fabricated_evidence_is_contained(self):
        exc = self.exceptions[0]
        hyp = investigate(exc, self.world, AuditChain(), NOW)
        hyp.supporting_evidence.append("gtx_FABRICATED")
        v = validate(hyp, self.world, self.split["sim_now"],
                     AuditChain(), NOW)
        self.assertEqual(v["result"], "CONTAINED")
        self.assertIn("gtx_FABRICATED", v["fabricated_evidence"])

    def test_malformed_hypothesis_type_rejected(self):
        self.assertNotIn("creative_theory", HYPOTHESIS_TYPES)
        exc = self.exceptions[0]
        hyp = investigate(exc, self.world, AuditChain(), NOW)
        # tampering with the type after the fact must not validate as truth
        hyp.hypothesis_type = "legitimate_difference"
        v = validate(hyp, self.world, self.split["sim_now"],
                     AuditChain(), NOW)
        self.assertEqual(v["result"], "CONTAINED")   # truth says leak
