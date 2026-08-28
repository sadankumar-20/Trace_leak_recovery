# Trace — Settlement & Refund Leak Recovery Agent

**Live demo:** https://trace-leak-recovery.vercel.app · **Sister project:** [Recourse — AI Chargeback Defense](https://github.com/sadankumar-20/Recourse_Ai_chargeback)

## Overview

Trace is a closed-loop revenue-recovery control plane. It finds money
that disappears between a customer's payment and the merchant's bank
account, proves each leak to the paisa, decides economically whether
recovery is worth pursuing, recovers it through a bounded executor, and
identifies the systemic cause so the leak stops recurring.

> **AI investigates. Deterministic systems prove. Policy decides. The
> executor acts.**

Trace is a **simulated architecture demonstration** built for the
Razorpay Student AI Builder program. It is **not a production financial
product**.

## The Problem

Every payment travels a trail:

```
Customer Payment → Gateway → Settlement → Bank
```

Money leaks silently at the joints. Trace detects seven leak families:

- fee overcharges (gateway charges above contract)
- missing settlements (captured, never posted to bank)
- double refunds
- duplicate captures
- partial-capture mismatches
- rounding drift beyond contract tolerance
- refunds marked successful but never settlement-adjusted

## Lifecycle

```
OBSERVE → RECONCILE → DETECT → INVESTIGATE → PROVE →
DECIDE → RECOVER → VERIFY → LEARN → PREVENT
```

| Stage | What happens |
|---|---|
| OBSERVE | Ingest orders, captures, refunds, settlements, bank entries |
| RECONCILE | Deterministic rules tie every record together, to the paisa |
| DETECT | Disagreements become typed, hashed exceptions |
| INVESTIGATE | A bounded AI proposes a root-cause hypothesis (labeled UNVERIFIED) |
| PROVE | Deterministic validation recomputes every claim from source records |
| DECIDE | Eight admissibility gates + counterparty economics choose an action |
| RECOVER | An idempotent executor files at most one action per exception |
| VERIFY | Counterparty responses reconcile into a recovery ledger |
| LEARN | Exceptions cluster into systemic root causes; false patterns are rejected |
| PREVENT | Confirmed causes get priced prevention recommendations (ESTIMATED) |

## How Trace Works

- **Deterministic reconciliation** is the source of truth: matching,
  amounts and rule violations are recomputed from immutable, hashed
  source records.
- **AI generates hypotheses only.** The investigator is deliberately
  fallible, reads through read-only tools, and its output is labeled
  UNVERIFIED. **AI never defines financial truth and never touches
  money** — it is structurally banned (test-enforced) from importing
  the execution layers.
- **Containment**: every AI conclusion is validated against
  deterministically recomputed truth. Errors become CONTAINED, never
  actions.
- **Admissibility gates** (eight of them): data integrity,
  reconciliation proof, contract proof, eligibility window,
  party-bound recoverability, paisa-exact amount integrity, economic
  viability (a real write-off stopping rule), and risk/approval.
- **Policy decisions** use per-counterparty economics (recovery
  probability, SLA, cost) — WAIT, ESCALATE, WRITE_OFF and NO_ACTION
  are first-class outcomes.
- **Bounded execution**: one exception → at most one execution, ever —
  under retries, timeouts, duplicates and concurrency.
- **Verification, clustering, prevention** close the loop, with false
  patterns rejected by deterministic challenge.

## Held-Out Benchmark

Frozen held-out split inside a 5,000-order simulated quarter. Evaluation
run hash `74a40c70c7a4e4ca…` · integrity **PASS** ·
byte-reproducible (identical config ⇒ identical hash, asserted in
tests).

| Metric | Result |
|---|---|
| Hidden leak cases | 71 |
| Matcher recall / precision | 100% / 100% |
| Observed gross leakage | Rs.159,373 |
| AI errors made / contained / **escaped** | 6 / 6 / **0** |
| Claims filed (after gates + economics) | 6 |
| Claimed | Rs.7,383 |
| Recovered gross (**ACTUAL**) | Rs.2,909 |
| Recovered net (**ACTUAL**) | Rs.2,649 |
| Written off (stopping rule) | 22 |
| Escalated to humans | 33 |
| Estimated future prevention (**ESTIMATED**) | Rs.831,730 |

**ACTUAL RECOVERY and ESTIMATED PREVENTION are never combined** — they
carry explicit labels through the entire system, from the KPI wall to
the evaluation artifact.

## Reconciliation Cockpit

The T11 frontend (vanilla HTML/CSS/JS on the Flask API):

