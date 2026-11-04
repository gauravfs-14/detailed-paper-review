#!/usr/bin/env python3
"""Apply agent fixes to a COPY of the user's source files. The originals are never touched.

Input:  <review>/fixes.json  ->  {"fixes": [{"id": "REF-003", "file": "references.bib",
                                             "find": "exact old text", "replace": "new text",
                                             "reason": "DOI resolves to another paper"}]}
        paths in "file" are relative to the manuscript's folder.
Output: <review>/corrected-by-agent/
          marked/   every edit shown in color (blue = new text, red strike = removed text)
          clean/    the same edits with no color, ready to submit
          CHANGES.md and changes.json  one row per fix, with applied / skipped and why

Supported: .tex .bib (LaTeX color via xcolor), .md/.txt (HTML spans), .docx (run color).
A fix is applied only if "find" occurs exactly once in the file; otherwise it is skipped and
reported, so an ambiguous edit can never land in the wrong place.

Usage: python apply_fixes.py --review paper-review/main --source-dir paper/ [--compile]
"""
import argparse
import difflib
import re

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import now_iso, read_json, write_json  # noqa: E402

TEX_MACROS = (
    "\n% --- added by detailed-paper-review (marked copy only) ---\n"
    "\\usepackage{xcolor}\n"
    "\\providecommand{\\dprnew}[1]{{\\color[HTML]{1D4ED8}#1}}\n"
    "\\providecommand{\\dprdel}[1]{{\\color[HTML]{B42318}[removed: #1]}}\n"
)
IGNORE = shutil.ignore_patterns("paper-review", "corrected-by-agent", ".git", "*.aux", "*.log", "*.out",
                                "*.fdb_latexmk", "*.fls", "*.synctex.gz", "*.blg", "__pycache__")


def _wrap(ext, old, new):
    if ext in (".tex", ".bib"):
        if not new:
            return "{\\dprdel{" + old + "}}" if ext == ".bib" else "\\dprdel{" + old + "}"
        return "{\\dprnew{" + new + "}}" if ext == ".bib" else "\\dprnew{" + new + "}"
    if not new:
        return f'<del style="color:#B42318">{old}</del>'
    return f'<span style="color:#1D4ED8">{new}</span>'


def _unsafe(ext, text):
    if ext not in (".tex", ".bib"):
        return False
    t = re.sub(r"\\[%&#$_{}]", "", text)  # escaped specials are fine
    return any(x in t for x in ("=", "\\begin", "\\end", "%")) or t.count("{") != t.count("}")


