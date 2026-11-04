#!/usr/bin/env python3
"""Compare two complete reviews of the same paper: before and after fixes (or two revision rounds).

  python compare_reviews.py --before $RV --after $RV/after

Each distinct issue (phases/_issues.json, made by `review_tool.py dedupe` in both reviews) is matched across
the two reviews by issue_key, else by title words and location. Result:
  resolved    in "before" and not in "after"
  still open  in both (with any change in severity)
  new         only in "after"  (a fix may have caused it: these must be explained)
Also compares phase coverage, so a phase that was skipped or incomplete in either review is visible.

Writes <after>/comparison.json and <after>/COMPARISON.md, and a copy of the JSON at <before>/phases/_comparison.json
for the dashboard.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import norm, now_iso, read_json, write_json  # noqa: E402
import review_tool  # noqa: E402


def issues(rv):
    data = read_json(os.path.join(rv, "phases", "_issues.json"))
    if not data:
        review_tool.dedupe(rv)
        data = read_json(os.path.join(rv, "phases", "_issues.json"))
    return data["issues"]


def words(t):
    return {w for w in norm(t).split() if len(w) > 3}


def same(a, b):
    if a.get("issue_key") and a.get("issue_key") == b.get("issue_key"):
        return True
    wa, wb = words(a["title"]), words(b["title"])
    sim = len(wa & wb) / max(1, min(len(wa), len(wb)))
    pa, pb = set(a["phases"]), set(b["phases"])
    return sim >= 0.55 and bool(pa & pb)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    a = ap.parse_args()
    before, after = issues(a.before), issues(a.after)
    used, rows = set(), []
    for b in before:
        match = next((x for k, x in enumerate(after) if k not in used and same(b, x)), None)
        if match:
            used.add(after.index(match))
            rows.append({"status": "still_open", "before": b, "after": match,
                         "severity_change": None if b["severity"] == match["severity"] else f"{b['severity']} -> {match['severity']}"})
        else:
            rows.append({"status": "resolved", "before": b, "after": None})
    for k, x in enumerate(after):
        if k not in used:
            rows.append({"status": "new", "before": None, "after": x})
    cov = []
    for pid, title in review_tool.PHASES:
        pb = read_json(os.path.join(a.before, "phases", pid + ".json")) or {}
        pa = read_json(os.path.join(a.after, "phases", pid + ".json")) or {}
        cov.append({"phase": pid, "title": title, "before": pb.get("status", "not_run"), "after": pa.get("status", "not_run")})
    n = {s: sum(1 for r in rows if r["status"] == s) for s in ("resolved", "still_open", "new")}
    out = {"generated": now_iso(), "counts": n, "issues": rows, "coverage": cov}
    write_json(os.path.join(a.after, "comparison.json"), out)
    write_json(os.path.join(a.before, "phases", "_comparison.json"), out)
    with open(os.path.join(a.after, "COMPARISON.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# Before and after\n\nResolved: **{n['resolved']}**  |  Still open: **{n['still_open']}**  |  New: **{n['new']}**\n\n")
        if n["new"]:
            fh.write("## New problems (appeared after the changes: explain or fix each)\n\n")
            for r in rows:
                if r["status"] == "new":
                    fh.write(f"- [{r['after']['severity']}] {r['after']['title']}\n")
            fh.write("\n")
        for st, title in (("still_open", "Still open"), ("resolved", "Resolved")):
            fh.write(f"## {title}\n\n")
            for r in rows:
                if r["status"] == st:
                    x = r["after"] or r["before"]
                    fh.write(f"- [{x['severity']}] {x['title']}" + (f" ({r['severity_change']})" if r.get("severity_change") else "") + "\n")
            fh.write("\n")
        bad = [c for c in cov if c["after"] not in ("complete", "skipped")]
        if bad:
            fh.write("## Phases not complete in the after-review\n\n" + "".join(f"- {c['title']}: {c['after']}\n" for c in bad))
    print(f"resolved {n['resolved']}, still open {n['still_open']}, new {n['new']} -> {os.path.join(a.after, 'COMPARISON.md')}")
    if n["new"]:
        print("NEW problems appeared after the changes: each must be explained or fixed before reporting.")


if __name__ == "__main__":
    main()
