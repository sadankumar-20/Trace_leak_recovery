"""Trace T1 — canonical financial object model.

Linked objects, not flat rows: Order -> Capture(s) -> GatewayTxn(s) ->
Refund(s) -> SettlementBatch -> BankEntry/UTR. Every object carries an
immutable record hash over its financial fields; nothing downstream may
mutate source records (the reconciliation engine and AI read, never write).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


def record_hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     default=str).encode()).hexdigest()


@dataclass(frozen=True)
class FeeSchedule:
    id: str; gateway: str; mdr_pct: float; gst_pct: float
    rounding_tolerance_paise: int; intl_surcharge_pct: float


@dataclass(frozen=True)
class Order:
    id: str; amount_paise: int; currency: str; created_at: str
    customer_email: str; international: bool


@dataclass(frozen=True)
class Capture:
    id: str; order_id: str; amount_paise: int; created_at: str; status: str


@dataclass(frozen=True)
class GatewayTxn:
    id: str; capture_id: str; order_id: str; gateway: str
    amount_paise: int; fee_paise: int; gst_paise: int; created_at: str
    status: str; settlement_ref: str | None


@dataclass(frozen=True)
class Refund:
    id: str; order_id: str; gateway_txn_id: str; amount_paise: int
    created_at: str; status: str; kind: str   # refund | reversal


@dataclass(frozen=True)
class SettlementBatch:
    id: str; gateway: str; utr: str; settlement_date: str
    total_net_paise: int


@dataclass(frozen=True)
class SettlementLine:
    id: str; batch_id: str; gateway_txn_id: str; net_paise: int


@dataclass(frozen=True)
class BankEntry:
    id: str; utr: str; amount_paise: int; posted_date: str; bank: str


TABLES = {"orders": Order, "captures": Capture, "gateway_txns": GatewayTxn,
          "refunds": Refund, "settlement_batches": SettlementBatch,
          "settlement_lines": SettlementLine, "bank_entries": BankEntry,
          "fee_schedules": FeeSchedule}


def to_row(obj) -> dict:
    d = asdict(obj)
    d["record_hash"] = record_hash(d)
    return d