def mark(ext, old, new):
    """Word-level diff: unchanged words stay plain, inserted words blue, removed words red.

    Returns None when a changed span would cut through LaTeX/BibTeX syntax; the caller then applies
    the edit uncolored and says so."""
    tok = lambda x: re.findall(r"\S+|\s+", x)  # noqa: E731
    a, b = tok(old), tok(new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append("".join(a[i1:i2]))
            continue
        gone, add = "".join(a[i1:i2]), "".join(b[j1:j2])
        lead = re.match(r"\s*", add or gone).group(0)
        g, d = gone.strip(), add.strip()
        if _unsafe(ext, g) or _unsafe(ext, d):
            return None
        piece = ""
        if g:
            piece += _wrap(ext, g, "")
        if d:
            piece += (" " if g else "") + _wrap(ext, "", d)
        trail = re.search(r"\s*$", add if add else gone).group(0)
        out.append(lead + piece + trail)
    return "".join(out)


def add_tex_macros(path):
    with open(path, encoding="utf-8") as fh:
        s = fh.read()
    if "\\dprnew" in s and "\\providecommand{\\dprnew}" not in s and "\\begin{document}" in s:
        s = s.replace("\\begin{document}", TEX_MACROS + "\\begin{document}", 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(s)


def docx_apply(path, find, replace, colored):
    import docx
    from docx.shared import RGBColor
    d = docx.Document(path)
    paras = list(d.paragraphs) + [p for t in d.tables for r in t.rows for c in r.cells for p in c.paragraphs]
    hits = [p for p in paras if find in p.text]
    if len(hits) != 1 or hits[0].text.count(find) != 1:
        return f"found {sum(p.text.count(find) for p in hits)} times"
    p = hits[0]
    full = p.text
    a = full.index(find)
    before, after = full[:a], full[a + len(find):]
    base = p.runs[0] if p.runs else None
    for r in p.runs[1:]:
        r._element.getparent().remove(r._element)
    if base is None:
        base = p.add_run("")
    base.text = before
    new_run = p.add_run(replace if replace else ("" if not colored else find))
    new_run.bold, new_run.italic = base.bold, base.italic
    if colored:
        if replace:
            new_run.font.color.rgb = RGBColor(0x1D, 0x4E, 0xD8)
        else:
            new_run.font.color.rgb = RGBColor(0xB4, 0x23, 0x18)
            new_run.font.strike = True
    tail = p.add_run(after)
    tail.bold, tail.italic = base.bold, base.italic
    d.save(path)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--review", required=True)
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--compile", action="store_true", help="latexmk both copies when the main file is .tex")
    a = ap.parse_args()
    fixes = read_json(os.path.join(a.review, "fixes.json"), {}).get("fixes", [])
    ms = read_json(os.path.join(a.review, "manuscript", "manuscript.json"))
    if ms and not ms.get("editable_source"):
        sys.exit("The manuscript was given as PDF only. Fixes need the source files (.tex/.docx/.md). Review only.")
    out = os.path.join(a.review, "corrected-by-agent")
    if os.path.exists(out):
        shutil.rmtree(out)
    for variant in ("marked", "clean"):
        shutil.copytree(a.source_dir, os.path.join(out, variant), ignore=IGNORE)
    log = []
    for fx in fixes:
        rel, find, rep = fx["file"], fx["find"], fx.get("replace", "")
        ext = os.path.splitext(rel)[1].lower()
        row = {**fx, "status": "applied", "note": ""}
        for variant in ("clean", "marked"):
            path = os.path.join(out, variant, rel)
            if not os.path.exists(path):
                row.update(status="skipped", note=f"file not found: {rel}")
                break
            if ext == ".docx":
                err = docx_apply(path, find, rep, colored=(variant == "marked"))
                if err:
                    row.update(status="skipped", note=f"'find' text {err}; must be exactly once in one paragraph")
                    break
                continue
            with open(path, encoding="utf-8") as fh:
                s = fh.read()
            n = s.count(find)
            if n != 1:
                row.update(status="skipped", note=f"'find' text occurs {n} times; must be exactly once")
                break
            new = rep if variant == "clean" else mark(ext, find, rep)
            if new is None:
                new = rep
                row["note"] = "applied without color in marked copy (edit spans LaTeX/BibTeX syntax)"
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(s.replace(find, new, 1))
        log.append(row)
    for root, _, files in os.walk(os.path.join(out, "marked")):
        for f in files:
            if f.endswith(".tex"):
                add_tex_macros(os.path.join(root, f))
    if any(r["status"] == "applied" and r["file"].endswith(".bib") for r in log):
        # the marked .bib uses \dprnew, which the main .tex of the marked copy defines
        main_tex = os.path.join(out, "marked", os.path.basename(ms["source"])) if ms else None
        if main_tex and os.path.exists(main_tex):
            with open(main_tex, encoding="utf-8") as fh:
                s = fh.read()
            if "\\providecommand{\\dprnew}" not in s and "\\begin{document}" in s:
                with open(main_tex, "w", encoding="utf-8") as fh:
                    fh.write(s.replace("\\begin{document}", TEX_MACROS + "\\begin{document}", 1))
    write_json(os.path.join(out, "changes.json"), {"generated": now_iso(), "changes": log})
    with open(os.path.join(out, "CHANGES.md"), "w", encoding="utf-8") as fh:
        fh.write("# Changes made by the review agent\n\n")
        fh.write("`marked/` shows every edit in color (blue = new, red = removed). `clean/` has the same edits without color.\n")
        fh.write("Your original files were not changed.\n\n| ID | File | Status | Reason | Old | New |\n|---|---|---|---|---|---|\n")
        for r in log:
            cell = lambda x: (x or "").replace("|", "\\|").replace("\n", " ")[:160]  # noqa: E731
            fh.write(f"| {r.get('id', '')} | {r['file']} | {r['status']}{(' (' + r['note'] + ')') if r['note'] else ''} | "
                     f"{cell(r.get('reason'))} | {cell(r['find'])} | {cell(r.get('replace'))} |\n")
    applied = sum(1 for r in log if r["status"] == "applied")
    print(f"{applied}/{len(log)} fixes applied -> {out}")
    for r in log:
        if r["status"] != "applied":
            print("SKIPPED:", r.get("id"), r["note"])
    if a.compile and ms and ms["format"] == "latex":
        for variant in ("clean", "marked"):
            d = os.path.join(out, variant)
            main_tex = os.path.relpath(ms["source"], os.path.abspath(a.source_dir))
            r = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", main_tex],
                               cwd=d, capture_output=True, text=True)
            print(f"compile {variant}: {'OK' if r.returncode == 0 else 'FAILED (see log in ' + d + ')'}")


if __name__ == "__main__":
    main()
