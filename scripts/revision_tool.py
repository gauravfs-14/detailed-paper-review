#!/usr/bin/env python3
"""Phase R (mechanical part): check a revision package against itself.

  python revision_tool.py --review $RV --revised paper/main.tex --response response.docx \
      [--previous old/main.tex] [--annotated main_diff.tex|tracked.docx|marked.pdf] [--comments decision.pdf]

What it does (agents adjudicate everything it reports):
  1. Splits the response letter into reviewer comments and author responses.
  2. Finds every quotation in the responses and checks it word for word against the revised manuscript
     (a response that quotes text the manuscript does not contain is a finding).
  3. Collects the locations each response points to (page, line, section, table, figure).
  4. With --previous: sentence-level diff of previous vs revised = the real list of changes.
  5. With --annotated: reads what the tracked/marked version shows as added or deleted (latexdiff \\DIFadd/
     \\DIFdel, Word w:ins/w:del, coloured text in a PDF) and compares it with the real changes:
     changes not marked, and marked text that is not in the revised manuscript.
  6. Flags real changes that no response mentions (possible unannounced changes).

Output: work/revision/auto.json
"""
import argparse
import difflib
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import norm, now_iso, read_json, write_json  # noqa: E402
from review_tool import locate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REV_HDR = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?\s*(reviewer|referee)\s*#?\s*(\d+|[A-Z])\b|^\s*(?:#+\s*)?(?:\*\*)?\s*((?:associate\s+)?editor)\b", re.I)
COMMENT = re.compile(r"^\s*(?:\*\*)?\s*((?:comment|point|issue|concern|query|question|remark)\s*#?\s*[\w.\-]*|"
                     r"[RC]\s?\d+[.\-]\d+|\d+(?:\.\d+)*[.)]|\(\d+\)|[QC]\d+[.:])\s*[:.)\-]?", re.I)
RESPONSE = re.compile(r"^\s*(?:\*\*)?\s*(response|reply|answer|author'?s?\s+response|our\s+response|"
                      r"A\d*[.:]|R:)\s*[:.\-]?", re.I)
QUOTE = re.compile(r"[\"“`]{1,2}([^\"”']{25,}?)[\"”']{1,2}")
LOC = re.compile(r"\b(page|p\.|line|lines|l\.|section|sec\.|table|fig(?:ure)?\.?|equation|eq\.|appendix)\s*~?"
                 r"([A-Z]?\d+(?:[.\-–]\d+)*)", re.I)


def doc_paragraphs(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        import docx
        return [p.text for p in docx.Document(path).paragraphs]
    if ext == ".pdf":
        import pymupdf
        out = []
        with pymupdf.open(path) as d:
            for pg in d:
                for b in pg.get_text("blocks"):
                    out.append(re.sub(r"\s+", " ", b[4]).strip())
        return out
    text = open(path, encoding="utf-8", errors="replace").read()
    if ext == ".tex":
        text = re.sub(r"(?<!\\)%.*", "", text)
        text = re.sub(r"\\(?:textbf|textit|emph)\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\\item\s*", "\n", text)
    paras, buf = [], []
    for line in text.split("\n"):
        if not line.strip():
            if buf:
                paras.append(" ".join(buf))
                buf = []
        elif COMMENT.match(line) or RESPONSE.match(line) or REV_HDR.match(line):
            if buf:
                paras.append(" ".join(buf))
            buf = [line.strip()]
        else:
            buf.append(line.strip())
    if buf:
        paras.append(" ".join(buf))
    return paras


def split_response(paras):
    items, reviewer, cur, mode = [], "general", None, None
    for p in paras:
        if not p.strip():
            continue
        h = REV_HDR.match(p)
        if h and len(p) < 120:
            reviewer = (h.group(1) or h.group(3) or "").title() + (" " + h.group(2) if h.group(2) else "")
            mode = None
            continue
        if RESPONSE.match(p):
            if cur is None:
                cur = {"reviewer": reviewer, "comment": "", "response": ""}
                items.append(cur)
            cur["response"] += " " + RESPONSE.sub("", p, count=1).strip()
            mode = "response"
            continue
        if COMMENT.match(p) and len(p.split()) > 3:  # every numbered comment starts a new item
            cur = {"reviewer": reviewer, "label": COMMENT.match(p).group(1).strip(), "comment": p.strip(), "response": ""}
            items.append(cur)
            mode = "comment"
            continue
        if cur is None:
            continue
        cur[mode or "comment"] += " " + p.strip()
    for i, it in enumerate(items, 1):
        it["id"] = f"RC{i:03d}"
        it["comment"], it["response"] = it["comment"].strip(), it["response"].strip()
    quality = "good" if items and sum(1 for i in items if i["response"]) >= 0.8 * len(items) else \
        "partial" if items else "failed"
    return items, quality


def manuscript(main, out):
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "extract_manuscript.py"), main, "--out", out],
                   capture_output=True, text=True)
    return read_json(os.path.join(out, "manuscript", "manuscript.json"))


