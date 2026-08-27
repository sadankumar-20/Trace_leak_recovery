"""Trace T2 — the deterministic reconciliation engine.

The star of the system, and deliberately AI-free: three-way matching
(gateway ledger <-> settlement batches <-> bank statements, anchored to
orders/captures/refunds and the contracted fee schedule) producing typed
states and paisa-exact discrepancy objects. Every discrepancy recomputes
mechanically from source records — an amount that cannot be re-derived is
not a discrepancy, it is a bug in this engine.

States: MATCHED, MATCHED_WITH_TOLERANCE, PARTIAL_MATCH, AMBIGUOUS,
EXCEPTION, UNRESOLVED.

Tolerance, batching, GST, international surcharges, reversal pairs, and
legitimate posting lags are modeled so that benign noise does NOT fire —
precision is the whole point.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

MATCHED = "MATCHED"
MATCHED_WITH_TOLERANCE = "MATCHED_WITH_TOLERANCE"
PARTIAL_MATCH = "PARTIAL_MATCH"
AMBIGUOUS = "AMBIGUOUS"
EXCEPTION = "EXCEPTION"
UNRESOLVED = "UNRESOLVED"

WIN_DAYS = {"fee_overcharge": 60, "missing_settlement": 45,
            "double_refund": 30, "refund_marked_success_not_settled": 60,
            "partial_capture_mismatch": 60, "duplicate_capture": 60,
            "rounding_drift": 60}
COUNTERPARTY = {"fee_overcharge": "gateway", "missing_settlement": "bank",
                "double_refund": "customer",
                "refund_marked_success_not_settled": "gateway",
                "partial_capture_mismatch": "gateway",
                "duplicate_capture": "gateway", "rounding_drift": "gateway"}
POSTING_LAG_DAYS = 2         # legitimate bank posting delay allowance


@dataclass(frozen=True)
class Discrepancy:
    exception_id: str
    discrepancy_type: str
    order_id: str
    expected_paise: int
    actual_paise: int
    delta_paise: int
    rule_violated: str
    affected_records: dict          # table -> [record ids]
    evidence_hashes: dict           # record id -> record_hash
    deterministic_confidence: float
    counterparty: str
    claim_deadline: str
    created_at: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["discrepancy_hash"] = hashlib.sha256(
            json.dumps(d, sort_keys=True).encode()).hexdigest()
        return d


@dataclass
class ReconResult:
    order_id: str
    txn_id: str
    state: str
    note: str = ""
    discrepancy: Discrepancy | None = None


def _correct_fees(order, txn, fs) -> tuple[int, int]:
    pct = fs["mdr_pct"] + (fs["intl_surcharge_pct"]
                           if order["international"] else 0.0)
    fee = round(txn["amount_paise"] * pct / 100)
    gst = round(fee * fs["gst_pct"] / 100)
    return fee, gst


class ReconciliationEngine:
    def __init__(self, world: dict, sim_now: str):
        self.w = world
        self.now = datetime.fromisoformat(sim_now)
        self.orders = {o["id"]: o for o in world["orders"]}
        self.captures = {c["id"]: c for c in world["captures"]}
        self.fs = {f["gateway"]: f for f in world["fee_schedules"]}
        self.lines_by_txn = {}
        for l in world["settlement_lines"]:
            self.lines_by_txn.setdefault(l["gateway_txn_id"], []).append(l)
        self.batches = {b["id"]: b for b in world["settlement_batches"]}
        self.bank_by_utr = {b["utr"]: b for b in world["bank_entries"]}
        self.refunds_by_txn = {}
        for r in world["refunds"]:
            self.refunds_by_txn.setdefault(r["gateway_txn_id"],
                                           []).append(r)
        self.txns_by_capture = {}
        for t in world["gateway_txns"]:
            self.txns_by_capture.setdefault(t["capture_id"], []).append(t)

    # ------------------------------------------------------------------
    def run(self) -> list[ReconResult]:
        out, seen_dup = [], set()
        for tx in self.w["gateway_txns"]:
            out.append(self._reconcile_txn(tx, seen_dup))
        return out

    def _exc(self, tx, dtype, rule, expected, actual, records,
             confidence=1.0) -> Discrepancy:
        order = self.orders[tx["order_id"]]
        hashes = {}
        for table, ids in records.items():
            rows = {r["id"]: r for r in self.w[table]}
            for i in ids:
                hashes[i] = rows[i]["record_hash"]
        deadline = (datetime.fromisoformat(tx["created_at"])
                    + timedelta(days=WIN_DAYS[dtype])).isoformat(
                        timespec="seconds")
        return Discrepancy(
            exception_id=f"exc_{dtype[:4]}_{tx['id']}",
            discrepancy_type=dtype, order_id=order["id"],
            expected_paise=expected, actual_paise=actual,
            delta_paise=expected - actual, rule_violated=rule,
            affected_records=records, evidence_hashes=hashes,
            deterministic_confidence=confidence,
            counterparty=COUNTERPARTY[dtype], claim_deadline=deadline,
            created_at=self.now.isoformat(timespec="seconds"))

    def _reconcile_txn(self, tx, seen_dup) -> ReconResult:
        order = self.orders[tx["order_id"]]
        cap = self.captures[tx["capture_id"]]
        fs = self.fs[tx["gateway"]]
        tol = fs["rounding_tolerance_paise"]
        base = {"orders": [order["id"]], "captures": [cap["id"]],
                "gateway_txns": [tx["id"]],
                "fee_schedules": [fs["id"]]}

        # Rule D — duplicate capture: >1 txn charging fees on one capture
        siblings = self.txns_by_capture[tx["capture_id"]]
        if len(siblings) > 1 and tx["id"] != siblings[0]["id"] \
                and tx["capture_id"] not in seen_dup:
            seen_dup.add(tx["capture_id"])
            recs = dict(base, gateway_txns=[s["id"] for s in siblings])
            return ReconResult(order["id"], tx["id"], EXCEPTION,
                "second capture-charge on one capture",
                self._exc(tx, "duplicate_capture", "one_charge_per_capture",
                          0, tx["fee_paise"] + tx["gst_paise"], recs))

        # Rule F — contract fee proof
        cfee, cgst = _correct_fees(order, tx, fs)
        fee_delta = (tx["fee_paise"] + tx["gst_paise"]) - (cfee + cgst)
        if fee_delta > tol:
            return ReconResult(order["id"], tx["id"], EXCEPTION,
                "charged fees exceed contract",
                self._exc(tx, "fee_overcharge", "contract_fee_schedule",
                          cfee + cgst, tx["fee_paise"] + tx["gst_paise"],
                          base))

        # Rule R — refund chain
        refunds = sorted(self.refunds_by_txn.get(tx["id"], []),
                         key=lambda r: r["id"])
        plain = [r for r in refunds if r["kind"] == "refund"]
        reversed_amt = -sum(r["amount_paise"] for r in refunds
                            if r["kind"] == "reversal")
        if len(plain) >= 2:
            a, b = plain[0], plain[1]
            if a["amount_paise"] == b["amount_paise"] \
                    and reversed_amt < b["amount_paise"]:
                recs = dict(base, refunds=[a["id"], b["id"]])
                return ReconResult(order["id"], tx["id"], EXCEPTION,
                    "same-amount refund executed twice, no reversal",
                    self._exc(tx, "double_refund",
                              "refund_chain_uniqueness",
                              a["amount_paise"],
                              a["amount_paise"] + b["amount_paise"], recs))
            if a["amount_paise"] != b["amount_paise"]:
                return ReconResult(order["id"], tx["id"], AMBIGUOUS,
                                   "multiple unequal refunds — human review")
        if plain and plain[0]["amount_paise"] == tx["amount_paise"] \
                and reversed_amt == 0:
            recs = dict(base, refunds=[plain[0]["id"]])
            return ReconResult(order["id"], tx["id"], EXCEPTION,
                "full refund marked processed; settlement never adjusted",
                self._exc(tx, "refund_marked_success_not_settled",
                          "refund_settlement_sync", 0, 0, recs,
                          confidence=0.85))

        # Rule S — settlement line vs charged amounts
        lines = self.lines_by_txn.get(tx["id"])
        if not lines:
            return ReconResult(order["id"], tx["id"], UNRESOLVED,
                               "no settlement line for transaction")
        line = lines[0]
        expected_line = tx["amount_paise"] - tx["fee_paise"] - tx["gst_paise"]
        line_delta = expected_line - line["net_paise"]
        recs_line = dict(base, settlement_lines=[line["id"]],
                         settlement_batches=[line["batch_id"]])
        if line_delta > tol:
            dtype = ("partial_capture_mismatch"
                     if cap["amount_paise"] < order["amount_paise"]
                     else "rounding_drift")
            rule = ("capture_vs_settlement_tieout"
                    if dtype == "partial_capture_mismatch"
                    else f"rounding_tolerance_{tol}p")
            return ReconResult(order["id"], tx["id"], EXCEPTION,
                "settlement short beyond contract tolerance",
                self._exc(tx, dtype, rule, expected_line,
                          line["net_paise"], recs_line))

        # Rule B — bank posting for the batch's UTR
        batch = self.batches[line["batch_id"]]
        bank = self.bank_by_utr.get(batch["utr"])
        if bank is None:
            due = (datetime.fromisoformat(batch["settlement_date"])
                   + timedelta(days=POSTING_LAG_DAYS))
            if self.now <= due:
                return ReconResult(order["id"], tx["id"], PARTIAL_MATCH,
                                   "gateway settled; bank inside posting lag")
            recs = dict(recs_line)
            return ReconResult(order["id"], tx["id"], EXCEPTION,
                "gateway batch never posted by bank",
                self._exc(tx, "missing_settlement",
                          "utr_must_post_within_lag",
                          line["net_paise"], 0, recs))

        state = MATCHED_WITH_TOLERANCE if 0 < line_delta <= tol else MATCHED
        return ReconResult(order["id"], tx["id"], state,
                           f"tied out (delta {line_delta}p within "
                           f"tolerance {tol}p)" if state != MATCHED else "")


def reconcile(data_dir: str | Path = "data") -> dict:
    d = Path(data_dir)
    world = json.loads((d / "world.json").read_text())
    split = json.loads((d / "split.json").read_text())
    results = ReconciliationEngine(world, split["sim_now"]).run()
    states: dict[str, int] = {}
    for r in results:
        states[r.state] = states.get(r.state, 0) + 1
    return {"results": results, "states": states,
            "exceptions": [r.discrepancy.to_dict() for r in results
                           if r.discrepancy]}


if __name__ == "__main__":
    out = reconcile()
    print(json.dumps({"states": out["states"],
                      "exceptions": len(out["exceptions"])}, indent=1))
