#!/usr/bin/env python3
"""Build the review dashboard from the phase JSON files. Run after every phase, and at the end.

  python build_dashboard.py --review paper-review/main [--open]

What it does (so agents never hand-write HTML):
  1. re-verifies every fact-check evidence quote against the saved source text (review_tool)
  2. recomputes real coverage and overrides any "complete" status the files cannot prove
  3. renders the PDF pages that hold evidence to PNG and attaches highlight boxes
  4. copies figure images so the figure phase can show them
  5. writes <review>/dashboard/index.html + data.js (works from file://, no server needed)
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import now_iso, read_json, write_json  # noqa: E402
import review_tool  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "dashboard", "index.html")


def render_page(pdf, page, dest, zoom=1.7):
    if os.path.exists(dest):
        return True
    import pymupdf
    with pymupdf.open(pdf) as doc:
        if not (1 <= page <= len(doc)):
            return False
        pix = doc[page - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        pix.save(dest)
    return True


# evidence of kind "computation" must show the command that produced it (any shell or Python command)
CMD_RE = re.compile(r"\.py\b|\bpython|\$PY|\bgrep\b|\bwc\b|\bawk\b|\bsed\b|\bpdfinfo\b|\blatexmk\b|\bpymupdf\b|^\s*\$ |\[cwd", re.M | re.I)

# minimum number of units a phase must cover, taken from the script that listed them
MIN_UNITS = {
    "02b-uncited-claims": ("uncited_auto.json", lambda d: d.get("total_uncited_sentences", 0), "sentences without a citation"),
    "02d-text-overlap": ("overlap_auto.json", lambda d: len(d.get("sentences", [])), "sentences with verbatim overlap"),
    "03b-claim-map": ("claimmap_auto.json", lambda d: len(d.get("claims", [])), "headline claims"),
    "04c-equations": ("equations.json", lambda d: len(d.get("equations", [])), "equations"),
    "R-revision": ("revision/auto.json", lambda d: len(d.get("items", [])), "reviewer comments"),
}


def enforce_status(ph, ms, manifest, rv=None):
    """Never show a phase as complete unless the data proves it."""
    pid = ph.get("phase")
    cov = ph.setdefault("coverage", {})
    reasons = [ph["status_reason"]] if ph.get("status_reason") else []
    if rv and pid in MIN_UNITS:
        fname, count, unit = MIN_UNITS[pid]
        src = read_json(os.path.join(rv, "work", fname))
        if src is not None:
            need = count(src)
            if (cov.get("total") or 0) < need:
                reasons.append(f"the scripts listed {need} {unit}, but the phase covers only {cov.get('total') or 0}")
    # every recomputed number must say which code produced it
    nocmd = [i for i in ph.get("items", []) if isinstance(i, dict) and ("recomputed" in i or "match" in i)
             and i.get("match") not in ("n/a", None) and not (i.get("command") or "").strip()]
    if nocmd:
        reasons.append(f"{len(nocmd)} recomputed value(s) have no recorded command, so they do not count as checked by code")
    nocode = [f.get("id") for f in ph.get("findings", []) for e in (f.get("evidence") or [])
              if e.get("kind") == "computation" and not CMD_RE.search(e.get("text", "") + " " + e.get("command", ""))]
    if nocode:
        reasons.append(f"computation evidence without the command that produced it: {', '.join(dict.fromkeys(nocode))}")
    if pid == "01-references" and ms:
        have = {i.get("key") for i in ph.get("items", []) if i.get("verdict")}
        miss = [r["ID"] for r in ms["references"] if r["ID"] not in have]
        cov.update(unit="references", total=len(ms["references"]), checked=len(ms["references"]) - len(miss))
        if miss:
            reasons.append(f"no verdict yet for {len(miss)} reference(s): {', '.join(miss[:12])}")
        cov["unverifiable"] = sum(1 for i in ph.get("items", []) if i.get("verdict") == "unverifiable")
        if manifest:
            cov["sources"] = manifest.get("counts")
    if cov.get("total") is not None and cov.get("checked", 0) < cov["total"]:
        if not any("checked" in r for r in reasons):
            reasons.append(f"only {cov.get('checked', 0)} of {cov['total']} {cov.get('unit', 'items')} checked")
    if reasons and ph.get("status") == "complete":
        ph["status_claimed"] = "complete"
    if reasons and ph.get("status") != "skipped":
        ph["status"] = "incomplete"
    ph["status_reason"] = "; ".join(dict.fromkeys(r for r in reasons if r))
    return ph


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    rv = os.path.abspath(a.review)
    ms = read_json(os.path.join(rv, "manuscript", "manuscript.json"))
    if ms and not ms.get("title") and os.path.exists(ms.get("source", "")):
        try:
            from extract_manuscript import guess_title
            ms["title"] = guess_title(ms["source"], ms.get("format"))
        except Exception:
            pass
    manifest = read_json(os.path.join(rv, "sources", "manifest.json"))
    dash = os.path.join(rv, "dashboard")
    os.makedirs(os.path.join(dash, "pages"), exist_ok=True)
    os.makedirs(os.path.join(dash, "figs"), exist_ok=True)

    fc_path = os.path.join(rv, "phases", "02-factcheck.json")
    if os.path.exists(fc_path):
        review_tool.verify_quotes(rv)

    # keep the merged issue list and the download list in step with the phase files
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        review_tool.dedupe(rv)
        import fetch_sources
        fetch_sources.write_download_list(rv)

    phases = []
    for pid, title in review_tool.PHASES:
        ph = read_json(os.path.join(rv, "phases", pid + ".json"))
        if not ph and pid == "R-revision" and (read_json(os.path.join(rv, "review.json"), {}) or {}).get("submission") != "revision":
            phases.append({"phase": pid, "title": title, "status": "skipped", "findings": [], "items": [],
                           "summary": "Not a revision: there is no response letter or tracked version to check.",
                           "status_reason": "first submission", "coverage": {}})
            continue
        if not ph:
            phases.append({"phase": pid, "title": title, "status": "not_run", "findings": [], "items": [],
                           "summary": "This phase has not been run yet.", "coverage": {}})
            continue
        ph.setdefault("title", title)
        ph.setdefault("findings", [])
        phases.append(enforce_status(ph, ms, manifest, rv))

    # evidence pages + manuscript context for every claim
    sent_index = {s["id"]: i for i, s in enumerate(ms["sentences"])} if ms else {}
    for ph in phases:
        if ph["phase"] != "02-factcheck":
            continue
        for it in ph.get("items", []):
            i = sent_index.get(it.get("sentence_id"))
            if i is not None:
                ss = ms["sentences"]
                it["context_prev"] = " ".join(s["text"] for s in ss[max(0, i - 2):i] if s["section"] == ss[i]["section"])
                it["context_next"] = " ".join(s["text"] for s in ss[i + 1:i + 3] if s["section"] == ss[i]["section"])
                it.setdefault("sentence", ss[i]["text"])
                it.setdefault("file", ss[i]["file"])
                it.setdefault("line", ss[i]["line"])
            for ev in it.get("evidence", []):
                if ev.get("pdf") and ev.get("page") and ev.get("highlight"):
                    name = re.sub(r"[^A-Za-z0-9_.-]", "_", ev["source_key"]) + f"-p{ev['page']}.png"
                    if render_page(os.path.join(rv, ev["pdf"]), ev["page"], os.path.join(dash, "pages", name)):
                        ev["page_image"] = "pages/" + name
                if ev.get("pdf"):
                    ev["pdf_link"] = "../" + ev["pdf"] + (f"#page={ev['page']}" if ev.get("page") else "")

    # figure images
    figs = []
    if ms:
        root = os.path.dirname(ms["source"])
        for d in ms["displays"]:
            for g in d.get("graphics", []):
                for ext in ("", ".png", ".pdf", ".jpg", ".jpeg"):
                    p = os.path.join(root, g + ext)
                    if os.path.isfile(p):
                        out = os.path.join(dash, "figs", re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(p)))
                        if p.lower().endswith(".pdf"):
                            out = out[:-4] + ".png"
                            render_page(p, 1, out, zoom=2.0)
                        else:
                            shutil.copyfile(p, out)
                        figs.append({"label": d["label"], "src": "figs/" + os.path.basename(out)})
                        break

    refs_meta = {}
    if manifest:
        for r in manifest["rows"]:
            refs_meta[r["key"]] = {"kind": r["kind"], "pdf": ("../" + r["fulltext_pdf"]) if r.get("fulltext_pdf") else None,
                                   "abstract": ("../" + r["abstract_file"]) if r.get("abstract_file") else None,
                                   "origin": r.get("origin"), "doi": r.get("doi"), "log": r.get("log", [])}
    auto = read_json(os.path.join(rv, "refcheck", "auto_refs.json"), {"results": []})
    summary = read_json(os.path.join(rv, "phases", "00-summary.json"), {})
    changes = read_json(os.path.join(rv, "corrected-by-agent", "changes.json"))
    data = {
        "generated": now_iso(),
        "paper": {"title": summary.get("paper_title") or (ms.get("title") if ms else "") or (os.path.basename(ms["source"]) if ms else "Manuscript"),
                  "source": ms["source"] if ms else None, "format": ms["format"] if ms else None,
                  "editable_source": ms.get("editable_source") if ms else None, "counts": ms["counts"] if ms else {}},
        "summary": summary,
        "phases": phases,
        "sources": refs_meta,
        "auto_refs": {r["key"]: {"records": r.get("records", []), "lookup_log": r.get("lookup_log", []),
                                 "issues": r.get("issues", []), "cited": r.get("cited")} for r in auto["results"]},
        "figures": figs,
        "changes": (changes or {}).get("changes"),
        "verify": read_json(os.path.join(rv, "corrected-by-agent", "verify.json")),
        "issues": (read_json(os.path.join(rv, "phases", "_issues.json")) or {}).get("issues"),
        "to_download": (read_json(os.path.join(rv, "sources", "to_download.json")) or {}).get("papers"),
        "comparison": read_json(os.path.join(rv, "phases", "_comparison.json")),
        "meta": read_json(os.path.join(rv, "review.json")),
        "report_pdf": "../REPORT.pdf" if os.path.exists(os.path.join(rv, "REPORT.pdf")) else None,
    }
    with open(os.path.join(dash, "data.js"), "w", encoding="utf-8") as fh:
        import json
        fh.write("window.REVIEW = ")
        json.dump(data, fh, ensure_ascii=False)
        fh.write(";\n")
    write_json(os.path.join(dash, "data.json"), data)  # the same verified data, for apps that show it themselves
    shutil.copyfile(TEMPLATE, os.path.join(dash, "index.html"))
    vend = os.path.join(os.path.dirname(TEMPLATE), "vendor")  # fonts and icons, so it works offline
    if os.path.isdir(vend):
        shutil.copytree(vend, os.path.join(dash, "vendor"), dirs_exist_ok=True)
    write_json(os.path.join(rv, "phases", "_status.json"),
               {p["phase"]: {"status": p["status"], "reason": p.get("status_reason", ""), "coverage": p.get("coverage")} for p in phases})
    incomplete = [p for p in phases if p["status"] not in ("complete", "skipped")]
    print(f"dashboard: {os.path.join(dash, 'index.html')}")
    for p in phases:
        print(f"  {p['status']:<11} {p['phase']:<22} {p.get('status_reason', '')}")
    if incomplete:
        print(f"{len(incomplete)} phase(s) are not complete. Do not report the review as finished.")
    try:  # keep Zotero in step with the review (new references, PDFs added later); never prompts
        import zotero_lib
        print(zotero_lib.sync(rv, quiet=True))
    except Exception as e:
        print(f"Zotero: sync skipped ({e})")
    if a.open:
        subprocess.run(["open", os.path.join(dash, "index.html")], check=False)


if __name__ == "__main__":
    main()
