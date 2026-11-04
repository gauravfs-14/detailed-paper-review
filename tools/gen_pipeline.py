#!/usr/bin/env python3
"""Writes pipeline.json, the step-by-step form of SKILL.md for apps that drive a review themselves.
Edit this file (not pipeline.json) and run it; tests/test_pipeline.py checks the two agree."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = "agents/_evidence-rules.md"


def script(id, run, after=None, when=None, optional=False, phase=None, label=None):
    s = {"id": id, "kind": "script", "run": run}
    if label:
        s["label"] = label
    if phase:
        s["phase"] = phase
    if after is not None:
        s["after"] = after
    if when:
        s["when"] = when
    if optional:
        s["optional"] = True
    return s


def agent(id, brief, task, outputs, after=None, when=None, phase=None, rulebook=None, plan=None, reads=None,
          tools=("read", "write"), label=None, isolated=False, vision=False, optional=False, may_write=None):
    s = {"id": id, "kind": "agents" if plan else "agent", "brief": brief, "task": task, "outputs": outputs,
         "tools": list(tools)}
    if may_write:
        s["may_write"] = may_write
    if label:
        s["label"] = label
    if phase:
        s["phase"] = phase
    if rulebook:
        s["rulebook"] = rulebook
    if plan:
        s["plan"] = plan
    if reads:
        s["reads"] = reads
    if isolated:
        s["isolated"] = True
    if vision:
        s["vision"] = True
    if after is not None:
        s["after"] = after
    if when:
        s["when"] = when
    if optional:
        s["optional"] = True
    return s


RT = "scripts/review_tool.py"
steps = [
    # ---- intake and mechanical first passes
    script("extract", ["scripts/extract_manuscript.py", "{MANUSCRIPT}", "--out", "{RV}", ["--bib", "{BIB}"]],
           after=[], label="Reading the manuscript"),
    script("text-checks", ["scripts/text_checks.py", "all", "--review", "{RV}"], after=["extract"]),
    script("claim-tools", ["scripts/claim_tools.py", "all", "--review", "{RV}"], after=["extract"]),
    script("plan-sections", [RT, "plan-sections", "--review", "{RV}"], after=["extract"]),

    # ---- phase 1: references
    script("verify-refs", ["scripts/verify_refs.py", "--review", "{RV}"], after=["extract"], phase="01-references",
           label="Looking up every reference"),
    script("fetch-sources", ["scripts/fetch_sources.py", "--review", "{RV}", ["--local-pdfs", "{LOCAL_PDFS}"]],
           after=["verify-refs"], phase="01-references", label="Downloading cited papers"),
    script("plan-refs", [RT, "plan-refs", "--review", "{RV}"], after=["fetch-sources"], phase="01-references"),
    agent("ref-check", "agents/ref-checker.md",
          "Reference keys: {keys}. Group file: {input}. Write the result to {output}.",
          ["{output}"], after=["plan-refs"], phase="01-references", rulebook="references/01-references.md",
          plan="work/refs/plan.json",
          reads=["manuscript/manuscript.json", "refcheck/records/", "sources/manifest.json"],
          tools=("read", "write", "scripts", "web"), label="Checking references"),
    script("merge-refs", [RT, "merge-refs", "--review", "{RV}"], after=["ref-check"], phase="01-references"),
    agent("ref-list", "agents/host/ref-list-auditor.md", "Write {output}.", ["work/refs/list.json"],
          after=["merge-refs"], phase="01-references", rulebook="references/01-references.md",
          reads=["phases/01-references.json", "manuscript/manuscript.json", "refcheck/auto_refs.json", "review.json"]),
    script("apply-ref-list", [RT, "apply-ref-list", "--review", "{RV}"], after=["ref-list"], phase="01-references"),
    script("zotero-push", ["scripts/zotero_lib.py", "push", "--review", "{RV}"], after=["apply-ref-list"],
           when="zotero", optional=True, phase="01-references", label="Filing references in Zotero"),

    # ---- phase 2: fact check (after phase 1: it may add full texts)
    script("plan-factcheck", [RT, "plan-factcheck", "--review", "{RV}"], after=["apply-ref-list"], phase="02-factcheck"),
    agent("factcheck", "agents/fact-checker.md",
          "Batch file: {input}. Write the result to {output}.", ["{output}"],
          after=["plan-factcheck"], phase="02-factcheck", rulebook="references/02-fact-check.md",
          plan="work/factcheck/index.json", reads=["sources/text/"], label="Fact-checking cited sentences"),
    script("merge-factcheck-1", [RT, "merge-factcheck", "--review", "{RV}"], after=["factcheck"], phase="02-factcheck"),
    script("plan-second", [RT, "plan-second", "--review", "{RV}"], after=["merge-factcheck-1"], phase="02-factcheck"),
    agent("second-check", "agents/second-checker.md",
          "Items: {input}. Write the result to {output}.", ["{output}"],
          after=["plan-second"], phase="02-factcheck", rulebook="references/02-fact-check.md",
          plan="work/factcheck/second-plan.json", reads=["sources/text/"], isolated=True,
          label="Independent second check"),
    script("attach-second", [RT, "attach-second", "--review", "{RV}"], after=["second-check"], phase="02-factcheck"),
    script("plan-adjudication", [RT, "plan-adjudication", "--review", "{RV}"], after=["attach-second"], phase="02-factcheck"),
    agent("adjudicate", "agents/host/adjudicator.md", "Items: {input}. Write the result to {output}.", ["{output}"],
          after=["plan-adjudication"], phase="02-factcheck", rulebook="references/02-fact-check.md",
          plan="work/factcheck/adjudication-plan.json", reads=["sources/text/"]),
    script("apply-adjudication", [RT, "apply-adjudication", "--review", "{RV}"], after=["adjudicate"], phase="02-factcheck"),
    script("merge-factcheck-2", [RT, "merge-factcheck", "--review", "{RV}"], after=["apply-adjudication"], phase="02-factcheck"),
    script("verify-quotes", [RT, "verify-quotes", "--review", "{RV}"], after=["merge-factcheck-2"], phase="02-factcheck",
           label="Checking every quote against the sources"),
    script("plan-redo", [RT, "plan-redo", "--review", "{RV}"], after=["verify-quotes"], phase="02-factcheck"),
    agent("redo", "agents/fact-checker.md", "Batch file: {input}. Write the result to {output}.", ["{output}"],
          after=["plan-redo"], phase="02-factcheck", rulebook="references/02-fact-check.md",
          plan="work/factcheck/redo-plan.json", reads=["sources/text/"], label="Redoing claims whose quotes were not found"),
    script("apply-redo", [RT, "apply-redo", "--review", "{RV}"], after=["redo"], phase="02-factcheck"),
    script("merge-factcheck-3", [RT, "merge-factcheck", "--review", "{RV}"], after=["apply-redo"], phase="02-factcheck"),
    script("plan-second-2", [RT, "plan-second", "--review", "{RV}"], after=["merge-factcheck-3"], phase="02-factcheck"),
    agent("second-check-2", "agents/second-checker.md", "Items: {input}. Write the result to {output}.", ["{output}"],
          after=["plan-second-2"], phase="02-factcheck", rulebook="references/02-fact-check.md",
          plan="work/factcheck/second-plan.json", reads=["sources/text/"], isolated=True),
    script("attach-second-2", [RT, "attach-second", "--review", "{RV}"], after=["second-check-2"], phase="02-factcheck"),
    script("plan-adjudication-2", [RT, "plan-adjudication", "--review", "{RV}"], after=["attach-second-2"], phase="02-factcheck"),
    agent("adjudicate-2", "agents/host/adjudicator.md", "Items: {input}. Write the result to {output}.", ["{output}"],
          after=["plan-adjudication-2"], phase="02-factcheck", rulebook="references/02-fact-check.md",
          plan="work/factcheck/adjudication-plan.json", reads=["sources/text/"]),
    script("apply-adjudication-2", [RT, "apply-adjudication", "--review", "{RV}"], after=["adjudicate-2"], phase="02-factcheck"),
    script("merge-factcheck-4", [RT, "merge-factcheck", "--review", "{RV}"], after=["apply-adjudication-2"], phase="02-factcheck"),
    script("verify-quotes-2", [RT, "verify-quotes", "--review", "{RV}"], after=["merge-factcheck-4"], phase="02-factcheck"),
]

P2 = "verify-quotes-2"
AUD = "agents/phase-auditor.md"
AUD_TASK = "Phase {phase}. Write {output}."


def auditor(phase, rulebook, reads, after=(P2,), when=None, vision=False, tools=("read", "write", "scripts")):
    return agent(f"audit-{phase}", AUD, AUD_TASK, [f"phases/{phase}.json"], after=list(after), when=when,
                 phase=phase, rulebook=rulebook, reads=["manuscript/manuscript.json"] + reads, tools=tools, vision=vision)


SECTION_TASKS = [("consistency", "references/03-consistency.md"), ("acronyms", "references/05-acronyms.md"),
                 ("editorial", "references/08-editorial.md")]
for task, rb in SECTION_TASKS:
    steps.append(agent(f"sections-{task}", "agents/section-auditor.md",
                       f"Task: {task}. Part file: {{input}}. Write the result to work/{task}/{{id}}.json.",
                       [f"work/{task}/{{id}}.json"], after=["plan-sections", P2], when="long",
                       rulebook=rb, plan="work/sections/plan.json",
                       phase={"consistency": "03-consistency", "acronyms": "05-acronyms", "editorial": "08-editorial"}[task]))

steps += [
    auditor("02b-uncited-claims", "references/02b-uncited-claims.md", ["work/uncited_auto.json"]),
    auditor("02c-literature", "references/02c-literature.md", ["phases/01-references.json"],
            tools=("read", "write", "scripts", "web")),
    auditor("02d-text-overlap", "references/02d-text-overlap.md", ["work/overlap_auto.json", "sources/text/"]),
    auditor("03-consistency", "references/03-consistency.md",
            ["work/consistency_auto.json", "work/numbers.json", "work/consistency/"], after=(P2, "sections-consistency")),
    auditor("03b-claim-map", "references/03b-claim-map.md", ["work/claimmap_auto.json", "phases/02-factcheck.json"]),
    auditor("04-methods-stats", "references/04-methods-stats.md", ["work/numbers.json"]),
    auditor("04b-missing-reporting", "references/04b-missing-reporting.md", ["review.json"],
            tools=("read", "write", "scripts", "web")),
    auditor("04c-equations", "references/04c-equations.md", ["work/equations.json"]),
    auditor("05-acronyms", "references/05-acronyms.md", ["work/acronyms_auto.json", "work/acronyms/"],
            after=(P2, "sections-acronyms")),
    auditor("06-figures-tables", "references/06-figures-tables.md", ["work/numbers.json"], vision=True),
    auditor("07-crossrefs", "references/07-crossrefs.md", ["work/crossrefs_auto.json"]),
    auditor("08-editorial", "references/08-editorial.md", ["work/editorial/", "review.json"], after=(P2, "sections-editorial"),
            tools=("read", "write", "scripts", "web")),

    # ---- phase R: revisions only
    script("revision-tool", ["scripts/revision_tool.py", "--review", "{RV}", "--revised", "{MANUSCRIPT}",
                             "--response", "{RESPONSE}", ["--previous", "{PREVIOUS}"], ["--annotated", "{ANNOTATED}"],
                             ["--comments", "{COMMENTS}"]], after=["extract"], when="revision", phase="R-revision"),
    auditor("R-revision", "references/11-revision.md", ["work/revision/auto.json"], after=(P2, "revision-tool"),
            when="revision"),

    # ---- phase 9: blind peer review (sees only the manuscript)
    agent("lenses", "agents/host/lens-setter.md", "Write {output}.", ["work/review/lenses.json"], after=["extract"],
          phase="09-peer-review", rulebook="references/09-peer-review.md", reads=["manuscript/manuscript.json"],
          isolated=True),
    agent("reviewers", "agents/reviewer.md", "You are Reviewer {id}. Your lens: {lens}. Write your report to {output}.",
          ["{output}"], after=["lenses"], phase="09-peer-review", rulebook="references/09-peer-review.md",
          plan="work/review/lenses.json", reads=["manuscript/manuscript.json"], isolated=True, vision=True,
          tools=("read", "write", "scripts"), label="Blind peer review"),
    script("merge-review", [RT, "merge-review", "--review", "{RV}"], after=["reviewers"], phase="09-peer-review"),
    agent("synthesis", "agents/host/synthesizer.md", "Write {output}.", ["work/review/synthesis.json"],
          after=["merge-review"], phase="09-peer-review", rulebook="references/09-peer-review.md",
          reads=["phases/09-peer-review.json"]),
    script("apply-synthesis", [RT, "apply-synthesis", "--review", "{RV}"], after=["synthesis"], phase="09-peer-review"),
]

AUDITS = [s["id"] for s in steps if s["id"].startswith("audit-")] + ["apply-synthesis"]
steps += [
    # ---- fix mode (editable source only)
    agent("fixes", "agents/host/fixes-writer.md", "Write {output}.", ["fixes.json"], after=AUDITS, when="fix",
          reads=["phases/", "review.json"], label="Writing fixes"),
    script("apply-fixes", ["scripts/apply_fixes.py", "--review", "{RV}", "--source-dir", "{SOURCE_DIR}"],
           after=["fixes"], when="fix"),
    script("verify-fixes", ["scripts/verify_fixes.py", "--review", "{RV}", "--source-dir", "{SOURCE_DIR}"],
           after=["apply-fixes"], when="fix", optional=True, label="Verifying fixes"),
    agent("fix-verify", "agents/fix-verifier.md", "Write {output}.", ["work/fixcheck/result.json"],
          after=["verify-fixes"], when="fix",
          reads=["work/fixcheck/changed.json", "corrected-by-agent/verify.json", "corrected-by-agent/clean/", "sources/text/"]),
    script("finalize-fixes", ["scripts/verify_fixes.py", "--review", "{RV}", "--source-dir", "{SOURCE_DIR}", "--finalize"],
           after=["fix-verify"], when="fix", optional=True),

    # ---- phases 10 and 11
    script("dedupe", [RT, "dedupe", "--review", "{RV}"], after=AUDITS + ["finalize-fixes"]),
    script("dashboard-1", ["scripts/build_dashboard.py", "--review", "{RV}"], after=["dedupe"]),
    agent("summary", "agents/host/summary-writer.md", "Write {output}.", ["phases/00-summary.json"],
          may_write=["phases/_merge.json"], after=["dashboard-1"], reads=["phases/", "review.json", "sources/to_download.json"],
          label="Writing the summary"),
    script("dedupe-2", [RT, "dedupe", "--review", "{RV}"], after=["summary"]),
    script("dashboard", ["scripts/build_dashboard.py", "--review", "{RV}"], after=["dedupe-2"],
           label="Checking coverage and building results"),
    script("report", ["scripts/build_report.py", "--review", "{RV}"], after=["dashboard"], optional=True,
           label="Building the PDF report"),
]

pipeline = {
    "schema": 1,
    "about": "Step-by-step form of SKILL.md for apps that run a review themselves. See PIPELINE.md. "
             "Generated by tools/gen_pipeline.py; do not edit by hand.",
    "evidence_rules": EV,
    "output_schema": "references/output-schema.md",
    "results": "dashboard/data.json",
    "steps": steps,
}
with open(os.path.join(ROOT, "pipeline.json"), "w", encoding="utf-8") as fh:
    json.dump(pipeline, fh, indent=1, ensure_ascii=False)
    fh.write("\n")
print(f"pipeline.json: {len(steps)} steps")
