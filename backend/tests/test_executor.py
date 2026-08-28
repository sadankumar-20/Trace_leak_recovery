"""T7: one exception -> at most one execution, under every failure mode."""
import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from app import gate as G
from app.audit import AuditChain
from app.counterparty import CounterpartySim
from app.decision import decide
from app.executor import ExecutionBlocked, Executor
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
        cls.gt = json.loads(Path(cls.tmp.name,
                                 "ground_truth.json").read_text())["labels"]
        cls.split = json.loads(Path(cls.tmp.name, "split.json").read_text())
        cls.now = cls.split["sim_now"]
        cls.exceptions = reconcile(cls.tmp.name)["exceptions"]
        cls.decisions = {e["exception_id"]:
                         decide(e, SUP, cls.world, cls.now)
                         for e in cls.exceptions}
        cls.packages = [d["action_package"]
                        for d in cls.decisions.values()
                        if "action_package" in d]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def make_exec(self, failure_plan=None):
        chain = AuditChain()
        cp = CounterpartySim(self.world, self.gt, self.now,
                             failure_plan=failure_plan)
        return Executor(self.world, self.now, cp, chain), cp, chain


class TestVerification(Base):
    def test_tampered_amount_hash_party_all_blocked(self):
        ex, cp, _ = self.make_exec()
        for mutate in (lambda p: p.update(claim_amount_paise=
                                          p["claim_amount_paise"] + 1),
                       lambda p: p.update(package_hash="f" * 64),
                       lambda p: p.update(responsible_counterparty="BankC",
                                          selected_action=
                                          "FILE_BANK_TRACE")):
            pkg = copy.deepcopy(self.packages[0])
            mutate(pkg)
            with self.assertRaises(ExecutionBlocked):
                ex.execute(pkg)
        self.assertEqual(len(cp.received), 0)      # nothing ever sent
        self.assertEqual(ex.monitors()["unauthorized_blocked"], 3)

    def test_expired_and_missing_approval_blocked(self):
        ex, cp, _ = self.make_exec()
        late = Executor(self.world, "2027-06-01T00:00:00",
                        CounterpartySim(self.world, self.gt,
                                        "2027-06-01T00:00:00"),
                        AuditChain())
        with self.assertRaises(ExecutionBlocked):
            late.execute(copy.deepcopy(self.packages[0]))
        pkg = copy.deepcopy(self.packages[0])
        pkg["required_approval"] = True
        pkg["package_hash"] = __import__("app.executor",
                                         fromlist=["x"])._pkg_hash(pkg)
        with self.assertRaises(ExecutionBlocked) as cm:
            ex.execute(pkg, approval=False)
        self.assertIn("approval", str(cm.exception))
        ex.execute(pkg, approval=True)             # with approval: fine

    def test_fabricated_exception_blocked(self):
        ex, cp, _ = self.make_exec()
        pkg = copy.deepcopy(self.packages[0])
        pkg["exception_id"] = "exc_fake_gtx_99999"
        pkg["idempotency_key"] = pkg["exception_id"]
        pkg["package_hash"] = __import__("app.executor",
                                         fromlist=["x"])._pkg_hash(pkg)
        with self.assertRaises(ExecutionBlocked):
            ex.execute(pkg)


