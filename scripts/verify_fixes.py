#!/usr/bin/env python3
"""Check the corrected copies after apply_fixes.py, so a fix never introduces a new problem.

Stage 1 (mechanical, run right after apply_fixes.py):
  python verify_fixes.py --review $RV --source-dir <original source folder>

  1. only-intended-changes  clean copy == original + the applied fixes, nothing else changed
  2. marked-matches-clean   the marked copy with color markup removed is identical to the clean copy
  3. compiles               (LaTeX) original, clean and marked compile; no NEW errors, undefined
                            citations/references or BibTeX errors compared with the original
  4. structure              same citation keys, labels and references, bibliography still parses,
                            every cited key still has an entry
  5. references             every edited reference is looked up again in Crossref/OpenAlex and
                            must have no critical or major field difference left
  6. no-new-text-issues     acronym and cross-reference checks rerun on the clean copy: issues that
                            did not exist before are failures
  7. new-numbers            numbers that appear in replacement text but nowhere in the original
                            manuscript are flagged for a source check
  It also writes work/fixcheck/changed.json: every edited sentence (with its citations and source
  files) for the fix-verifier agent.

Stage 2 (after the fix-verifier agent wrote work/fixcheck/result.json):
  python verify_fixes.py --review $RV --source-dir <...> --finalize
  verifies the agent's quotes against the saved sources (same rule as the fact check) and merges its
  verdicts. A fix is "verified" only when every mechanical check and the agent check passed for it.

Output: corrected-by-agent/verify.json and VERIFY.md. Exit code 1 when anything failed.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import now_iso, parse_bibtex, read_json, write_json  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_EXT = (".tex", ".bib", ".md", ".txt", ".qmd", ".rmd")


def py():
    return sys.executable


def strip_braced_macro(s, name, keep):
    """Remove \\name{...} (balanced), keeping the content if keep=True."""
    out, i, tag = [], 0, "\\" + name + "{"
    while True:
        j = s.find(tag, i)
        if j < 0:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:j])
        k, depth = j + len(tag), 1
        while k < len(s) and depth:
            depth += {"{": 1, "}": -1}.get(s[k], 0)
            k += 1
        if keep:
            out.append(s[j + len(tag):k - 1])
        i = k


def unmark(path, text):
    """Remove the color markup apply_fixes.py adds, so the marked copy can be compared with the clean one."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tex", ".bib"):
        from apply_fixes import TEX_MACROS
        text = text.replace(TEX_MACROS, "")
        if ext == ".bib":
            text = text.replace("{\\dprdel{", "\\dprdel{")
            text = re.sub(r"(\\dprdel\{(?:[^{}]|\{[^{}]*\})*\})\}", r"\1", text)  # drop the outer brace
        text = strip_braced_macro(text, "dprdel", keep=False)
        out, i = [], 0
        while True:
            j = text.find("\\dprnew{", i)
            if j < 0:
                out.append(text[i:])
                return "".join(out)
            k, depth = j + 8, 1
            while k < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            content = text[j + 8:k - 1]
            if ext == ".bib" and text[j - 1:j] == "{" and text[k:k + 1] == "}":  # {\dprnew{x}} in .bib
                out.append(text[i:j - 1] + content)
                i = k + 1
            else:
                out.append(text[i:j] + content)
                i = k
    text = re.sub(r'<span style="color:#1D4ED8">(.*?)</span>', r"\1", text, flags=re.S)
    return re.sub(r'<del style="color:#B42318">.*?</del>', "", text, flags=re.S)


def latex_problems(folder, main_rel):
    r = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-f", main_rel], cwd=folder,
                       capture_output=True, text=True)
    stem = os.path.splitext(main_rel)[0]
    log = open(os.path.join(folder, stem + ".log"), encoding="latin-1").read() if os.path.exists(os.path.join(folder, stem + ".log")) else ""
    blg = open(os.path.join(folder, stem + ".blg"), encoding="latin-1").read() if os.path.exists(os.path.join(folder, stem + ".blg")) else ""
    probs = set()
    probs |= {"error: " + m.strip() for m in re.findall(r"^! (.+)$", log, re.M)}
    probs |= {"undefined citation " + m for m in re.findall(r"Citation `([^']+)' .*undefined", log)}
    probs |= {"undefined reference " + m for m in re.findall(r"Reference `([^']+)' .*undefined", log)}
    probs |= {"bibtex: " + m.strip() for m in re.findall(r"^(.*)---line \d+ of file", blg, re.M)}
    probs |= {"bibtex warning: " + m.strip() for m in re.findall(r"^Warning--(.+)$", blg, re.M)}
    pdf_ok = os.path.exists(os.path.join(folder, stem + ".pdf"))
    return probs, pdf_ok, r.returncode


