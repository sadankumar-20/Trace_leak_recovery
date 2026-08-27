"""Trace T1 — the seeded synthetic quarter.

~5,000 orders across two gateways and two banks; correct records plus
seven injected leak scenarios and deliberate benign noise (T+1/T+2 delays,
batching offsets, in-tolerance rounding, valid reversals that LOOK like
double refunds, GST lines, international surcharges). Hidden ground truth
per corrupted case: leak type, true/recoverable amounts, responsible
counterparty, eligibility window, outcome-if-claimed, expected response
time, rejection reason. Frozen dev/held-out split over exception order ids;
the evaluation set never leaks ground truth into the agent.

Determinism contract: same seed -> byte-identical world (tested via the
corpus hash).
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from .models import (
    BankEntry, Capture, FeeSchedule, GatewayTxn, Order, Refund,
    SettlementBatch, SettlementLine, to_row,
)

LEAKS = ("fee_overcharge", "missing_settlement", "double_refund",
         "refund_marked_success_not_settled", "partial_capture_mismatch",
         "duplicate_capture", "rounding_drift")
LEAK_COUNTS = {"fee_overcharge": 90, "missing_settlement": 28,
               "double_refund": 22, "refund_marked_success_not_settled": 20,
               "partial_capture_mismatch": 18, "duplicate_capture": 14,
               "rounding_drift": 24}          # 216 corrupted cases
COUNTERPARTY = {"fee_overcharge": "gateway", "missing_settlement": "bank",
                "double_refund": "customer",
                "refund_marked_success_not_settled": "gateway",
                "partial_capture_mismatch": "gateway",
                "duplicate_capture": "gateway", "rounding_drift": "gateway"}
WIN_DAYS = {"gateway": 60, "bank": 45, "customer": 30}
Q_START = datetime(2026, 4, 1)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def generate(seed: int = 42, out_dir: str | Path = "data",
             n_orders: int = 5000) -> dict:
    rng = random.Random(seed)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    fees = [FeeSchedule("fs_gwA", "GatewayA", 1.80, 18.0, 50, 0.50),
            FeeSchedule("fs_gwB", "GatewayB", 2.10, 18.0, 50, 0.75)]
    fee_by_gw = {f.gateway: f for f in fees}
    world = {t: [] for t in ("orders", "captures", "gateway_txns", "refunds",
                             "settlement_batches", "settlement_lines",
                             "bank_entries")}
    gt: dict[str, dict] = {}
    pending_lines: dict[tuple, list] = {}    # (gateway, day) -> lines

    def base_txn(i: int) -> tuple:
        day = Q_START + timedelta(days=rng.randrange(0, 88),
                                  seconds=rng.randrange(0, 86000))
        gw = rng.choice(("GatewayA", "GatewayB"))
        intl = rng.random() < 0.06
        amount = rng.randrange(20000, 2500000)      # ₹200–₹25,000 in paise
        o = Order(f"ord_{i:05d}", amount, "INR", _iso(day),
                  f"c{i}@shop.example", intl)
        cap = Capture(f"cap_{i:05d}", o.id, amount, _iso(day), "captured")
        fs = fee_by_gw[gw]
        pct = fs.mdr_pct + (fs.intl_surcharge_pct if intl else 0.0)
        fee = round(amount * pct / 100)
        gst = round(fee * fs.gst_pct / 100)
        tx = GatewayTxn(f"gtx_{i:05d}", cap.id, o.id, gw, amount, fee, gst,
                        _iso(day + timedelta(minutes=2)), "captured", None)
        return day, o, cap, tx, fs

    def settle(tx: GatewayTxn, day: datetime, delay: int | None = None,
               net_override: int | None = None, skip_bank: bool = False):
        d = delay if delay is not None else rng.choice((1, 1, 2, 2, 3))
        sd = (day + timedelta(days=d)).date().isoformat()
        net = net_override if net_override is not None else \
            tx.amount_paise - tx.fee_paise - tx.gst_paise
        pending_lines.setdefault((tx.gateway, sd, skip_bank), []).append(
            (tx, net))

    leak_ids = []
    for lt, cnt in LEAK_COUNTS.items():
        leak_ids += [lt] * cnt
    rng.shuffle(leak_ids)
    corrupt_at = dict(zip(sorted(rng.sample(range(n_orders), len(leak_ids))),
                          leak_ids))

    for i in range(n_orders):
        day, o, cap, tx, fs = base_txn(i)
        world["orders"].append(o); world["captures"].append(cap)
        lt = corrupt_at.get(i)
        expected_net = tx.amount_paise - tx.fee_paise - tx.gst_paise
        deadline = _iso(day + timedelta(days=WIN_DAYS.get(
            COUNTERPARTY.get(lt, "gateway"), 60)))

        if lt is None:
            # benign world, with deliberate noise
            world["gateway_txns"].append(tx)
            r = rng.random()
            if r < 0.06:      # legit partial refund
                amt = round(tx.amount_paise * rng.choice((0.25, 0.5)))
                world["refunds"].append(Refund(
                    f"ref_{i:05d}a", o.id, tx.id, amt,
                    _iso(day + timedelta(days=4)), "processed", "refund"))
                settle(tx, day)
            elif r < 0.085:   # refund + VALID reversal (looks like a double)
                amt = round(tx.amount_paise * 0.5)
                world["refunds"].append(Refund(
                    f"ref_{i:05d}a", o.id, tx.id, amt,
                    _iso(day + timedelta(days=4)), "processed", "refund"))
                world["refunds"].append(Refund(
                    f"ref_{i:05d}b", o.id, tx.id, -amt,
                    _iso(day + timedelta(days=5)), "processed", "reversal"))
                settle(tx, day)
            elif r < 0.12:    # in-tolerance rounding noise (NOT a leak)
                settle(tx, day, net_override=expected_net
                       - rng.randrange(1, fs.rounding_tolerance_paise))
            elif r < 0.15:    # late-but-legit T+3 posting
                settle(tx, day, delay=3)
            else:
                settle(tx, day)
            continue

        # ---- injected leaks (ground truth recorded) ----
        if lt == "fee_overcharge":
            over_pct = rng.choice((0.20, 0.25, 0.35))
            bad_fee = round(tx.amount_paise
                            * (fs.mdr_pct + over_pct
                               + (fs.intl_surcharge_pct if o.international
                                  else 0)) / 100)
            bad_gst = round(bad_fee * fs.gst_pct / 100)
            tx = GatewayTxn(tx.id, cap.id, o.id, tx.gateway, tx.amount_paise,
                            bad_fee, bad_gst, tx.created_at, "captured", None)
            world["gateway_txns"].append(tx)
            settle(tx, day, net_override=tx.amount_paise - bad_fee - bad_gst)
            leaked = (bad_fee + bad_gst) - (round(tx.amount_paise * (
                fs.mdr_pct + (fs.intl_surcharge_pct if o.international
                              else 0)) / 100) * 0)  # placeholder replaced below
            correct_fee = round(tx.amount_paise * (fs.mdr_pct +
                (fs.intl_surcharge_pct if o.international else 0)) / 100)
            correct_gst = round(correct_fee * fs.gst_pct / 100)
            leaked = (bad_fee + bad_gst) - (correct_fee + correct_gst)
            outcome = rng.choices(("approved", "partially_approved",
                                   "rejected"), (0.72, 0.16, 0.12))[0]
        elif lt == "missing_settlement":
            world["gateway_txns"].append(tx)
            settle(tx, day, skip_bank=True)          # batch exists, bank silent
            leaked = expected_net
            outcome = rng.choices(("approved", "needs_information"),
                                  (0.8, 0.2))[0]
        elif lt == "double_refund":
            world["gateway_txns"].append(tx)
            amt = round(tx.amount_paise * 0.5)
            for suf in ("a", "b"):                    # duplicate, NOT reversal
                world["refunds"].append(Refund(
                    f"ref_{i:05d}{suf}", o.id, tx.id, amt,
                    _iso(day + timedelta(days=4)), "processed", "refund"))
            settle(tx, day)
            leaked = amt
            outcome = rng.choices(("approved", "rejected"), (0.55, 0.45))[0]
        elif lt == "refund_marked_success_not_settled":
            world["gateway_txns"].append(tx)
            world["refunds"].append(Refund(
                f"ref_{i:05d}a", o.id, tx.id, tx.amount_paise,
                _iso(day + timedelta(days=3)), "processed", "refund"))
            settle(tx, day)     # merchant debited later w/o refund credit —
            leaked = 0          # customer-side risk: chargeback exposure
            outcome = "needs_information"
        elif lt == "partial_capture_mismatch":
            part = round(o.amount_paise * 0.6)
            # the capture IS the partial event — reflect it in the record
            world["captures"][-1] = Capture(cap.id, o.id, part,
                                            cap.created_at, "captured")
            tx = GatewayTxn(tx.id, cap.id, o.id, tx.gateway, part,
                            round(part * fs.mdr_pct / 100),
                            round(part * fs.mdr_pct / 100 * fs.gst_pct / 100),
                            tx.created_at, "captured", None)
            world["gateway_txns"].append(tx)
            # bank settles as if FULL amount was captured minus fees on part
            settle(tx, day, net_override=part - tx.fee_paise - tx.gst_paise
                   - rng.randrange(5000, 40000))
            leaked = None       # delta derived by recon in T2
            outcome = rng.choices(("approved", "rejected"), (0.6, 0.4))[0]
        elif lt == "duplicate_capture":
            world["gateway_txns"].append(tx)
            dup = GatewayTxn(f"gtx_{i:05d}d", cap.id, o.id, tx.gateway,
                             tx.amount_paise, tx.fee_paise, tx.gst_paise,
                             _iso(day + timedelta(seconds=40)), "captured",
                             None)
            world["gateway_txns"].append(dup)
            settle(tx, day); settle(dup, day)
            leaked = tx.fee_paise + tx.gst_paise    # merchant double-charged fees
            outcome = "approved"
        else:  # rounding_drift — beyond contract tolerance
            world["gateway_txns"].append(tx)
            drift = rng.randrange(fs.rounding_tolerance_paise + 30,
                                  fs.rounding_tolerance_paise + 400)
            settle(tx, day, net_override=expected_net - drift)
            leaked = drift
            outcome = rng.choices(("approved", "rejected"), (0.5, 0.5))[0]

        gt[o.id] = {"leak_type": lt,
                    "true_leak_paise": leaked,
                    "recoverable_paise": leaked,
                    "counterparty": COUNTERPARTY[lt],
                    "claim_deadline": deadline,
                    "outcome_if_claimed": outcome,
                    "expected_response_days": rng.randrange(3, 15),
                    "rejection_reason": ("insufficient documentation"
                                         if outcome == "rejected" else None)}

    # materialize settlement batches + bank entries
    for (gw, sd, skip_bank), lines in sorted(pending_lines.items()):
        for chunk_no in range(0, len(lines), 40):     # batching: many->one
            chunk = lines[chunk_no:chunk_no + 40]
            mark = "X" if skip_bank else ""
            bid = f"stl_{gw[-1]}_{sd}_{chunk_no // 40}{mark}"
            utr = (f"UTR{gw[-1]}{sd.replace('-', '')}"
                   f"{chunk_no // 40:02d}{mark}")
            total = sum(n for _, n in chunk)
            world["settlement_batches"].append(
                SettlementBatch(bid, gw, utr, sd, total))
            for j, (tx, net) in enumerate(chunk):
                world["settlement_lines"].append(
                    SettlementLine(f"{bid}_l{j}", bid, tx.id, net))
            if not skip_bank:
                post = (datetime.fromisoformat(sd)
                        + timedelta(days=rng.choice((0, 0, 1)))).date()
                world["bank_entries"].append(BankEntry(
                    f"bank_{utr}", utr, total, post.isoformat(),
                    "BankC" if gw == "GatewayA" else "BankD"))

    rows = {t: [to_row(x) for x in v] for t, v in world.items()}
    rows["fee_schedules"] = [to_row(f) for f in fees]
    corpus = hashlib.sha256(json.dumps(rows, sort_keys=True)
                            .encode()).hexdigest()
    leak_orders = sorted(gt)
    rng2 = random.Random(seed + 1)
    held = sorted(rng2.sample(leak_orders, round(len(leak_orders) * 0.33)))
    split = {"seed": seed, "corpus_sha256": corpus,
             "dev": [o for o in leak_orders if o not in set(held)],
             "held_out": held,
             "q_start": _iso(Q_START), "sim_now": _iso(Q_START
                                                       + timedelta(days=95))}
    (out / "world.json").write_text(json.dumps(rows, indent=0))
    (out / "ground_truth.json").write_text(json.dumps(
        {"labels": gt}, indent=0))
    (out / "split.json").write_text(json.dumps(split, indent=1))
    return {"rows": {t: len(v) for t, v in rows.items()},
            "leaks": {lt: sum(1 for g in gt.values()
                              if g["leak_type"] == lt) for lt in LEAKS},
            "corpus_sha256": corpus, "split": {"dev": len(split["dev"]),
                                               "held_out": len(held)}}


if __name__ == "__main__":
    import sys
    print(json.dumps(generate(
        seed=int(sys.argv[sys.argv.index("--seed") + 1])
        if "--seed" in sys.argv else 42), indent=1))
