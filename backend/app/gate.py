"""Trace T6a — the Claim Admissibility Gate: eight deterministic checks.

No single positive signal files a claim. Each gate returns PASS / FAIL /
NOT_APPLICABLE / REQUIRES_APPROVAL with a reason; the report never
collapses to one boolean. Nothing here trusts the AI: amounts, rules and
lineage are recomputed from source records every time.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .evidence import EvidenceGraphBuilder
from .models import record_hash
from .recon import ReconciliationEngine

_TRUTH_CACHE: dict = {}


def recon_truth(world: dict, sim_now: str) -> dict:
    """exception_id -> Discrepancy, computed once per (world, sim_now).
    Reconciliation is deterministic, so memoizing is safe — and turns the
    per-decision cost from a 5,000-txn scan into a dict lookup."""
    key = (id(world), sim_now)
    if key not in _TRUTH_CACHE:
        eng = ReconciliationEngine(world, sim_now)
        _TRUTH_CACHE[key] = {r.discrepancy.exception_id: r.discrepancy
                             for r in eng.run() if r.discrepancy}
    return _TRUTH_CACHE[key]

GATES = ("data_integrity", "reconciliation_proof", "contract_proof",
         "eligibility", "recoverability", "amount_integrity",
         "economic_viability", "risk")
ACTION_FOR_PARTY = {"gateway": "FILE_GATEWAY_CLAIM",
                    "bank": "FILE_BANK_TRACE",
                    "customer": "REQUEST_CUSTOMER_CLAWBACK"}
MIN_EXPECTED_NET_PAISE = 1_000          # the stopping-rule threshold
APPROVAL_THRESHOLD_PAISE = 500_000     # >= Rs.5,000 needs a human
CLAIMS_PER_COUNTERPARTY_LIMIT = 200


def evaluate(disc: dict, verdict: dict, proposed_amount: int,
             proposed_action: str, world: dict, sim_now: str,
             profile: dict, prior_claims: int = 0) -> dict:
    now = datetime.fromisoformat(sim_now)
    results, reasons = {}, {}

    def gate(name, status, reason=""):
        results[name] = status
        reasons[name] = reason

    # ---- Gate 1: data integrity (records exist, hashes intact, lineage) --
    rows = {t: {r["id"]: r for r in v} for t, v in world.items()}
    bad = []
    for table, ids in disc["affected_records"].items():
        for i in ids:
            row = rows.get(table, {}).get(i)
            if row is None:
                bad.append(f"missing {table}:{i}")
                continue
            body = {k: v for k, v in row.items() if k != "record_hash"}
            if record_hash(body) != row["record_hash"]:
                bad.append(f"hash invalid {table}:{i}")
    graph = None
    if not bad:
        graph = EvidenceGraphBuilder(world).build(disc)
        broken = {e["type"] for e in graph.broken_edges()}
        allowed_broken = {"POSTED_AS"} if disc["discrepancy_type"] == \
            "missing_settlement" else set()
        if broken - allowed_broken:
            bad.append(f"unexpected broken lineage {broken}")
    gate("data_integrity", "FAIL" if bad else "PASS", "; ".join(bad))

    # ---- Gate 2: reconciliation proof (recompute from sources) ----------
    truth = None
    if not bad:
        truth = recon_truth(world, sim_now).get(disc["exception_id"])
        gate("reconciliation_proof",
             "PASS" if truth else "FAIL",
             "" if truth else "discrepancy does not recompute from sources")
    else:
        gate("reconciliation_proof", "NOT_APPLICABLE", "gate 1 failed")

    # ---- Gate 3: contract/rule proof ------------------------------------
    if truth:
        gate("contract_proof",
             "PASS" if truth.rule_violated else "FAIL",
             f"rule: {truth.rule_violated}")
    else:
        gate("contract_proof", "NOT_APPLICABLE", "no recomputed discrepancy")

    # ---- Gate 4: eligibility window --------------------------------------
    deadline = datetime.fromisoformat(disc["claim_deadline"])
    remaining_h = (deadline - now).total_seconds() / 3600
    gate("eligibility", "PASS" if remaining_h > 0 else "FAIL",
         f"{'ELIGIBLE' if remaining_h > 0 else 'EXPIRED'}; "
         f"{remaining_h:.1f}h remaining")

    # ---- Gate 5: recoverability (party matches action) ------------------
    want = ACTION_FOR_PARTY.get(disc["counterparty"])
    gate("recoverability",
         "PASS" if proposed_action == want else "FAIL",
         f"responsible={disc['counterparty']} requires {want}, "
         f"proposed {proposed_action}")

    # ---- Gate 6: amount integrity (exact, to the paisa) ------------------
    admissible_amt = None
    if truth:
        admissible_amt = (truth.actual_paise - truth.expected_paise
                          if truth.discrepancy_type == "double_refund"
                          else abs(truth.delta_paise))
        ok = (proposed_amount == admissible_amt and proposed_amount > 0)
        gate("amount_integrity", "PASS" if ok else "FAIL",
             f"proposed {proposed_amount}p vs recomputed "
             f"{admissible_amt}p")
    else:
        gate("amount_integrity", "NOT_APPLICABLE", "no recomputed amount")

    # ---- Gate 7: economic viability (the stopping rule) ------------------
    ev = expected_net(admissible_amt or 0, profile)
    gate("economic_viability",
         "PASS" if ev["expected_net_paise"] >= MIN_EXPECTED_NET_PAISE
         else "FAIL",
         f"expected net {ev['expected_net_paise']}p vs threshold "
         f"{MIN_EXPECTED_NET_PAISE}p — "
         + ("financially admissible" if ev["expected_net_paise"]
            >= MIN_EXPECTED_NET_PAISE else
            "economically not worth pursuing"))

    # ---- Gate 8: relationship / compliance risk ---------------------------
    if prior_claims >= CLAIMS_PER_COUNTERPARTY_LIMIT:
        gate("risk", "FAIL", "counterparty claim-frequency limit reached")
    elif (admissible_amt or 0) >= APPROVAL_THRESHOLD_PAISE:
        gate("risk", "REQUIRES_APPROVAL",
             f"amount >= Rs.{APPROVAL_THRESHOLD_PAISE / 100:,.0f} "
             f"approval threshold")
    else:
        gate("risk", "PASS", f"relationship risk "
             f"{profile['relationship_risk']:.2f} within bounds")

    failed = [g for g in GATES if results[g] == "FAIL"]
    admissible = not failed and results["risk"] != "FAIL"
    return {"exception_id": disc["exception_id"],
            "claim_type": disc["discrepancy_type"],
            "responsible_counterparty": disc["counterparty"],
            "verified_leak_amount_paise": admissible_amt,
            "verified_recoverable_amount_paise": admissible_amt,
            "proposed_claim_amount_paise": proposed_amount,
            "gate_results": results, "gate_reasons": reasons,
            "failed_gates": failed,
            "eligibility_deadline": disc["claim_deadline"],
            "expected_recovery_paise": ev["expected_gross_paise"],
            "expected_cost_paise": ev["total_cost_paise"],
            "expected_net_paise": ev["expected_net_paise"],
            "risk_score": profile["relationship_risk"],
            "required_approval": results["risk"] == "REQUIRES_APPROVAL",
            "final_admissibility": admissible,
            "reason": "; ".join(f"{g}:{reasons[g]}" for g in failed)
                      or "all gates passed"}


def expected_net(amount_paise: int, profile: dict) -> dict:
    gross = round(amount_paise * profile["recovery_probability"])
    cost = (profile["claim_cost_paise"] + profile["ops_cost_paise"]
            + round(amount_paise * profile["relationship_risk"] * 0.02))
    return {"expected_gross_paise": gross, "total_cost_paise": cost,
            "expected_net_paise": gross - cost}