def find_quote(q, sents, full):
    r = locate(q, full)
    if r["match"] == "not_found":
        return {"match": "not_found", "score": r["score"]}
    pos, acc = r["start"], 0
    for s in sents:
        acc += len(s["text"]) + 1
        if acc > pos:
            return {"match": r["match"], "score": r["score"], "file": s["file"], "line": s["line"]}
    return {"match": r["match"], "score": r["score"]}


def annotated_spans(path):
    ext = os.path.splitext(path)[1].lower()
    add, dele = [], []
    if ext == ".tex":
        t = open(path, encoding="utf-8", errors="replace").read()
        for name, bucket in (("DIFadd", add), ("DIFdel", dele)):
            for m in re.finditer(r"\\" + name + r"\{", t):
                k, depth = m.end(), 1
                while k < len(t) and depth:
                    depth += {"{": 1, "}": -1}.get(t[k], 0)
                    k += 1
                bucket.append(re.sub(r"\\[A-Za-z]+\*?|[{}]", " ", t[m.end():k - 1]))
    elif ext == ".docx":
        import zipfile
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
        for m in re.finditer(r"<w:ins\b.*?</w:ins>", xml, re.S):
            add.append(" ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", m.group(0))))
        for m in re.finditer(r"<w:del\b.*?</w:del>", xml, re.S):
            dele.append(" ".join(re.findall(r"<w:delText[^>]*>([^<]*)</w:delText>", m.group(0))))
    elif ext == ".pdf":
        import pymupdf
        with pymupdf.open(path) as d:
            for pg in d:
                for b in pg.get_text("dict")["blocks"]:
                    for line in b.get("lines", []):
                        for sp in line["spans"]:
                            c = sp["color"]
                            r, g, bl = (c >> 16) & 255, (c >> 8) & 255, c & 255
                            if max(r, g, bl) - min(r, g, bl) > 60 and sp["text"].strip():
                                (dele if r > 150 and g < 100 and bl < 100 else add).append(sp["text"])
    add = [re.sub(r"\s+", " ", a).strip() for a in add if len(norm(a).split()) >= 1]
    dele = [re.sub(r"\s+", " ", a).strip() for a in dele if len(norm(a).split()) >= 1]
    return add, dele


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--review", required=True)
    ap.add_argument("--revised", required=True)
    ap.add_argument("--response", required=True)
    ap.add_argument("--previous")
    ap.add_argument("--annotated")
    ap.add_argument("--comments")
    a = ap.parse_args()
    wd = os.path.join(a.review, "work", "revision")
    os.makedirs(wd, exist_ok=True)
    cur = manuscript(a.revised, os.path.join(wd, "revised"))
    sents = cur["sentences"]
    full = " ".join(s["text"] for s in sents)

    items, quality = split_response(doc_paragraphs(a.response))
    for it in items:
        it["quotes"] = []
        for q in QUOTE.findall(it["response"]):
            if len(q.split()) >= 6:
                it["quotes"].append({"text": q, **find_quote(q, sents, full)})
        it["locations"] = [f"{m.group(1)} {m.group(2)}" for m in LOC.finditer(it["response"])]
        it["has_response"] = bool(it["response"])
    comments_extra = None
    if a.comments:
        comments_extra = [p for p in doc_paragraphs(a.comments) if len(p.split()) > 6]

    out = {"generated": now_iso(), "response_parse": {"quality": quality, "items": len(items),
                                                      "without_response": [i["id"] for i in items if not i["has_response"]]},
           "items": items, "decision_letter_paragraphs": comments_extra}
    if quality != "good":
        out["response_parse"]["note"] = ("The letter could not be split cleanly into comment/response pairs. An agent must "
                                         "pair them by reading the letter; every reviewer comment still needs a verdict.")

    changes = []
    if a.previous:
        prev = manuscript(a.previous, os.path.join(wd, "previous"))
        pa, pb = [norm(s["text"]) for s in prev["sentences"]], [norm(s["text"]) for s in sents]
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, pa, pb, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            changes.append({"id": f"CH{len(changes) + 1:03d}", "type": op,
                            "old": [{"line": s["line"], "text": s["text"]} for s in prev["sentences"][i1:i2]],
                            "new": [{"file": s["file"], "line": s["line"], "text": s["text"]} for s in sents[j1:j2]]})
        resp_norm = norm(" ".join(i["response"] for i in items))
        for ch in changes:
            new_txt = " ".join(x["text"] for x in ch["new"]) or " ".join(x["text"] for x in ch["old"])
            words = norm(new_txt).split()
            grams = {" ".join(words[k:k + 6]) for k in range(max(1, len(words) - 5))}
            ch["mentioned_in_response"] = any(g and g in resp_norm for g in grams)
        out["changes"] = changes
        out["unannounced_candidates"] = [c["id"] for c in changes if not c["mentioned_in_response"]]

    if a.annotated:
        add, dele = annotated_spans(a.annotated)
        add_words = set(norm(" ".join(add)).split())
        out["annotated"] = {"file": a.annotated, "added_spans": len(add), "deleted_spans": len(dele),
                            "added_text_sample": add[:20]}
        out["marked_not_in_revised"] = [x for x in add if len(norm(x).split()) >= 4 and locate(x, full)["match"] == "not_found"][:50]
        if changes:
            unmarked = []
            for ch in changes:
                for s in ch["new"]:
                    w = norm(s["text"]).split()
                    old_words = set(norm(" ".join(o["text"] for o in ch["old"])).split())
                    new_words = [x for x in w if x not in old_words]
                    content = [x for x in new_words if len(x) > 3]
                    marked = sum(1 for x in content if x in add_words)
                    if content and marked < 0.5 * len(content):
                        unmarked.append({"change": ch["id"], "line": s["line"], "text": s["text"], "new_words": new_words[:12]})
            out["changes_not_marked"] = unmarked
    write_json(os.path.join(wd, "auto.json"), out)
    print(f"response letter: {len(items)} comment/response pairs (parse quality: {quality}); "
          f"{len(out['response_parse']['without_response'])} without a response")
    nq = sum(len(i["quotes"]) for i in items)
    bad = sum(1 for i in items for q in i["quotes"] if q["match"] == "not_found")
    print(f"quotes in responses: {nq}, not found in the revised manuscript: {bad}")
    if changes:
        print(f"real changes vs previous version: {len(changes)}; not mentioned in any response: {len(out['unannounced_candidates'])}")
    if a.annotated:
        print(f"annotated version: {out['annotated']['added_spans']} added / {out['annotated']['deleted_spans']} deleted spans; "
              f"marked text not in revised: {len(out['marked_not_in_revised'])}; "
              f"changes not marked: {len(out.get('changes_not_marked', []))}")


if __name__ == "__main__":
    main()