class TestIdempotency(Base):
    def test_duplicate_request_returns_original(self):
        ex, cp, _ = self.make_exec()
        pkg = self.packages[0]
        r1 = ex.execute(pkg)
        r2 = ex.execute(pkg)
        self.assertIs(r1, r2)
        self.assertEqual(len(cp.claims), 1)
        self.assertEqual(ex.monitors()["double_executions"], 0)

    def test_timeout_before_receipt_safe_retry_one_claim(self):
        pkg = self.packages[0]
        ex, cp, _ = self.make_exec(
            {pkg["idempotency_key"]: ["timeout_before", "timeout_before"]})
        r = ex.execute(pkg)
        self.assertIn(r["execution_status"],
                      ("SUCCEEDED", "PARTIALLY_RECOVERED", "REJECTED",
                       "NEEDS_INFORMATION"))
        self.assertEqual(r["attempt_count"], 3)
        self.assertEqual(len(cp.claims), 1)

    def test_timeout_after_receipt_resolves_existing(self):
        pkg = self.packages[0]
        ex, cp, _ = self.make_exec(
            {pkg["idempotency_key"]: ["timeout_after"]})
        r = ex.execute(pkg)
        self.assertEqual(len(cp.claims), 1)         # ONE claim ever
        self.assertGreaterEqual(r["attempt_count"], 2)
        self.assertIn(r["execution_status"],
                      ("SUCCEEDED", "PARTIALLY_RECOVERED", "REJECTED",
                       "NEEDS_INFORMATION"))
        self.assertLessEqual(len(ex.recoveries), 1)  # never double-counted

    def test_exhausted_retries_fail_safe(self):
        pkg = self.packages[1]
        ex, cp, _ = self.make_exec(
            {pkg["idempotency_key"]: ["timeout_before"] * 5})
        r = ex.execute(pkg)
        self.assertEqual(r["execution_status"], "FAILED_SAFE")
        self.assertEqual(len(cp.claims), 0)
        self.assertEqual(ex.monitors()["gross_recovered_paise"], 0)

    def test_malformed_over_recovery_fails_safe(self):
        pkg = self.packages[0]
        ex, cp, _ = self.make_exec(
            {pkg["idempotency_key"]: ["malformed"]})
        r = ex.execute(pkg)
        self.assertEqual(r["execution_status"], "FAILED_SAFE")
        self.assertEqual(r["recovered_amount_paise"], 0)
        self.assertEqual(ex.recoveries, [])

    def test_concurrent_requests_single_execution(self):
        ex, cp, _ = self.make_exec()
        pkg = self.packages[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: ex.execute(pkg), range(4)))
        m = ex.monitors()
        self.assertEqual(m["unique_exceptions"], 1)
        self.assertEqual(m["double_executions"], 0)
        self.assertEqual(len(cp.claims), 1)

    def test_retry_after_success_returns_original(self):
        ex, cp, _ = self.make_exec()
        pkg = self.packages[0]
        r1 = ex.execute(pkg)
        ref = r1["counterparty_reference"]
        r2 = ex.execute(pkg)
        self.assertEqual(r2["counterparty_reference"], ref)
        self.assertEqual(len(ex.recoveries), min(1, len(ex.recoveries)))
        self.assertEqual(len(cp.claims), 1)


class TestPortfolio(Base):
    def test_end_to_end_only_packages_reach_counterparty(self):
        chain = AuditChain()
        cp = CounterpartySim(self.world, self.gt, self.now)
        ex = Executor(self.world, self.now, cp, chain)
        for pkg in self.packages:
            ex.execute(pkg, approval=pkg.get("required_approval", False))
        pkg_ids = {p["exception_id"] for p in self.packages}
        self.assertEqual(set(cp.claims), pkg_ids)   # nothing else ever
        m = ex.monitors()
        self.assertEqual(m["double_executions"], 0)
        self.assertEqual(m["unique_exceptions"], len(pkg_ids))
        self.assertGreater(m["gross_recovered_paise"], 0)
        # exact accounting per recovery
        for r in ex.recoveries:
            self.assertEqual(r["claimed_paise"],
                             r["recovered_paise"] + r["unrecovered_paise"])
            self.assertEqual(r["net_recovery_paise"],
                             r["recovered_paise"]
                             - r["recovery_cost_paise"])
        self.assertTrue(chain.verify(NOW)["valid"])
        # expected vs actual comparison exists and is finite
        expected = sum(self.decisions[p["exception_id"]]
                       ["admissibility"]["expected_net_paise"]
                       for p in self.packages)
        actual = m["net_recovered_paise"]
        self.assertIsInstance(expected - actual, int)

    def test_reproducible_double_run(self):
        def run():
            cp = CounterpartySim(self.world, self.gt, self.now)
            ex = Executor(self.world, self.now, cp, AuditChain())
            for pkg in self.packages:
                ex.execute(pkg,
                           approval=pkg.get("required_approval", False))
            return json.dumps(sorted(ex.recoveries,
                                     key=lambda r: r["exception_id"]),
                              sort_keys=True)
        self.assertEqual(run(), run())

    def test_non_executable_decisions_never_reach_counterparty(self):
        chain = AuditChain()
        cp = CounterpartySim(self.world, self.gt, self.now)
        ex = Executor(self.world, self.now, cp, chain)
        for exc in self.exceptions:
            d = self.decisions[exc["exception_id"]]
            if d["selected_action"] in ("WRITE_OFF", "NO_ACTION",
                                        "ESCALATE", "WAIT"):
                self.assertNotIn("action_package", d)
        contained = decide(self.exceptions[0],
                           {"result": "CONTAINED", "checks": []},
                           self.world, self.now)
        self.assertNotIn("action_package", contained)
        self.assertEqual(len(cp.received), 0)