def extract(src_main, out):
    subprocess.run([py(), "-I", os.path.join(HERE, "extract_manuscript.py"), src_main, "--out", out],
                   capture_output=True, text=True)
    subprocess.run([py(), "-I", os.path.join(HERE, "text_checks.py"), "acronyms", "--review", out], capture_output=True, text=True)
    subprocess.run([py(), "-I", os.path.join(HERE, "text_checks.py"), "crossrefs", "--review", out], capture_output=True, text=True)
    return read_json(os.path.join(out, "manuscript", "manuscript.json"))


def issue_set(review):
    acr = read_json(os.path.join(review, "work", "acronyms_auto.json"), {"acronyms": []})
    xr = read_json(os.path.join(review, "work", "crossrefs_auto.json"), {"issues": []})
    s = {f"acronym {a['acronym']}: {i}" for a in acr["acronyms"] for i in a["issues"]}
    s |= {f"crossref {i['issue']}: {i.get('label', i.get('type', ''))}" for i in xr["issues"]}
    return s


def numbers(text):
    text = re.sub(r"https?://\S+|10\.\d{4,9}/\S+|\\(?:cite|ref|label)\w*\{[^}]*\}", " ", text)  # ids are not data
    return set(re.findall(r"(?<![\w.])\d[\d,]*\.?\d*", text))


