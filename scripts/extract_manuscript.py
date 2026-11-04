#!/usr/bin/env python3
"""Turn a manuscript into structured JSON that every later phase works from.

Supports .tex (follows \\input/\\include), .md, .docx, .pdf.

Writes into <review_dir>/manuscript/:
  manuscript.json   sections, sentences (with citations), displays (figures/tables/...),
                    display mentions, references, and coverage notes
  fulltext.txt      plain text with [file:line] or [p.N] anchors, for agents to grep

Usage:
  python extract_manuscript.py paper/main.tex --out paper-review/main [--bib refs.bib]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import parse_bibtex, bib_authors, clean_doi, write_json, now_iso, _read_braced, norm  # noqa: E402

ABBREV = r"(?:et al|e\.g|i\.e|cf|vs|Fig|Figs|Eq|Eqs|Ref|Refs|No|Sec|Tab|approx|ca|Dr|Mr|Ms|St|U\.S|etc|resp)"
SENT_SPLIT = re.compile(r"(?<!\b" + "et al" + r")(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9\\(\[])")


def split_sentences(text):
    # protect abbreviations from splitting
    protected = re.sub(r"\b" + ABBREV + r"\.", lambda m: m.group(0).replace(".", "<DOT>"), text)
    protected = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", protected)
    parts = SENT_SPLIT.split(protected)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


# =================================================================== LaTeX
CITE_RE = re.compile(r"\\(?:[a-zA-Z]*cite[a-zA-Z]*|cite)\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")
REF_RE = re.compile(r"\\(?:ref|autoref|cref|Cref|eqref|pageref|vref|subref)\{([^}]*)\}")
LABEL_RE = re.compile(r"\\label\{([^}]*)\}")
SEC_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)(\*?)\s*(?:\[[^\]]*\])?(?=\{)")
DISPLAY_ENVS = {
    "figure": "figure", "figure*": "figure", "subfigure": "figure", "wrapfigure": "figure",
    "table": "table", "table*": "table", "longtable": "table", "sidewaystable": "table",
    "equation": "equation", "align": "equation", "equation*": None, "align*": None,
    "algorithm": "algorithm", "listing": "listing", "box": "box", "tcolorbox": "box",
    "theorem": "theorem", "lemma": "theorem", "definition": "theorem",
}


def strip_tex_comment(line):
    out, i = [], 0
    while i < len(line):
        if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
            break
        out.append(line[i])
        i += 1
    return "".join(out)


def load_tex(path, seen=None):
    """Return list of (file, lineno, text) with \\input/\\include expanded."""
    seen = seen or set()
    path = os.path.abspath(path)
    if path in seen or not os.path.exists(path):
        return []
    seen.add(path)
    base = os.path.dirname(path)
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, raw in enumerate(fh, 1):
            line = strip_tex_comment(raw.rstrip("\n"))
            m = re.search(r"\\(?:input|include|subfile)\{([^}]*)\}", line)
            if m:
                target = m.group(1)
                cand = os.path.join(base, target)
                if not os.path.exists(cand) and os.path.exists(cand + ".tex"):
                    cand += ".tex"
                before = line[:m.start()]
                if before.strip():
                    rows.append((path, n, before))
                rows.extend(load_tex(cand, seen))
                after = line[m.end():]
                if after.strip():
                    rows.append((path, n, after))
                continue
            rows.append((path, n, line))
    return rows


def tex_to_plain(s):
    s = CITE_RE.sub(lambda m: "[" + m.group(1) + "]", s)
    s = REF_RE.sub(lambda m: "<" + m.group(1) + ">", s)
    s = LABEL_RE.sub("", s)
    s = re.sub(r"\\(?:textbf|textit|emph|texttt|textsc|textrm|mathrm|mbox|text|underline)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\(?:begin|end)\{[^}]*\}", " ", s)
    s = re.sub(r"\\url\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", s)
    s = s.replace("~", " ").replace("\\%", "%").replace("\\&", "&").replace("\\_", "_").replace("\\$", "$")
    s = re.sub(r"\\(?:,|;|!| )", " ", s)
    s = s.replace("``", '"').replace("''", '"').replace("--", "-")
    return re.sub(r"\s+", " ", s).strip()


def parse_tex(main, bib_override=None):
    rows = load_tex(main)
    root = os.path.dirname(os.path.abspath(main))
    rel = lambda p: os.path.relpath(p, root)  # noqa: E731

    sections, sentences, displays, mentions, notes = [], [], [], [], []
    cur = {"id": "S0", "title": "Front matter", "level": 0, "file": rel(main), "line": 1}
    sections.append(cur)
    in_doc = not any("\\begin{document}" in r[2] for r in rows)
    env_stack, para, para_start = [], [], None
    display = None
    bib_files = []

    def flush():
        nonlocal para, para_start
        if not para:
            return
        text = " ".join(t for _, _, t in para)
        f0, l0 = para_start
        # map sentence -> line by locating its first 30 chars in the original rows
        for sent in split_sentences(text):
            line = l0
            probe = sent[:40]
            for f, l, t in para:
                if probe[:20] and probe[:20] in t:
                    line = l
                    break
            keys = []
            for m in CITE_RE.finditer(sent):
                keys += [k.strip() for k in m.group(1).split(",") if k.strip()]
            refs = []
            for m in REF_RE.finditer(sent):
                refs += [k.strip() for k in m.group(1).split(",") if k.strip()]
            sentences.append({
                "id": f"s{len(sentences) + 1:04d}", "section": cur["id"], "section_title": cur["title"],
                "file": rel(f0), "line": line, "raw": sent, "text": tex_to_plain(sent),
                "cites": keys, "refs": refs,
                "in_display": display["label"] if display else None,
            })
        para, para_start = [], None

    for f, n, line in rows:
        if "\\begin{document}" in line:
            in_doc = True
            continue
        if not in_doc:
            bm = re.search(r"\\(?:bibliography|addbibresource)\{([^}]*)\}", line)
            if bm:
                bib_files += [b.strip() for b in bm.group(1).split(",")]
            continue
        if "\\end{document}" in line:
            break
        bm = re.search(r"\\(?:bibliography|addbibresource)\{([^}]*)\}", line)
        if bm:
            bib_files += [b.strip() for b in bm.group(1).split(",")]

        for em in re.finditer(r"\\(begin|end)\{([^}]*)\}", line):
            kind, env = em.group(1), em.group(2)
            if kind == "begin":
                env_stack.append(env)
                if env == "abstract":
                    flush()
                    cur = {"id": f"S{len(sections)}", "title": "Abstract", "level": 1, "file": rel(f), "line": n}
                    sections.append(cur)
                dtype = DISPLAY_ENVS.get(env)
                if dtype and display is None:
                    flush()
                    display = {"type": dtype, "env": env, "file": rel(f), "line": n, "label": None,
                               "caption": "", "graphics": [], "section": cur["id"]}
            else:
                if env_stack and env_stack[-1] == env:
                    env_stack.pop()
                if display is not None and env == display["env"]:
                    flush()
                    if not display["label"]:
                        display["label"] = f"__unlabeled_{display['type']}_{display['line']}"
                    # unlabeled equations are not cross-reference targets; keep everything else
                    if not (display["type"] == "equation" and display["label"].startswith("__unlabeled")):
                        displays.append(display)
                    display = None
                if env == "abstract":
                    flush()

        sm = SEC_RE.search(line)
        if sm and display is None:
            flush()
            level = ["part", "chapter", "section", "subsection", "subsubsection", "paragraph"].index(sm.group(1))
            title, _ = _read_braced(line, sm.end())
            cur = {"id": f"S{len(sections)}", "title": tex_to_plain(title), "level": level,
                   "starred": bool(sm.group(2)), "file": rel(f), "line": n}
            lm = LABEL_RE.search(line)
            if lm:
                cur["label"] = lm.group(1)
            sections.append(cur)
            continue

        if display is not None:
            lm = LABEL_RE.search(line)
            if lm and not display["label"]:
                display["label"] = lm.group(1)
            cm = re.search(r"\\caption\*?(?:\[[^\]]*\])?\{", line)
            if cm or display.get("_in_caption"):
                display["caption"] += " " + line
                display["_in_caption"] = display["caption"].count("{") > display["caption"].count("}")
            gm = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", line)
            display["graphics"] += gm
            # sentences inside captions are still checked for citations
            if cm or display.get("_in_caption") or CITE_RE.search(line):
                if para_start is None:
                    para_start = (f, n)
                para.append((f, n, line))
            continue
        lm = LABEL_RE.search(line)
        if lm and display is None and env_stack and DISPLAY_ENVS.get(env_stack[-1]) == "equation" \
                and not any(d["label"] == lm.group(1) for d in displays):
            displays.append({"type": "equation", "env": env_stack[-1], "file": rel(f), "line": n,
                             "label": lm.group(1), "caption": "", "graphics": [], "section": cur["id"]})
        if not line.strip():
            flush()
            continue
        if re.match(r"\s*\\(?:maketitle|centering|small|footnotesize|noindent|clearpage|newpage)\s*$", line):
            continue
        if para_start is None:
            para_start = (f, n)
        para.append((f, n, line))
    flush()

    for d in displays:
        cap = d["caption"].strip()
        cm = re.search(r"\\caption\*?(?:\[[^\]]*\])?(?=\{)", cap)
        d["caption"] = tex_to_plain(_read_braced(cap, cm.end())[0]) if cm else tex_to_plain(cap)
        d.pop("_in_caption", None)

    # mentions of every label anywhere in body text
    for f, n, line in rows:
        for m in REF_RE.finditer(line):
            for k in m.group(1).split(","):
                mentions.append({"label": k.strip(), "file": rel(f), "line": n, "context": tex_to_plain(line)[:240]})

    refs = []
    bib_paths = []
    if bib_override:
        bib_paths = [bib_override]
    else:
        for b in bib_files:
            p = os.path.join(root, b if b.endswith(".bib") else b + ".bib")
            if os.path.exists(p):
                bib_paths.append(p)
    for bp in bib_paths:
        with open(bp, encoding="utf-8", errors="replace") as fh:
            for e in parse_bibtex(fh.read()):
                e["_file"] = rel(bp)
                refs.append(e)
    if not bib_paths:
        bibitems = parse_bibitems(rows)
        if bibitems:
            refs = bibitems
            notes.append("References read from \\bibitem entries (no .bib file found).")
        else:
            notes.append("No .bib or \\bibitem found: reference list must be supplied or extracted by hand.")
    return sections, sentences, displays, mentions, refs, notes, rows


def parse_bibitems(rows):
    text = "\n".join(t for _, _, t in rows)
    m = re.search(r"\\begin\{thebibliography\}(.*?)\\end\{thebibliography\}", text, re.S)
    if not m:
        return []
    out = []
    for part in re.split(r"\\bibitem", m.group(1))[1:]:
        km = re.match(r"(?:\[[^\]]*\])?\{([^}]*)\}(.*)", part, re.S)
        if km:
            raw = tex_to_plain(km.group(2))
            out.append({"ID": km.group(1).strip(), "ENTRYTYPE": "unknown", "raw": raw, "doi": clean_doi(raw) or ""})
    return out


# =================================================================== Markdown / DOCX / PDF
NUM_CITE = re.compile(r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]")
# parenthetical author-year: (Entman, 1993) (Belin et al., 2012; Smith and Jones, 2019a) (Org Name, 2025)
AY_CITE = re.compile(r"\(((?:e\.g\.,?\s*|see\s+|cf\.\s*)?[A-Z][^()]{0,200}?(?:19|20)\d\d[a-z]?(?:\s*[;,]\s*[^()]{0,120}?(?:19|20)\d\d[a-z]?)*)\)")
# narrative author-year: Entman (1993), Belin et al. (2012), Ralph and Goddard (2019a)
AY_NARR = re.compile(r"\b([A-Z][A-Za-zÀ-ÿ'’\-]+(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-zÀ-ÿ'’\-]+)?)\s+\(((?:19|20)\d\d[a-z]?(?:\s*,\s*(?:19|20)\d\d[a-z]?)*)\)")
PANDOC_CITE = re.compile(r"\[(@[^\]]+)\]|(?<![\w@])@([A-Za-z][\w:-]+)")
REF_HEADING = re.compile(r"^\s*(?:\d+\.?\s*)?(references|reference list|bibliography|literature cited|works cited|sources|"
                         r"endnotes|notes and references|citations)\s*:?\s*$", re.I)


def expand_numeric(s):
    keys = []
    for part in re.split(r"\s*,\s*", s):
        r = re.split(r"\s*[-–]\s*", part)
        if len(r) == 2 and r[0].isdigit() and r[1].isdigit() and int(r[1]) - int(r[0]) < 200:
            keys += [str(i) for i in range(int(r[0]), int(r[1]) + 1)]
        elif part.strip().isdigit():
            keys.append(part.strip())
    return keys


def cites_in_plain(sent):
    keys = []
    for m in NUM_CITE.finditer(sent):
        keys += expand_numeric(m.group(1))
    for m in PANDOC_CITE.finditer(sent):
        blob = m.group(1) or "@" + m.group(2)
        keys += [k.strip().lstrip("@").split()[0].rstrip(";,") for k in blob.split(";") if "@" in k]
    for m in AY_CITE.finditer(sent):
        for c in m.group(1).split(";"):
            c = re.sub(r"^(e\.g\.,?|see|cf\.)\s*", "", c.strip())
            # "Smith, 2019, 2020" -> two citations of the same author
            yrs = re.findall(r"(?:19|20)\d\d[a-z]?", c)
            who = re.split(r",?\s*(?:19|20)\d\d", c)[0].strip(" ,")
            if who and re.match(r"[A-Z]", who) and not re.match(r"(Table|Figure|Fig|Section|Eq|n|N|p)\b", who):
                keys += [f"AY:{who}, {y}" for y in yrs]
    for m in AY_NARR.finditer(sent):
        for y in re.findall(r"(?:19|20)\d\d[a-z]?", m.group(2)):
            keys.append(f"AY:{m.group(1)}, {y}")
    return list(dict.fromkeys(keys))


def trailing_reference_start(blocks):
    """Index where an un-headed reference list starts at the end of the document ([1] ... or 1. ...)."""
    start, numbered = None, 0
    for i in range(len(blocks) - 1, -1, -1):
        t = blocks[i][2].strip()
        if not t:
            continue
        if re.match(r"^\s*(\[\d+\]|\d+\.\s)", t):
            numbered += 1
            start = i
        elif re.match(r"^\s*(https?://|doi:|www\.)\S+\s*$", t) or (len(t.split()) <= 30 and start is not None and i == start - 1):
            continue  # URL or wrapped line belonging to the next entry
        elif blocks[i][1] == "heading":
            break
        else:
            break
    return start if numbered >= 3 else None


def parse_blocks(blocks, source_name, ref_lines_override=None):
    """blocks: list of (anchor, kind, text) where kind in heading/para. Generic for md/docx/pdf."""
    sections = [{"id": "S0", "title": "Front matter", "level": 0, "file": source_name, "line": 1}]
    cur = sections[0]
    sentences, displays, mentions, ref_lines = [], [], [], []
    in_refs = False
    has_heading = any(REF_HEADING.match(t.strip()) for _, _, t in blocks)
    tail = None if (has_heading or ref_lines_override is not None) else trailing_reference_start(blocks)
    cap_re = re.compile(r"^\s*(Figure|Fig\.|Table|Box|Supplementary (?:Figure|Table)|Extended Data Fig\.?)\s*(S?\d+)[a-z]?"
                        r"(?:\s*[.:|]\s*(.*)|\s*$)", re.I)
    for idx, (anchor, kind, text) in enumerate(blocks):
        t = text.strip()
        if not t:
            continue
        if tail is not None and idx >= tail:
            if not in_refs:
                cur = {"id": f"S{len(sections)}", "title": "References (list without a heading)", "level": 1,
                       "file": source_name, "line": anchor}
                sections.append(cur)
                in_refs = True
            ref_lines.append((anchor, t))
            continue
        if kind == "heading" or REF_HEADING.match(t):
            if REF_HEADING.match(t):
                in_refs = True
            elif in_refs and re.match(r"^(appendix|supplementary|acknowledg)", t, re.I):
                in_refs = False
            cur = {"id": f"S{len(sections)}", "title": t[:120], "level": 1, "file": source_name, "line": anchor}
            sections.append(cur)
            continue
        if in_refs:
            ref_lines.append((anchor, t))
            continue
        cm = cap_re.match(t)
        if cm:
            dtype = cm.group(1).lower().split()[0].rstrip(".")
            dtype = {"fig": "figure", "supplementary": "supplementary", "extended": "figure"}.get(dtype, dtype)
            cap = cm.group(3) or ""
            if not cap and idx + 1 < len(blocks):  # "Table 1" on its own line: the caption is the next block
                cap = blocks[idx + 1][2].strip()
            if not any(d_["label"].split()[-1] == cm.group(2) and d_["type"] == dtype for d_ in displays):
                displays.append({"type": dtype, "label": f"{cm.group(1)} {cm.group(2)}", "line": anchor,
                                 "caption": cap[:600], "file": source_name, "section": cur["id"], "graphics": []})
        for sent in split_sentences(t):
            sentences.append({"id": f"s{len(sentences) + 1:04d}", "section": cur["id"], "section_title": cur["title"],
                              "file": source_name, "line": anchor, "raw": sent, "text": sent,
                              "cites": cites_in_plain(sent), "refs": [], "in_display": None})
            for m in re.finditer(r"\b(Fig(?:ure)?s?\.?|Tables?|Box(?:es)?|Eq(?:uation)?s?\.?|Supplementary (?:Figure|Table)s?)\s*(S?\d+[a-z]?)", sent):
                kindw = m.group(1).lower()
                norm_kind = "Figure" if kindw.startswith("fig") else "Table" if kindw.startswith("tab") else \
                    "Box" if kindw.startswith("box") else "Equation" if kindw.startswith("eq") else m.group(1)
                mentions.append({"label": f"{norm_kind} {re.sub(r'[a-z]$', '', m.group(2))}", "file": source_name, "line": anchor,
                                 "context": sent[:240]})
    for d in displays:
        num = d["label"].split()[-1]
        d["label"] = {"figure": "Figure", "table": "Table", "box": "Box"}.get(d["type"], d["type"].title()) + " " + num
    refs = split_reference_list(ref_lines_override if ref_lines_override is not None else ref_lines)
    resolve_author_year(sentences, refs)
    return sections, sentences, displays, mentions, refs


# a new author-year entry starts with "Surname, I." / "Surname Other, I." / "Org Name, 2025."
AY_ENTRY = re.compile(r"^(?:[A-Z][A-Za-zÀ-ÿ'’\-]+(?:\s+(?:[a-z]{1,3}\s+)?[A-Za-zÀ-ÿ'’\-]+){0,3}),\s+(?:[A-Z][a-zà-ÿ]?\.|[A-Z][a-zà-ÿ]+,?\s+[A-Z]\.)"
                      r"|^[A-Z][^,\n]{2,90},\s+(?:19|20)\d\d[a-z]?\.")


def split_reference_list(ref_lines):
    """Entries from reference-list lines. Works for numbered ([1] / 1.) and author-year lists, including
    entries that wrap over several lines or pages."""
    entries, cur = [], None
    numbered = sum(1 for _, t in ref_lines if re.match(r"^\s*(?:\[\d+\]|\d+\.)\s", t)) >= max(3, len(ref_lines) // 4)
    multi = {}
    texts = [t for _, t in ref_lines]
    for li, (anchor, t) in enumerate(ref_lines):
        ahead = " ".join(texts[li:li + 6])  # a PDF may break one entry's first words over several lines
        mm = re.match(r"^\s*((?:\[\d+\]\s*){2,})(.*)", t)  # "[1] [2] [5] Title": one source, several numbers
        if mm and numbered:
            nums = re.findall(r"\d+", mm.group(1))
            t = f"[{nums[0]}] {mm.group(2)}"
            multi[nums[0]] = nums[1:]
        m = re.match(r"^\s*(?:\[(\d+)\]|(\d+)\.)\s+(.*)", t)
        prev_done = cur is None or re.search(r"[.)\]]\s*$|\d\s*$|https?://\S+\s*$", cur["raw"])
        if numbered:
            starts = bool(m)
        else:
            starts = cur is None or (bool(AY_ENTRY.match(t) or (t[:1].isupper() and AY_ENTRY.match(ahead))) and bool(prev_done))
        if starts:
            if cur:
                entries.append(cur)
            num = (m.group(1) or m.group(2)) if (m and numbered) else str(len(entries) + 1)
            cur = {"ID": num, "ENTRYTYPE": "unknown", "raw": (m.group(3) if (m and numbered) else t), "_line": anchor}
        else:
            joiner = "" if cur["raw"].endswith("-") and t[:1].islower() else " "
            cur["raw"] = (cur["raw"][:-1] if joiner == "" else cur["raw"]) + joiner + t
    if cur:
        entries.append(cur)
    for e in entries:
        e["raw"] = re.sub(r"\s+", " ", e["raw"]).strip()
        joined = re.sub(r"((?:doi:\s*|doi\.org/)10\.\d{4,9}/\S*[./\-])\s+(?=[\w(])", r"\1", e["raw"])  # DOI broken at a line end
        joined = re.sub(r"((?:doi:\s*|doi\.org/)10\.\d{4,9}/)\s+", r"\1", joined)
        e["doi"] = clean_doi(joined) or ""
        y = re.search(r"\b(19|20)\d\d[a-z]?\b", e["raw"])
        e["year"] = y.group(0) if y else ""
        first = re.split(r",|\s+\(", e["raw"], maxsplit=1)[0].strip()
        e["first_author"] = first
    for e in list(entries):  # aliases for multi-number entries
        for extra in multi.get(e["ID"], []):
            entries.append({**e, "ID": extra, "alias_of": e["ID"]})
    if entries and not numbered:  # author-year lists get readable keys: entman1993, belin2012a...
        seen = {}
        for e in entries:
            base = (norm(e["first_author"]).split() or ["ref"])[-1 if "," in e["raw"][:40] else 0][:20] + e["year"][:4]
            seen[base] = seen.get(base, 0) + 1
            e["ID"] = base
        dup = {k for k, v in seen.items() if v > 1}
        count = {}
        for e in entries:
            if e["ID"] in dup:
                count[e["ID"]] = count.get(e["ID"], 0) + 1
                e["ID"] += "abcdefghij"[count[e["ID"]] - 1]
    return entries


def resolve_author_year(sentences, refs):
    """Replace 'AY:Surname et al., 2012' citations with the key of the matching reference entry."""
    if not refs:
        return
    def surname_keys(s):
        s = re.split(r"\s+et\s+al|\s+(?:and|&)\s+", s)[0]
        return norm(s)
    table = []
    for r in refs:
        table.append((norm(r.get("first_author") or r.get("raw", "")[:60]), (r.get("year") or "")[:4], r.get("year", ""), r["ID"]))
    for s in sentences:
        out = []
        for k in s["cites"]:
            if not k.startswith("AY:"):
                out.append(k)
                continue
            who, _, yr = k[3:].rpartition(",")
            who, yr = surname_keys(who.strip()), yr.strip()
            cands = [rid for fa, y4, yfull, rid in table if y4 == yr[:4] and fa and who and
                     (fa == who or fa.split()[-1] == who.split()[-1] or fa.startswith(who) or who.startswith(fa))]
            if len(cands) > 1 and len(yr) == 5:  # 2019a / 2019b
                cands = [c for c in cands if c.endswith(yr[4])] or cands
            out.append(cands[0] if len(cands) == 1 else k)
        s["cites"] = list(dict.fromkeys(out))


def parse_md(path):
    blocks, buf, start = [], [], None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            if line.startswith("#"):
                if buf:
                    blocks.append((start, "para", " ".join(buf)))
                    buf = []
                blocks.append((n, "heading", line.lstrip("#").strip()))
            elif not line.strip():
                if buf:
                    blocks.append((start, "para", " ".join(buf)))
                    buf = []
            else:
                if not buf:
                    start = n
                buf.append(line.strip())
    if buf:
        blocks.append((start, "para", " ".join(buf)))
    return parse_blocks(blocks, os.path.basename(path))


def parse_docx(path):
    """Paragraphs and tables in document order (tables in place, so a reference list at the end is found)."""
    import docx  # python-docx, from setup_env.sh
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(path)
    blocks, n, tn = [], 0, 0
    for el in d.element.body.iterchildren():
        tag = el.tag.split("}")[-1]
        if tag == "p":
            n += 1
            p = Paragraph(el, d)
            style = (p.style.name or "").lower() if p.style is not None else ""
            kind = "heading" if style.startswith("heading") or style == "title" else "para"
            blocks.append((n, kind, p.text))
        elif tag == "tbl":
            tn += 1
            t = Table(el, d)
            blocks.append((f"table{tn}", "para", " | ".join(c.text for r in t.rows for c in r.cells)[:2000]))
    return parse_blocks(blocks, os.path.basename(path))


def parse_pdf(path):
    """Line-based PDF reading: spans joined without extra spaces, running headers/footers removed,
    headings detected from font, reference list split line by line."""
    import pymupdf
    doc = pymupdf.open(path)
    pages, sizes = [], []
    for pno, page in enumerate(doc, 1):
        blks = []
        ph = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            lines = []
            for l in b.get("lines", []):
                spans = [s for s in l["spans"] if s["text"].strip() or s["text"] == " "]
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans)
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    y = l["bbox"][1] / ph
                    lines.append({"text": text, "size": max(s["size"] for s in spans), "margin": y < 0.08 or y > 0.92,
                                  "bold": all("bold" in s["font"].lower() or s["flags"] & 16 for s in spans if s["text"].strip())})
                    for sp in spans:
                        sizes += [round(sp["size"], 1)] * len(sp["text"])
            if lines:
                blks.append(lines)
        pages.append(blks)
    body = max(set(sizes), key=sizes.count) if sizes else 10
    # running headers/footers: the same short line (digits ignored) on 3+ pages
    from collections import Counter
    sig = lambda t: re.sub(r"\d+", "#", t.lower())  # noqa: E731
    # only lines in the top/bottom 8% of the page can be running headers or footers
    cnt = Counter(sig(l["text"]) for blks in pages for lines in blks for l in lines if len(l["text"]) < 100 and l["margin"])
    # "Table 1", "Figure 2" also repeat once digits are ignored, but they are captions, not headers
    repeated = {k for k, v in cnt.items() if v >= 3 and not re.match(r"^(table|figure|fig\.|box|eq\.?|equation)\s*#", k)}
    is_noise = lambda l: l["margin"] and (sig(l["text"]) in repeated or re.fullmatch(r"(page )?#( of #)?", sig(l["text"])))  # noqa: E731
    blocks, ref_lines, in_refs = [], [], False
    for pno, blks in enumerate(pages, 1):
        for lines in blks:
            lines = [l for l in lines if not is_noise(l)]
            if not lines:
                continue
            # "3.1. Corpus and text cleaning" as the first line of a paragraph block: split off the heading
            if len(lines) > 1 and not in_refs and re.match(r"^\d+(\.\d+)+\.?\s+[A-Z][^.]{2,80}$", lines[0]["text"]) \
                    and len(lines[0]["text"]) < 90:
                blocks.append((f"p{pno}", "heading", lines[0]["text"]))
                lines = lines[1:]
            text = ""
            if len(lines) > 1 and re.match(r"^(Table|Figure|Fig\.|Box)\s*S?\d+[a-z]?\s*$", lines[0]["text"], re.I):
                lines = [{**lines[0], "text": lines[0]["text"].strip() + ":"}] + lines[1:]  # "Table 1" / caption lines
            for l in lines:
                t = l["text"]
                text = text[:-1] + t if text.endswith("-") and t[:1].islower() else (text + " " + t if text else t)
            alpha = sum(c.isalpha() for c in text) / max(1, len(text))
            big = max(l["size"] for l in lines) > body + 1.2
            bold = all(l["bold"] for l in lines)
            numbered_head = re.match(r"^\d+(\.\d+)*\.?\s+[A-Z][^.]{2,80}$", text)
            caption_label = re.match(r"^(Table|Figure|Fig\.|Box)\s*S?\d+[a-z]?\s*[.:|]?\s*$", text, re.I)
            heading = (len(text) < 90 and alpha > 0.6 and not text.endswith(".") and (big or bold or numbered_head)
                       and not caption_label)
            if REF_HEADING.match(text):
                in_refs = True
                blocks.append((f"p{pno}", "heading", text))
                continue
            if in_refs:
                if heading and re.match(r"^(appendix|supplementary)", text, re.I):
                    in_refs = False
                else:
                    ref_lines += [(f"p{pno}", l["text"]) for l in lines]
                    continue
            blocks.append((f"p{pno}", "heading" if heading else "para", text))
    # a paragraph that runs over a page or column break arrives as two blocks: join them when the first does
    # not end a sentence and the second starts in lower case (or with a citation/number continuation)
    joined = []
    for a, k, t in blocks:
        if joined and k == "para" and joined[-1][1] == "para" and not re.search(r"[.!?:]\s*[\)\]\"”']?\s*$", joined[-1][2]) \
                and re.match(r"^[a-z(\[0-9]", t) and not re.match(r"^(Table|Figure|Fig\.)", joined[-1][2]):
            pa, pk, pt = joined[-1]
            joined[-1] = (pa, pk, (pt[:-1] + t) if pt.endswith("-") else pt + " " + t)
        else:
            joined.append((a, k, t))
    blocks = joined
    # if the paper numbers its headings ("2.1 Data"), unnumbered bold lines are usually figure or table text;
    # keep only standard unnumbered headings
    STD = re.compile(r"^(abstract|highlights|keywords|acknowledg\w*|references|bibliography|appendix\b.*|data (and code )?availability.*|"
                     r"code availability.*|credit .*|author contributions?.*|declaration.*|competing interests?.*|funding.*|ethics.*|"
                     r"conflicts? of interest.*|supplementary.*|nomenclature|abbreviations)$", re.I)
    numbered = sum(1 for _, k, t in blocks if k == "heading" and re.match(r"^\d+(\.\d+)*\.?\s+\S", t))
    if numbered >= 3:
        blocks = [(a, k if (k != "heading" or re.match(r"^\d+(\.\d+)*\.?\s+\S", t) or STD.match(t.strip())) else "para", t)
                  for a, k, t in blocks]
    return parse_blocks(blocks, os.path.basename(path), ref_lines_override=ref_lines)


def guess_title(src, fmt):
    """Paper title for display: \\title{} in LaTeX, Title style or first heading in Word, largest text on PDF page 1."""
    try:
        if fmt == "latex":
            t = open(src, encoding="utf-8", errors="replace").read()
            m = re.search(r"\\title(?:\[[^\]]*\])?\{", t)
            return tex_to_plain(_read_braced(t, m.end() - 1)[0]) if m else ""
        if fmt == "docx":
            import docx
            for p in docx.Document(src).paragraphs:
                st = (p.style.name or "").lower() if p.style is not None else ""
                if p.text.strip() and (st == "title" or st.startswith("heading")):
                    return p.text.strip()[:200]
        if fmt == "pdf":
            import pymupdf
            with pymupdf.open(src) as d:
                spans = [(sp["size"], sp["text"]) for b in d[0].get_text("dict")["blocks"] for l in b.get("lines", [])
                         for sp in l["spans"] if sp["text"].strip()]
            if spans:
                big = max(sz for sz, _ in spans)
                return re.sub(r"\s+", " ", " ".join(t for sz, t in spans if sz >= big - 0.5)).strip()[:200]
        if fmt == "markdown":
            for line in open(src, encoding="utf-8", errors="replace"):
                if line.startswith("# "):
                    return line[2:].strip()
    except Exception:
        return ""
    return ""


# =================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manuscript")
    ap.add_argument("--out", required=True, help="review directory (paper-review/<name>)")
    ap.add_argument("--bib", help="override .bib path")
    args = ap.parse_args()

    src = os.path.abspath(args.manuscript)
    ext = os.path.splitext(src)[1].lower()
    notes = []
    rows = None
    if ext == ".tex":
        sections, sentences, displays, mentions, refs, notes, rows = parse_tex(src, args.bib)
        fmt = "latex"
    elif ext in (".md", ".markdown", ".qmd", ".rmd"):
        sections, sentences, displays, mentions, refs = parse_md(src)
        fmt = "markdown"
    elif ext == ".docx":
        sections, sentences, displays, mentions, refs = parse_docx(src)
        fmt = "docx"
    elif ext == ".pdf":
        sections, sentences, displays, mentions, refs = parse_pdf(src)
        fmt = "pdf"
        notes.append("PDF input: section headings and reference boundaries are heuristic. "
                     "Agents must confirm the section list and reference count against the PDF itself.")
    else:
        sys.exit(f"Unsupported manuscript type: {ext}")

    if args.bib and ext != ".tex":
        with open(args.bib, encoding="utf-8", errors="replace") as fh:
            refs = parse_bibtex(fh.read())

    for r in refs:
        r["doi"] = clean_doi(r.get("doi") or r.get("url") or r.get("raw") or "") or ""
        if "author" in r:
            r["_authors"] = bib_authors(r["author"])

    cited_keys = []
    for s in sentences:
        for k in s["cites"]:
            if k not in cited_keys:
                cited_keys.append(k)
    ref_ids = [r["ID"] for r in refs]
    missing = [k for k in cited_keys if not k.startswith("AY:") and k not in ref_ids]
    uncited = [k for k in ref_ids if k not in cited_keys] if fmt in ("latex", "markdown") or \
        any(not k.startswith("AY:") for k in cited_keys) else []

    citing = [s for s in sentences if s["cites"]]
    data = {
        "generated": now_iso(),
        "title": guess_title(src, fmt),
        "source": src,
        "format": fmt,
        "editable_source": fmt in ("latex", "markdown", "docx"),
        "sections": sections,
        "sentences": sentences,
        "displays": displays,
        "mentions": mentions,
        "references": refs,
        "counts": {
            "sections": len(sections), "sentences": len(sentences), "citing_sentences": len(citing),
            "citation_instances": sum(len(s["cites"]) for s in citing), "references": len(refs),
            "displays": len(displays), "cited_keys": len(cited_keys),
        },
        "cited_but_missing_from_reference_list": missing,
        "in_reference_list_but_never_cited": uncited,
        "notes": notes,
    }
    out_dir = os.path.join(args.out, "manuscript")
    write_json(os.path.join(out_dir, "manuscript.json"), data)

    with open(os.path.join(out_dir, "fulltext.txt"), "w", encoding="utf-8") as fh:
        if rows is not None:
            root = os.path.dirname(src)
            for f, n, t in rows:
                fh.write(f"[{os.path.relpath(f, root)}:{n}] {t}\n")
        else:
            for s in sentences:
                fh.write(f"[{s['file']}:{s['line']}] {s['text']}\n")

    c = data["counts"]
    print(f"format={fmt} sections={c['sections']} sentences={c['sentences']} citing_sentences={c['citing_sentences']} "
          f"citation_instances={c['citation_instances']} references={c['references']} displays={c['displays']}")
    if missing:
        print("CITED BUT NOT IN REFERENCE LIST:", ", ".join(missing))
    if uncited:
        print("IN REFERENCE LIST BUT NEVER CITED:", ", ".join(uncited))
    for n in notes:
        print("NOTE:", n)


if __name__ == "__main__":
    main()