- cinematic interface: boot sequence, ambient motion, scroll-driven
  ten-chapter lifecycle story with word reveal
- clickable lifecycle navigation (both directions) + top navigation
  with active-section tracking
- searchable case files (order id, case id, gateway txn, type,
  decision, state) with live filters and result count
- interactive case cards (hover sweep, evidence-status chips) opening a
  full-screen investigation dossier
- dossier: financial reconciliation (expected/actual/delta), per-case
  money-flow visualization with the pipe breaking at the leak,
  evidence graph, eight-gate results, decision economics, execution
  and recovery, audit timeline
- audit-chain verification button (real endpoint, staged states)
- real-time local clock in the hero status line
- benchmark wall fed live from the evaluation artifact
- responsive design, reduced-motion support, custom Trace favicon

## Case Investigation

```
Case selected → records loaded → reconciliation examined →
discrepancy identified → evidence reviewed → decision displayed
```

Every dossier displays the selected case's own data — order, gateway
transaction, amounts, verdict, gates, decision, execution, audit trail.

## Responsive Experience

The cockpit adapts across desktop, laptop, tablet and mobile: responsive
case grids, collapsed mobile navigation, adaptive lifecycle chapters
(sticky on desktop, static on small screens), single-column dossiers,
mobile-friendly money-flow, touch-target buttons, and no horizontal
overflow.

## Data Integrity

| Label | Meaning |
|---|---|
| OBSERVED | Measured from the simulated world (e.g. gross leakage) |
| VERIFIED | Recomputed deterministically from source records |
| ACTUAL | Money that reconciled into the recovery ledger |
| ESTIMATED | Modeled prevention value, with assumptions attached |

**Recovered money is ACTUAL. Prevented future loss is ESTIMATED. They
are never represented as the same category.**

## Technology

- **Python 3** (standard library) + **Flask** — the only runtime
  dependency (`requirements.txt`)
- **Vanilla HTML / CSS / JavaScript** frontend — no frameworks, no
  build step
- **unittest** — 106 tests
- **Vercel** (`@vercel/python`) — deployment serves precomputed,
  ground-truth-free API payloads

## Project Structure

```
Trace_leak_recovery/
├── api/index.py              # Vercel serverless entry (static mode)
├── backend/
│   ├── app/                  # 13 modules: world, recon, lifecycle,
│   │                         # evidence, audit, tools, investigator,
│   │                         # gate, decision, counterparty, executor,
│   │                         # portfolio, evaluation, api, static_api
│   └── tests/                # 106 tests (unittest)
├── frontend/                 # index.html, app.js, style.css, favicons
├── data/precomputed/         # frozen API payloads for deployment
├── scripts/
│   ├── serve.py              # local cockpit (full pipeline)
│   └── precompute.py         # freezes payloads for deploy
├── docs/                     # STORY.md, ROADMAP.md
├── requirements.txt          # flask (only runtime dependency)
└── vercel.json               # deployment config
```

## Running the Project

```bash
cd backend && python3 -m unittest discover -s tests && cd ..   # 106 OK, ~40s
python3 scripts/serve.py    # cockpit → http://localhost:8000 (startup ~30–60s)
```

The deployed demo (precomputed mode) runs at
https://trace-leak-recovery.vercel.app with no environment variables.

## Testing

```bash
cd backend && python3 -m unittest discover -s tests
# Ran 106 tests ... OK
```

Tests cover the world, reconciliation, lifecycle, evidence and audit,
AI containment (including adversarial cases), gates, decisions,
execution idempotency under concurrency, clustering, the evaluation
framework's integrity checks, the API contract, security boundaries,
and the frontend's wiring to real data.

## Design Principles

1. AI investigates, but does not determine financial truth.
2. Deterministic systems prove discrepancies.
3. Policy decides whether recovery is worthwhile.
4. The executor is bounded and idempotent.
5. Actual and estimated money remain separate.
6. Important actions are auditable (tamper-evident hash chain).
7. The ultimate goal is prevention.

## Limitations / Disclaimer

- The world, counterparties and outcomes are **simulated and labeled**
  as such throughout the UI and API.
- This is an **architecture demonstration** and **student project**
  for the **Razorpay Student AI Builder program** — not a production
  financial product.
- Benchmark results are properties of the simulated world and the
  frozen held-out split; the matcher's perfect recall/precision is a
  property of this world, stated as such.
- The deployed demo serves a precomputed, frozen pipeline state.

## Sister Project

**[Recourse — AI Chargeback Defense](https://github.com/sadankumar-20/Recourse_Ai_chargeback)**
— the same doctrine applied to chargeback disputes, with a live
AI-powered deployment.
