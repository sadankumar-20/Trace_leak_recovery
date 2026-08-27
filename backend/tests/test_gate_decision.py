"""T6: no single positive signal files a claim; economics can say no."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import gate as G
from app.audit import AuditChain
from app.decision import PROFILES, decide
from app.investigator import investigate, validate
from app.recon import reconcile
from app.world import generate

NOW = datetime(2026, 7, 5, 12, 0)
SUP = {"result": "SUPPORTED", "checks": []}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        generate(seed=42, out_dir=cls.tmp.name)
        cls.world = json.loads(Path(cls.tmp.name, "world.json").read_text())
        cls.split = json.loads(Path(cls.tmp.name, "split.json").read_text())
        cls.now = cls.split["sim_now"]
        cls.exceptions = reconcile(cls.tmp.name)["exceptions"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def exc_of(self, dtype, min_amt=0, max_amt=10**9):
        return next(e for e in self.exceptions
                    if e["discrepancy_type"] == dtype
                    and min_amt <= abs(e["delta_paise"]) <= max_amt
                    and e["claim_deadline"] > self.now)

    @classmethod
    def happy_gateway_exc(cls):
        """Find a fully-admissible gateway-party exception by asking the
        system itself — no guessed amount bounds."""
        if not hasattr(cls, "_happy"):
            from app.decision import counterparty_name, _admissible_amount
            cls._happy = None
            for e in cls.exceptions:
                if e["counterparty"] != "gateway":
                    continue
                cp = counterparty_name(e, cls.world)
                r = G.evaluate(e, SUP,
                               _admissible_amount(e, cls.world, cls.now),
                               "FILE_GATEWAY_CLAIM", cls.world, cls.now,
                               PROFILES[cp])
                if not r["failed_gates"] and not r["required_approval"]:
                    cls._happy = e
                    break
            assert cls._happy is not None, "no admissible gateway case"
        return cls._happy

    def run_gate(self, exc, amount=None, action=None, sim_now=None,
                 world=None):
        from app.decision import counterparty_name, _admissible_amount
        w = world or self.world
        cp = counterparty_name(exc, w)
        return G.evaluate(
            exc, SUP,
            proposed_amount=amount if amount is not None
            else _admissible_amount(exc, w, sim_now or self.now),
            proposed_action=action or G.ACTION_FOR_PARTY[exc["counterparty"]],
            world=w, sim_now=sim_now or self.now, profile=PROFILES[cp])


class TestGates(Base):
    def test_happy_path_all_gates_pass(self):
        exc = self.happy_gateway_exc()
        r = self.run_gate(exc)
        self.assertEqual(r["failed_gates"], [], r["reason"])
        self.assertTrue(r["final_admissibility"])
        self.assertEqual(set(r["gate_results"]), set(G.GATES))

    def test_inflated_amount_blocked_by_gate6(self):
        exc = self.exc_of("fee_overcharge", min_amt=8_000)
        r = self.run_gate(exc, amount=abs(exc["delta_paise"]) * 2)
        self.assertIn("amount_integrity", r["failed_gates"])
        self.assertFalse(r["final_admissibility"])
        r2 = self.run_gate(exc, amount=-5)
        self.assertIn("amount_integrity", r2["failed_gates"])

    def test_wrong_counterparty_blocked_by_gate5(self):
        exc = self.exc_of("fee_overcharge", min_amt=8_000)
        r = self.run_gate(exc, action="FILE_BANK_TRACE")
        self.assertIn("recoverability", r["failed_gates"])

    def test_expired_window_blocked_by_gate4(self):
        exc = self.exceptions[0]
        r = self.run_gate(exc, sim_now="2027-06-01T00:00:00")
        self.assertIn("eligibility", r["failed_gates"])
        self.assertIn("EXPIRED", r["gate_reasons"]["eligibility"])

    def test_tampered_hash_blocked_by_gate1(self):
        exc = self.exc_of("fee_overcharge", min_amt=8_000)
        w = copy.deepcopy(self.world)
        tid = exc["affected_records"]["gateway_txns"][0]
        row = next(t for t in w["gateway_txns"] if t["id"] == tid)
        row["fee_paise"] += 1                   # mutate without re-hashing
        r = self.run_gate(exc, world=w)
        self.assertIn("data_integrity", r["failed_gates"])
        self.assertIn("hash invalid", r["reason"])

    def test_fake_exception_blocked_by_gate2(self):
        exc = dict(self.exc_of("fee_overcharge", min_amt=8_000))
        exc["exception_id"] = "exc_fabricated_claim"
        r = self.run_gate(exc, amount=999)
        self.assertIn("reconciliation_proof", r["failed_gates"])

    def test_tiny_leak_fails_gate7_only(self):
        exc = self.exc_of("rounding_drift", max_amt=400)
        r = self.run_gate(exc)
        self.assertEqual(r["failed_gates"], ["economic_viability"])
        self.assertIn("not worth pursuing",
                      r["gate_reasons"]["economic_viability"])

    def test_big_amount_requires_approval_gate8(self):
        exc = self.exc_of("missing_settlement",
                          min_amt=G.APPROVAL_THRESHOLD_PAISE)
        r = self.run_gate(exc)
        self.assertEqual(r["gate_results"]["risk"], "REQUIRES_APPROVAL")
        self.assertTrue(r["required_approval"])


class TestDecisions(Base):
    def test_writeoff_stopping_rule(self):
        exc = self.exc_of("rounding_drift", max_amt=400)
        d = decide(exc, SUP, self.world, self.now)
        self.assertEqual(d["selected_action"], "WRITE_OFF")
        self.assertIn("below the cost-to-recover threshold", d["reason"])

    def test_bank_trace_selected_for_missing_settlement(self):
        exc = self.exc_of("missing_settlement", min_amt=10_000,
                          max_amt=G.APPROVAL_THRESHOLD_PAISE - 1)
        d = decide(exc, SUP, self.world, self.now)
        self.assertEqual(d["selected_action"], "FILE_BANK_TRACE")
        self.assertIn("action_package", d)
        pkg = d["action_package"]
        self.assertEqual(pkg["idempotency_key"], exc["exception_id"])
        self.assertEqual(pkg["claim_amount_paise"],
                         abs(exc["delta_paise"]))
        self.assertIn("FILE_GATEWAY_CLAIM", d["rejected_actions"])
        self.assertIn("does not owe", d["rejected_actions"]
                      ["FILE_GATEWAY_CLAIM"])

    def test_gateway_claim_for_fee_overcharge_with_why_nots(self):
        exc = self.happy_gateway_exc()
        d = decide(exc, SUP, self.world, self.now)
        self.assertEqual(d["selected_action"], "FILE_GATEWAY_CLAIM")
        self.assertIn("WRITE_OFF", d["rejected_actions"])
        self.assertIn("exceeds the threshold",
                      d["rejected_actions"]["WRITE_OFF"])

    def test_unsupported_verdict_means_no_action(self):
        exc = self.exceptions[0]
        d = decide(exc, {"result": "CONTAINED", "checks": []},
                   self.world, self.now)
        self.assertEqual(d["selected_action"], "NO_ACTION")
        self.assertNotIn("action_package", d)

    def test_expired_case_escalates_never_files(self):
        exc = self.exceptions[0]
        d = decide(exc, SUP, self.world, "2027-06-01T00:00:00")
        self.assertEqual(d["selected_action"], "ESCALATE")
        self.assertIn("EXPIRED", d["reason"])
        self.assertNotIn("action_package", d)

    def test_approval_amounts_escalate(self):
        exc = self.exc_of("missing_settlement",
                          min_amt=G.APPROVAL_THRESHOLD_PAISE)
        d = decide(exc, SUP, self.world, self.now)
        self.assertEqual(d["selected_action"], "ESCALATE")
        self.assertIn("approval", d["reason"])

    def test_decisions_deterministic_and_packages_immutable(self):
        exc = self.happy_gateway_exc()
        d1 = decide(exc, SUP, self.world, self.now)
        d2 = decide(exc, SUP, self.world, self.now)
        self.assertEqual(d1, d2)
        self.assertEqual(d1["action_package"]["package_hash"],
                         d2["action_package"]["package_hash"])

    def test_portfolio_run_no_unauthorized_actions(self):
        """Full pipeline over every exception: a claim package exists ONLY
        when the verdict is SUPPORTED and all gates pass."""
        chain = AuditChain()
        stats = {"packages": 0, "write_off": 0, "escalate": 0,
                 "no_action": 0, "blocked_inadmissible": 0}
        for exc in self.exceptions:
            hyp = investigate(exc, self.world, chain, NOW)
            v = validate(hyp, self.world, self.now, chain, NOW)
            d = decide(exc, v, self.world, self.now)
            a = d["selected_action"]
            if "action_package" in d:
                stats["packages"] += 1
                self.assertEqual(v["result"], "SUPPORTED")
                self.assertEqual(d["admissibility"]["failed_gates"], [])
            elif a == "WRITE_OFF":
                stats["write_off"] += 1
            elif a == "ESCALATE":
                stats["escalate"] += 1
            else:
                stats["no_action"] += 1
        self.assertGreater(stats["packages"], 15)
        self.assertGreater(stats["write_off"], 50)     # stopping rule real
        self.assertGreater(stats["escalate"], 80)      # approvals real
        self.assertGreater(stats["no_action"], 15)     # containment real
        self.assertTrue(chain.verify(NOW)["valid"])
