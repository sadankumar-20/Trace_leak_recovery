# Trace — the Settlement & Refund Leak Recovery Agent

Merchants lose money invisibly between "customer paid" and "money in the
bank": fee overcharges, settlements that never post, double refunds,
capture mismatches, rounding drift. Trace is a closed-loop revenue-
recovery control plane that finds these leaks, proves them to the paisa,
decides economically whether to pursue them, recovers the money through a
bounded executor — and then finds the systemic cause so it stops
happening.

> **AI investigates. Deterministic systems prove. Policy decides. The
> executor acts.**

Trace does not trust the AI with financial truth. The LLM-shaped
investigator can be wrong — the architecture makes its errors inert.

## The lifecycle
OBSERVE -> RECONCILE -> DETECT -> INVESTIGATE -> PROVE -> DECIDE ->
RECOVER -> VERIFY -> LEARN -> PREVENT

## The final question, answered by the held-out benchmark
On the frozen held-out split (71 hidden leak cases inside a
5,000-order quarter, evaluation run hash `74a40c70c7a4e4ca…`, integrity PASS,
byte-reproducible):

| | |
|---|---|
| **Found** (matcher, recall/precision) | 100% / 100% — OBSERVED gross Rs.159,373 |
| **Proved** (AI errors made / contained / ESCAPED) | 6 / 6 / **0** |
| **Filed** (packages after 8 gates + economics) | 6 — Rs.7,383 claimed |
| **Recovered** (ACTUAL, via simulated counterparties) | Rs.2,909 gross · Rs.2,649 net |
| **Safely refused** (stopping rule / approvals) | 22 written off · 33 escalated to humans |
| **Prevented** (ESTIMATED, labeled, never summed with actual) | Rs.831,730 across 5 confirmed root causes |

## Architecture (one commit per stage, an honest failure in most)
T1 seeded financial world + immutable record hashes · T2 deterministic
reconciliation (the star — typed states, paisa-exact discrepancies) ·
T3 lifecycle + WAIT + SLA clocks · T4 evidence graphs (a leak is a broken
edge) + tamper-evident audit chain · T5 deliberately fallible AI
investigator + containment · T6 eight-gate admissibility + EV decisions +
the write-off stopping rule · T7 counterparty simulation + idempotent
executor · T8 clustering + prevention (ACTUAL vs ESTIMATED, never merged)
· T9 four-way ablation, integrity-gated benchmark — which caught a real
containment escape and forced the fix · T10 the reconciliation cockpit ·
T11 roles + this story.

## Run it
```bash
python3 -c "import sys; sys.path.insert(0,'backend'); from app.world import generate; generate(seed=42, out_dir='data')"
cd backend && python3 -m unittest discover -s tests && cd ..   # 101 green, ~60s
python3 scripts/serve.py    # cockpit -> http://localhost:8000 (startup ~60s)
```

Simulated world, labeled everywhere. A student project for the Razorpay
Student AI Builder program — an architecture demonstration, not a
production financial product. Sister project (same doctrine, chargebacks):
https://github.com/sadankumar-20/Recourse_Ai_chargeback
