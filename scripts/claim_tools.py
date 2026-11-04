#!/usr/bin/env python3
"""Mechanical first passes for phases 2b, 2d, 3b and 4c. Output is CANDIDATES for agents to decide.

  uncited    every sentence with no citation, classified: refers-to-own-work, factual-claim candidate
             (numbers, comparisons, generalisations, "studies show"), or other  -> work/uncited_auto.json
  claims     headline claims to map to evidence: abstract, contributions, discussion and conclusion
             sentences, plus strong-claim words anywhere                         -> work/claimmap_auto.json
  overlap    manuscript sentences that share long verbatim word runs with a saved source text
             (possible copying without quotation marks)                          -> work/overlap_auto.json
  equations  every display equation and inline formula with "=", with label, line and context
                                                                                 -> work/equations.json
Usage: python claim_tools.py <cmd|all> --review paper-review/main
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import norm, now_iso, read_json, write_json  # noqa: E402

OWN = re.compile(r"\b(we|our|us|this (study|paper|work|article|analysis|research)|the present study|table|fig(ure)?s?|"
                 r"section|appendix|eq(uation)?|the proposed|the model|the classifier)\b|<[^>]+>", re.I)
FACT_CUES = re.compile(
    r"\d|\bper ?cent\b|\b(most|majority|minority|more|less|fewer|higher|lower|greater|increase[sd]?|decrease[sd]?|"
    r"rise|rose|decline[sd]?|double[sd]?|leading|largest|smallest|primary|main|major|common(ly)?|often|usually|"
    r"typically|frequently|rarely|widely|generally|known|well[- ]established|shown|demonstrated|evidence|studies|"
    r"research|literature|prior work|previous work|reported|found|according)\b", re.I)
STRONG = re.compile(r"\b(first|novel|new|outperform\w*|superior|best|state[- ]of[- ]the[- ]art|significant\w*|"
                    r"demonstrat\w*|prove\w*|establish\w*|show(s|ed|n)?|substantial\w*|robust\w*|generaliz\w*|"
                    r"always|never|all|only|clearly|strongly|consistently|calibrated|reliable|accurate\w*)\b", re.I)
HEADLINE_SECTIONS = re.compile(r"abstract|introduction|contribution|discussion|conclusion|summary|implication", re.I)
NARRATIVE_SECTIONS = re.compile(r"introduction|background|related|literature|motivation|discussion|framing|"
                                r"evidence|context|implication|conclusion", re.I)


def load(review):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    if not ms:
        sys.exit("run extract_manuscript.py first")
    return ms


def section_path(ms):
    """Map section id -> 'Parent > Child' title so subsections inherit their parent's kind."""
    out, stack = {}, []
    for s in ms["sections"]:
        lvl = s.get("level", 1)
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        stack.append((lvl, s["title"]))
        out[s["id"]] = " > ".join(t for _, t in stack)
    return out


TITLE_PAGE = re.compile(r"^\s*\\(author|affiliation|title|runninghead|corrauth|address|email|thanks|maketitle|keywords?)\b")


def body_sentences(ms):
    """Sentences of the paper body: skip title-page macros and the front-matter block itself."""
    front = {s["id"] for s in ms["sections"] if s.get("level", 1) == 0}
    return [s for s in ms["sentences"] if s["section"] not in front and not TITLE_PAGE.match(s["raw"])]


def uncited(review):
    ms = load(review)
    path = section_path(ms)
    rows, counts = [], {"own_work": 0, "candidate": 0, "other": 0}
    for s in body_sentences(ms):
        if s["cites"] or len(s["text"].split()) < 5:
            continue
        sec = path.get(s["section"], "")
        own = bool(OWN.search(s["raw"]) or OWN.search(s["text"]))
        cue = FACT_CUES.findall(s["text"])
        narrative = bool(NARRATIVE_SECTIONS.search(sec))
        if cue and (narrative or not own):
            kind = "candidate"
        elif own:
            kind = "own_work"
        else:
            kind = "other"
        counts[kind] += 1
        rows.append({"sentence": s["id"], "file": s["file"], "line": s["line"], "section": sec, "text": s["text"],
                     "class": kind, "cues": sorted({c.lower() if isinstance(c, str) else c[0].lower() for c in cue})[:8],
                     "in_display": s.get("in_display")})
    write_json(os.path.join(review, "work", "uncited_auto.json"),
               {"generated": now_iso(), "total_uncited_sentences": len(rows), "counts": counts, "sentences": rows})
    print(f"{len(rows)} sentences without a citation: {counts['candidate']} factual-claim candidates, "
          f"{counts['own_work']} about the paper's own work, {counts['other']} other")


def claims(review):
    ms = load(review)
    path = section_path(ms)
    rows = []
    for s in body_sentences(ms):
        sec = path.get(s["section"], "")
        headline = bool(HEADLINE_SECTIONS.search(sec)) and not s.get("in_display")
        strong = STRONG.findall(s["text"])
        we = re.search(r"\b(we|this (study|paper|work)|our)\b.*\b(show|find|found|demonstrat|propos|develop|introduc|"
                       r"achiev|outperform|establish|reveal|provide)", s["text"], re.I)
        if (headline and (strong or we or re.search(r"\d", s["text"]))) or (strong and we):
            rows.append({"sentence": s["id"], "file": s["file"], "line": s["line"], "section": sec, "text": s["text"],
                         "strong_words": sorted({w if isinstance(w, str) else w[0] for w in strong})[:8],
                         "cites": s["cites"], "headline_section": headline})
    write_json(os.path.join(review, "work", "claimmap_auto.json"), {"generated": now_iso(), "claims": rows})
    print(f"{len(rows)} headline-claim candidates to map to evidence")


