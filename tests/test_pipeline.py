"""pipeline.json is generated, consistent, and names only files and commands that exist."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return json.load(fh)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.p = load("pipeline.json")
        self.steps = self.p["steps"]

    def test_generated_file_is_current(self):
        with tempfile.TemporaryDirectory() as t:
            with open(os.path.join(ROOT, "tools", "gen_pipeline.py"), encoding="utf-8") as fh:
                src = fh.read()
            os.makedirs(os.path.join(t, "tools"))
            script = os.path.join(t, "tools", "gen.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(src)
            subprocess.run([sys.executable, "-I", script], check=True, capture_output=True)
            with open(os.path.join(t, "pipeline.json"), encoding="utf-8") as fh:
                fresh = json.load(fh)
        self.assertEqual(fresh, self.p, "pipeline.json is out of date: run python tools/gen_pipeline.py")

    def test_schema_matches_skill_json(self):
        self.assertEqual(load("skill.json")["pipeline_schema"], self.p["schema"])

    def test_ids_unique_and_after_refers_back(self):
        seen = set()
        for s in self.steps:
            self.assertNotIn(s["id"], seen)
            for a in s.get("after", []):
                self.assertIn(a, seen, f"{s['id']} runs after {a}, which is not an earlier step")
            seen.add(s["id"])

    def test_files_exist(self):
        for f in (self.p["evidence_rules"], self.p["output_schema"]):
            self.assertTrue(os.path.exists(os.path.join(ROOT, f)), f)
        for s in self.steps:
            if s["kind"] == "script":
                self.assertTrue(os.path.exists(os.path.join(ROOT, s["run"][0])), s["id"])
            else:
                self.assertTrue(os.path.exists(os.path.join(ROOT, s["brief"])), s["id"])
                if s.get("rulebook"):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, s["rulebook"])), s["id"])

    def test_review_tool_commands_exist(self):
        help_text = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "scripts", "review_tool.py"), "--help"],
                                   capture_output=True, text=True).stdout
        for s in self.steps:
            if s["kind"] == "script" and s["run"][0].endswith("review_tool.py"):
                self.assertIn(s["run"][1], help_text, s["id"])

    def test_known_values(self):
        placeholders = {"SKILL", "RV", "PY", "MANUSCRIPT", "BIB", "PDF", "LOCAL_PDFS", "SOURCE_DIR", "RESPONSE",
                        "PREVIOUS", "ANNOTATED", "COMMENTS"}
        for s in self.steps:
            self.assertIn(s.get("when", "revision"), {"revision", "fix", "long", "zotero"}, s["id"])
            if s["kind"] == "script":
                flat = json.dumps(s["run"])
                for ph in re.findall(r"\{([A-Z_]+)\}", flat):
                    self.assertIn(ph, placeholders, s["id"])
            else:
                self.assertTrue(set(s["tools"]) <= {"read", "write", "scripts", "web"}, s["id"])
                self.assertTrue(s["outputs"], s["id"])
                if s["kind"] == "agents":
                    self.assertIn("plan", s)

    def test_plans_are_made_by_an_earlier_step(self):
        made_by = {"work/refs/plan.json": "plan-refs", "work/factcheck/index.json": "plan-factcheck",
                   "work/factcheck/second-plan.json": "plan-second", "work/factcheck/adjudication-plan.json": "plan-adjudication",
                   "work/factcheck/redo-plan.json": "plan-redo", "work/sections/plan.json": "plan-sections",
                   "work/review/lenses.json": None}
        order = {s["id"]: i for i, s in enumerate(self.steps)}
        for s in self.steps:
            if s["kind"] != "agents":
                continue
            self.assertIn(s["plan"], made_by, s["id"])
            maker = made_by[s["plan"]]
            if maker:
                self.assertTrue(any(order[a] < order[s["id"]] and self.steps[order[a]]["run"][1].startswith(maker)
                                    for a in s["after"] if self.steps[order[a]]["kind"] == "script"
                                    and len(self.steps[order[a]]["run"]) > 1), s["id"])

    def test_every_phase_has_a_step(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import review_tool
        covered = {s.get("phase") for s in self.steps}
        for pid, _ in review_tool.PHASES:
            self.assertIn(pid, covered, pid)


if __name__ == "__main__":
    unittest.main()
