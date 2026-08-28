"""T11: boundaries hold — the AI lane cannot reach money, sources stay
immutable, roles gate mutations, and every number in the story is the
system's own."""
import ast
import json
import tempfile
import unittest
from pathlib import Path

from app.api import create_app
from app.models import record_hash

APP = Path(__file__).resolve().parents[1] / "app"
AI_LANE = ("investigator.py", "tools.py")
FORBIDDEN_FOR_AI = {"app.executor", "app.counterparty", ".executor",
                    ".counterparty"}


class TestBoundaries(unittest.TestCase):
    def test_ai_lane_cannot_import_money_layers(self):
        for fname in AI_LANE:
            tree = ast.parse((APP / fname).read_text())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom):
                    mods = [("." * node.level) + (node.module or "")]
                for m in mods:
                    for bad in FORBIDDEN_FOR_AI:
                        self.assertFalse(
                            m.endswith(bad.lstrip(".")) and
                            ("executor" in m or "counterparty" in m),
                            f"{fname} imports {m}")

    def test_tool_registry_exposes_no_write_methods(self):
        from app.tools import ToolRegistry
        public = [m for m in dir(ToolRegistry)
                  if not m.startswith("_")]
        for m in public:
            for verb in ("set", "write", "update", "delete", "create",
                         "post", "file", "execute"):
                self.assertFalse(m.startswith(verb), m)


class TestRolesAndImmutability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.world_before = record_hash(json.loads(
            (Path(cls.tmp.name) / "world.json").read_text())
            if (Path(cls.tmp.name) / "world.json").exists() else {})
        app = create_app(cls.tmp.name)
        app.testing = True
        cls.c = app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_source_records_unchanged_by_full_pipeline(self):
        # the on-disk world written at startup still hash-verifies row by
        # row after investigation, gating, decisions and executions
        world = json.loads((Path(self.tmp.name) / "world.json").read_text())
        for table, rows in world.items():
            for r in rows:
                body = {k: v for k, v in r.items() if k != "record_hash"}
                self.assertEqual(record_hash(body), r["record_hash"],
                                 (table, r["id"]))

    def test_roles_matrix(self):
        rows = self.c.get("/exceptions").get_json()["exceptions"]
        target = next(r for r in rows
                      if r["decision"] == "FILE_GATEWAY_CLAIM")
        url = f"/exceptions/{target['exception_id']}/action"
        body = {"action": "FILE_GATEWAY_CLAIM"}
        for role, code in (("analyst", 403), ("investigator", 403),
                           ("executor", 200), ("approver", 200)):
            r = self.c.post(url, json=body, headers={"X-Role": role})
            self.assertEqual(r.status_code, code, role)

    def test_every_case_has_traced_evidence_retrieval(self):
        rows = self.c.get("/exceptions").get_json()["exceptions"]
        d = self.c.get(f"/exceptions/{rows[0]['exception_id']}").get_json()
        steps = [e["event_type"] for e in d["audit"]]
        for must in ("EXCEPTION_CREATED", "INVESTIGATION_STARTED",
                     "EVIDENCE_RETRIEVED", "HYPOTHESIS_CREATED"):
            self.assertIn(must, steps)
