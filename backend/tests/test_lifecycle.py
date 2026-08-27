"""T3: time rules — legal paths, illegal moves, WAIT, SLA clocks."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.lifecycle import (
    CLAIMABLE, LATE, SETTLEMENT_PENDING, TRACE_REQUIRED,
    WITHIN_EXPECTED_WINDOW, Case, IllegalTransition, case_from_discrepancy,
    portfolio_sla, temporal_state,
)
from app.recon import reconcile
from app.world import generate

NOW = datetime(2026, 7, 5, 12, 0)


def mkcase(deadline_days=30, state="OPEN") -> Case:
    c = Case("case_x", "exc_x", "ord_x", "fee_overcharge", "gateway",
             18200, NOW.isoformat(timespec="seconds"),
             (NOW + timedelta(days=deadline_days)).isoformat(
                 timespec="seconds"))
    c.state = state
    return c


class TestTemporal(unittest.TestCase):
    def test_classifier_progression(self):
        cap = (NOW - timedelta(days=1)).isoformat(timespec="seconds")
        self.assertEqual(temporal_state(cap, None, False, NOW),
                         SETTLEMENT_PENDING)
        old = (NOW - timedelta(days=10)).isoformat(timespec="seconds")
        self.assertEqual(temporal_state(old, None, False, NOW),
                         TRACE_REQUIRED)
        sd = (NOW - timedelta(days=1)).date().isoformat()
        self.assertEqual(temporal_state(old, sd, False, NOW),
                         WITHIN_EXPECTED_WINDOW)
        # date-only settlement dates resolve to midnight: day-3 + 2 lag
        # puts the grace window across "now" -> LATE
        sd = (NOW - timedelta(days=3)).date().isoformat()
        self.assertEqual(temporal_state(old, sd, False, NOW), LATE)
        sd = (NOW - timedelta(days=9)).date().isoformat()
        self.assertEqual(temporal_state(old, sd, False, NOW), CLAIMABLE)


class TestCaseMachine(unittest.TestCase):
    def test_full_legal_path_to_recovered(self):
        c = mkcase()
        for to in ("INVESTIGATING", "WAITING_FOR_INPUT", "INVESTIGATING",
                   "ADMISSIBILITY_REVIEW", "CLAIM_FILED",
                   "COUNTERPARTY_PENDING", "PARTIAL_RECOVERY", "RECOVERED"):
            c.transition(to, NOW)
        self.assertEqual(c.state, "RECOVERED")
        self.assertEqual(len(c.history), 8)
        self.assertIsNotNone(c.claim_filed_at)

    def test_illegal_transitions_raise(self):
        with self.assertRaises(IllegalTransition):
            mkcase().transition("CLAIM_FILED", NOW)          # skip gates
        with self.assertRaises(IllegalTransition):
            mkcase(state="RECOVERED").transition("OPEN", NOW)
        with self.assertRaises(IllegalTransition):
            mkcase().transition("NOT_A_STATE", NOW)

    def test_expired_window_blocks_filing_structurally(self):
        c = mkcase(deadline_days=30)
        c.transition("INVESTIGATING", NOW)
        c.transition("ADMISSIBILITY_REVIEW", NOW)
        late = NOW + timedelta(days=31)
        with self.assertRaises(IllegalTransition) as cm:
            c.transition("CLAIM_FILED", late)
        self.assertIn("window expired", str(cm.exception))
        self.assertNotIn("CLAIM_FILED", c.allowed(late))
        self.assertIn("WRITTEN_OFF", c.allowed(late))

    def test_wait_semantics(self):
        c = mkcase(state="INVESTIGATING")
        wake = NOW + timedelta(days=2)
        c.wait(wake, NOW, "bank inside posting lag")
        self.assertEqual(c.state, "INVESTIGATING")     # WAIT is not a move
        self.assertEqual(c.wake_at, wake.isoformat(timespec="seconds"))
        self.assertIn("WAIT until", c.history[-1]["note"])
        with self.assertRaises(IllegalTransition):
            mkcase(state="RECOVERED").wait(wake, NOW, "x")

    def test_sla_clocks(self):
        c = mkcase()
        for to in ("INVESTIGATING", "ADMISSIBILITY_REVIEW", "CLAIM_FILED"):
            c.transition(to, NOW)
        clk = c.clocks()
        self.assertEqual(clk["counterparty_sla"],
                         (NOW + timedelta(days=10)).isoformat(
                             timespec="seconds"))
        self.assertEqual(clk["escalation_deadline"],
                         (NOW + timedelta(days=15)).isoformat(
                             timespec="seconds"))
        self.assertEqual(clk["write_off_deadline"], c.claim_deadline)

    def test_serialization_roundtrip_fields(self):
        d = mkcase().to_dict()
        for k in ("clocks", "history", "state", "claim_deadline",
                  "amount_paise"):
            self.assertIn(k, d)
        json.dumps(d)                                   # serializable


class TestPortfolio(unittest.TestCase):
    def test_cases_from_real_discrepancies_and_sla_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            generate(seed=42, out_dir=tmp)
            exceptions = reconcile(tmp)["exceptions"]
        now = datetime(2026, 7, 5, 12, 0)
        cases = [case_from_discrepancy(e, now) for e in exceptions]
        self.assertEqual(len(cases), 216)
        self.assertTrue(all(c.state == "OPEN" for c in cases))
        # drive a slice into pending-with-overdue-SLA
        for c in cases[:3]:
            c.transition("INVESTIGATING", now)
            c.transition("ADMISSIBILITY_REVIEW", now)
            if now <= datetime.fromisoformat(c.claim_deadline):
                c.transition("CLAIM_FILED", now)
                c.transition("COUNTERPARTY_PENDING", now)
        later = now + timedelta(days=13)
        s = portfolio_sla(cases, later)
        self.assertGreaterEqual(s["responses_overdue"], 1)
        self.assertGreater(s["pending_beyond_sla_paise"], 0)
        c0 = cases[10]
        c0.wait(later - timedelta(hours=1), now, "counterparty lag")
        self.assertGreaterEqual(portfolio_sla(cases, later)["wakes_due"], 1)
        for k in ("claims_expiring_24h", "expiring_amount_paise"):
            self.assertIn(k, s)
