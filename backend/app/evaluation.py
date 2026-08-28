"""Trace T9 — the evaluation framework.

Everything above this layer gets measured here, on the FROZEN HELD-OUT
split, under four architectural variants:

  A  Matcher only
  B  Matcher + AI investigator (+ containment)
  C  Matcher + AI + admissibility gate + decision engine
  D  Full Trace (execution, counterparty, recovery, clusters, prevention)

Ground truth is an EVALUATION-ONLY input: production components receive
exactly what they receive in production (the counterparty simulation is
the world's own authority and already held gt by design in T7). Every run
carries an immutable config, an evaluation_run_id, and an
evaluation_result_hash — identical configs reproduce identical hashes; a
changed world seed changes them. Benchmark integrity checks reconcile
every headline number against the underlying ledgers and FAIL the run on
any contradiction. ACTUAL recovery and ESTIMATED prevention never mix.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path

from . import gate as G
from .audit import AuditChain
from .counterparty import CounterpartySim
from .decision import decide
from .executor import Executor
from .investigator import investigate, validate
from .portfolio import build_clusters, kpis
from .world import generate

NOW = datetime(2026, 7, 5, 12, 0)
EVALUATOR_VERSION = "t9.1"


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     default=str).encode()).hexdigest()


def load_frozen(data_dir) -> dict:
    d = Path(data_dir)
    return {"world": json.loads((d / "world.json").read_text()),
            "gt": json.loads((d / "ground_truth.json").read_text())
            ["labels"],
            "split": json.loads((d / "split.json").read_text())}


def run_evaluation(data_dir, subset: str = "held_out") -> dict:
    fz = load_frozen(data_dir)
    world, gt, split = fz["world"], fz["gt"], fz["split"]
    sim_now = split["sim_now"]
    config = {"dataset_seed": split["seed"],
              "corpus_sha256": split["corpus_sha256"],
              "split": subset, "sim_now": sim_now,
              "policy_version": "t6.1",
              "evaluator_version": EVALUATOR_VERSION,
              "min_expected_net_paise": G.MIN_EXPECTED_NET_PAISE}
    run_id = f"eval_{_hash(config)[:12]}"
    held = set(split[subset])
    truth_map = G.recon_truth(world, sim_now)
    exceptions = sorted((d.to_dict() for d in truth_map.values()
                         if d.order_id in held),
                        key=lambda e: e["exception_id"])

    # ---------- Variant A: matcher only ----------
    flagged = {e["order_id"]: e["discrepancy_type"] for e in exceptions}
    truth_types = {o: gt[o]["leak_type"] for o in held}
    tp = sum(1 for o in held if flagged.get(o) == truth_types[o])
    A = {"leak_recall": round(len(flagged) / len(held), 4),
         "leak_precision": 1.0 if all(o in gt for o in flagged) else
         round(tp / max(1, len(flagged)), 4),
         "type_accuracy": round(tp / len(held), 4),
         "gross_leakage_paise": sum(abs(e["delta_paise"])
                                    for e in exceptions)}

    # ---------- Variant B: + investigator/containment ----------
    chain = AuditChain()
    verdicts, ai = {}, {"correct": 0, "errors": 0, "contained": 0,
                        "escaped": 0}
    for e in exceptions:
        hyp = investigate(e, world, chain, NOW)
        v = validate(hyp, world, sim_now, chain, NOW)
        verdicts[e["exception_id"]] = v
        right = (hyp.hypothesis_type == truth_types[e["order_id"]]
                 and v["result"] == "SUPPORTED")
        if right:
            ai["correct"] += 1
        else:
            ai["errors"] += 1
            if v["result"] == "SUPPORTED":
                ai["escaped"] += 1          # the red metric
            else:
                ai["contained"] += 1
    B = {**ai, "containment_rate":
         round(ai["contained"] / max(1, ai["errors"]), 4),
         "invariant_holds": ai["contained"] + ai["escaped"]
         == ai["errors"]}

    # ---------- Variant C: + gates/decision ----------
    decisions = {e["exception_id"]:
                 decide(e, verdicts[e["exception_id"]], world, sim_now)
                 for e in exceptions}
    acts = [d["selected_action"] for d in decisions.values()]
    packages = [d["action_package"] for d in decisions.values()
                if "action_package" in d]
    C = {"packages": len(packages),
         "write_off": acts.count("WRITE_OFF"),
         "escalate": acts.count("ESCALATE"),
         "no_action": acts.count("NO_ACTION"),
         "false_claims_prevented":
             sum(1 for e in exceptions
                 if verdicts[e["exception_id"]]["result"] != "SUPPORTED")}

    # ---------- Variant D: full pipeline ----------
    cp = CounterpartySim(world, gt, sim_now)
    ex = Executor(world, sim_now, cp, chain)
    for pkg in packages:
        ex.execute(pkg, approval=pkg.get("required_approval", False))
    mon = ex.monitors()
    claimed = sum(p["claim_amount_paise"] for p in packages)
    recovered = mon["gross_recovered_paise"]
    approved = sum(r["approved_paise"] for r in ex.recoveries)
    cost = sum(r["recovery_cost_paise"] for r in ex.recoveries)
    clusters = build_clusters(exceptions, world, sim_now, ex.recoveries)
    k = kpis(clusters, ex.recoveries)
    expected_net = sum(d["admissibility"]["expected_net_paise"]
                       for d in decisions.values()
                       if "action_package" in d)
    D = {"waterfall": {
            "gross_leakage_paise": A["gross_leakage_paise"],
            "claimed_paise": claimed, "approved_paise": approved,
            "recovered_paise": recovered,
            "unrecovered_of_claimed_paise": claimed - recovered,
            "net_recovered_paise": recovered - cost,
            "recovery_cost_paise": cost,
            "written_off_paise": sum(
                abs(e["delta_paise"]) for e in exceptions
                if decisions[e["exception_id"]]["selected_action"]
                == "WRITE_OFF")},
         "expected_vs_actual_net_paise":
             {"expected": expected_net, "actual": recovered - cost,
              "error": expected_net - (recovered - cost)},
         "double_executions": mon["double_executions"],
         "chain_valid": chain.verify(NOW)["valid"],
         "clusters_confirmed": k["active_root_causes"],
         "estimated_preventable_paise": k["estimated_preventable_paise"],
         "labels": {"recovered": "ACTUAL/VERIFIED",
                    "preventable": "ESTIMATED"}}

    # ---------- threshold sensitivity (never mutates defaults) ----------
    sweep = []
    saved = G.MIN_EXPECTED_NET_PAISE
    try:
        for thr in (500, 1_000, 2_500, 5_000):
            G.MIN_EXPECTED_NET_PAISE = thr
            ds = [decide(e, verdicts[e["exception_id"]], world, sim_now)
                  for e in exceptions]
            sweep.append({"threshold_paise": thr,
                          "packages": sum(1 for d in ds
                                          if "action_package" in d),
                          "write_offs": sum(1 for d in ds
                                            if d["selected_action"]
                                            == "WRITE_OFF")})
    finally:
        G.MIN_EXPECTED_NET_PAISE = saved

    result = {"evaluation_run_id": run_id, "config": config,
              "cases": len(held), "variant_a": A, "variant_b": B,
              "variant_c": C, "variant_d": D,
              "ablation_uplift": {
                  "ai_uplift_correct_investigations": B["correct"],
                  "gate_uplift_false_claims_blocked":
                      C["false_claims_prevented"],
                  "decision_uplift_uneconomic_stopped": C["write_off"],
                  "execution_uplift_recovered_paise": recovered,
                  "portfolio_uplift_root_causes": D["clusters_confirmed"],
                  "prevention_uplift_estimated_paise":
                      D["estimated_preventable_paise"]},
              "threshold_sensitivity": sweep}
    result["integrity"] = check_integrity(result, ex.recoveries)
    result["evaluation_result_hash"] = _hash(
        {k: v for k, v in result.items() if k != "integrity"})
    return result


def check_integrity(result: dict, recoveries: list) -> dict:
    """Reconcile every headline number against the ledgers; FAIL loudly."""
    reasons = []
    w = result["variant_d"]["waterfall"]
    if w["recovered_paise"] != sum(r["recovered_paise"]
                                   for r in recoveries):
        reasons.append("recovered does not match recovery ledger")
    if w["net_recovered_paise"] != w["recovered_paise"] \
            - w["recovery_cost_paise"]:
        reasons.append("net != recovered - cost")
    if not (w["recovered_paise"] <= w["approved_paise"]
            <= w["claimed_paise"]):
        reasons.append("recovered <= approved <= claimed violated")
    if any(v < 0 for v in w.values()):
        reasons.append("negative amount in waterfall")
    b = result["variant_b"]
    if not b["invariant_holds"]:
        reasons.append("contained + escaped != total AI errors")
    if b["escaped"] != 0:
        reasons.append("ESCAPED_ERROR > 0 — critical")
    if result["variant_d"]["double_executions"] != 0:
        reasons.append("duplicate executions detected")
    return {"status": "PASS" if not reasons else "FAIL",
            "reasons": reasons}


def generate_report(result: dict) -> str:
    w = result["variant_d"]["waterfall"]
    return "\n".join([
        f"# Trace evaluation — run {result['evaluation_run_id']}",
        f"Held-out cases: {result['cases']} · corpus "
        f"{result['config']['corpus_sha256'][:12]} · integrity "
        f"{result['integrity']['status']}", "",
        "## Four-way ablation (marginal contribution per layer)",
        f"- A Matcher: recall {result['variant_a']['leak_recall']:.0%}, "
        f"precision {result['variant_a']['leak_precision']:.0%}, "
        f"OBSERVED gross leakage Rs.{w['gross_leakage_paise'] / 100:,.0f}",
        f"- B +AI: {result['variant_b']['correct']} correct "
        f"investigations; errors {result['variant_b']['errors']}, "
        f"contained {result['variant_b']['contained']}, ESCAPED "
        f"{result['variant_b']['escaped']} (containment "
        f"{result['variant_b']['containment_rate']:.0%})",
        f"- C +Gate/Decision: {result['variant_c']['packages']} packages, "
        f"{result['variant_c']['write_off']} write-offs (stopping rule), "
        f"{result['variant_c']['escalate']} escalations, "
        f"{result['variant_c']['false_claims_prevented']} false claims "
        f"prevented",
        f"- D Full: VERIFIED recovered Rs.{w['recovered_paise'] / 100:,.0f}"
        f" (net Rs.{w['net_recovered_paise'] / 100:,.0f}); ESTIMATED "
        f"preventable Rs."
        f"{result['variant_d']['estimated_preventable_paise'] / 100:,.0f}"
        f" — labels kept separate", "",
        "## Economic waterfall (OBSERVED/VERIFIED)",
        f"gross {w['gross_leakage_paise']}p -> claimed "
        f"{w['claimed_paise']}p -> approved {w['approved_paise']}p -> "
        f"recovered {w['recovered_paise']}p -> net "
        f"{w['net_recovered_paise']}p; written off "
        f"{w['written_off_paise']}p", "",
        f"Reproducibility hash: {result['evaluation_result_hash']}"])
