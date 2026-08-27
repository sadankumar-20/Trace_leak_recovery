"""Trace T5a — read-only investigator tools + the simulated knowledge base.

Tools return deep copies of source records: the investigator can hold
evidence, never touch it. Unknown ids and bad arguments return structured
errors; every call is counted against a budget and traced. Nothing in this
module can write.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

KB_DOCS = [
    {"document_id": "kb_fee_gwA", "title": "GatewayA merchant fee contract",
     "category": "fee_schedule", "effective_from": "2026-01-01",
     "effective_to": None,
     "relevant_rule": "MDR 1.80% + 18% GST; international surcharge 0.50%; "
                      "rounding tolerance 50 paise per settlement line",
     "source_reference": "contract:gwA:v4"},
    {"document_id": "kb_fee_gwB", "title": "GatewayB merchant fee contract",
     "category": "fee_schedule", "effective_from": "2026-01-01",
     "effective_to": None,
     "relevant_rule": "MDR 2.10% + 18% GST; international surcharge 0.75%; "
                      "rounding tolerance 50 paise per settlement line",
     "source_reference": "contract:gwB:v4"},
    {"document_id": "kb_settle_win", "title": "Settlement timing rules",
     "category": "settlement", "effective_from": "2026-01-01",
     "effective_to": None,
     "relevant_rule": "Expected settlement T+3; bank posting lag up to 2 "
                      "days is legitimate; grace 2 further days before "
                      "trace",
     "source_reference": "ops:settlement:v2"},
    {"document_id": "kb_refund_rev", "title": "Refund and reversal rules",
     "category": "refund", "effective_from": "2026-01-01",
     "effective_to": None,
     "relevant_rule": "A reversal (negative amount, kind=reversal) cancels "
                      "a prior refund; a same-amount refund pair WITHOUT a "
                      "reversal is a duplicate. RBI window: refunds credit "
                      "within 7 working days.",
     "source_reference": "rbi:refunds:2025"},
    {"document_id": "kb_partial", "title": "Partial capture rules",
     "category": "capture", "effective_from": "2026-01-01",
     "effective_to": None,
     "relevant_rule": "Settlement ties to the CAPTURED amount, not the "
                      "order amount; fees compute on captured value",
     "source_reference": "ops:capture:v1"},
]


class ToolError(RuntimeError):
    pass


@dataclass
class ToolRegistry:
    world: dict
    budget: int = 8
    trace: list = field(default_factory=list)

    def __post_init__(self):
        self._by = {t: {r["id"]: r for r in rows}
                    for t, rows in self.world.items()}
        self._lines_by_txn = {}
        for l in self.world["settlement_lines"]:
            self._lines_by_txn.setdefault(l["gateway_txn_id"],
                                          []).append(l)
        self._bank_by_utr = {b["utr"]: b for b in self.world["bank_entries"]}
        self._refunds_by_txn = {}
        for r in self.world["refunds"]:
            self._refunds_by_txn.setdefault(r["gateway_txn_id"],
                                            []).append(r)
        self._fs_by_gw = {f["gateway"]: f
                          for f in self.world["fee_schedules"]}

    def _call(self, tool: str, args: dict, fn):
        if len([t for t in self.trace if t["ok"]]) >= self.budget:
            raise ToolError(f"tool budget of {self.budget} exhausted")
        try:
            if not all(isinstance(v, str) and v for v in args.values()):
                raise ToolError(f"{tool}: arguments must be non-empty "
                                f"strings, got {args!r}")
            out = fn()
            self.trace.append({"step": len(self.trace) + 1, "tool": tool,
                               "args": args, "ok": True,
                               "result_ids": _ids(out)})
            return copy.deepcopy(out)
        except ToolError as e:
            self.trace.append({"step": len(self.trace) + 1, "tool": tool,
                               "args": args, "ok": False,
                               "error": str(e)})
            raise

    def get_order(self, order_id: str):
        return self._call("get_order", {"order_id": order_id}, lambda:
            self._by["orders"].get(order_id)
            or _missing("order", order_id))

    def get_gateway_txn(self, txn_id: str):
        return self._call("get_gateway_txn", {"txn_id": txn_id}, lambda:
            self._by["gateway_txns"].get(txn_id)
            or _missing("gateway_txn", txn_id))

    def get_settlement_batch(self, txn_id: str):
        def fn():
            lines = self._lines_by_txn.get(txn_id)
            if not lines:
                _missing("settlement line for txn", txn_id)
            batch = self._by["settlement_batches"][lines[0]["batch_id"]]
            return {"line": lines[0], "batch": batch}
        return self._call("get_settlement_batch", {"txn_id": txn_id}, fn)

    def trace_utr(self, utr: str):
        return self._call("trace_utr", {"utr": utr}, lambda:
            {"utr": utr, "bank_entry": self._bank_by_utr.get(utr),
             "posted": utr in self._bank_by_utr})

    def get_refund_chain(self, txn_id: str):
        return self._call("get_refund_chain", {"txn_id": txn_id}, lambda:
            sorted(self._refunds_by_txn.get(txn_id, []),
                   key=lambda r: r["id"]))

    def get_fee_schedule(self, gateway: str):
        return self._call("get_fee_schedule", {"gateway": gateway}, lambda:
            self._fs_by_gw.get(gateway) or _missing("fee schedule", gateway))

    def search_knowledge(self, category: str):
        return self._call("search_knowledge", {"category": category},
            lambda: [dict(d, confidence=1.0,
                          matching_reason=f"category == {category!r}")
                     for d in KB_DOCS if d["category"] == category])


def _missing(kind, key):
    raise ToolError(f"no such {kind}: {key!r}")


def _ids(out):
    if isinstance(out, dict):
        return [v for k, v in out.items() if k == "id"] or \
               [x.get("id") for x in out.values()
                if isinstance(x, dict) and "id" in x]
    if isinstance(out, list):
        return [x.get("id") or x.get("document_id") for x in out
                if isinstance(x, dict)]
    return []
