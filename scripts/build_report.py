#!/usr/bin/env python3
"""Write REPORT.md and REPORT.pdf from the phase files. The agent writes only phases/00-summary.json.

  python build_report.py --review paper-review/main

Layout (plain English, short blocks, most important first):
  verdict -> the short version -> fix these first -> was everything checked? ->
  what could not be checked -> phase by phase -> appendices (references, claims, reviewers)
PDF: pandoc + xelatex when available, otherwise a print-ready HTML file is written instead.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import read_json  # noqa: E402
import review_tool  # noqa: E402

SEV = ["critical", "major", "minor", "info"]
SEV_WORD = {"critical": "CRITICAL", "major": "MAJOR", "minor": "minor", "info": "info"}
STATUS_WORD = {"complete": "Done", "incomplete": "NOT FINISHED", "not_run": "NOT RUN", "skipped": "Skipped"}
VERDICT = {"ready": "Ready for submission", "almost": "Almost ready", "not_ready": "Not ready yet"}
VWORD = {"supported": "Supported", "partial": "Partly supported", "not_supported": "NOT supported",
         "contradicted": "CONTRADICTS source", "cannot_verify": "Could not verify", "verified": "Verified",
         "needs_fix": "Needs fix", "check": "Check by hand", "unverifiable": "Could not verify"}


def md_escape(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ").strip()


def where(loc):
    if not loc:
        return ""
    s = f"{loc.get('file') or ''}{(':' + str(loc['line'])) if loc.get('line') else ''}"
    if loc.get("section"):
        s += f" ({loc['section']})"
    if loc.get("label"):
        s += f" [{loc['label']}]"
    return s.strip()


def finding_block(f):
    out = [f"**{SEV_WORD.get(f.get('severity'), f.get('severity', ''))}: {f.get('title', '')}**  "]
    if where(f.get("location")):
        out.append(f"*Where:* `{where(f['location'])}`  ")
    if f.get("what"):
        out.append(f"*Problem:* {f['what']}  ")
    if f.get("why"):
        out.append(f"*Why it matters:* {f['why']}  ")
    if f.get("fix"):
        out.append(f"*Fix:* {f['fix']}  ")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    a = ap.parse_args()
    rv = a.review
    S = read_json(os.path.join(rv, "phases", "00-summary.json"), {})
    status = read_json(os.path.join(rv, "phases", "_status.json"), {})
    phases = []
    for pid, title in review_tool.PHASES:
        ph = read_json(os.path.join(rv, "phases", pid + ".json")) or {"phase": pid, "title": title, "status": "not_run", "findings": []}
        ph.setdefault("title", title)
        if pid in status:  # status as enforced by build_dashboard.py
            ph["status"] = status[pid]["status"]
            ph["status_reason"] = status[pid]["reason"]
        phases.append(ph)
    allf = [dict(f, _phase=p["title"]) for p in phases for f in p.get("findings", [])]
    issues = (read_json(os.path.join(rv, "phases", "_issues.json"), {}) or {}).get("issues") or allf
    n = {s: sum(1 for f in issues if f.get("severity") == s) for s in SEV}
    meta = read_json(os.path.join(rv, "review.json"), {}) or {}
    L = []
    title = S.get("paper_title")
    if not title:
        try:
            dj = open(os.path.join(rv, "dashboard", "data.js"), encoding="utf-8").read()
            title = json.loads(dj[dj.index("{"):dj.rstrip().rstrip(";").rindex("}") + 1])["paper"]["title"]
        except Exception:
            title = "manuscript"
    L.append(f"# Paper review: {title}\n")
    L.append(f"**Verdict: {VERDICT.get(S.get('verdict'), 'no verdict yet')}**\n")
    if meta:
        L.append(f"Target: {meta.get('journal') or 'no journal given'}  |  "
                 f"{'Revision' + (' round ' + str(meta['round']) if meta.get('round') else '') if meta.get('submission') == 'revision' else 'First submission'}  |  "
                 f"{'Review and fix' if meta.get('mode') == 'fix' else 'Review only'}\n")
    applicable = [p for p in phases if p["status"] != "skipped"]
    L.append(f"Distinct issues: Critical **{n['critical']}**  |  Major **{n['major']}**  |  Minor {n['minor']}  |  "
             f"Phases finished: {sum(1 for p in applicable if p['status'] == 'complete')} of {len(applicable)}"
             + (f"  ({len(allf)} findings from all phases, merged where they describe the same problem)" if len(allf) != len(issues) else "") + "\n")
    notdone = [p for p in phases if p["status"] not in ("complete", "skipped")]
    if notdone:
        L.append("> **Warning: this review is not finished.** These phases are incomplete, so their problems are "
                 "not in this report: " + ", ".join(p["title"] for p in notdone) + ".\n")
    if S.get("short_version"):
        L.append("## The short version\n")
        L += [f"- {x}" for x in S["short_version"]]
        L.append("")
    elif S.get("overview"):
        L.append("## The short version\n\n" + S["overview"] + "\n")
    L.append("## Fix these first\n")
    top = S.get("top_problems") or [{"title": f["title"], "why": f.get("what", "")} for f in allf if f.get("severity") == "critical"][:5]
    if top:
        for i, t in enumerate(top, 1):
            L.append(f"{i}. **{t.get('title', t) if isinstance(t, dict) else t}**" +
                     (f"  \n   {t['why']}" if isinstance(t, dict) and t.get("why") else "") +
                     (f"  \n   *Fix:* {t['fix']}" if isinstance(t, dict) and t.get("fix") else ""))
        L.append("")
    else:
        L.append("No critical problems were recorded.\n")
    L.append("## Was everything checked?\n")
    L.append("| Phase | Status | Coverage | Critical | Major |\n|---|---|---|---|---|")
    for p in phases:
        c = p.get("coverage") or {}
        cov = f"{c.get('checked')}/{c.get('total')} {c.get('unit', '')}" if c.get("total") is not None else ""
        fs = p.get("findings", [])
        L.append(f"| {p['title']} | {STATUS_WORD.get(p['status'], p['status'])} | {cov} | "
                 f"{sum(1 for f in fs if f.get('severity') == 'critical')} | {sum(1 for f in fs if f.get('severity') == 'major')} |")
    L.append("")
    cant = list(meta.get("missing") or []) + list(S.get("could_not_check") or [])
    for p in phases:
        if p.get("status_reason"):
            cant.append(f"{p['title']}: {p['status_reason']}")
    if cant:
        L.append("## What could not be checked\n")
        L += [f"- {x}" for x in dict.fromkeys(cant)]
        L.append("")
    todo = (read_json(os.path.join(rv, "sources", "to_download.json"), {}) or {}).get("papers") or []
    if todo:
        L.append("## Papers to download yourself\n")
        L.append("No legal full text was available for these, so claims citing them were checked against an abstract or not at all. "
                 "Put the PDFs in one folder and rerun the source step with `--local-pdfs`.\n")
        for x in todo:
            L.append(f"- **{x['key']}** ({'abstract only' if x['have'] == 'abstract' else 'no text'}, {len(x['claims'])} claim(s)): "
                     f"{md_escape(x.get('title'))} {x.get('link') or ''}")
        L.append("")
    comp = read_json(os.path.join(rv, "phases", "_comparison.json"))
    if comp:
        c = comp["counts"]
        L.append("## Before and after the fixes\n")
        L.append(f"Resolved: **{c['resolved']}**  |  Still open: **{c['still_open']}**  |  New: **{c['new']}**\n")
        for r in comp["issues"]:
            if r["status"] == "new":
                L.append(f"- NEW [{r['after']['severity']}]: {r['after']['title']}")
        L.append("")
    for p in phases:
        L.append(f"## {p['title']}\n")
        L.append(f"*Status:* {STATUS_WORD.get(p['status'], p['status'])}" +
                 (f"  |  *Coverage:* {p['coverage'].get('checked')}/{p['coverage'].get('total')} {p['coverage'].get('unit', '')}"
                  if (p.get("coverage") or {}).get("total") is not None else "") + "\n")
        if p.get("summary"):
            L.append(p["summary"] + "\n")
        if p["status"] == "skipped":
            L.append(f"Skipped: {p.get('status_reason') or 'not applicable'}.\n")
            continue
        fs = sorted(p.get("findings", []), key=lambda f: SEV.index(f.get("severity", "info")) if f.get("severity") in SEV else 9)
        if not fs and p["status"] == "complete":
            L.append("No problems found in this phase.\n")
        for f in fs:
            L.append(finding_block(f))
    # appendices
    ref = next(p for p in phases if p["phase"] == "01-references")
    if ref.get("items"):
        L.append("## Appendix A: every reference\n")
        L.append("| Key | Verdict | Problems | Note |\n|---|---|---|---|")
        for r in ref["items"]:
            L.append(f"| `{r.get('key')}` | {VWORD.get(r.get('verdict'), r.get('verdict'))} | "
                     f"{md_escape(', '.join((x.get('field') if isinstance(x, dict) else str(x)) for x in r.get('problems', [])))} | "
                     f"{md_escape(r.get('reason', ''))[:160]} |")
        L.append("")
    fc = next(p for p in phases if p["phase"] == "02-factcheck")
    if fc.get("items"):
        L.append("## Appendix B: every cited claim\n")
        L.append("| ID | Where | Cites | Verdict | Evidence |\n|---|---|---|---|---|")
        for it in fc["items"]:
            ev = next((e for e in it.get("evidence", []) if e.get("match") in ("exact", "close")), None)
            evs = (f"\"{md_escape(ev.get('context_match') or ev.get('quote'))[:140]}\" ({ev.get('found_in')}{', p. ' + str(ev['page']) if ev.get('page') else ''})"
                   if ev else "no verified quote")
            L.append(f"| {it.get('id')} | {it.get('file')}:{it.get('line')} | `{it.get('cite')}` | "
                     f"{VWORD.get(it.get('verdict'), it.get('verdict'))} | {evs} |")
        L.append("")
    pr = next(p for p in phases if p["phase"] == "09-peer-review")
    if pr.get("reviewers"):
        L.append("## Appendix C: expert reviewer reports\n")
        for r in pr["reviewers"]:
            L.append(f"### {r.get('name', 'Reviewer')} ({r.get('lens', '')})\n")
            if r.get("summary"):
                L.append(r["summary"] + "\n")
            if r.get("recommendation"):
                L.append(f"*Recommendation:* {r['recommendation']}\n")
            for c in r.get("concerns", []):
                L.append(f"- **{c.get('id', '')} {SEV_WORD.get(c.get('severity'), '')}{' (blocking)' if c.get('blocking') else ''}:** "
                         f"{c.get('title', '')}. {c.get('detail', '')}" + (f" *Would resolve it:* {c['resolution']}" if c.get("resolution") else ""))
            L.append("")
        if pr.get("synthesis"):
            L.append("### Synthesis\n\n" + pr["synthesis"] + "\n")
    md = "\n".join(L)
    mdp = os.path.join(rv, "REPORT.md")
    with open(mdp, "w", encoding="utf-8") as fh:
        fh.write(md)
    print("wrote", mdp)
    pdf = os.path.join(rv, "REPORT.pdf")
    if shutil.which("pandoc"):
        # findings quote raw LaTeX and dollar signs from the manuscript: treat them as plain text
        base = ["pandoc", mdp, "-f", "markdown-raw_tex-tex_math_dollars-raw_attribute", "-o", pdf, "--pdf-engine=xelatex", "-V", "geometry:margin=2.2cm", "-V", "fontsize=11pt",
                "-V", "colorlinks=true", "-V", "linestretch=1.25"]
        for extra in (["-V", "mainfont=Helvetica Neue", "-V", "monofont=Menlo"], []):
            r = subprocess.run(base + extra, capture_output=True, text=True)
            if r.returncode == 0:
                print("wrote", pdf)
                return
        print("PDF build failed:", r.stderr[-600:])
        html = os.path.join(rv, "REPORT.html")
        subprocess.run(["pandoc", mdp, "-f", "markdown-raw_tex-tex_math_dollars", "-s", "-o", html, "--metadata", "title=Paper review"], check=False)
        print("wrote", html, "(print it to PDF from a browser)")
    else:
        print("pandoc not found: REPORT.md written; convert it to PDF with any Markdown tool")


if __name__ == "__main__":
    main()
