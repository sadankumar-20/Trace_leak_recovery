"""Trace T4b — the audit hash chain.

One append-only chain; every meaningful state change is an event hashed
over (seq, case_id, event_type, payload, at, prev_hash). verify() walks
the chain and reports the FIRST invalid seq on tampering. Event vocabulary
is closed — unknown types raise, so 'creative' logging is impossible.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

EVENT_TYPES = ("MATCH_CREATED", "EXCEPTION_CREATED",
               "INVESTIGATION_STARTED", "EVIDENCE_RETRIEVED",
               "HYPOTHESIS_CREATED", "GATE_PASSED", "GATE_FAILED",
               "CLAIM_FILED", "COUNTERPARTY_RESPONDED", "RECOVERY_RECEIVED",
               "CLAIM_REJECTED", "WRITE_OFF_APPROVED", "WAIT_SCHEDULED",
               "CASE_STATE_CHANGED", "AUDIT_VERIFIED")

GENESIS = "0" * 64


def _h(seq, case_id, etype, payload, at, prev):
    return hashlib.sha256(json.dumps(
        [seq, case_id, etype, payload, at, prev],
        sort_keys=True).encode()).hexdigest()


class AuditChain:
    def __init__(self):
        self.events: list[dict] = []

    def append(self, case_id: str, event_type: str, payload: dict,
               now: datetime) -> dict:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown audit event type {event_type!r}")
        prev = self.events[-1]["hash"] if self.events else GENESIS
        seq = len(self.events) + 1
        at = now.isoformat(timespec="seconds")
        e = {"seq": seq, "case_id": case_id, "event_type": event_type,
             "payload": payload, "at": at, "prev_hash": prev,
             "hash": _h(seq, case_id, event_type, payload, at, prev)}
        self.events.append(e)
        return e

    def for_case(self, case_id: str) -> list[dict]:
        return [e for e in self.events if e["case_id"] == case_id]

    def verify(self, now: datetime | None = None) -> dict:
        prev = GENESIS
        for e in self.events:
            ok = (e["prev_hash"] == prev and e["hash"] == _h(
                e["seq"], e["case_id"], e["event_type"], e["payload"],
                e["at"], e["prev_hash"]))
            if not ok:
                return {"valid": False, "events": len(self.events),
                        "first_invalid_seq": e["seq"],
                        "verified_at": now.isoformat(timespec="seconds")
                        if now else None}
            prev = e["hash"]
        return {"valid": True, "events": len(self.events),
                "first_invalid_seq": None,
                "verified_at": now.isoformat(timespec="seconds")
                if now else None}

    def dump(self) -> str:
        return json.dumps(self.events, sort_keys=True)

    @classmethod
    def load(cls, s: str) -> "AuditChain":
        c = cls(); c.events = json.loads(s); return c
