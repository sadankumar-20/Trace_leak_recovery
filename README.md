# Trace — the Settlement & Refund Leak Recovery Agent

Merchants lose 0.5–2% of GMV invisibly between "customer paid" and "money
in bank": fee overcharges, settlements that never land, double refunds,
capture mismatches, rounding drift. Trace detects, proves, prioritizes,
and recovers these leaks — as a closed-loop control plane where
**AI investigates → deterministic systems prove → policy decides →
a bounded executor acts.** The LLM never declares financial truth, never
touches money.

Lifecycle: OBSERVE → RECONCILE → DETECT → INVESTIGATE → PROVE → DECIDE →
RECOVER → VERIFY → LEARN → PREVENT.

Stage T1 (this commit): the seeded synthetic quarter — 5,000 orders across
two gateways and two banks; Order → Capture → GatewayTxn → Refund →
SettlementBatch → BankEntry/UTR with per-record immutable hashes; seven
injected leak types (fee_overcharge, missing_settlement, double_refund,
refund_marked_success_not_settled, partial_capture_mismatch,
duplicate_capture, rounding_drift) with hidden ground truth (true/
recoverable amounts, counterparty, claim window, outcome-if-claimed);
deliberate benign noise (valid reversals that LOOK like double refunds,
in-tolerance rounding, T+3 postings, batching, GST, international
surcharges) so precision has to be earned; frozen dev/held-out split
pinned to the corpus SHA-256.

```bash
python3 backend/app/world.py --seed 42
cd backend && python3 -m unittest discover -s tests   # 8 green, zero network
```

Roadmap: docs/ROADMAP.md. Sister project (same doctrine, shipped):
Recourse — https://github.com/sadankumar-20/Recourse_Ai_chargeback
