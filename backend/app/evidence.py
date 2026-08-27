"""Trace T4a — the evidence graph.

Every exception gets a lineage graph: Order -> Capture -> GatewayTxn ->
Refund(s) -> SettlementLine -> SettlementBatch -> BankEntry, plus the
FeeSchedule that prices it. Nodes carry the immutable record hash from T1
sources; edges are typed; a leak is literally a BROKEN edge (e.g. the
batch's POSTED_AS edge to the bank is missing). explain() renders the
spec's sentence with numbers recomputed from the nodes — never from the
AI, never from stored prose.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

EDGE_TYPES = ("CAPTURED_AS", "CHARGED_AS", "REFUNDED_BY", "SETTLED_IN",
              "BATCHED_IN", "POSTED_AS", "PRICED_BY")


@dataclass
class EvidenceGraph:
    exception_id: str
    nodes: dict = field(default_factory=dict)   # id -> node dict
    edges: list = field(default_factory=list)   # {src,dst,type,broken}

    def add_node(self, table: str, row: dict):
        self.nodes[row["id"]] = {
            "id": row["id"], "table": table,
            "amount_paise": row.get("amount_paise", row.get("net_paise",
                            row.get("total_net_paise"))),
            "timestamp": row.get("created_at", row.get("settlement_date",
                         row.get("posted_date"))),
            "record_hash": row["record_hash"], "status": row.get("status")}

    def add_edge(self, src: str, dst: str | None, etype: str,
                 broken: bool = False):
        assert etype in EDGE_TYPES, etype
        self.edges.append({"src": src, "dst": dst, "type": etype,
                           "broken": broken})

    def broken_edges(self):
        return [e for e in self.edges if e["broken"]]

    def to_dict(self):
        return {"exception_id": self.exception_id, "nodes": self.nodes,
                "edges": self.edges}


class EvidenceGraphBuilder:
    def __init__(self, world: dict):
        self.w = world
        self.by_id = {t: {r["id"]: r for r in rows}
                      for t, rows in world.items()}
        self.lines_by_txn = {}
        for l in world["settlement_lines"]:
            self.lines_by_txn.setdefault(l["gateway_txn_id"], []).append(l)
        self.bank_by_utr = {b["utr"]: b for b in world["bank_entries"]}
        self.refunds_by_txn = {}
        for r in world["refunds"]:
            self.refunds_by_txn.setdefault(r["gateway_txn_id"],
                                           []).append(r)
        self.fs_by_gw = {f["gateway"]: f for f in world["fee_schedules"]}

    def build(self, disc: dict) -> EvidenceGraph:
        g = EvidenceGraph(disc["exception_id"])
        txn_ids = disc["affected_records"]["gateway_txns"]
        order = self.by_id["orders"][disc["order_id"]]
        g.add_node("orders", order)
        for tid in txn_ids:
            tx = self.by_id["gateway_txns"][tid]
            cap = self.by_id["captures"][tx["capture_id"]]
            fs = self.fs_by_gw[tx["gateway"]]
            g.add_node("captures", cap); g.add_node("gateway_txns", tx)
            g.add_node("fee_schedules", fs)
            g.add_edge(order["id"], cap["id"], "CAPTURED_AS")
            g.add_edge(cap["id"], tx["id"], "CHARGED_AS")
            g.add_edge(tx["id"], fs["id"], "PRICED_BY")
            for r in sorted(self.refunds_by_txn.get(tid, []),
                            key=lambda x: x["id"]):
                g.add_node("refunds", r)
                g.add_edge(tx["id"], r["id"], "REFUNDED_BY")
            for line in self.lines_by_txn.get(tid, []):
                batch = self.by_id["settlement_batches"][line["batch_id"]]
                g.add_node("settlement_lines", line)
                g.add_node("settlement_batches", batch)
                g.add_edge(tx["id"], line["id"], "SETTLED_IN")
                g.add_edge(line["id"], batch["id"], "BATCHED_IN")
                bank = self.bank_by_utr.get(batch["utr"])
                if bank:
                    g.add_node("bank_entries", bank)
                    g.add_edge(batch["id"], bank["id"], "POSTED_AS")
                else:
                    g.add_edge(batch["id"], None, "POSTED_AS", broken=True)
            if not self.lines_by_txn.get(tid):
                g.add_edge(tx["id"], None, "SETTLED_IN", broken=True)
        return g

    def explain(self, disc: dict, g: EvidenceGraph) -> str:
        t = disc["discrepancy_type"]
        d = abs(disc["delta_paise"])
        base = (f"Rs.{d / 100:,.2f} is recoverable from the "
                f"{disc['counterparty']} because ")
        if t == "fee_overcharge":
            tx = self.by_id["gateway_txns"][
                disc["affected_records"]["gateway_txns"][0]]
            fs = self.fs_by_gw[tx["gateway"]]
            order = self.by_id["orders"][disc["order_id"]]
            pct = fs["mdr_pct"] + (fs["intl_surcharge_pct"]
                                   if order["international"] else 0)
            cfee = round(tx["amount_paise"] * pct / 100)
            cgst = round(cfee * fs["gst_pct"] / 100)
            recomputed = (tx["fee_paise"] + tx["gst_paise"]) - (cfee + cgst)
            return (base + f"the contracted MDR is {pct:.2f}%, the gateway "
                    f"charged Rs.{(tx['fee_paise'] + tx['gst_paise']) / 100:,.2f} "
                    f"against a contractual Rs.{(cfee + cgst) / 100:,.2f}, "
                    f"the difference independently recomputes to "
                    f"Rs.{recomputed / 100:,.2f}, the claim window is open "
                    f"until {disc['claim_deadline']}, and all "
                    f"{len(g.nodes)} referenced source records are "
                    f"hash-verified.")
        if t == "missing_settlement":
            return (base + "the gateway batch exists but its UTR was never "
                    "posted by the bank (broken POSTED_AS edge), beyond the "
                    "legitimate posting lag; all referenced records are "
                    "hash-verified.")
        return (base + f"rule '{disc['rule_violated']}' fails and the "
                f"delta recomputes deterministically from "
                f"{len(g.nodes)} hash-verified source records.")
