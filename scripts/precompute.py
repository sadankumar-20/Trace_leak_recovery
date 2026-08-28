#!/usr/bin/env python3
"""Precompute every API payload Trace's cockpit serves, so the deployed
demo answers from static JSON instead of rebuilding the pipeline per
serverless cold start. Only API-shaped (ground-truth-free) payloads are
written; world.json and ground_truth.json never ship."""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "backend"))
from app.api import create_app  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "precomputed"


def main():
    app = create_app(tempfile.mkdtemp())
    app.testing = True
    c = app.test_client()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "details").mkdir(exist_ok=True)
    (OUT / "actions").mkdir(exist_ok=True)

    for name, path in (("health", "/health"), ("kpis", "/kpis"),
                       ("exceptions", "/exceptions"),
                       ("clusters", "/clusters"),
                       ("evaluation", "/evaluation"),
                       ("audit_verify", "/audit/verify"),
                       ("stream", "/stream?n=40")):
        (OUT / f"{name}.json").write_text(
            json.dumps(c.get(path).get_json()))

    rows = c.get("/exceptions").get_json()["exceptions"]
    filed = 0
    # execute every authorized package once so actions replay idempotently
    for r in rows:
        if r["decision"].startswith(("FILE_", "REQUEST_")):
            resp = c.post(f"/exceptions/{r['exception_id']}/action",
                          json={"action": r["decision"]},
                          headers={"X-Role": "approver"})
            assert resp.status_code == 200, r
            (OUT / "actions" / f"{r['exception_id']}.json").write_text(
                json.dumps(resp.get_json()))
            filed += 1
    # refresh aggregates AFTER executions so KPIs show recovered money
    for name, path in (("kpis", "/kpis"), ("stream", "/stream?n=40"),
                       ("audit_verify", "/audit/verify"),
                       ("exceptions", "/exceptions")):
        (OUT / f"{name}.json").write_text(
            json.dumps(c.get(path).get_json()))
    for r in c.get("/exceptions").get_json()["exceptions"]:
        (OUT / "details" / f"{r['exception_id']}.json").write_text(
            json.dumps(c.get(f"/exceptions/{r['exception_id']}")
                       .get_json()))
    blob = "".join(f.read_text() for f in OUT.rglob("*.json"))
    for forbidden in ("outcome_if_claimed", "true_leak_paise", "gt_"):
        assert forbidden not in blob, forbidden
    size = sum(f.stat().st_size for f in OUT.rglob("*.json"))
    print(f"precomputed {filed} executions, "
          f"{len(list(OUT.rglob('*.json')))} files, "
          f"{size / 1e6:.1f} MB, gt-scan clean")


if __name__ == "__main__":
    main()
