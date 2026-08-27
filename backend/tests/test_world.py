"""T1: the world is deterministic, referentially intact, honestly labeled."""
import json
import tempfile
import unittest
from pathlib import Path

from app.world import LEAK_COUNTS, LEAKS, generate


class TestWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.meta = generate(seed=42, out_dir=cls.tmp.name)
        cls.world = json.loads(Path(cls.tmp.name, "world.json").read_text())
        cls.gt = json.loads(Path(cls.tmp.name,
                                 "ground_truth.json").read_text())["labels"]
        cls.split = json.loads(Path(cls.tmp.name, "split.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_deterministic_byte_identical(self):
        with tempfile.TemporaryDirectory() as t2:
            self.assertEqual(generate(seed=42, out_dir=t2)["corpus_sha256"],
                             self.meta["corpus_sha256"])
        with tempfile.TemporaryDirectory() as t3:
            self.assertNotEqual(generate(seed=7, out_dir=t3)["corpus_sha256"],
                                self.meta["corpus_sha256"])

    def test_scale_and_leak_taxonomy(self):
        self.assertEqual(len(self.world["orders"]), 5000)
        self.assertEqual(self.meta["leaks"], LEAK_COUNTS)
        self.assertEqual(set(g["leak_type"] for g in self.gt.values()),
                         set(LEAKS))

    def test_referential_integrity(self):
        orders = {o["id"] for o in self.world["orders"]}
        txns = {t["id"]: t for t in self.world["gateway_txns"]}
        batches = {b["id"] for b in self.world["settlement_batches"]}
        utrs = {b["utr"] for b in self.world["settlement_batches"]}
        for t in txns.values():
            self.assertIn(t["order_id"], orders)
        for r in self.world["refunds"]:
            self.assertIn(r["gateway_txn_id"], txns)
        for l in self.world["settlement_lines"]:
            self.assertIn(l["batch_id"], batches)
            self.assertIn(l["gateway_txn_id"], txns)
        for be in self.world["bank_entries"]:
            self.assertIn(be["utr"], utrs)

    def test_missing_settlement_means_bank_silent_not_batch_absent(self):
        bank_utrs = {b["utr"] for b in self.world["bank_entries"]}
        missing = [o for o, g in self.gt.items()
                   if g["leak_type"] == "missing_settlement"]
        lines = {l["gateway_txn_id"]: l for l in
                 self.world["settlement_lines"]}
        batches = {b["id"]: b for b in self.world["settlement_batches"]}
        for o in missing:
            tx = next(t for t in self.world["gateway_txns"]
                      if t["order_id"] == o)
            line = lines[tx["id"]]
            self.assertNotIn(batches[line["batch_id"]]["utr"], bank_utrs)

    def test_fee_overcharge_recomputes_to_ground_truth(self):
        fs = {f["gateway"]: f for f in self.world["fee_schedules"]}
        for o, g in self.gt.items():
            if g["leak_type"] != "fee_overcharge":
                continue
            tx = next(t for t in self.world["gateway_txns"]
                      if t["order_id"] == o)
            order = next(x for x in self.world["orders"] if x["id"] == o)
            f = fs[tx["gateway"]]
            pct = f["mdr_pct"] + (f["intl_surcharge_pct"]
                                  if order["international"] else 0)
            correct_fee = round(tx["amount_paise"] * pct / 100)
            correct_gst = round(correct_fee * f["gst_pct"] / 100)
            delta = (tx["fee_paise"] + tx["gst_paise"]) \
                - (correct_fee + correct_gst)
            self.assertEqual(delta, g["true_leak_paise"], o)
            self.assertGreater(delta, 0)

    def test_benign_noise_exists_and_is_unlabeled(self):
        reversals = [r for r in self.world["refunds"]
                     if r["kind"] == "reversal"]
        self.assertGreater(len(reversals), 50)     # double-refund lookalikes
        for r in reversals:
            self.assertNotIn(r["order_id"], self.gt)   # never labeled leaks

    def test_split_frozen_and_disjoint(self):
        dev, held = set(self.split["dev"]), set(self.split["held_out"])
        self.assertFalse(dev & held)
        self.assertEqual(dev | held, set(self.gt))
        self.assertEqual(self.split["corpus_sha256"],
                         self.meta["corpus_sha256"])

    def test_record_hashes_immutable(self):
        from app.models import record_hash
        row = dict(self.world["orders"][0])
        h = row.pop("record_hash")
        self.assertEqual(record_hash(row), h)
        row["amount_paise"] += 1
        self.assertNotEqual(record_hash(row), h)