def mechanical(rv, src_dir):
    ca = os.path.join(rv, "corrected-by-agent")
    changes = read_json(os.path.join(ca, "changes.json"))
    if not changes:
        sys.exit("corrected-by-agent/changes.json not found: run apply_fixes.py first")
    ms = read_json(os.path.join(rv, "manuscript", "manuscript.json"))
    applied = [c for c in changes["changes"] if c["status"] == "applied"]
    main_rel = os.path.relpath(ms["source"], os.path.abspath(src_dir))
    checks, per_fix = [], {c["id"]: {"status": "pending", "notes": []} for c in applied}
    for c in changes["changes"]:
        if c["status"] != "applied":
            per_fix[c["id"]] = {"status": "not_applied", "notes": [c.get("note", "")]}

    def check(name, status, detail, fixes=None):
        checks.append({"name": name, "status": status, "detail": detail})
        for fid in fixes or []:
            if fid in per_fix:
                per_fix[fid]["notes"].append(f"{name}: {status}")
                if status == "fail":
                    per_fix[fid]["status"] = "failed"

    # 1. only intended changes
    bad = []
    for root, _, files in os.walk(os.path.join(ca, "clean")):
        for f in files:
            if not f.lower().endswith(TEXT_EXT):
                continue
            cp = os.path.join(root, f)
            rel = os.path.relpath(cp, os.path.join(ca, "clean"))
            op = os.path.join(src_dir, rel)
            if not os.path.exists(op):
                continue
            exp = open(op, encoding="utf-8", errors="replace").read()
            for c in applied:
                if c["file"] == rel:
                    exp = exp.replace(c["find"], c.get("replace", ""), 1)
            got = open(cp, encoding="utf-8", errors="replace").read()
            if exp != got:
                bad.append(rel)
    check("only-intended-changes", "fail" if bad else "pass",
          f"unexpected differences in: {', '.join(bad)}" if bad else "the clean copy differs from the original only by the listed fixes")

    # 2. marked == clean after removing markup
    bad = []
    for root, _, files in os.walk(os.path.join(ca, "marked")):
        for f in files:
            if not f.lower().endswith(TEXT_EXT):
                continue
            mp = os.path.join(root, f)
            rel = os.path.relpath(mp, os.path.join(ca, "marked"))
            cp = os.path.join(ca, "clean", rel)
            if os.path.exists(cp):
                # LaTeX treats runs of spaces as one, and a removed word leaves two
                a = re.sub(r"[ \t]+", " ", unmark(rel, open(mp, encoding="utf-8").read()))
                b = re.sub(r"[ \t]+", " ", open(cp, encoding="utf-8").read())
                if a != b:
                    bad.append(rel)
    check("marked-matches-clean", "fail" if bad else "pass",
          f"marked copy has different content from clean in: {', '.join(bad)}" if bad else "marked copy shows exactly the clean copy's text, only with color")

    # 3. compile (LaTeX)
    if ms["format"] == "latex" and shutil.which("latexmk"):
        base = os.path.join(ca, "_check", "original")
        if os.path.exists(base):
            shutil.rmtree(base)
        shutil.copytree(src_dir, base, ignore=shutil.ignore_patterns("*.aux", "*.log", "*.bbl", "*.blg", "*.fls",
                                                                    "*.fdb_latexmk", "*.out", "paper-review", "corrected-by-agent"))
        p0, _, _ = latex_problems(base, main_rel)
        for variant in ("clean", "marked"):
            p, ok, _ = latex_problems(os.path.join(ca, variant), main_rel)
            new = sorted(p - p0)
            hard = [x for x in new if not x.startswith("bibtex warning")]
            soft = [x for x in new if x.startswith("bibtex warning")]
            status = "fail" if (hard or not ok) else "warn" if soft else "pass"
            detail = ("PDF not produced. " if not ok else "")
            detail += (f"new problems vs original: {'; '.join(hard[:12])}. " if hard else "compiles with no new errors or undefined citations/references. ")
            if soft:
                detail += f"New BibTeX warnings (check they are expected, e.g. conference papers without pages): {'; '.join(soft[:8])}"
            check(f"compiles-{variant}", status, detail.strip(), [c["id"] for c in applied] if status == "fail" else None)
    else:
        check("compiles", "skipped", "not a LaTeX manuscript or latexmk not available")

    # LaTeX syntax inside replacement text: an unescaped % silently comments out the rest of the line
    for c in applied:
        if c["file"].endswith(".tex"):
            rep = re.sub(r"\\[%&#$_{}]", "", c.get("replace", ""))
            rep = re.sub(r"\$[^$]*\$", "", rep)  # inline math may use _ and &
            bad_chars = sorted(set(ch for ch in "%&#_" if ch in rep))
            if bad_chars or rep.count("{") != rep.count("}"):
                check(f"latex-syntax-{c['id']}", "fail",
                      f"replacement has unescaped LaTeX special characters {bad_chars} or unbalanced braces; "
                      "write \\% \\& \\# \\_ (an unescaped % comments out the rest of the line)", [c["id"]])

    # 4. structure and 6. text issues on the clean copy
    clean_main = os.path.join(ca, "clean", main_rel)
    crv = os.path.join(ca, "_check", "review")
    if os.path.exists(crv):
        shutil.rmtree(crv)
    ms2 = extract(clean_main, crv)
    k1 = {k for s in ms["sentences"] for k in s["cites"]}
    k2 = {k for s in ms2["sentences"] for k in s["cites"]}
    r1, r2 = {r["ID"] for r in ms["references"]}, {r["ID"] for r in ms2["references"]}
    l1, l2 = {d["label"] for d in ms["displays"]}, {d["label"] for d in ms2["displays"]}
    probs = []
    if k1 != k2:
        probs.append(f"citation keys changed: removed {sorted(k1 - k2)}, added {sorted(k2 - k1)}")
    if r1 != r2:
        probs.append(f"reference list changed: removed {sorted(r1 - r2)}, added {sorted(r2 - r1)}")
    if l1 != l2:
        probs.append(f"display labels changed: {sorted(l1 ^ l2)}")
    from collections import Counter
    n1 = Counter(k for s in ms["sentences"] for k in s["cites"])
    n2 = Counter(k for s in ms2["sentences"] for k in s["cites"])
    lost = {k: (n1[k], n2[k]) for k in n1 if n2[k] < n1[k]}
    if lost:
        probs.append("citations disappeared (before, after): " + ", ".join(f"{k} {a}->{b}" for k, (a, b) in lost.items()))
    w1 = sum(len(s["text"].split()) for s in ms["sentences"])
    w2 = sum(len(s["text"].split()) for s in ms2["sentences"])
    expected_dw = sum(len(c.get("replace", "").split()) - len(c["find"].split()) for c in applied if not c["file"].endswith(".bib"))
    if abs((w2 - w1) - expected_dw) > max(10, 0.02 * w1):
        probs.append(f"text length changed by {w2 - w1} words but the fixes account for {expected_dw}: text may have been lost")
    missing = sorted(k2 - r2 - {k for k in k2 if k.startswith("AY:")})
    if missing:
        probs.append(f"cited but no entry: {missing}")
    for r in ms2["references"]:
        if r.get("ENTRYTYPE") in ("article", "inproceedings", "misc", "book", "techreport") and not r.get("title"):
            probs.append(f"entry {r['ID']} has no title after the fix (BibTeX syntax broken?)")
    check("structure", "fail" if probs else "pass", "; ".join(probs) if probs else
          f"{len(k2)} citation keys ({sum(n2.values())} citations), {len(r2)} references and {len(l2)} labels unchanged; "
          f"text length consistent with the fixes; bibliography parses")

    tmp_orig = os.path.join(ca, "_check", "review_original")
    if os.path.exists(tmp_orig):
        shutil.rmtree(tmp_orig)
    extract(ms["source"], tmp_orig)
    before, after = issue_set(tmp_orig), issue_set(crv)
    new, gone = sorted(after - before), sorted(before - after)
    check("no-new-text-issues", "fail" if new else "pass",
          (f"new: {'; '.join(new)}" if new else "no new acronym or cross-reference issues") +
          (f"; resolved: {'; '.join(gone)}" if gone else ""))

    # 5. edited references re-verified
    bib_fixes = [c for c in applied if c["file"].endswith(".bib")]
    if bib_fixes:
        import verify_refs
        by_id = {r["ID"]: r for r in ms2["references"]}
        for c in bib_fixes:
            keys = re.findall(r"@\w+\{([^,\s]+),", c.get("replace", "") + c["find"])
            if not keys:  # field-level edit: find the entry that contains the replacement text
                for root, _, files in os.walk(os.path.join(ca, "clean")):
                    for f in files:
                        if f == os.path.basename(c["file"]):
                            txt = open(os.path.join(root, f), encoding="utf-8").read()
                            pos = txt.find(c.get("replace", ""))
                            m = list(re.finditer(r"@\w+\{([^,\s]+),", txt[:pos]))
                            if m:
                                keys = [m[-1].group(1)]
            for key in dict.fromkeys(keys):
                if key not in by_id:
                    check(f"reference-{key}", "fail", "entry not found after the fix", [c["id"]])
                    continue
                res = verify_refs.check_one(by_id[key], crv)
                serious = [i for i in res["issues"] if i["severity"] in ("critical", "major")]
                # registries often hold only the arXiv record of a conference paper: a year/venue difference
                # against that record is expected when the fix moved the entry to the proceedings version
                arxiv_only = res["records"] and all("arxiv" in str(r.get("journal") or "").lower() or r.get("type") in ("posted-content", "preprint")
                                                    for r in res["records"])
                soft = [i for i in serious if arxiv_only and i["field"] in ("year", "venue")]
                hard = [i for i in serious if i not in soft]
                status = "fail" if hard else "warn" if soft else "pass"
                detail = "; ".join(f"{i['field']}: {i['note']}" for i in hard) if hard else \
                    (f"title and authors match; the registry holds only the arXiv record, so the proceedings venue/year must be "
                     f"confirmed from the source given in the fix ({c.get('reason', '')})" if soft else
                     f"matches the registry record ({', '.join(r.get('source', '') for r in res['records']) or 'no record; checked by hand'})")
                check(f"reference-{key}", status, detail, [c["id"]] if hard else None)
                if soft:
                    per_fix[c["id"]]["notes"].append(f"{key}: venue/year needs the agent to confirm on the proceedings page")
                if not serious:
                    per_fix[c["id"]]["notes"].append(f"{key} re-verified against registry")

    # 7. new numbers
    orig_nums = numbers("\n".join(s["text"] for s in ms["sentences"]))
    for c in [c for c in applied if not c["file"].endswith(".bib")]:  # .bib edits are checked against registries
        nn = sorted(numbers(c.get("replace", "")) - numbers(c["find"]) - orig_nums - numbers(c.get("reason", "")))
        if nn:
            check(f"new-numbers-{c['id']}", "warn", f"numbers not found anywhere in the original: {nn}; confirm their source", [c["id"]])

    # changed sentences for the fix-verifier agent
    old = {s["text"] for s in ms["sentences"]}
    changed = [s for s in ms2["sentences"] if s["text"] not in old]
    fx_for = lambda s: [c["id"] for c in applied if c["file"].endswith((".tex", ".md", ".docx")) and  # noqa: E731
                        any(w in s["raw"] for w in [c.get("replace", "")[:40]] if w)]
    items = []
    for s in changed:
        items.append({"sentence_id": s["id"], "file": s["file"], "line": s["line"], "text": s["text"], "cites": s["cites"],
                      "fix_ids": fx_for(s),
                      "sources": [{"key": k, "text_file": f"sources/text/{re.sub(r'[^A-Za-z0-9_.-]', '_', k)}.txt"} for k in s["cites"]]})
    write_json(os.path.join(rv, "work", "fixcheck", "changed.json"), {"generated": now_iso(), "sentences": items,
                                                                      "fixes": applied})
    return checks, per_fix, items


