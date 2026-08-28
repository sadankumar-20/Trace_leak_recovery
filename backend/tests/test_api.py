"""T10: the cockpit renders only what the system did; the server enforces
what humans may do."""
import json
import tempfile
import unittest
from pathlib import Path

from app.api import create_app


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        app = create_app(cls.tmp.name)
        app.testing = True
        cls.c = app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def find(self, pred):
        rows = self.c.get("/exceptions").get_json()["exceptions"]
        return next(r for r in rows if pred(r))


class TestCockpit(Base):
    def test_kpis_labeled_and_consistent_with_ledger(self):
        k = self.c.get("/kpis").get_json()
        self.assertEqual(k["labels"]["recovered"], "ACTUAL")
        self.assertEqual(k["labels"]["preventable"], "ESTIMATED")
        self.assertEqual(k["false_claims_escaped"], 0)
        self.assertEqual(k["double_executions"], 0)
        self.assertGreater(k["leakage_found_paise"], k["claimed_paise"])
        self.assertGreaterEqual(k["claimed_paise"], k["recovered_paise"])
        self.assertEqual(k["recovered_paise"] >= k["net_recovered_paise"],
                         True)

    def test_recon_rows_carry_three_columns(self):
        rows = self.c.get("/exceptions").get_json()["exceptions"]
        self.assertEqual(len(rows), 216)
        r = rows[0]
        for col in ("order", "gateway", "bank"):
            self.assertIn(col, r)
        self.assertIn("delta_paise", r)
        # part 2: evidence status exposed from existing verdicts
        self.assertIn(r["evidence"], ("SUPPORTED", "CONTAINED",
                                      "REJECTED", "INSUFFICIENT_EVIDENCE"))

    def test_detail_has_graph_gates_labels_and_lineage(self):
        row = self.find(lambda r: r["decision"] == "FILE_GATEWAY_CLAIM")
        d = self.c.get(f"/exceptions/{row['exception_id']}").get_json()
        self.assertIn("UNVERIFIED", d["ai"]["hypothesis"]["label"])
        self.assertEqual(len(d["admissibility"]["gate_results"]), 8)
        for n in d["evidence_graph"]["nodes"].values():
            self.assertEqual(len(n["record_hash"]), 64)
        self.assertGreater(len(d["audit"]), 2)
        for forbidden in ("outcome_if_claimed", "true_leak_paise", "gt_"):
            self.assertNotIn(forbidden, json.dumps(d))

    def test_role_enforced_server_side(self):
        row = self.find(lambda r: r["decision"] == "FILE_GATEWAY_CLAIM")
        r = self.c.post(f"/exceptions/{row['exception_id']}/action",
                        json={"action": "FILE_GATEWAY_CLAIM"},
                        headers={"X-Role": "analyst"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("cannot execute", r.get_json()["error"])

    def test_inadmissible_action_rejected_with_machine_reason(self):
        row = self.find(lambda r: r["decision"] == "WRITE_OFF")
        r = self.c.post(f"/exceptions/{row['exception_id']}/action",
                        json={"action": "FILE_GATEWAY_CLAIM"},
                        headers={"X-Role": "executor"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("reason", r.get_json())

    def test_authorized_file_executes_idempotently(self):
        row = self.find(lambda r: r["decision"] == "FILE_GATEWAY_CLAIM")
        url = f"/exceptions/{row['exception_id']}/action"
        h = {"X-Role": "executor"}
        r1 = self.c.post(url, json={"action": "FILE_GATEWAY_CLAIM"},
                         headers=h).get_json()["execution"]
        r2 = self.c.post(url, json={"action": "FILE_GATEWAY_CLAIM"},
                         headers=h).get_json()["execution"]
        self.assertEqual(r1["execution_id"], r2["execution_id"])
        k = self.c.get("/kpis").get_json()
        self.assertEqual(k["double_executions"], 0)

    def test_audit_verify_and_stream(self):
        v = self.c.get("/audit/verify").get_json()
        self.assertTrue(v["valid"])
        self.assertGreater(v["events"], 400)
        ev = self.c.get("/stream?n=10").get_json()["events"]
        self.assertEqual(len(ev), 10)

    def test_evaluation_served_for_t10_without_recalc(self):
        e = self.c.get("/evaluation").get_json()
        self.assertEqual(e["result"]["integrity"]["status"], "PASS")
        self.assertIn("Four-way ablation", e["report"])

    def test_frontend_files_exist_and_reference_endpoints(self):
        fe = Path(__file__).resolve().parents[2] / "frontend"
        js = (fe / "app.js").read_text()
        html = (fe / "index.html").read_text()
        for needle in ("/kpis", "/exceptions", "/audit/verify", "/stream"):
            self.assertIn(needle, js)
        self.assertIn("VERIFY AUDIT CHAIN", html)
        self.assertIn("SIMULATED WORLD", html)
        self.assertIn("enforcement is server-side", js)


    def test_premium_layer_wired_to_real_data(self):
        fe = Path(__file__).resolve().parents[2] / "frontend"
        js = (fe / "app.js").read_text()
        css = (fe / "style.css").read_text()
        html = (fe / "index.html").read_text()
        # story beats present and fed from APIs, not literals
        for needle in ("Money appears correct", "IntersectionObserver",
                       "prefers-reduced-motion", "countUp",
                       '"/clusters"', '"/evaluation"', "wordize",
                       "moneyFlow", "brokenEdge", "Escape",
                       "CASE IDENTIFIED", "ESCAPED",
                       "AI was allowed to fail", "never merged",
                       "NOT A PRODUCTION FINANCIAL PRODUCT",
                       "AUDIT VERIFIED", "aria-label"):
            self.assertIn(needle, js + css)
        self.assertIn("id=\"story\"", html)
        self.assertIn("Root Causes", html)
        # reduced-motion path disables animation and un-sticks beats
        self.assertIn("transition:none !important", css)
        # no hardcoded financial values (>=4 digit literals, excluding
        # unicode escapes and the millisecond timer intervals: the 5000ms
        # stream poll and the 1000ms live-clock tick)
        import re
        clean = re.sub(r"\\u[0-9a-fA-F]{4}", "", js)
        nums = set(re.findall(r"\b\d{4,}\b", clean)) - {"5000", "1000"}
        self.assertEqual(nums, set(), nums)


    def test_hidden_overlay_cannot_shield_clicks(self):
        """Regression: .overlay pairs the hidden ATTRIBUTE with an author
        display rule; author styles beat the UA [hidden]{display:none},
        so without an explicit override the closed overlay is a
        full-viewport z-40 click shield killing every interaction."""
        css = (Path(__file__).resolve().parents[2] / "frontend"
               / "style.css").read_text()
        self.assertIn(".overlay[hidden]{display:none !important}", css)
        # and every other fixed full-viewport decorative layer must
        # explicitly pass clicks through
        import re
        for name in ("dustfield",):
            block = re.search(r"\." + name + r"\{[^}]*\}", css).group()
            self.assertIn("pointer-events:none", block)
