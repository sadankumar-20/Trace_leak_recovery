"""Trace T8 — portfolio intelligence: clusters, false patterns, prevention.

Individual exceptions -> systemic patterns. The AI (a naive pattern
hypothesizer, same doctrine as T5) may PROPOSE a cluster; a deterministic
challenge layer must confirm it: contract recomputation (a legitimate
intl surcharge is not pricing drift), temporal rules (a T+2 posting is
not a mapping failure), refund-kind checks (a reversal pair is not a sync
bug), and member recounts from source (an AI that says 83 when the
source says 76 gets corrected, not believed). Hidden ground truth is
NEVER an input here — it exists only for the evaluation tests. Recovery
numbers are ACTUAL; prevention numbers are ESTIMATED, labeled, with
assumptions attached, and the two are never summed.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime

from . import gate as G

CLUSTER_RULES = {
    "fee_overcharge": ("Gateway pricing configuration drift",
                       "Correct the merchant pricing tier and submit a "
                       "consolidated contract adjustment.",
                       "fee_recompute"),
    "missing_settlement": ("Recurring bank posting failure",
                           "Add daily UTR-to-bank reconciliation with "
                           "T+1 alerting.", "temporal"),
    "double_refund": ("Refund synchronization bug",
                      "Enforce refund idempotency and add refund-to-"
                      "settlement daily tieout.", "refund_kind"),
    "duplicate_capture": ("Capture integration retry issue",
                          "Enforce gateway request idempotency keyed by "
                          "capture_id.", "capture_count"),
    "rounding_drift": ("Gateway rounding behavior beyond contract",
                       "Tighten per-line rounding validation against the "
                       "contract tolerance.", "fee_recompute"),
    "partial_capture_mismatch": ("Partial-capture settlement mapping "
                                 "failure",
                                 "Reconcile settlements against CAPTURED "
                                 "amounts, not order amounts.",
                                 "fee_recompute"),
    "refund_marked_success_not_settled": (
        "Refund success/settlement divergence",
        "Alert on full refunds with unadjusted settlements within T+1.",
        "refund_kind"),
}
MIN_MEMBERS = 5
HORIZON_WEEKS, EFFECTIVENESS = 10, 0.9
IMPLEMENTATION_COST_PAISE = 25_000


def _gw_of(exc, world):
    tx = next(t for t in world["gateway_txns"]
              if t["id"] in exc["affected_records"]["gateway_txns"])
    return tx["gateway"]


def ai_pattern_hypothesis(members: list[dict], dtype: str, gw: str) -> dict:
    """Naive portfolio AI: proposes cause and (deliberately) rounds the
    member count up to a 'nice' number — deterministic validation must
    correct it."""
    title, prevention, _ = CLUSTER_RULES[dtype]
    return {"suspected_root_cause": title,
            "claimed_affected_count": ((len(members) + 9) // 10) * 10,
            "prevention_hypothesis": prevention,
            "label": "AI PATTERN HYPOTHESIS — UNVERIFIED"}


def _challenge(members, dtype, world, sim_now) -> tuple[bool, str]:
    """Deterministic checks that can kill a proposed cluster."""
    truth = G.recon_truth(world, sim_now)
    kind = CLUSTER_RULES[dtype][2]
    verified = [m for m in members if m["exception_id"] in truth]
    if len(verified) < MIN_MEMBERS:
        return False, (f"only {len(verified)} members recompute "
                       f"deterministically (< {MIN_MEMBERS})")
    if kind == "fee_recompute":
        for m in verified:
            t = truth[m["exception_id"]]
            if t.discrepancy_type != dtype:
                return False, f"{m['exception_id']} recomputes as " \
                              f"{t.discrepancy_type}, not {dtype}"
    if kind == "refund_kind":
        refs = {r["gateway_txn_id"]: [] for r in world["refunds"]}
        for r in world["refunds"]:
            refs[r["gateway_txn_id"]].append(r)
        for m in verified:
            txid = m["affected_records"]["gateway_txns"][0]
            if any(r["kind"] == "reversal" for r in refs.get(txid, [])):
                return False, (f"{m['exception_id']} contains a legitimate "
                               f"reversal — not a sync bug")
    if kind == "temporal":
        for m in verified:
            if truth[m["exception_id"]].discrepancy_type != \
                    "missing_settlement":
                return False, "member is inside the legitimate posting lag"
    return True, "survived contract, refund-kind and temporal challenges"


def build_clusters(exceptions, world, sim_now, recoveries=None) -> list:
    recoveries = {r["exception_id"]: r for r in (recoveries or [])}
    groups = defaultdict(list)
    for e in exceptions:
        groups[(e["discrepancy_type"], _gw_of(e, world))].append(e)
    clusters = []
    for (dtype, gw), members in sorted(groups.items()):
        if dtype not in CLUSTER_RULES or len(members) < MIN_MEMBERS:
            continue
        hyp = ai_pattern_hypothesis(members, dtype, gw)
        ok, why = _challenge(members, dtype, world, sim_now)
        title, prevention, _ = CLUSTER_RULES[dtype]
        gross = sum(abs(m["delta_paise"]) for m in members)
        recov = sum(recoveries[m["exception_id"]]["recovered_paise"]
                    for m in members if m["exception_id"] in recoveries)
        dates = sorted(datetime.fromisoformat(m["created_at"])
                       for m in members)
        weeks = max(1.0, (dates[-1] - dates[0]).days / 7) if len(dates) > 1 \
            else 1.0
        weekly = gross / weeks
        preventable = round(weekly * HORIZON_WEEKS * EFFECTIVENESS)
        c = {"cluster_id": f"cl_{dtype}_{gw}",
             "cluster_type": dtype, "counterparty": gw,
             "cluster_title": f"{gw} — {title}",
             "suspected_root_cause": title,
             "ai_hypothesis": hyp,
             "affected_exception_ids":
                 sorted(m["exception_id"] for m in members),
             "affected_transaction_count": len(members),   # deterministic,
             "ai_claimed_count_corrected":                  # never the AI's
                 hyp["claimed_affected_count"] != len(members),
             "first_seen": dates[0].isoformat(timespec="seconds"),
             "last_seen": dates[-1].isoformat(timespec="seconds"),
             "gross_leakage_paise": gross,
             "recovered_paise": recov,
             "unrecovered_paise": gross - recov,
             "status": "CONFIRMED" if ok else "FALSE_PATTERN",
             "validation_reason": why,
             "pattern_explanation": f"{len(members)} {dtype} exceptions "
                                    f"on {gw} sharing one rule violation",
             "trend": _trend(dates),
             "prevention": None,
             "evidence_bundle_hash": hashlib.sha256(json.dumps(
                 sorted(m["exception_id"] for m in members))
                 .encode()).hexdigest()}
        if ok:
            net_prev = preventable - IMPLEMENTATION_COST_PAISE
            c["prevention"] = {
                "recommendation_id": f"prev_{c['cluster_id']}",
                "problem": c["cluster_title"],
                "proposed_control": prevention,
                "label": "ESTIMATED PREVENTABLE LOSS",
                "assumptions": {"observed_weekly_leak_paise": round(weekly),
                                "horizon_weeks": HORIZON_WEEKS,
                                "mitigation_effectiveness": EFFECTIVENESS,
                                "implementation_cost_paise":
                                    IMPLEMENTATION_COST_PAISE},
                "estimated_preventable_paise": preventable,
                "expected_net_prevention_paise": net_prev,
                "priority": ("CRITICAL" if net_prev > 400_000 else
                             "HIGH" if net_prev > 100_000 else
                             "MEDIUM" if net_prev > 20_000 else "LOW"),
                "monitoring_metric": f"weekly {dtype} rate on {gw}"}
            if gw in ("GatewayA", "GatewayB"):
                c["consolidated_recovery"] = {
                    "counterparty": gw,
                    "affected_exceptions": len(members),
                    "claim_count_reduction": len(members) - 1,
                    "total_recoverable_paise": gross,
                    "required_approval": True,
                    "note": "candidate only — must pass the T6 gates and "
                            "decision engine before any package exists"}
        clusters.append(c)
    return clusters


def _trend(dates) -> str:
    if len(dates) < 4:
        return "NEW"
    mid = dates[0] + (dates[-1] - dates[0]) / 2
    first = sum(1 for d in dates if d <= mid)
    second = len(dates) - first
    if second > first * 1.5:
        return "GROWING"
    if first > second * 1.5:
        return "DECLINING"
    return "STABLE"


def kpis(clusters, recoveries) -> dict:
    confirmed = [c for c in clusters if c["status"] == "CONFIRMED"]
    return {"systemic_leakage_paise": sum(c["gross_leakage_paise"]
                                          for c in confirmed),
            "recovered_from_systemic_paise":
                sum(c["recovered_paise"] for c in confirmed),
            "estimated_preventable_paise":
                sum(c["prevention"]["estimated_preventable_paise"]
                    for c in confirmed),
            "labels": {"recovered": "ACTUAL", "preventable": "ESTIMATED"},
            "active_root_causes": len(confirmed),
            "false_patterns_rejected":
                sum(1 for c in clusters if c["status"] == "FALSE_PATTERN")}