def finalize(rv, data):
    import review_tool
    res = read_json(os.path.join(rv, "work", "fixcheck", "result.json"))
    if not res:
        data["agent_check"] = {"status": "missing", "detail": "fix-verifier result not found"}
        return data
    bad = 0
    for it in res.get("items", []):
        for ev in it.get("evidence", []):
            review_tool.verify_evidence(rv, ev)
        if it.get("verdict") in ("supported", "ok") and it.get("evidence") and not any(e["match"] in ("exact", "close") for e in it["evidence"]):
            it["verdict"] = "cannot_verify"
            it["quote_check_failed"] = True
        ok = it.get("verdict") in ("supported", "ok")
        for fid in it.get("fix_ids", []):
            pf = data["per_fix"].setdefault(fid, {"status": "pending", "notes": []})
            pf["notes"].append(f"agent: {it.get('verdict')} - {it.get('note', '')}")
            if not ok:
                pf["status"] = "failed"
                bad += 1
    # every mechanical warning must be reviewed and accepted by the agent
    reviewed = {w.get("check"): w for w in res.get("warnings_reviewed", [])}
    for c in data["checks"]:
        if c["status"] == "warn":
            w = reviewed.get(c["name"])
            if not w:
                c["status"], c["detail"] = "fail", c["detail"] + " | not reviewed by the fix verifier"
                bad += 1
            elif not w.get("acceptable"):
                c["status"], c["detail"] = "fail", c["detail"] + f" | verifier: {w.get('note', '')}"
                bad += 1
            else:
                c["status"], c["detail"] = "pass", c["detail"] + f" | accepted by verifier: {w.get('note', '')}" + \
                    (f" ({w['url']})" if w.get("url") else "")
    expected = len(read_json(os.path.join(rv, "work", "fixcheck", "changed.json"), {"sentences": []})["sentences"])
    got = len({it.get("sentence_id") for it in res.get("items", [])})
    if got < expected:
        bad += 1
    data["agent_check"] = {"status": "fail" if bad else "pass", "items": res.get("items", []),
                           "marked_pdf": res.get("marked_pdf"),
                           "detail": f"{got} of {expected} edited sentences re-checked; {bad} problem(s)"}
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--review", required=True)
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--finalize", action="store_true")
    a = ap.parse_args()
    rv = a.review
    path = os.path.join(rv, "corrected-by-agent", "verify.json")
    if a.finalize:
        data = read_json(path)
        if not data:
            sys.exit("run verify_fixes.py without --finalize first")
        data = finalize(rv, data)
    else:
        checks, per_fix, items = mechanical(rv, a.source_dir)
        data = {"generated": now_iso(), "checks": checks, "per_fix": per_fix,
                "agent_check": {"status": "pending", "detail": f"{len(items)} edited sentences waiting for the fix-verifier agent"}}
    mech_fail = any(c["status"] == "fail" for c in data["checks"])
    for fid, pf in data["per_fix"].items():
        if pf["status"] in ("failed", "not_applied"):
            continue
        pf["status"] = "verified" if (not mech_fail and data["agent_check"]["status"] == "pass") else \
            ("needs_agent_check" if data["agent_check"]["status"] in ("pending", "missing") else "verified_mechanical")
    data["overall"] = ("fail" if mech_fail or data["agent_check"]["status"] == "fail" else
                       "pass" if data["agent_check"]["status"] == "pass" else "incomplete")
    write_json(path, data)
    with open(os.path.join(rv, "corrected-by-agent", "VERIFY.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# Post-fix verification: {data['overall'].upper()}\n\n| Check | Result | Detail |\n|---|---|---|\n")
        for c in data["checks"]:
            fh.write(f"| {c['name']} | {c['status']} | {c['detail'].replace('|', '/')} |\n")
        fh.write(f"| agent re-check of edited sentences | {data['agent_check']['status']} | {data['agent_check']['detail']} |\n\n")
        fh.write("| Fix | Status | Notes |\n|---|---|---|\n")
        for fid, pf in data["per_fix"].items():
            fh.write(f"| {fid} | {pf['status']} | {'; '.join(pf['notes']).replace('|', '/')[:300]} |\n")
    for c in data["checks"]:
        print(f"[{c['status'].upper():<7}] {c['name']}: {c['detail'][:160]}")
    print(f"[{data['agent_check']['status'].upper():<7}] agent re-check: {data['agent_check']['detail']}")
    print("overall:", data["overall"])
    sys.exit(1 if data["overall"] == "fail" else 0)


if __name__ == "__main__":
    main()
