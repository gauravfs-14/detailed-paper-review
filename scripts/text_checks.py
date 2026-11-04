#!/usr/bin/env python3
"""Mechanical first passes for phases 3, 4, 5 and 7. Output is CANDIDATES for agents to confirm.

  acronyms     definitions, first use, use-before-definition, double definitions, never defined,
               defined-but-unused, long form repeated after definition       -> work/acronyms_auto.json
  crossrefs    every figure/table/box/equation/section label: mentions, first-mention order,
               never referenced, references to labels that do not exist       -> work/crossrefs_auto.json
  consistency  spelling (US/UK), hyphenation and spacing variants, self-reference variants,
               SD/Std style, one value printed at two precisions               -> work/consistency_auto.json
  numbers      every number in prose, captions and tables with its context   -> work/numbers.json

Usage: python text_checks.py <cmd> --review paper-review/main
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import now_iso, read_json, write_json  # noqa: E402

NOT_ACRONYMS = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "A", "OK", "USA", "UK", "US", "EU",
                "AND", "OR", "THE", "NOT", "TM", "AM", "PM", "DOI", "URL", "ID", "PDF", "ISBN", "ISSN", "HTTP", "HTTPS",
                "WWW", "LLC", "INC", "LTD", "ET", "AL", "VS", "NA", "NB", "QED"}
DEF_RE = re.compile(r"((?:[A-Za-z][\w'\-/]*\s+){0,9}[A-Za-z][\w'\-/]*)\s*\(\s*([A-Z][A-Za-z0-9&/\-]*[A-Z0-9]s?)\s*(?:[;,][^)]*)?\)")
ACR_TOKEN = re.compile(r"(?<![\w\-])([A-Z][A-Za-z0-9&\-]*[A-Z0-9](?:s)?)(?![\w])")


def initials_match(long_form, acr):
    acr_core = re.sub(r"s$", "", acr).replace("-", "").replace("&", "").replace("/", "").upper()
    words = [w for w in re.split(r"[\s\-/]+", long_form) if w]
    small = {"of", "and", "the", "for", "in", "on", "to", "a", "an", "with", "by", "at"}
    for start in range(len(words)):
        cand = words[start:]
        letters = "".join(w[0] for w in cand if w.lower() not in small).upper()
        letters_all = "".join(w[0] for w in cand).upper()
        if letters == acr_core or letters_all == acr_core:
            return " ".join(cand)
        # allow inner capitals: "TensorFlow" style or multi-letter from a word (e.g. "eXtreme")
        caps = "".join(c for w in cand for c in (w[0] + "".join(ch for ch in w[1:] if ch.isupper()))).upper()
        if caps == acr_core:
            return " ".join(cand)
    return None


def is_acronym(tok):
    core = tok[:-1] if tok.endswith("s") and tok[:-1].isupper() else tok
    caps = sum(1 for c in core if c.isupper())
    if core in NOT_ACRONYMS or len(core) < 2 or len(core) > 12:
        return False
    if re.fullmatch(r"[A-Z]\d+", core):  # A1, S2 labels
        return False
    if re.fullmatch(r"[IVXLC]+", core):
        return False
    return caps >= 2 and caps / len(core.replace("-", "")) >= 0.5


def acronyms(review):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    sents = ms["sentences"]
    sec_title = {s["id"]: s["title"] for s in ms["sections"]}
    abstract_ids = {s["id"] for s in ms["sections"] if s["title"].lower().startswith("abstract")}
    info = collections.OrderedDict()

    def rec(a):
        return info.setdefault(a, {"acronym": a, "definitions": [], "uses": [], "long_form": None})

    for s in sents:
        text = s["text"]
        for m in DEF_RE.finditer(text):
            acr = m.group(2)
            if not is_acronym(acr):
                continue
            lf = initials_match(m.group(1), acr)
            if lf:
                r = rec(re.sub(r"s$", "", acr) if acr.endswith("s") and acr[:-1].isupper() else acr)
                r["definitions"].append({"sentence": s["id"], "file": s["file"], "line": s["line"],
                                         "section": sec_title.get(s["section"]), "long_form": lf,
                                         "in_abstract": s["section"] in abstract_ids})
                r["long_form"] = r["long_form"] or lf
        for m in ACR_TOKEN.finditer(text):
            tok = m.group(1)
            if not is_acronym(tok):
                continue
            base = tok[:-1] if tok.endswith("s") and tok[:-1].isupper() else tok
            rec(base)["uses"].append({"sentence": s["id"], "file": s["file"], "line": s["line"],
                                      "section": sec_title.get(s["section"]), "in_abstract": s["section"] in abstract_ids,
                                      "in_display": s.get("in_display")})
    order = {s["id"]: i for i, s in enumerate(sents)}
    results = []
    for a, r in info.items():
        body_defs = [d for d in r["definitions"] if not d["in_abstract"]]
        body_uses = [u for u in r["uses"] if not u["in_abstract"]]
        issues = []
        if not r["definitions"]:
            if len(r["uses"]) >= 1:
                issues.append("never_defined")
        else:
            first_def = min(order[d["sentence"]] for d in (body_defs or r["definitions"]))
            before = [u for u in body_uses if order[u["sentence"]] < first_def]
            if before:
                issues.append("used_before_definition")
            if len(body_defs) > 1:
                issues.append("defined_more_than_once")
            uses_after = [u for u in body_uses if order[u["sentence"]] > first_def]
            def_sents = [d["sentence"] for d in (body_defs or r["definitions"]) if order[d["sentence"]] == first_def]
            # a later use in the same sentence as the definition counts too
            if sum(1 for u in r["uses"] if def_sents and u["sentence"] == def_sents[0]) >= 2:
                uses_after.append(r["uses"][0])
            if len(uses_after) == 0:
                issues.append("defined_but_never_used_again")
            if r["definitions"] and not body_defs and body_uses:
                issues.append("defined_only_in_abstract")
            lf = r["long_form"]
            if lf and len(lf.split()) >= 2:
                lf_re = re.compile(re.escape(lf), re.I)
                later = [s for s in sents if order[s["id"]] > first_def and lf_re.search(s["text"])
                         and not re.search(re.escape(lf) + r"\s*\(", s["text"], re.I)]
                if later:
                    issues.append("long_form_repeated_after_definition")
                    r["long_form_repeats"] = [{"sentence": s["id"], "line": s["line"], "file": s["file"]} for s in later[:10]]
        r["n_uses"] = len(r["uses"])
        r["first_use"] = r["uses"][0] if r["uses"] else None
        r["issues"] = issues
        r["uses"] = r["uses"][:40]
        results.append(r)
    results.sort(key=lambda x: (-len(x["issues"]), x["acronym"]))
    write_json(os.path.join(review, "work", "acronyms_auto.json"), {"generated": now_iso(), "acronyms": results})
    for r in results:
        if r["issues"]:
            print(f"{r['acronym']:<12} uses={r['n_uses']:<3} {','.join(r['issues'])}")
    print(f"{len(results)} acronym candidates; {sum(1 for r in results if r['issues'])} with possible issues "
          "(candidates only: model names like RoBERTa or units may be false positives)")


def crossrefs(review):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    displays = ms["displays"]
    mentions = ms["mentions"]
    labels = {d["label"]: d for d in displays}
    sec_labels = {s.get("label") for s in ms["sections"] if s.get("label")}
    by_type = collections.defaultdict(list)
    for d in displays:
        by_type[d["type"]].append(d)
    rows = []
    for t, ds in by_type.items():
        for num, d in enumerate(ds, 1):
            own = [m for m in mentions if m["label"] == d["label"]]
            # a mention inside the display's own caption does not count as a text citation
            def pos(x):  # LaTeX/Markdown give line numbers; PDF gives "p5" (page), DOCX paragraph numbers or "table3"
                if isinstance(x, int):
                    return x
                mm = re.match(r"p(\d+)$", str(x))
                return int(mm.group(1)) * 10000 if mm else 10 ** 9
            in_caption = lambda m: (m["context"] and d["caption"][:40] and d["caption"][:40] in m["context"])  # noqa: E731
            outside = [m for m in own if not (m["file"] == d["file"] and in_caption(m))]
            first = min((m["line"] for m in outside), key=pos, default=None)
            rows.append({"label": d["label"], "type": t, "number": num, "file": d["file"], "line": d["line"],
                         "caption": d["caption"][:200], "mentions": len(outside),
                         "first_mention_line": first, "mention_lines": [m["line"] for m in outside][:20],
                         "mentioned_after_display": bool(first is not None and isinstance(first, int) and isinstance(d["line"], int)
                                                         and first > d["line"] + 80)})
    issues = []
    for t in by_type:
        seq = sorted([r for r in rows if r["type"] == t and r["first_mention_line"] is not None],
                     key=lambda r: r["first_mention_line"] if isinstance(r["first_mention_line"], int)
                     else int(re.sub(r"\D", "", str(r["first_mention_line"])) or 0) * 10000)
        nums = [r["number"] for r in seq]
        if nums != sorted(nums):
            issues.append({"issue": "first_mention_out_of_order", "type": t, "order_of_first_mentions": nums})
    for r in rows:
        if r["mentions"] == 0 and not r["label"].startswith("__unlabeled_equation"):
            issues.append({"issue": "never_referenced", "label": r["label"], "type": r["type"], "line": r["line"]})
        if r["label"].startswith("__unlabeled") and r["type"] in ("figure", "table"):
            issues.append({"issue": "no_label_so_cannot_be_referenced", "type": r["type"], "line": r["line"]})
    known = set(labels) | sec_labels
    for m in mentions:
        if ms["format"] == "latex" and m["label"] not in known and not m["label"].startswith(("eq", "sec", "app")):
            issues.append({"issue": "reference_to_unknown_label", "label": m["label"], "line": m["line"], "file": m["file"]})
        elif ms["format"] == "latex" and m["label"] not in known:
            issues.append({"issue": "reference_to_unknown_label", "label": m["label"], "line": m["line"], "file": m["file"]})
    if ms["format"] != "latex":
        known_disp = {d["label"].lower() for d in displays}
        for m in mentions:
            if m["label"].lower() not in known_disp:
                issues.append({"issue": "mention_of_missing_display", "label": m["label"], "line": m["line"]})
    write_json(os.path.join(review, "work", "crossrefs_auto.json"), {"generated": now_iso(), "displays": rows, "issues": issues})
    for r in rows:
        print(f"{r['type']:<9} {r['number']:<3} {r['label']:<28} mentions={r['mentions']} first@{r['first_mention_line']}")
    for i in issues:
        print("ISSUE:", i)


US_UK = [("analyze", "analyse"), ("behavior", "behaviour"), ("color", "colour"), ("center", "centre"),
         ("modeling", "modelling"), ("labeled", "labelled"), ("labeling", "labelling"), ("organization", "organisation"),
         ("optimize", "optimise"), ("recognize", "recognise"), ("utilize", "utilise"), ("generalize", "generalise"),
         ("normalize", "normalise"), ("prioritize", "prioritise"), ("characterize", "characterise"), ("favor", "favour"),
         ("defense", "defence"), ("gray", "grey"), ("traveled", "travelled"), ("program", "programme"),
         ("emphasize", "emphasise"), ("summarize", "summarise"), ("minimize", "minimise"), ("maximize", "maximise")]
SELF_REF = ["this study", "this paper", "this work", "this article", "this research", "the present study", "this manuscript"]


def consistency(review):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    sents = ms["sentences"]
    full = "\n".join(s["text"] for s in sents)
    low = full.lower()
    out = {"generated": now_iso(), "spelling": [], "hyphenation": [], "self_reference": {}, "stat_abbrev": {},
           "precision": [], "percent_spacing": {}}
    for us, uk in US_UK:
        a = len(re.findall(r"\b" + us[:-1] + r"\w*", low)) if us.endswith("e") else len(re.findall(r"\b" + us + r"\w*", low))
        b = len(re.findall(r"\b" + uk[:-1] + r"\w*", low)) if uk.endswith("e") else len(re.findall(r"\b" + uk + r"\w*", low))
        if a and b and us[:4] != uk[:4] or (a and b and us != uk and re.search(r"\b" + re.escape(uk), low) and re.search(r"\b" + re.escape(us), low)):
            out["spelling"].append({"us": us, "uk": uk, "us_count": a, "uk_count": b})
    words = collections.Counter(re.findall(r"\b[a-z]+(?:-[a-z]+)+\b", low))
    for hw, n in words.items():
        parts = hw.split("-")
        joined, spaced = "".join(parts), " ".join(parts)
        nj = len(re.findall(r"\b" + joined + r"\b", low))
        ns = len(re.findall(r"\b" + re.escape(spaced) + r"\b", low))
        if nj or (ns and len(parts) == 2 and ns >= 1):
            out["hyphenation"].append({"hyphenated": hw, "n_hyphenated": n, "joined": joined, "n_joined": nj,
                                       "spaced": spaced, "n_spaced": ns,
                                       "note": "spaced form can be a correct noun phrase vs hyphenated modifier; check contexts"})
    for p in SELF_REF:
        c = low.count(p)
        if c:
            out["self_reference"][p] = c
    for pat, name in [(r"\bSD\b", "SD"), (r"\bs\.d\.", "s.d."), (r"\bStd\.?\b", "Std"), (r"\bSE\b", "SE"),
                      (r"\bSEM\b", "SEM"), (r"\bs\.e\.m\.", "s.e.m."), (r"\b95\s?% CI\b", "95% CI"), (r"\bCI\b", "CI")]:
        c = len(re.findall(pat, full))
        if c:
            out["stat_abbrev"][name] = c
    out["percent_spacing"] = {"no_space": len(re.findall(r"\d%", full)), "space": len(re.findall(r"\d\s%", full))}
    # same value printed at different precision (e.g. 0.8239 vs 0.824 vs 82.4%)
    nums = collections.defaultdict(list)
    for s in sents:
        for m in re.finditer(r"(?<![\w.])(\d+\.\d+)(%?)", s["text"]):
            nums[m.group(1)].append(s["id"])
    vals = list(nums)
    for v in vals:
        d = len(v.split(".")[1])
        if d < 3:
            continue
        x = float(v)
        for w in vals:
            dw = len(w.split(".")[1])
            if dw < d and abs(round(x, dw) - float(w)) < 1e-9 and float(w) != 0:
                out["precision"].append({"long": v, "short": w, "long_in": nums[v][:5], "short_in": nums[w][:5]})
    write_json(os.path.join(review, "work", "consistency_auto.json"), out)
    print(f"spelling variants: {len(out['spelling'])}, hyphenation variants: {len(out['hyphenation'])}, "
          f"self-reference forms: {out['self_reference']}, stat abbreviations: {out['stat_abbrev']}, "
          f"precision pairs: {len(out['precision'])}")


NUM_RE = re.compile(r"(?<![\w.])[-\u2212]?\d[\d,]*(?:\.\d+)?\s?%?")


def numbers(review):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    rows = []
    for s in ms["sentences"]:
        for m in NUM_RE.finditer(s["text"]):
            raw = m.group(0).strip()
            if re.fullmatch(r"(19|20)\d\d", raw):  # years
                continue
            a, b = max(0, m.start() - 70), min(len(s["text"]), m.end() + 70)
            rows.append({"value": raw, "sentence": s["id"], "file": s["file"], "line": s["line"],
                         "section": s.get("section_title"), "in_display": s.get("in_display"),
                         "context": s["text"][a:b]})
    # tables: pull raw tabular rows from LaTeX so numbers in tables are included
    tables = []
    src = ms["source"]
    if ms["format"] == "latex" and os.path.exists(src):
        text = open(src, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"\\begin\{(tabular\*?|tabularx|longtable)\}(.*?)\\end\{\1\}", text, re.S):
            line = text.count("\n", 0, m.start()) + 1
            body = re.sub(r"\\(?:toprule|midrule|bottomrule|hline|cline\{[^}]*\}|cmidrule(?:\([^)]*\))?\{[^}]*\})", "", m.group(2))
            cells = [[c.strip() for c in r.split("&")] for r in re.split(r"\\\\", body) if r.strip()]
            tables.append({"line": line, "rows": cells})
    write_json(os.path.join(review, "work", "numbers.json"), {"generated": now_iso(), "numbers": rows, "latex_tables": tables})
    print(f"{len(rows)} numbers in text/captions; {len(tables)} LaTeX tables extracted")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["acronyms", "crossrefs", "consistency", "numbers", "all"])
    ap.add_argument("--review", required=True)
    a = ap.parse_args()
    for c in (["acronyms", "crossrefs", "consistency", "numbers"] if a.cmd == "all" else [a.cmd]):
        print(f"--- {c}")
        globals()[c](a.review)


if __name__ == "__main__":
    main()
