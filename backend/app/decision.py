"""Trace T6b — the economic decision engine.

Given a SUPPORTED, gate-evaluated exception, compare every admissible
action's expected value under counterparty-specific economics and
deadline risk; select deterministically (highest EV, name-order tie
break); explain every rejection ("why not?"); and, for admissible
selections, emit an immutable action package keyed by exception_id for
the T7 executor. WAIT, ESCALATE, WRITE_OFF and NO_ACTION are first-class
outcomes — action is not always the optimal decision.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from . import gate as G

PROFILES = {
    "GatewayA": {"recovery_probability": 0.91, "sla_days": 2.1,
                 "claim_cost_paise": 4_000, "ops_cost_paise": 1_500,
                 "relationship_risk": 0.10},
    "GatewayB": {"recovery_probability": 0.64, "sla_days": 8.4,
                 "claim_cost_paise": 4_500, "ops_cost_paise": 1_500,
                 "relationship_risk": 0.22},
    "BankC": {"recovery_probability": 0.97, "sla_days": 1.2,
              "claim_cost_paise": 7_000, "ops_cost_paise": 1_500,
              "relationship_risk": 0.05},
    "BankD": {"recovery_probability": 0.80, "sla_days": 3.0,
              "claim_cost_paise": 6_500, "ops_cost_paise": 1_500,
              "relationship_risk": 0.12},
    "customer": {"recovery_probability": 0.50, "sla_days": 7.0,
                 "claim_cost_paise": 3_000, "ops_cost_paise": 1_500,
                 "relationship_risk": 0.30},
}
BANK_FOR_GATEWAY = {"GatewayA": "BankC", "GatewayB": "BankD"}
ACTIONS = ("FILE_GATEWAY_CLAIM", "FILE_BANK_TRACE",
           "REQUEST_CUSTOMER_CLAWBACK", "WAIT", "ESCALATE", "WRITE_OFF",
           "NO_ACTION")
POLICY_VERSION = "t6.1"


def counterparty_name(disc: dict, world: dict) -> str:
    tx = next(t for t in world["gateway_txns"]
              if t["id"] in disc["affected_records"]["gateway_txns"])
    if disc["counterparty"] == "gateway":
        return tx["gateway"]
    if disc["counterparty"] == "bank":
        return BANK_FOR_GATEWAY[tx["gateway"]]
    return "customer"


def decide(disc: dict, verdict: dict, world: dict, sim_now: str,
           prior_claims: int = 0) -> dict:
    now = datetime.fromisoformat(sim_now)
    rec = {"decision_id": f"dec_{disc['exception_id']}",
           "exception_id": disc["exception_id"],
           "policy_version": POLICY_VERSION,
           "decision_timestamp": sim_now, "candidate_actions": [],
           "rejected_actions": {}, "assumptions": {}}

    if verdict["result"] != "SUPPORTED":
        rec.update(selected_action="NO_ACTION",
                   reason=f"investigation verdict {verdict['result']} — "
                          "nothing verified to act on")
        return rec

    cp = counterparty_name(disc, world)
    profile = PROFILES[cp]
    rec["assumptions"] = {"counterparty": cp, **profile}
    party_action = G.ACTION_FOR_PARTY[disc["counterparty"]]
    report = G.evaluate(disc, verdict,
                        proposed_amount=_admissible_amount(disc, world,
                                                           sim_now),
                        proposed_action=party_action, world=world,
                        sim_now=sim_now, profile=profile,
                        prior_claims=prior_claims)
    rec["admissibility"] = report
    amount = report["verified_recoverable_amount_paise"] or 0

    # why-not table for the party-mismatched actions
    for a in ("FILE_GATEWAY_CLAIM", "FILE_BANK_TRACE",
              "REQUEST_CUSTOMER_CLAWBACK"):
        if a != party_action:
            rec["rejected_actions"][a] = (
                f"responsible party is {disc['counterparty']}; "
                f"{a} targets a party that does not owe this amount")

    deadline = datetime.fromisoformat(disc["claim_deadline"])
    hours_left = (deadline - now).total_seconds() / 3600

    if report["gate_results"]["eligibility"] == "FAIL":
        rec.update(selected_action="ESCALATE",
                   reason="claim window EXPIRED — filing is impossible; "
                          "human review for internal remediation")
        return rec
    if not report["final_admissibility"] and \
            report["gate_results"]["economic_viability"] == "FAIL" and \
            not report["failed_gates"] == []:
        other_fails = [g for g in report["failed_gates"]
                       if g != "economic_viability"]
        if not other_fails:
            rec.update(selected_action="WRITE_OFF",
                       reason=f"verified leakage exists ({amount}p) but "
                              f"expected net "
                              f"{report['expected_net_paise']}p is below "
                              f"the cost-to-recover threshold "
                              f"{G.MIN_EXPECTED_NET_PAISE}p")
            rec["rejected_actions"][party_action] = \
                "economically not worth pursuing"
            return rec
    if report["failed_gates"]:
        rec.update(selected_action="NO_ACTION",
                   reason=f"admissibility failed: {report['reason']}")
        return rec
    if hours_left < profile["sla_days"] * 24:
        rec.update(selected_action="ESCALATE",
                   reason=f"deadline risk: {hours_left:.0f}h remain but "
                          f"{cp} SLA is {profile['sla_days']}d — normal "
                          f"filing cannot complete in time")
        rec["rejected_actions"][party_action] = "deadline shorter than SLA"
        return rec
    if report["required_approval"]:
        rec.update(selected_action="ESCALATE",
                   reason=f"amount requires human approval "
                          f"(>= Rs.{G.APPROVAL_THRESHOLD_PAISE / 100:,.0f})")
        return rec

    ev = G.expected_net(amount, profile)
    rec["candidate_actions"].append(
        {"action": party_action, **ev, "recovery_probability":
         profile["recovery_probability"], "sla_days": profile["sla_days"]})
    rec["rejected_actions"]["WRITE_OFF"] = (
        f"expected net {ev['expected_net_paise']}p exceeds the threshold")
    rec.update(selected_action=party_action,
               reason=f"highest admissible expected net: "
                      f"{ev['expected_net_paise']}p via {cp} "
                      f"(p={profile['recovery_probability']}, "
                      f"cost={ev['total_cost_paise']}p)")
    rec["action_package"] = _package(disc, report, party_action, cp)
    return rec


def _admissible_amount(disc, world, sim_now):
    t = G.recon_truth(world, sim_now).get(disc["exception_id"])
    if not t:
        return 0
    return (t.actual_paise - t.expected_paise
            if t.discrepancy_type == "double_refund"
            else abs(t.delta_paise))


def _package(disc, report, action, cp) -> dict:
    pkg = {"exception_id": disc["exception_id"],
           "selected_action": action,
           "claim_amount_paise":
               report["verified_recoverable_amount_paise"],
           "responsible_counterparty": cp,
           "evidence_ids": sorted(
               i for ids in disc["affected_records"].values() for i in ids),
           "policy_version": POLICY_VERSION,
           "expected_net_paise": report["expected_net_paise"],
           "required_approval": report["required_approval"],
           "idempotency_key": disc["exception_id"]}
    pkg["package_hash"] = hashlib.sha256(
        json.dumps(pkg, sort_keys=True).encode()).hexdigest()
    return pkg
