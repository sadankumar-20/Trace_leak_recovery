"""Trace T7b — the bounded, idempotent executor.

The only layer that touches a counterparty, and it accepts exactly one
input: an unmodified T6 action package. Before anything is sent it
independently re-verifies the package (hash, recomputed amount, party-
bound action, open window, approval) against authoritative state — never
trusting the caller. The invariant: ONE exception_id -> AT MOST ONE
ACTIVE EXECUTION, enforced under a lock, across retries, timeouts,
restarts and duplicates. Timeout-after-receipt resolves the existing
counterparty claim instead of filing a second one. Recovery is derived
state in its own ledger; source records are never mutated.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime

from . import gate as G
from .counterparty import (CounterpartySim, CounterpartyUnavailable,
                           TimeoutAfterReceipt, TimeoutBeforeReceipt)

EXEC_STATES = ("READY", "VALIDATING", "SUBMITTING", "PENDING",
               "RETRY_REQUIRED", "RESOLVING", "SUCCEEDED",
               "PARTIALLY_RECOVERED", "REJECTED", "NEEDS_INFORMATION",
               "ESCALATION_REQUIRED", "FAILED_SAFE")
TERMINAL = {"SUCCEEDED", "PARTIALLY_RECOVERED", "REJECTED",
            "NEEDS_INFORMATION", "ESCALATION_REQUIRED", "FAILED_SAFE"}
MAX_ATTEMPTS = 3
STATUS_TO_STATE = {"ACCEPTED": "SUCCEEDED",
                   "PARTIALLY_RECOVERED": "PARTIALLY_RECOVERED",
                   "REJECTED": "REJECTED", "EXPIRED": "REJECTED",
                   "NO_RECOVERABLE_AMOUNT": "REJECTED",
                   "NEEDS_INFORMATION": "NEEDS_INFORMATION",
                   "DUPLICATE": None}


class ExecutionBlocked(RuntimeError):
    pass


def _pkg_hash(pkg: dict) -> str:
    body = {k: v for k, v in pkg.items() if k != "package_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True)
                          .encode()).hexdigest()


class Executor:
    def __init__(self, world: dict, sim_now: str, cp: CounterpartySim,
                 chain):
        self.world, self.sim_now, self.cp, self.chain = (world, sim_now,
                                                         cp, chain)
        self.ledger: dict[str, dict] = {}        # idempotency ledger
        self.recoveries: list[dict] = []
        self.blocked: list[dict] = []
        self._lock = threading.Lock()

    # -------------------------- verification --------------------------
    def verify_package(self, pkg: dict, approval: bool) -> None:
        if _pkg_hash(pkg) != pkg.get("package_hash"):
            raise ExecutionBlocked("package hash invalid — tampering")
        truth = G.recon_truth(self.world, self.sim_now).get(
            pkg["exception_id"])
        if truth is None:
            raise ExecutionBlocked("no such verified exception")
        true_amt = (truth.actual_paise - truth.expected_paise
                    if truth.discrepancy_type == "double_refund"
                    else abs(truth.delta_paise))
        if pkg["claim_amount_paise"] != true_amt:
            raise ExecutionBlocked("claim amount no longer matches the "
                                   "recomputed recoverable amount")
        want = G.ACTION_FOR_PARTY[truth.counterparty]
        if pkg["selected_action"] != want:
            raise ExecutionBlocked("action does not match responsible "
                                   "party")
        if self.sim_now > truth.claim_deadline:
            raise ExecutionBlocked("claim window expired")
        if pkg.get("required_approval") and not approval:
            raise ExecutionBlocked("required human approval missing")

    # ---------------------------- execution ---------------------------
    def execute(self, pkg: dict, approval: bool = False,
                now: datetime | None = None) -> dict:
        now = now or datetime.fromisoformat(self.sim_now)
        key = pkg.get("idempotency_key")
        with self._lock:
            existing = self.ledger.get(key)
            if existing:
                if existing["execution_status"] in TERMINAL:
                    return existing               # retry after terminal
                existing["execution_status"] = "RESOLVING"
            else:
                try:
                    self.verify_package(pkg, approval)
                except ExecutionBlocked as e:
                    self.blocked.append({"exception_id":
                                         pkg.get("exception_id"),
                                         "reason": str(e)})
                    self.chain.append(f"case_{pkg.get('exception_id')}",
                                      "GATE_FAILED",
                                      {"stage": "executor_verify",
                                       "reason": str(e)}, now)
                    raise
                self.ledger[key] = {
                    "exception_id": pkg["exception_id"],
                    "execution_id": f"exe_{pkg['exception_id']}",
                    "action_package_hash": pkg["package_hash"],
                    "counterparty_id": pkg["responsible_counterparty"],
                    "action": pkg["selected_action"],
                    "execution_status": "SUBMITTING", "attempt_count": 0,
                    "first_attempt_at": now.isoformat(timespec="seconds"),
                    "last_attempt_at": None, "completed_at": None,
                    "counterparty_reference": None,
                    "recovered_amount_paise": 0,
                    "final_response_hash": None}
                self.chain.append(f"case_{pkg['exception_id']}",
                                  "CLAIM_FILED",
                                  {"package_hash": pkg["package_hash"],
                                   "amount_paise":
                                       pkg["claim_amount_paise"]}, now)
            rec = self.ledger[key]
        return self._drive(pkg, rec, now)

    def _drive(self, pkg: dict, rec: dict, now: datetime) -> dict:
        key = pkg["idempotency_key"]
        while rec["execution_status"] not in TERMINAL:
            if rec["attempt_count"] >= MAX_ATTEMPTS:
                rec["execution_status"] = "FAILED_SAFE"
                break
            rec["attempt_count"] += 1
            rec["last_attempt_at"] = now.isoformat(timespec="seconds")
            try:
                if key in self.cp.received:      # resolve, never resubmit
                    resp = dict(self.cp.claims[key],
                                response_status=self.cp.claims[key]
                                ["response_status"])
                else:
                    resp = self.cp.adjudicate(
                        pkg, now.isoformat(timespec="seconds"))
            except TimeoutBeforeReceipt:
                rec["execution_status"] = "RETRY_REQUIRED"
                continue                          # safe: never received
            except TimeoutAfterReceipt:
                rec["execution_status"] = "PENDING"
                continue                          # resolve on next pass
            except CounterpartyUnavailable:
                rec["execution_status"] = "RETRY_REQUIRED"
                continue
            self._settle(pkg, rec, resp, now)
        return rec

    def _settle(self, pkg: dict, rec: dict, resp: dict, now: datetime):
        req = pkg["claim_amount_paise"]
        recov = resp["recovered_amount_paise"]
        appr = resp["approved_amount_paise"]
        if recov > req or appr > req or recov > appr:
            rec["execution_status"] = "FAILED_SAFE"     # malformed money
            self.chain.append(f"case_{pkg['exception_id']}",
                              "COUNTERPARTY_RESPONDED",
                              {"status": "MALFORMED",
                               "reason": "recovery exceeds claim"}, now)
            return
        state = STATUS_TO_STATE.get(resp["response_status"])
        if state is None:                    # DUPLICATE -> adopt original
            resp = self.cp.claims[pkg["idempotency_key"]]
            state = STATUS_TO_STATE[resp["response_status"]]
            recov, appr = (resp["recovered_amount_paise"],
                           resp["approved_amount_paise"])
        rec["execution_status"] = state
        rec["completed_at"] = now.isoformat(timespec="seconds")
        rec["counterparty_reference"] = resp["counterparty_reference"]
        rec["recovered_amount_paise"] = recov
        rec["final_response_hash"] = hashlib.sha256(
            json.dumps(resp, sort_keys=True).encode()).hexdigest()
        self.chain.append(f"case_{pkg['exception_id']}",
                          "COUNTERPARTY_RESPONDED",
                          {"status": resp["response_status"],
                           "approved_paise": appr,
                           "reference": resp["counterparty_reference"]},
                          now)
        if recov > 0 and not any(r["exception_id"] == rec["exception_id"]
                                 for r in self.recoveries):
            profile_cost = 0
            from .decision import PROFILES
            p = PROFILES.get(rec["counterparty_id"], PROFILES["customer"])
            profile_cost = p["claim_cost_paise"] + p["ops_cost_paise"]
            self.recoveries.append({
                "recovery_id": f"rcv_{rec['exception_id']}",
                "exception_id": rec["exception_id"],
                "execution_id": rec["execution_id"],
                "claimed_paise": req, "approved_paise": appr,
                "recovered_paise": recov,
                "unrecovered_paise": req - recov,
                "recovery_cost_paise": profile_cost,
                "net_recovery_paise": recov - profile_cost,
                "counterparty_reference": resp["counterparty_reference"],
                "status": rec["execution_status"],
                "at": rec["completed_at"]})
            self.chain.append(f"case_{pkg['exception_id']}",
                              "RECOVERY_RECEIVED",
                              {"recovered_paise": recov,
                               "net_paise": recov - profile_cost}, now)
        elif state == "REJECTED":
            self.chain.append(f"case_{pkg['exception_id']}",
                              "CLAIM_REJECTED",
                              {"reason": resp["rejection_reason"]}, now)

    # ---------------------------- monitors ----------------------------
    def monitors(self) -> dict:
        vals = list(self.ledger.values())
        return {"total_execution_requests": len(vals),
                "unique_exceptions": len({v["exception_id"] for v in vals}),
                "double_executions": len(vals)
                - len({v["exception_id"] for v in vals}),
                "unauthorized_blocked": len(self.blocked),
                "gross_recovered_paise": sum(r["recovered_paise"]
                                             for r in self.recoveries),
                "net_recovered_paise": sum(r["net_recovery_paise"]
                                           for r in self.recoveries),
                "by_state": {s: sum(1 for v in vals
                                    if v["execution_status"] == s)
                             for s in EXEC_STATES
                             if any(v["execution_status"] == s
                                    for v in vals)}}
