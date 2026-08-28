"""Trace deploy mode: serve the precomputed, ground-truth-free API
payloads. Fast enough for serverless cold starts; role enforcement stays
server-side; POST actions replay the precomputed idempotent execution
(the demo is honest about being a frozen simulated world)."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parents[2]
PRE = ROOT / "data" / "precomputed"
FE = ROOT / "frontend"
ROLES_WRITE = {"executor", "approver", "admin"}


def _load(name):
    return json.loads((PRE / f"{name}.json").read_text())


def create_static_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/health")
    def health():
        h = _load("health")
        h["mode"] = "simulated world — labeled · precomputed demo"
        return jsonify(h)

    @app.get("/kpis")
    def kpis():
        return jsonify(_load("kpis"))

    @app.get("/exceptions")
    def exceptions():
        return jsonify(_load("exceptions"))

    @app.get("/exceptions/<eid>")
    def detail(eid):
        f = PRE / "details" / f"{eid}.json"
        if not f.exists():
            return jsonify({"error": "no such exception"}), 404
        return jsonify(json.loads(f.read_text()))

    @app.post("/exceptions/<eid>/action")
    def act(eid):
        role = request.headers.get("X-Role", "analyst")
        if role not in ROLES_WRITE:
            return jsonify({"error": f"role '{role}' cannot execute "
                                     f"actions"}), 403
        f = PRE / "actions" / f"{eid}.json"
        if f.exists():           # idempotent replay of the one execution
            return jsonify(json.loads(f.read_text()))
        det = PRE / "details" / f"{eid}.json"
        if not det.exists():
            return jsonify({"error": "no such exception"}), 404
        d = json.loads(det.read_text())
        want = (request.get_json(silent=True) or {}).get("action")
        allowed = d.get("allowed_actions", {})
        if want not in allowed or not allowed[want]["enabled"]:
            return jsonify({"error": "action not admissible",
                            "reason": allowed.get(want, {}).get(
                                "reason", "unknown action")}), 403
        return jsonify({"case": d["case"],
                        "note": "frozen demo world — non-filing actions "
                                "acknowledged without mutation"})

    @app.get("/clusters")
    def clusters():
        return jsonify(_load("clusters"))

    @app.get("/evaluation")
    def evaluation():
        return jsonify(_load("evaluation"))

    @app.get("/audit/verify")
    def verify():
        return jsonify(_load("audit_verify"))

    @app.get("/stream")
    def stream():
        return jsonify(_load("stream"))

    @app.get("/")
    def index():
        return send_from_directory(FE, "index.html")

    @app.get("/<path:p>")
    def static_files(p):
        return send_from_directory(FE, p)

    return app
