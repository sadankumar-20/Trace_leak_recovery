"""Trace T7a — the counterparty simulation.

GatewayA/B, BankC/D (and the customer desk) adjudicate claims against
their own authoritative records: the source world plus hidden ground
truth outcomes. Nothing here trusts the submitted amount — the
counterparty independently recomputes what is actually recoverable and
approves, partially approves, or rejects per its deterministic profile.
Hidden ground truth never leaves this module: responses carry outcomes
and references, never labels. All randomness is a seeded hash of the
exception id, so the same world + config reproduces byte-identical
adjudication. Failure injection (timeout before/after receipt, transient,
malformed, unavailable) is a deterministic per-exception plan consumed
attempt by attempt.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from . import gate as G
from .decision import PROFILES


class TimeoutBeforeReceipt(RuntimeError):
    """The request never reached the counterparty."""


class TimeoutAfterReceipt(RuntimeError):
    """The counterparty processed the claim but the response was lost."""


class CounterpartyUnavailable(RuntimeError):
    pass


def _det(exception_id: str, salt: str, seed: int) -> float:
    h = hashlib.sha256(f"{seed}:{salt}:{exception_id}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class CounterpartySim:
    def __init__(self, world: dict, gt: dict, sim_now: str, seed: int = 42,
                 failure_plan: dict | None = None):
        self.world, self.gt, self.sim_now = world, gt, sim_now
        self.seed = seed
        self.failure_plan = {k: list(v)
                             for k, v in (failure_plan or {}).items()}
        self.claims: dict[str, dict] = {}     # idempotency_key -> response
        self.received: set[str] = set()

    def _inject(self, exception_id: str):
        plan = self.failure_plan.get(exception_id)
        if plan:
            mode = plan.pop(0)
            if mode == "timeout_before":
                raise TimeoutBeforeReceipt(exception_id)
            if mode == "unavailable":
                raise CounterpartyUnavailable(exception_id)
            return mode          # timeout_after / malformed / normal
        return "normal"

    def adjudicate(self, package: dict, submitted_at: str) -> dict:
        key = package["idempotency_key"]
        mode = self._inject(key)               # may raise (never received)
        if key in self.claims:                 # duplicate: same claim back
            return dict(self.claims[key], response_status="DUPLICATE")
        self.received.add(key)
        resp = self._decide(package, submitted_at)
        self.claims[key] = resp
        if mode == "timeout_after":
            raise TimeoutAfterReceipt(key)     # processed, response lost
        if mode == "malformed":
            bad = dict(resp)
            bad["recovered_amount_paise"] = \
                resp["requested_amount_paise"] * 10   # impossible money
            return bad
        return resp

    def _decide(self, pkg: dict, submitted_at: str) -> dict:
        cp = pkg["responsible_counterparty"]
        exc_id = pkg["exception_id"]
        order_id = exc_id.split("_", 2)[-1].replace("gtx", "ord") \
            if False else None
        truth = G.recon_truth(self.world, self.sim_now).get(exc_id)
        g = None
        if truth:
            g = self.gt.get(truth.order_id)
        base = {"counterparty_id": cp, "claim_id": f"clm_{exc_id}",
                "exception_id": exc_id,
                "requested_amount_paise": pkg["claim_amount_paise"],
                "approved_amount_paise": 0, "recovered_amount_paise": 0,
                "rejection_reason": None, "required_information": None,
                "response_at": self._latency(exc_id, cp, submitted_at),
                "counterparty_reference": f"ref_{cp}_{exc_id[-8:]}"}
        if pkg["selected_action"] not in ("FILE_GATEWAY_CLAIM",
                                          "FILE_BANK_TRACE",
                                          "REQUEST_CUSTOMER_CLAWBACK"):
            return dict(base, response_status="REJECTED",
                        rejection_reason="unsupported action")
        if truth is None or g is None:
            return dict(base, response_status="NO_RECOVERABLE_AMOUNT",
                        rejection_reason="no such recoverable exception "
                                         "in counterparty records")
        want_party = truth.counterparty
        got_party = ("gateway" if pkg["selected_action"] ==
                     "FILE_GATEWAY_CLAIM" else
                     "bank" if pkg["selected_action"] == "FILE_BANK_TRACE"
                     else "customer")
        if want_party != got_party:
            return dict(base, response_status="REJECTED",
                        rejection_reason="claim addressed to a party that "
                                         "does not owe this amount")
        if submitted_at > truth.claim_deadline:
            return dict(base, response_status="EXPIRED",
                        rejection_reason="claim window closed")
        true_amt = (truth.actual_paise - truth.expected_paise
                    if truth.discrepancy_type == "double_refund"
                    else abs(truth.delta_paise))
        req = pkg["claim_amount_paise"]
        if req > true_amt:
            return dict(base, response_status="PARTIALLY_RECOVERED",
                        approved_amount_paise=true_amt,
                        recovered_amount_paise=true_amt,
                        rejection_reason="requested exceeds recoverable; "
                                         "approved at verified amount")
        outcome = g["outcome_if_claimed"]
        if outcome == "rejected":
            return dict(base, response_status="REJECTED",
                        rejection_reason=g.get("rejection_reason")
                        or "per counterparty review")
        if outcome == "needs_information":
            return dict(base, response_status="NEEDS_INFORMATION",
                        required_information="supporting settlement "
                                             "statement")
        if outcome == "partially_approved":
            frac = 0.5 + 0.4 * _det(exc_id, "partial", self.seed)
            amt = round(req * frac)
            return dict(base, response_status="PARTIALLY_RECOVERED",
                        approved_amount_paise=amt,
                        recovered_amount_paise=amt)
        return dict(base, response_status="ACCEPTED",
                    approved_amount_paise=req,
                    recovered_amount_paise=req)

    def _latency(self, exc_id: str, cp: str, submitted_at: str) -> str:
        prof = PROFILES.get(cp, PROFILES["customer"])
        days = prof["sla_days"] * (0.4 + 0.5 * _det(exc_id, "lat",
                                                    self.seed))
        return (datetime.fromisoformat(submitted_at)
                + timedelta(days=days)).isoformat(timespec="seconds")
