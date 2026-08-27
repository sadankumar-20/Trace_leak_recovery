"""Trace T5b — the AI investigator + the containment layer.

The investigator is a bounded agentic loop over read-only tools that
emits a STRUCTURED hypothesis — never prose-as-truth. Its heuristics are
DELIBERATELY naive (they ignore reversal kinds, international surcharges,
contract tolerance, and posting lags), because a containment architecture
is only proven if the AI can genuinely be wrong. The deterministic
validator then: (1) rejects any evidence reference that doesn't resolve
to a real source record, (2) recomputes the claim through the T2
reconciliation engine, and (3) marks the hypothesis SUPPORTED, CONTAINED
(wrong, caught), or INSUFFICIENT_EVIDENCE. The AI never declares
CLAIMABLE; the validator's verdict is what the T6 gate will receive.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .audit import AuditChain
from .recon import ReconciliationEngine
from .tools import ToolError, ToolRegistry

HYPOTHESIS_TYPES = ("fee_overcharge", "missing_settlement", "double_refund",
                    "refund_marked_success_not_settled",
                    "partial_capture_mismatch", "duplicate_capture",
                    "rounding_drift", "legitimate_difference",
                    "insufficient_evidence", "unknown")
INVESTIGATION_STATES = ("NOT_STARTED", "INVESTIGATING",
                        "WAITING_FOR_EVIDENCE", "HYPOTHESIS_FORMED",
                        "VALIDATING", "CONTAINED", "SUPPORTED",
                        "REJECTED", "INSUFFICIENT_EVIDENCE", "COMPLETED")
PLAYBOOK = {   # tool-selection per exception type (spec) — not conclusions
    "fee_overcharge": ("get_order", "get_gateway_txn", "get_fee_schedule"),
    "missing_settlement": ("get_order", "get_gateway_txn",
                           "get_settlement_batch", "trace_utr",
                           "search_knowledge"),
    "double_refund": ("get_order", "get_refund_chain", "get_gateway_txn"),
    "refund_marked_success_not_settled": ("get_refund_chain",
                                          "get_settlement_batch",
                                          "trace_utr", "search_knowledge"),
    "partial_capture_mismatch": ("get_order", "get_gateway_txn",
                                 "get_settlement_batch"),
}
DEFAULT_PLAN = ("get_order", "get_gateway_txn", "get_settlement_batch",
                "get_refund_chain", "get_fee_schedule")


@dataclass
class Hypothesis:
    hypothesis_id: str
    exception_id: str
    hypothesis_type: str
    suspected_leak_paise: int
    affected_objects: list
    supporting_evidence: list
    contradicting_evidence: list
    missing_information: list
    recommended_next_step: str
    confidence: float
    rationale_summary: str            # explanatory ONLY, never truth
    tool_trace: list
    investigation_status: str


def investigate(exc: dict, world: dict, chain: AuditChain,
                now: datetime) -> Hypothesis:
    """Bounded loop: plan -> tools -> observe -> hypothesize (naively)."""
    reg = ToolRegistry(world)
    chain.append(f"case_{exc['exception_id']}", "INVESTIGATION_STARTED",
                 {"exception_id": exc["exception_id"]}, now)
    txn_id = exc["affected_records"]["gateway_txns"][0]
    seen, ev = {}, []
    plan = PLAYBOOK.get(exc["discrepancy_type"], DEFAULT_PLAN)
    for tool in plan:
        try:
            if tool == "get_order":
                seen["order"] = reg.get_order(exc["order_id"])
            elif tool == "get_gateway_txn":
                seen["txn"] = reg.get_gateway_txn(txn_id)
            elif tool == "get_settlement_batch":
                seen["settle"] = reg.get_settlement_batch(txn_id)
            elif tool == "trace_utr":
                seen["utr"] = reg.trace_utr(
                    seen["settle"]["batch"]["utr"]) if "settle" in seen \
                    else None
            elif tool == "get_refund_chain":
                seen["refunds"] = reg.get_refund_chain(txn_id)
            elif tool == "get_fee_schedule":
                seen["fs"] = reg.get_fee_schedule(
                    seen.get("txn", {}).get("gateway", ""))
            elif tool == "search_knowledge":
                seen["kb"] = reg.search_knowledge("settlement")
        except ToolError:
            continue
    # an investigator that notices missing core records goes and gets
    # them (still bounded by the tool budget)
    if "txn" not in seen or seen.get("txn") is None:
        try:
            seen["txn"] = reg.get_gateway_txn(txn_id)
        except ToolError:
            pass
    if "order" not in seen or seen.get("order") is None:
        try:
            seen["order"] = reg.get_order(exc["order_id"])
        except ToolError:
            pass
    for k in ("order", "txn"):
        if k in seen and seen[k]:
            ev.append(seen[k]["id"])
    if seen.get("settle"):
        ev += [seen["settle"]["line"]["id"], seen["settle"]["batch"]["id"]]
    ev += [r["id"] for r in seen.get("refunds", []) or []]
    if seen.get("fs"):
        ev.append(seen["fs"]["id"])
    chain.append(f"case_{exc['exception_id']}", "EVIDENCE_RETRIEVED",
                 {"ids": ev, "tools": len(reg.trace)}, now)

    # ---- the deliberately NAIVE hypothesis heuristics ----
    htype, amount, contra, why = "unknown", 0, [], ""
    txn, order, fs = seen.get("txn"), seen.get("order"), seen.get("fs")
    refunds = seen.get("refunds") or []
    if txn is None or order is None:
        htype, why = "insufficient_evidence", "core records unavailable"
    else:
        plain_amts = [abs(r["amount_paise"]) for r in refunds]
        if len(refunds) == 1 and refunds[0]["kind"] == "refund" \
                and refunds[0]["amount_paise"] == txn["amount_paise"]:
            htype, amount = "refund_marked_success_not_settled", 0
            why = ("full-amount refund marked processed while settlement "
                   "retained the full net")
        elif len(refunds) >= 2 and len(set(plain_amts[:2])) == 1:
            # NAIVE: ignores kind=reversal
            htype, amount = "double_refund", plain_amts[0]
            why = "two refunds of identical amount observed"
        elif fs and (txn["fee_paise"] + txn["gst_paise"]) > (
                round(txn["amount_paise"] * fs["mdr_pct"] / 100)
                + round(round(txn["amount_paise"] * fs["mdr_pct"] / 100)
                        * fs["gst_pct"] / 100)):
            # NAIVE: ignores intl surcharge AND contract tolerance
            cfee = round(txn["amount_paise"] * fs["mdr_pct"] / 100)
            cgst = round(cfee * fs["gst_pct"] / 100)
            htype = "fee_overcharge"
            amount = (txn["fee_paise"] + txn["gst_paise"]) - (cfee + cgst)
            why = "charged fee exceeds base MDR"
        elif seen.get("utr") and not seen["utr"]["posted"]:
            # NAIVE: ignores legitimate posting lag
            htype = "missing_settlement"
            amount = seen["settle"]["line"]["net_paise"]
            why = "batch UTR absent from bank statement"
        elif seen.get("settle") and (txn["amount_paise"] - txn["fee_paise"]
                - txn["gst_paise"]) > seen["settle"]["line"]["net_paise"]:
            short = (txn["amount_paise"] - txn["fee_paise"]
                     - txn["gst_paise"]) - seen["settle"]["line"]["net_paise"]
            cap_partial = order and txn["amount_paise"] < \
                order["amount_paise"]
            htype = ("partial_capture_mismatch" if cap_partial
                     else "rounding_drift")
            amount = short
            why = "settlement line short of charged expectation"
        else:
            htype, why = "legitimate_difference", "figures tie out"
    hyp = Hypothesis(
        hypothesis_id=f"hyp_{exc['exception_id']}",
        exception_id=exc["exception_id"], hypothesis_type=htype,
        suspected_leak_paise=amount, affected_objects=[txn_id],
        supporting_evidence=ev, contradicting_evidence=contra,
        missing_information=[] if txn else ["gateway_txn"],
        recommended_next_step="deterministic_validation",
        confidence=0.7 if htype not in ("insufficient_evidence", "unknown")
        else 0.2,
        rationale_summary=f"AI HYPOTHESIS (unverified): {why}",
        tool_trace=reg.trace,
        investigation_status="HYPOTHESIS_FORMED")
    if htype not in HYPOTHESIS_TYPES:
        raise ValueError(f"unsupported hypothesis type {htype!r}")
    chain.append(f"case_{exc['exception_id']}", "HYPOTHESIS_CREATED",
                 {"type": htype, "amount_paise": amount,
                  "evidence": len(ev)}, now)
    return hyp


def validate(hyp: Hypothesis, world: dict, sim_now: str,
             chain: AuditChain, now: datetime) -> dict:
    """Containment: evidence grounding -> deterministic recomputation."""
    all_ids = set()
    for rows in world.values():
        all_ids |= {r["id"] for r in rows}
    fabricated = [e for e in hyp.supporting_evidence if e not in all_ids]
    verdict = {"hypothesis_id": hyp.hypothesis_id, "fabricated_evidence":
               fabricated, "checks": []}
    if fabricated:
        verdict["result"] = "CONTAINED"
        verdict["checks"].append(("evidence_grounding", "FAIL",
                                  f"unknown ids {fabricated}"))
    elif hyp.hypothesis_type in ("insufficient_evidence", "unknown"):
        verdict["result"] = "INSUFFICIENT_EVIDENCE"
    else:
        verdict["checks"].append(("evidence_grounding", "PASS", ""))
        eng = ReconciliationEngine(world, sim_now)
        res = next(r for r in eng.run()
                   if r.txn_id in hyp.affected_objects
                   or (r.discrepancy and r.discrepancy.exception_id
                       == hyp.exception_id))
        truth_type = (res.discrepancy.discrepancy_type
                      if res.discrepancy else "legitimate_difference")
        truth_amt = abs(res.discrepancy.delta_paise) if res.discrepancy \
            else 0
        if hyp.hypothesis_type == "double_refund" and res.discrepancy:
            truth_amt = res.discrepancy.actual_paise \
                - res.discrepancy.expected_paise
        agrees = (hyp.hypothesis_type == truth_type
                  and (truth_type == "legitimate_difference"
                       or hyp.suspected_leak_paise == truth_amt
                       or truth_type ==
                       "refund_marked_success_not_settled"))
        verdict["checks"].append(("deterministic_recomputation",
                                  "PASS" if agrees else "FAIL",
                                  f"truth={truth_type}:{truth_amt}p vs "
                                  f"AI={hyp.hypothesis_type}:"
                                  f"{hyp.suspected_leak_paise}p"))
        verdict["result"] = "SUPPORTED" if agrees else "CONTAINED"
    chain.append(f"case_{hyp.exception_id}",
                 "GATE_PASSED" if verdict["result"] == "SUPPORTED"
                 else "GATE_FAILED",
                 {"stage": "containment", "result": verdict["result"]},
                 now)
    return verdict


def report(exc: dict, hyp: Hypothesis, verdict: dict) -> dict:
    return {"appeared_to_be": exc["discrepancy_type"],
            "evidence_inspected": hyp.supporting_evidence,
            "tools_used": [t["tool"] for t in hyp.tool_trace if t["ok"]],
            "hypothesis": {"type": hyp.hypothesis_type,
                           "amount_paise": hyp.suspected_leak_paise,
                           "label": "AI HYPOTHESIS — UNVERIFIED"},
            "contradicting_evidence": hyp.contradicting_evidence,
            "validation": verdict["checks"],
            "verdict": verdict["result"],
            "ready_for_admissibility_gate":
                verdict["result"] == "SUPPORTED"}
