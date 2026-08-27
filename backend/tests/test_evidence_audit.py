"""T4: lineage graphs with broken edges; a chain that catches tampering."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.audit import GENESIS, AuditChain
from app.evidence import EvidenceGraphBuilder
from app.recon import reconcile
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
        cls.exceptions = reconcile(cls.tmp.name)["exceptions"]
        cls.builder = EvidenceGraphBuilder(cls.world)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestEvidenceGraph(Base):
    def test_all_216_graphs_build_with_hashed_nodes(self):
        rows = {t: {r["id"]: r for r in v} for t, v in self.world.items()}
        for d in self.exceptions:
            g = self.builder.build(d)
            self.assertGreaterEqual(len(g.nodes), 4, d["exception_id"])
            for n in g.nodes.values():
                self.assertEqual(n["record_hash"],
                                 rows[n["table"]][n["id"]]["record_hash"])

    def test_missing_settlement_is_a_broken_posted_edge(self):
        for d in self.exceptions:
            g = self.builder.build(d)
            broken = [e["type"] for e in g.broken_edges()]
            if d["discrepancy_type"] == "missing_settlement":
                self.assertIn("POSTED_AS", broken, d["order_id"])
            else:
                self.assertNotIn("POSTED_AS", broken, d["order_id"])

    def test_type_specific_lineage(self):
        for d in self.exceptions:
            g = self.builder.build(d)
            tables = {n["table"] for n in g.nodes.values()}
            self.assertIn("fee_schedules", tables)
            if d["discrepancy_type"] == "double_refund":
                self.assertEqual(sum(1 for n in g.nodes.values()
                                     if n["table"] == "refunds"), 2)
            if d["discrepancy_type"] == "duplicate_capture":
                self.assertEqual(sum(1 for n in g.nodes.values()
                                     if n["table"] == "gateway_txns"), 2)

    def test_explanation_recomputes_to_the_paisa(self):
        d = next(x for x in self.exceptions
                 if x["discrepancy_type"] == "fee_overcharge")
        text = self.builder.explain(d, self.builder.build(d))
        want = abs(d["delta_paise"]) / 100
        self.assertIn(f"Rs.{want:,.2f}", text)
        self.assertIn("independently recomputes", text)
        self.assertIn("hash-verified", text)

    def test_graph_build_deterministic(self):
        d = self.exceptions[0]
        self.assertEqual(self.builder.build(d).to_dict(),
                         self.builder.build(d).to_dict())


class TestAuditChain(Base):
    def make_chain(self):
        c = AuditChain()
        for d in self.exceptions[:5]:
            cid = f"case_{d['exception_id']}"
            c.append(cid, "EXCEPTION_CREATED",
                     {"delta": d["delta_paise"]}, NOW)
            c.append(cid, "INVESTIGATION_STARTED", {}, NOW)
            c.append(cid, "GATE_PASSED", {"gate": "reconciliation"}, NOW)
        return c

    def test_chain_links_and_verifies(self):
        c = self.make_chain()
        self.assertEqual(c.events[0]["prev_hash"], GENESIS)
        for a, b in zip(c.events, c.events[1:]):
            self.assertEqual(b["prev_hash"], a["hash"])
        v = c.verify(NOW)
        self.assertTrue(v["valid"])
        self.assertEqual(v["events"], 15)

    def test_tampering_detected_at_first_invalid_seq(self):
        for mutate in (lambda e: e["payload"].update(delta=1),
                       lambda e: e.update(event_type="GATE_PASSED"),
                       lambda e: e.update(prev_hash="f" * 64)):
            c = self.make_chain()
            mutate(c.events[6])
            v = c.verify(NOW)
            self.assertFalse(v["valid"])
            self.assertEqual(v["first_invalid_seq"], 7)

    def test_vocabulary_closed_and_roundtrip(self):
        c = self.make_chain()
        with self.assertRaises(ValueError):
            c.append("case_x", "CREATIVE_EVENT", {}, NOW)
        c2 = AuditChain.load(c.dump())
        self.assertTrue(c2.verify(NOW)["valid"])
        self.assertEqual(len(c2.for_case(c.events[0]["case_id"])), 3)
