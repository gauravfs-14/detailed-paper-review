"""The task-plan commands for apps (plan-refs, plan-second, adjudication, redo, list findings, synthesis)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
SOURCE = ("Pedestrian deaths rose by 13 percent between 2019 and 2022 in the study area, according to the "
          "state crash database maintained by the department of transportation.")


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class ReviewTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rv = self.rv = self.tmp.name
        refs = [{"ID": f"r{i}", "title": f"Paper {i}"} for i in range(1, 15)] + [{"ID": "r1b", "alias_of": "r1"}]
        sents = [{"id": f"s{i:04d}", "section": "intro", "file": "main.tex", "line": i, "text": f"Claim {i}.",
                  "raw": f"Claim {i} \\cite{{r{i}}}.", "cites": [f"r{i}"]} for i in range(1, 15)]
        write(os.path.join(rv, "manuscript", "manuscript.json"),
              {"references": refs, "sentences": sents, "sections": [{"id": "intro", "title": "Introduction"}]})
        for i in range(1, 15):
            write(os.path.join(rv, "sources", "text", f"r{i}.json"), {"kind": "fulltext", "pages": [SOURCE], "abstract": ""})

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, cmd):
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "review_tool.py"), cmd, "--review", self.rv],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def results(self, verdicts):
        items = [{"id": f"b01-{i:02d}", "sentence_id": f"s{i:04d}", "cite": f"r{i}", "claim": f"Claim {i}",
                  "verdict": v, "evidence": [{"source_key": f"r{i}", "quote": "rose by 13 percent between 2019 and 2022"}]}
                 for i, v in enumerate(verdicts, 1)]
        write(os.path.join(self.rv, "work", "factcheck", "batch-01.result.json"), {"batch": "batch-01", "items": items})

    def test_plan_refs_skips_aliases_and_groups(self):
        self.run_tool("plan-refs")
        plan = read(os.path.join(self.rv, "work", "refs", "plan.json"))
        keys = [k for t in plan["tasks"] for k in t["keys"]]
        self.assertEqual(len(keys), 14)
        self.assertNotIn("r1b", keys)
        self.assertEqual([len(t["keys"]) for t in plan["tasks"]], [12, 2])
        self.assertTrue(os.path.exists(os.path.join(self.rv, plan["tasks"][0]["input"])))

    def test_plan_factcheck_lists_tasks(self):
        self.run_tool("plan-factcheck")
        idx = read(os.path.join(self.rv, "work", "factcheck", "index.json"))
        self.assertEqual([t["id"] for t in idx["tasks"]], [b["batch"] for b in idx["batches"]])

    def test_second_check_hides_first_verdict_and_samples(self):
        self.results(["supported"] * 12 + ["partial", "not_supported"])
        self.run_tool("plan-second")
        plan = read(os.path.join(self.rv, "work", "factcheck", "second-plan.json"))
        self.assertEqual(plan["flagged"], 2)
        self.assertEqual(plan["sampled_supported"], 3)
        rows = [r for t in plan["tasks"] for r in read(os.path.join(self.rv, t["input"]))["items"]]
        self.assertEqual(len(rows), 5)
        for r in rows:
            self.assertNotIn("verdict", r)
            self.assertNotIn("evidence", r)
        # once attached, the same items are not planned again
        write(os.path.join(self.rv, "work", "factcheck", "second-01.json"),
              {"items": [{"id": r["id"], "verdict": "supported", "quote": "rose by 13 percent", "page": 1} for r in rows]})
        self.run_tool("attach-second")
        self.run_tool("plan-second")
        self.assertEqual(read(os.path.join(self.rv, "work", "factcheck", "second-plan.json"))["tasks"], [])

    def test_adjudication_round_trip(self):
        self.results(["supported"] * 13 + ["not_supported"])
        write(os.path.join(self.rv, "work", "factcheck", "second-01.json"),
              {"items": [{"id": "b01-14", "verdict": "supported", "quote": "rose by 13 percent", "page": 1}]})
        self.run_tool("attach-second")
        self.run_tool("plan-adjudication")
        plan = read(os.path.join(self.rv, "work", "factcheck", "adjudication-plan.json"))
        self.assertEqual(plan["disagreements"], 1)
        write(os.path.join(self.rv, "work", "factcheck", "adjudication.json"),
              {"items": [{"id": "b01-14", "verdict": "supported", "reason": "page 1 states it"}]})
        self.run_tool("apply-adjudication")
        it = read(os.path.join(self.rv, "work", "factcheck", "batch-01.result.json"))["items"][13]
        self.assertEqual((it["verdict"], it["first_verdict"]), ("supported", "not_supported"))
        self.assertIn("page 1", it["second_check"]["adjudication"])
        self.run_tool("plan-adjudication")
        self.assertEqual(read(os.path.join(self.rv, "work", "factcheck", "adjudication-plan.json"))["tasks"], [])

    def test_redo_replaces_failed_quotes(self):
        self.run_tool("plan-factcheck")
        self.results(["supported"] * 14)
        items = read(os.path.join(self.rv, "work", "factcheck", "batch-01.result.json"))
        items["items"][0]["evidence"][0]["quote"] = "a sentence that is nowhere in the source text at all"
        write(os.path.join(self.rv, "work", "factcheck", "batch-01.result.json"), items)
        self.run_tool("merge-factcheck")
        self.run_tool("verify-quotes")
        self.run_tool("plan-redo")
        plan = read(os.path.join(self.rv, "work", "factcheck", "redo-plan.json"))
        self.assertEqual(plan["items"], 1)
        batch = read(os.path.join(self.rv, plan["tasks"][0]["input"]))
        self.assertEqual([s["cites"] for s in batch["sentences"]], [["r1"]])
        write(os.path.join(self.rv, plan["tasks"][0]["output"]), {"items": [
            {"id": "x", "sentence_id": "s0001", "cite": "r1", "verdict": "supported",
             "evidence": [{"source_key": "r1", "quote": "rose by 13 percent between 2019 and 2022"}]}]})
        self.run_tool("apply-redo")
        it = read(os.path.join(self.rv, "work", "factcheck", "batch-01.result.json"))["items"][0]
        self.assertEqual((it["id"], it["redone"]), ("b01-01", True))
        self.run_tool("merge-factcheck")
        self.run_tool("verify-quotes")
        ph = read(os.path.join(self.rv, "phases", "02-factcheck.json"))
        self.assertFalse([i for i in ph["items"] if i.get("quote_check_failed")])

    def test_list_findings_and_synthesis(self):
        write(os.path.join(self.rv, "phases", "01-references.json"),
              {"phase": "01-references", "items": [], "findings": [{"id": "REF-001"}, {"id": "REF-L01", "old": True}]})
        write(os.path.join(self.rv, "work", "refs", "list.json"),
              {"summary": "All fine.", "findings": [{"id": "REF-L01"}, {"id": "not-a-list-finding"}]})
        self.run_tool("apply-ref-list")
        ph = read(os.path.join(self.rv, "phases", "01-references.json"))
        self.assertEqual([f["id"] for f in ph["findings"]], ["REF-001", "REF-L01"])
        self.assertNotIn("old", ph["findings"][1])
        self.assertEqual(ph["summary"], "All fine.")
        write(os.path.join(self.rv, "work", "review", "R1.json"), {"name": "Reviewer 1"})
        self.run_tool("merge-review")
        write(os.path.join(self.rv, "work", "review", "synthesis.json"),
              {"summary": "s", "synthesis": "Both agree.", "findings": [{"id": "PR-01"}]})
        self.run_tool("apply-synthesis")
        ph = read(os.path.join(self.rv, "phases", "09-peer-review.json"))
        self.assertEqual((ph["status"], ph["synthesis"], len(ph["reviewers"])), ("complete", "Both agree.", 1))


if __name__ == "__main__":
    unittest.main()
