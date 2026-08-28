"""Deploy mode: precomputed payloads serve identically-shaped, gt-free
responses with roles and idempotency intact."""
import json
import unittest
from pathlib import Path

from app.static_api import PRE, create_static_app


@unittest.skipUnless((PRE / "kpis.json").exists(),
                     "precomputed artifacts not generated")
class TestStaticApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = create_static_app()
        app.testing = True
        cls.c = app.test_client()

    def test_surfaces_and_gt_hygiene(self):
        for path in ("/health", "/kpis", "/exceptions", "/clusters",
                     "/evaluation", "/audit/verify", "/stream"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 200, path)
        blob = json.dumps(self.c.get("/exceptions").get_json())
        for bad in ("outcome_if_claimed", "true_leak_paise", "gt_"):
            self.assertNotIn(bad, blob)
        self.assertIn("precomputed demo",
                      self.c.get("/health").get_json()["mode"])

    def test_roles_and_idempotent_replay(self):
        rows = self.c.get("/exceptions").get_json()["exceptions"]
        filed = next(r for r in rows
                     if r["decision"].startswith("FILE_"))
        url = f"/exceptions/{filed['exception_id']}/action"
        self.assertEqual(self.c.post(url, json={"action":
                         filed["decision"]},
                         headers={"X-Role": "analyst"}).status_code, 403)
        a = self.c.post(url, json={"action": filed["decision"]},
                        headers={"X-Role": "executor"}).get_json()
        b = self.c.post(url, json={"action": filed["decision"]},
                        headers={"X-Role": "executor"}).get_json()
        self.assertEqual(a["execution"]["execution_id"],
                         b["execution"]["execution_id"])
        wo = next(r for r in rows if r["decision"] == "WRITE_OFF")
        r = self.c.post(f"/exceptions/{wo['exception_id']}/action",
                        json={"action": "FILE_GATEWAY_CLAIM"},
                        headers={"X-Role": "executor"})
        self.assertEqual(r.status_code, 403)

    def test_kpis_reflect_executed_state(self):
        k = self.c.get("/kpis").get_json()
        self.assertGreater(k["recovered_paise"], 0)
        self.assertEqual(k["double_executions"], 0)
        self.assertEqual(k["labels"]["preventable"], "ESTIMATED")
