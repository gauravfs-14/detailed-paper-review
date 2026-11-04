#!/usr/bin/env python3
"""Check, before a review starts, that this agent's environment can do the work.

Works the same under Claude Code, Codex or any other agent. Checks:
  - Python packages (PyMuPDF, python-docx) in the interpreter running this script
  - network access to the registries used for references and downloads
  - write access to the output folder
  - optional tools for the PDF report (pandoc, xelatex) and for compiling LaTeX fixes (latexmk/pdflatex)

Usage: $PY -I preflight.py [--out paper-review]
Exit code 0 when the review can run, 3 when something required is missing. The printed lines say what to fix.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import NETWORK_HELP, http_get  # noqa: E402

HOSTS = {
    "Crossref": "https://api.crossref.org/",
    "OpenAlex": "https://api.openalex.org/",
    "Semantic Scholar": "https://api.semanticscholar.org/graph/v1/paper/search?query=test&limit=1",
    "arXiv": "https://export.arxiv.org/api/query?search_query=all:test&max_results=1",
    "doi.org": "https://doi.org/",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="paper-review")
    a = ap.parse_args()
    res = {"python": sys.executable, "packages": {}, "network": {}, "write": None, "tools": {}}
    for mod in ("pymupdf", "docx"):
        try:
            __import__(mod)
            res["packages"][mod] = True
        except Exception:
            res["packages"][mod] = False
    for name, url in HOSTS.items():
        st, _ = http_get(url, accept="*/*", timeout=10, retries=1)
        res["network"][name] = st  # 0 = no connection; any HTTP status (even 4xx/429) means reachable
    try:
        os.makedirs(a.out, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=a.out):
            pass
        res["write"] = True
    except Exception as e:
        res["write"] = f"{type(e).__name__}: {e}"
    for t in ("pandoc", "xelatex", "latexmk", "pdflatex", "bibtex", "biber"):
        res["tools"][t] = bool(shutil.which(t))

    problems = []
    if not all(res["packages"].values()):
        problems.append("Python packages missing: run `eval \"$(bash <skill>/scripts/setup_env.sh)\"` (needs network "
                        "and write access to ~/.cache, or set DPR_VENV to a writable folder) and use that $PY.")
    if not any(res["network"].values()):
        problems.append(NETWORK_HELP)
    elif not all(res["network"].values()):
        down = [k for k, v in res["network"].items() if not v]
        problems.append("Some registries are unreachable: " + ", ".join(down) + ". Lookups there will be marked "
                        "lookup_failed (not checked), never 'not found'.")
    if res["write"] is not True:
        problems.append(f"Cannot write to {a.out}: {res['write']}")
    notes = []
    if not (res["tools"]["pandoc"] and res["tools"]["xelatex"]):
        notes.append("pandoc or xelatex missing: the dashboard works, but the PDF report will not be built.")
    if not (res["tools"]["latexmk"] or res["tools"]["pdflatex"]):
        notes.append("No LaTeX compiler: in fix mode the 'compiles' check cannot run and will be reported as not run.")

    print(json.dumps(res, indent=1))
    required_fail = (not all(res["packages"].values())) or (not any(res["network"].values())) or res["write"] is not True
    print("\nREADY" if not required_fail else "\nNOT READY")
    for p in problems:
        print("- " + p)
    for n in notes:
        print("- note: " + n)
    sys.exit(3 if required_fail else 0)


if __name__ == "__main__":
    main()
