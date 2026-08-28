"""Trace T10 — the cockpit API. Every number served here is derived from
the real pipeline objects (discrepancies, verdicts, gate reports,
decisions, executions, recoveries, clusters, evaluation artifact) — the
UI can render only what the system actually did. Actions are enforced
server-side: an action the decision engine did not authorize returns 403
with the machine reason, and mutations require the executor/approver
role. Disabled is not hidden: the API names why."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import gate as G
from .audit import AuditChain
from .counterparty import CounterpartySim
from .decision import decide
from .evaluation import generate_report, run_evaluation
from .executor import ExecutionBlocked, Executor
from .investigator import investigate, report as inv_report, validate
from .lifecycle import case_from_discrepancy, portfolio_sla
from .portfolio import build_clusters, kpis as cluster_kpis
from .world import generate

NOW = datetime(2026, 7, 5, 12, 0)
ROLES_WRITE = {"executor", "approver", "admin"}


def build_state(data_dir: str | Path) -> dict:
    d = Path(data_dir)
    if not (d / "world.json").exists():
        generate(seed=42, out_dir=d)
    world = json.loads((d / "world.json").read_text())
    gt = json.loads((d / "ground_truth.json").read_text())["labels"]
    split = json.loads((d / "split.json").read_text())
    sim_now = split["sim_now"]
    chain = AuditChain()
    truth = G.recon_truth(world, sim_now)
    exceptions = sorted((t.to_dict() for t in truth.values()),
                        key=lambda e: e["exception_id"])
    st = {"world": world, "sim_now": sim_now, "chain": chain,
          "exceptions": {e["exception_id"]: e for e in exceptions},
          "hyps": {}, "verdicts": {}, "decisions": {}, "cases": {}}
    for e in exceptions:
        chain.append(f"case_{e['exception_id']}", "EXCEPTION_CREATED",
                     {"type": e["discrepancy_type"],
                      "delta_paise": e["delta_paise"]}, NOW)
        hyp = investigate(e, world, chain, NOW)
        v = validate(hyp, world, sim_now, chain, NOW)
        st["hyps"][e["exception_id"]] = hyp
        st["verdicts"][e["exception_id"]] = v
        st["decisions"][e["exception_id"]] = decide(e, v, world, sim_now)
        st["cases"][e["exception_id"]] = case_from_discrepancy(e, NOW)
    st["cp"] = CounterpartySim(world, gt, sim_now)
    st["executor"] = Executor(world, sim_now, st["cp"], chain)
    st["clusters"] = build_clusters(exceptions, world, sim_now,
                                    st["executor"].recoveries)
    st["evaluation"] = run_evaluation(d)
    return st


def allowed_actions(st, eid: str) -> dict:
    d = st["decisions"][eid]
    sel = d["selected_action"]
    out = {}
    for a in ("FILE_GATEWAY_CLAIM", "FILE_BANK_TRACE",
              "REQUEST_CUSTOMER_CLAWBACK", "WAIT", "ESCALATE",
              "WRITE_OFF"):
        if a == sel and "action_package" in d:
            out[a] = {"enabled": True, "reason": d["reason"]}
        elif a == sel:
            out[a] = {"enabled": True, "reason": d["reason"]}
        elif a in d.get("rejected_actions", {}):
            out[a] = {"enabled": False,
                      "reason": d["rejected_actions"][a]}
        elif a in ("WAIT", "ESCALATE"):
            out[a] = {"enabled": True,
                      "reason": "always available to humans"}
        else:
            out[a] = {"enabled": False,
                      "reason": f"decision engine selected {sel}"}
    return out


def create_app(data_dir: str | Path,
               frontend_dir: str | Path | None = None) -> Flask:
    st = build_state(data_dir)
    fe = Path(frontend_dir or Path(__file__).resolve().parents[2]
              / "frontend")
    app = Flask(__name__, static_folder=None)

    def role():
        return request.headers.get("X-Role", "analyst")

    @app.get("/health")
    def health():
        return jsonify({"clock": st["sim_now"],
                        "exceptions": len(st["exceptions"]),
                        "mode": "simulated world — labeled",
                        "chain_events": len(st["chain"].events)})

    @app.get("/kpis")
    def kpis():
        ex = st["executor"]
        mon = ex.monitors()
        w = st["evaluation"]["variant_d"]["waterfall"]
        gross = sum(abs(e["delta_paise"])
                    for e in st["exceptions"].values())
        claimed = sum(p["claim_amount_paise"] for did, p in
                      ((k, v.get("action_package")) for k, v in
                       st["decisions"].items()) if p)
        written = sum(abs(e["delta_paise"])
                      for k, e in st["exceptions"].items()
                      if st["decisions"][k]["selected_action"]
                      == "WRITE_OFF")
        ck = cluster_kpis(st["clusters"], ex.recoveries)
        sla = portfolio_sla(list(st["cases"].values()), NOW)
        return jsonify({
            "leakage_found_paise": gross,
            "claimed_paise": claimed,
            "recovered_paise": mon["gross_recovered_paise"],
            "net_recovered_paise": mon["net_recovered_paise"],
            "written_off_paise": written,
            "estimated_preventable_paise":
                ck["estimated_preventable_paise"],
            "labels": {"recovered": "ACTUAL",
                       "preventable": "ESTIMATED"},
            "false_claims_escaped":
                st["evaluation"]["variant_b"]["escaped"],
            "double_executions": mon["double_executions"],
            "sla": sla})

    @app.get("/exceptions")
    def list_exceptions():
        rows = []
        for eid, e in st["exceptions"].items():
            tx = next(t for t in st["world"]["gateway_txns"]
                      if t["id"] in e["affected_records"]["gateway_txns"])
            rows.append({"exception_id": eid,
                         "type": e["discrepancy_type"],
                         "order": {"id": e["order_id"]},
                         "gateway": {"id": tx["id"], "gw": tx["gateway"],
                                     "amount_paise": tx["amount_paise"]},
                         "bank": {"expected_paise": e["expected_paise"],
                                  "actual_paise": e["actual_paise"]},
                         "delta_paise": e["delta_paise"],
                         "decision":
                             st["decisions"][eid]["selected_action"],
                         "evidence": st["verdicts"][eid]["result"],
                         "state": st["cases"][eid].state,
                         "deadline": e["claim_deadline"]})
        return jsonify({"exceptions": rows})

    @app.get("/exceptions/<eid>")
    def detail(eid):
        if eid not in st["exceptions"]:
            return jsonify({"error": "no such exception"}), 404
        e = st["exceptions"][eid]
        hyp = st["hyps"][eid]
        graph = G.graph_builder(st["world"]).build(e)
        exec_rec = st["executor"].ledger.get(eid)
        recovery = next((r for r in st["executor"].recoveries
                         if r["exception_id"] == eid), None)
        return jsonify({
            "discrepancy": e,
            "explanation": G.graph_builder(st["world"])
            .explain(e, graph) if hasattr(
                G.graph_builder(st["world"]), "explain") else None,
            "evidence_graph": graph.to_dict(),
            "ai": inv_report(e, hyp, st["verdicts"][eid]),
            "admissibility": st["decisions"][eid].get("admissibility"),
            "decision": {k: v for k, v in st["decisions"][eid].items()
                         if k != "admissibility"},
            "allowed_actions": allowed_actions(st, eid),
            "execution": exec_rec, "recovery": recovery,
            "case": st["cases"][eid].to_dict(),
            "audit": st["chain"].for_case(f"case_{eid}")})

    @app.post("/exceptions/<eid>/action")
    def act(eid):
        if role() not in ROLES_WRITE:
            return jsonify({"error": f"role '{role()}' cannot execute "
                                     f"actions"}), 403
        if eid not in st["exceptions"]:
            return jsonify({"error": "no such exception"}), 404
        want = (request.get_json(silent=True) or {}).get("action")
        allowed = allowed_actions(st, eid)
        if want not in allowed or not allowed[want]["enabled"]:
            return jsonify({"error": "action not admissible",
                            "reason": allowed.get(want, {}).get(
                                "reason", "unknown action")}), 403
        d = st["decisions"][eid]
        if want.startswith(("FILE_", "REQUEST_")) and \
                "action_package" in d:
            pkg = d["action_package"]
            try:
                rec = st["executor"].execute(
                    pkg, approval=(role() in ("approver", "admin")))
            except ExecutionBlocked as ex:
                return jsonify({"error": str(ex)}), 403
            return jsonify({"execution": rec})
        case = st["cases"][eid]
        if want == "WAIT":
            case.wait(NOW, NOW, "human-requested wait")
        else:
            try:
                target = "ESCALATED" if want == "ESCALATE" \
                    else "WRITTEN_OFF"
                if case.state == "OPEN":
                    case.transition("INVESTIGATING", NOW)
                case.transition(target, NOW, f"human {want}")
            except Exception as ex:
                return jsonify({"error": str(ex)}), 409
        st["chain"].append(f"case_{eid}", "CASE_STATE_CHANGED",
                           {"by": role(), "action": want}, NOW)
        return jsonify({"case": case.to_dict()})

    @app.get("/clusters")
    def clusters():
        return jsonify({"clusters": st["clusters"]})

    @app.get("/evaluation")
    def evaluation():
        return jsonify({"result": st["evaluation"],
                        "report": generate_report(st["evaluation"])})

    @app.get("/audit/verify")
    def verify():
        return jsonify(st["chain"].verify(NOW))

    @app.get("/stream")
    def stream():
        n = int(request.args.get("n", 40))
        return jsonify({"events": st["chain"].events[-n:]})

    @app.get("/")
    def index():
        return send_from_directory(fe, "index.html")

    @app.get("/<path:p>")
    def static_files(p):
        return send_from_directory(fe, p)

    return app