def ngrams(tokens, n):
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def overlap(review, n=8, min_run=10):
    ms = load(review)
    index = {}
    for f in glob.glob(os.path.join(review, "sources", "text", "*.json")):
        js = read_json(f)
        if not js:
            continue
        pages = [(i, pg) for i, pg in enumerate(js.get("pages") or [], 1)]
        if js.get("abstract") and js.get("kind") != "abstract":
            pages = [("abstract", js["abstract"])] + pages
        for pno, pg in pages:
            toks = norm(pg).split()
            for i, g in enumerate(ngrams(toks, n)):
                index.setdefault(g, []).append((js["key"], pno, i))
    rows = []
    for s in body_sentences(ms):
        text = re.sub(r"[\"“”`'‘’]{1,2}[^\"“”`'‘’]{10,}?[\"“”`'‘’]{1,2}", " ", s["text"])  # quoted text is allowed
        toks = norm(text).split()
        if len(toks) < n:
            continue
        hits = {}
        for i, g in enumerate(ngrams(toks, n)):
            for key, pno, j in index.get(g, []):
                hits.setdefault((key, pno), []).append((i, j))
        best = None
        for (key, pno), pairs in hits.items():
            # longest run of consecutive matching n-grams = longest shared word run
            pairs.sort()
            run, longest, last = 0, 0, None
            for i, j in pairs:
                run = run + 1 if last and i == last[0] + 1 and j == last[1] + 1 else 1
                longest = max(longest, run)
                last = (i, j)
            words = longest + n - 1
            if words >= min_run and (not best or words > best["shared_words"]):
                best = {"source_key": key, "page": pno, "shared_words": words}
        if best:
            share = best["shared_words"] / max(1, len(toks))
            rows.append({"sentence": s["id"], "file": s["file"], "line": s["line"], "text": s["text"], **best,
                         "share_of_sentence": round(share, 2), "cites_source": best["source_key"] in s["cites"]})
    rows.sort(key=lambda r: -r["shared_words"])
    write_json(os.path.join(review, "work", "overlap_auto.json"),
               {"generated": now_iso(), "min_shared_words": min_run, "sentences": rows,
                "sources_indexed": len(glob.glob(os.path.join(review, "sources", "text", "*.json")))})
    print(f"{len(rows)} sentences share {min_run}+ consecutive words with a saved source")


def equations(review):
    ms = load(review)
    rows = []
    src = ms["source"]
    if ms["format"] == "latex" and os.path.exists(src):
        text = open(src, encoding="utf-8", errors="replace").read()
        text = re.sub(r"(?<!\\)%.*", "", text)
        envs = r"equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?|displaymath"
        for m in re.finditer(r"\\begin\{(" + envs + r")\}(.*?)\\end\{\1\}|\\\[(.*?)\\\]|\$\$(.*?)\$\$", text, re.S):
            body = m.group(2) or m.group(3) or m.group(4) or ""
            line = text.count("\n", 0, m.start()) + 1
            lab = re.search(r"\\label\{([^}]*)\}", body)
            before = re.sub(r"\s+", " ", text[max(0, m.start() - 300):m.start()])[-300:]
            after = re.sub(r"\s+", " ", text[m.end():m.end() + 300])[:300]
            rows.append({"kind": "display", "line": line, "label": lab.group(1) if lab else None,
                         "latex": body.strip(), "context_before": before, "context_after": after})
        for m in re.finditer(r"(?<![\\$])\$([^$\n]{3,200}?)\$", text):
            if "=" in m.group(1) or "\\frac" in m.group(1) or "\\sum" in m.group(1):
                rows.append({"kind": "inline", "line": text.count("\n", 0, m.start()) + 1, "label": None,
                             "latex": m.group(1).strip(),
                             "context_before": re.sub(r"\s+", " ", text[max(0, m.start() - 160):m.start()]),
                             "context_after": re.sub(r"\s+", " ", text[m.end():m.end() + 160])})
    else:
        for s in ms["sentences"]:
            if re.search(r"[=∑∏√≤≥±×]", s["text"]):
                rows.append({"kind": "text", "line": s["line"], "label": None, "latex": s["text"],
                             "context_before": "", "context_after": ""})
        if ms["format"] in ("pdf", "docx"):
            print("NOTE: equations in PDF/DOCX are extracted from text only; check the rendered pages for any missed")
    rows.sort(key=lambda r: r["line"])
    write_json(os.path.join(review, "work", "equations.json"), {"generated": now_iso(), "equations": rows})
    print(f"{len(rows)} equations/formulas ({sum(1 for r in rows if r['kind'] == 'display')} display)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["uncited", "claims", "overlap", "equations", "all"])
    ap.add_argument("--review", required=True)
    a = ap.parse_args()
    for c in (["uncited", "claims", "overlap", "equations"] if a.cmd == "all" else [a.cmd]):
        print(f"--- {c}")
        globals()[c](a.review)


if __name__ == "__main__":
    main()
