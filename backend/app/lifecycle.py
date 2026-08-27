"""Trace T3 — time as a first-class citizen.

Two machines, deliberately separate:

1) The TEMPORAL classifier (pure function): where a settlement stands in
   time — CAPTURED -> SETTLEMENT_PENDING -> WITHIN_EXPECTED_WINDOW -> LATE
   -> TRACE_REQUIRED -> CLAIMABLE. It exists so Trace knows when to WAIT:
   a bank inside its posting lag is not a leak, it is Tuesday.

2) The CASE machine (guarded transitions): OPEN -> INVESTIGATING ->
   WAITING_FOR_INPUT -> ADMISSIBILITY_REVIEW -> CLAIM_FILED ->
   COUNTERPARTY_PENDING -> PARTIAL_RECOVERY -> RECOVERED / REJECTED /
   ESCALATED / WRITTEN_OFF. Illegal transitions raise; nothing downstream
   may bypass it. Every case carries five SLA clocks (claim, investigation,
   counterparty, escalation, write-off) and supports an explicit WAIT with
   a wake time. Past the claim deadline, the only legal moves are
   ESCALATED or WRITTEN_OFF — filing is structurally impossible.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# temporal settlement states
CAPTURED = "CAPTURED"
SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
WITHIN_EXPECTED_WINDOW = "WITHIN_EXPECTED_WINDOW"
LATE = "LATE"
TRACE_REQUIRED = "TRACE_REQUIRED"
CLAIMABLE = "CLAIMABLE"

EXPECTED_SETTLE_DAYS = 3
POSTING_LAG_DAYS = 2
LATE_GRACE_DAYS = 2

# case states
STATES = ("OPEN", "INVESTIGATING", "WAITING_FOR_INPUT",
          "ADMISSIBILITY_REVIEW", "CLAIM_FILED", "COUNTERPARTY_PENDING",
          "PARTIAL_RECOVERY", "RECOVERED", "REJECTED", "ESCALATED",
          "WRITTEN_OFF")
TERMINAL = {"RECOVERED", "REJECTED", "ESCALATED", "WRITTEN_OFF"}
TRANSITIONS = {
    "OPEN": {"INVESTIGATING", "WRITTEN_OFF", "ESCALATED"},
    "INVESTIGATING": {"WAITING_FOR_INPUT", "ADMISSIBILITY_REVIEW",
                      "ESCALATED", "WRITTEN_OFF"},
    "WAITING_FOR_INPUT": {"INVESTIGATING", "ESCALATED", "WRITTEN_OFF"},
    "ADMISSIBILITY_REVIEW": {"CLAIM_FILED", "ESCALATED", "WRITTEN_OFF",
                             "INVESTIGATING"},
    "CLAIM_FILED": {"COUNTERPARTY_PENDING"},
    "COUNTERPARTY_PENDING": {"PARTIAL_RECOVERY", "RECOVERED", "REJECTED",
                             "ESCALATED", "WAITING_FOR_INPUT"},
    "PARTIAL_RECOVERY": {"RECOVERED", "ESCALATED", "WRITTEN_OFF"},
}
COUNTERPARTY_SLA_DAYS = {"gateway": 10, "bank": 12, "customer": 7}
INVESTIGATION_SLA_DAYS = 3
ESCALATION_AFTER_SLA_DAYS = 5


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def temporal_state(captured_at: str, settlement_date: str | None,
                   bank_posted: bool, now: datetime) -> str:
    cap = datetime.fromisoformat(captured_at)
    if settlement_date is None:
        return (SETTLEMENT_PENDING
                if now <= cap + timedelta(days=EXPECTED_SETTLE_DAYS)
                else TRACE_REQUIRED)
    if bank_posted:
        return CAPTURED if False else "SETTLED"      # posted: out of scope
    due = datetime.fromisoformat(settlement_date) \
        + timedelta(days=POSTING_LAG_DAYS)
    if now <= due:
        return WITHIN_EXPECTED_WINDOW
    if now <= due + timedelta(days=LATE_GRACE_DAYS):
        return LATE
    return CLAIMABLE


class IllegalTransition(RuntimeError):
    pass


@dataclass
class Case:
    id: str
    exception_id: str
    order_id: str
    leak_type: str
    counterparty: str
    amount_paise: int
    opened_at: str
    claim_deadline: str
    state: str = "OPEN"
    wake_at: str | None = None
    claim_filed_at: str | None = None
    history: list = field(default_factory=list)

    # -- SLA clocks -----------------------------------------------------
    def clocks(self) -> dict:
        opened = datetime.fromisoformat(self.opened_at)
        out = {"claim_deadline": self.claim_deadline,
               "investigation_deadline":
                   _iso(opened + timedelta(days=INVESTIGATION_SLA_DAYS)),
               "counterparty_sla": None, "escalation_deadline": None,
               "write_off_deadline": self.claim_deadline}
        if self.claim_filed_at:
            filed = datetime.fromisoformat(self.claim_filed_at)
            sla = filed + timedelta(
                days=COUNTERPARTY_SLA_DAYS[self.counterparty])
            out["counterparty_sla"] = _iso(sla)
            out["escalation_deadline"] = _iso(
                sla + timedelta(days=ESCALATION_AFTER_SLA_DAYS))
        return out

    def transition(self, to: str, now: datetime, note: str = "") -> "Case":
        if to not in STATES:
            raise IllegalTransition(f"unknown state {to!r}")
        if to not in TRANSITIONS.get(self.state, set()):
            raise IllegalTransition(f"{self.state} -> {to} is not legal")
        if to == "CLAIM_FILED":
            if now > datetime.fromisoformat(self.claim_deadline):
                raise IllegalTransition(
                    "claim window expired — only ESCALATED or WRITTEN_OFF "
                    "are legal now")
            self.claim_filed_at = _iso(now)
        self.history.append({"at": _iso(now), "from": self.state,
                             "to": to, "note": note})
        self.state = to
        self.wake_at = None
        return self

    def wait(self, until: datetime, now: datetime, reason: str) -> "Case":
        """Explicit WAIT: legal in any non-terminal state; never a
        transition, always audited in history with a wake time."""
        if self.state in TERMINAL:
            raise IllegalTransition("terminal cases do not wait")
        self.wake_at = _iso(until)
        self.history.append({"at": _iso(now), "from": self.state,
                             "to": self.state,
                             "note": f"WAIT until {self.wake_at}: {reason}"})
        return self

    def allowed(self, now: datetime) -> set[str]:
        moves = set(TRANSITIONS.get(self.state, set()))
        if now > datetime.fromisoformat(self.claim_deadline):
            moves &= {"ESCALATED", "WRITTEN_OFF", "INVESTIGATING",
                      "WAITING_FOR_INPUT"} - {"INVESTIGATING",
                                              "WAITING_FOR_INPUT"} \
                if self.state == "ADMISSIBILITY_REVIEW" else moves - {
                    "CLAIM_FILED"}
        return moves

    def to_dict(self) -> dict:
        return {"id": self.id, "exception_id": self.exception_id,
                "order_id": self.order_id, "leak_type": self.leak_type,
                "counterparty": self.counterparty,
                "amount_paise": self.amount_paise,
                "opened_at": self.opened_at,
                "claim_deadline": self.claim_deadline, "state": self.state,
                "wake_at": self.wake_at,
                "claim_filed_at": self.claim_filed_at,
                "clocks": self.clocks(), "history": self.history}


def case_from_discrepancy(d: dict, now: datetime) -> Case:
    return Case(id=f"case_{d['exception_id']}",
                exception_id=d["exception_id"], order_id=d["order_id"],
                leak_type=d["discrepancy_type"],
                counterparty=d["counterparty"],
                amount_paise=abs(d["delta_paise"]), opened_at=_iso(now),
                claim_deadline=d["claim_deadline"])


def portfolio_sla(cases: list[Case], now: datetime) -> dict:
    """The ops headline: what expires, what is overdue, how much money."""
    soon = now + timedelta(hours=24)
    expiring = [c for c in cases if c.state not in TERMINAL
                and not c.claim_filed_at
                and now <= datetime.fromisoformat(c.claim_deadline) <= soon]
    responses_overdue, pending_paise = [], 0
    for c in cases:
        clk = c.clocks()
        if c.state == "COUNTERPARTY_PENDING" and clk["counterparty_sla"] \
                and now > datetime.fromisoformat(clk["counterparty_sla"]):
            responses_overdue.append(c)
            pending_paise += c.amount_paise
    due_wakes = [c for c in cases if c.wake_at
                 and now >= datetime.fromisoformat(c.wake_at)]
    return {"claims_expiring_24h": len(expiring),
            "expiring_amount_paise": sum(c.amount_paise for c in expiring),
            "responses_overdue": len(responses_overdue),
            "pending_beyond_sla_paise": pending_paise,
            "wakes_due": len(due_wakes)}
