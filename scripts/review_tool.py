#!/usr/bin/env python3
"""Coverage and evidence tools that keep the review honest.

Subcommands
  plan-factcheck   split every citing sentence into batches (by section) for fact-check subagents
  verify-quotes    check that every evidence quote really exists in the saved source text;
                   locate it on the PDF page (word boxes) so the dashboard can highlight it
  merge-factcheck  merge batch outputs into phases/02-factcheck.json and compute real coverage
  coverage         print what is done / not done for every phase (exit 1 if anything is missing)
  plan-sections    write one batch per manuscript section (for acronym / editorial / consistency agents)
  merge-refs       merge work/refs/*.json from ref-checker agents into phases/01-references.json
  merge-review     merge work/review/R*.json from reviewer agents into phases/09-peer-review.json
  attach-second    attach second-checker verdicts (work/factcheck/second-*.json) to the batch results
  dedupe           group findings that describe the same problem across phases -> phases/_issues.json

Task plans for apps that run the review step by step (see pipeline.json). Each writes a plan file with
{"tasks": [{"id", "input", "output"}]}, paths relative to the review folder:
  plan-refs           groups of reference keys for ref-checker agents   -> work/refs/plan.json
  plan-second         flagged items plus a sample of supported ones for second checkers -> work/factcheck/second-plan.json
  plan-adjudication   items where the two checkers disagree             -> work/factcheck/adjudication-plan.json
  apply-adjudication  copy the decisions (work/factcheck/adjudication.json) into the batch results
  plan-redo           items whose quote was not found in the source, for a fresh fact checker -> work/factcheck/redo-plan.json
  apply-redo          replace those items in the batch results with the fresh verdicts
  apply-ref-list      add list-level reference findings (work/refs/list.json) to phases/01-references.json
  apply-synthesis     add the peer-review synthesis (work/review/synthesis.json) to phases/09-peer-review.json

The rule these tools enforce: a phase is "complete" only when the files prove it. An agent saying
"done" is never enough.
"""
import argparse
import difflib
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import norm, now_iso, read_json, write_json  # noqa: E402

PHASES = [
    ("01-references", "Reference check"),
    ("02-factcheck", "Fact check against sources"),
    ("02b-uncited-claims", "Uncited factual claims"),
    ("02c-literature", "Literature coverage"),
    ("02d-text-overlap", "Text copied from sources"),
    ("03-consistency", "Consistency"),
    ("03b-claim-map", "Claims mapped to evidence"),
    ("04-methods-stats", "Methods, statistics and numbers"),
    ("04b-missing-reporting", "Missing critical reporting"),
    ("04c-equations", "Equations"),
    ("05-acronyms", "Acronyms"),
    ("06-figures-tables", "Figures and tables"),
    ("07-crossrefs", "Cross-references"),
    ("08-editorial", "Editorial check"),
    ("09-peer-review", "Expert peer review"),
    ("R-revision", "Revision and response to reviewers"),
]
FACT_VERDICTS = {"supported", "partial", "not_supported", "contradicted", "cannot_verify"}


def safe(key):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", key)


def src_text(review, key):
    return read_json(os.path.join(review, "sources", "text", safe(key) + ".json"))


def ensure_txt(review, key):
    """Write sources/text/<key>.txt with page markers so agents can Read/Grep it."""
    js = src_text(review, key)
    if not js:
        return None, "none", 0
    p = os.path.join(review, "sources", "text", safe(key) + ".txt")
    jp = os.path.join(review, "sources", "text", safe(key) + ".json")
    if not os.path.exists(p) or os.path.getmtime(jp) > os.path.getmtime(p):  # refresh after --add
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f"SOURCE {key} | kind={js['kind']} | origin={js.get('origin')}\n")
            if js.get("abstract") and js["kind"] != "abstract":
                fh.write("=== ABSTRACT ===\n" + js["abstract"] + "\n")
            for i, pg in enumerate(js["pages"], 1):
                fh.write(f"\n=== PAGE {i} ===\n{pg}\n")
    return p, js["kind"], sum(len(x) for x in js["pages"])


# ------------------------------------------------------------------ plan-factcheck
def plan_factcheck(review, max_claims=15, max_chars=220000):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    citing = [s for s in ms["sentences"] if s["cites"]]
    bydoc = {}
    for s in citing:
        bydoc.setdefault(s["section"], []).append(s)
    batches = []
    for sec, sents in bydoc.items():
        cur, keys, chars = [], set(), 0
        for s in sents:
            new = [k for k in s["cites"] if k not in keys]
            add_chars = 0
            for k in new:
                _, _, n = ensure_txt(review, k)
                add_chars += n
            if cur and (len(cur) >= max_claims or chars + add_chars > max_chars):
                batches.append((sec, cur, sorted(keys)))
                cur, keys, chars = [], set(), 0
                add_chars = sum(ensure_txt(review, k)[2] for k in s["cites"])
            cur.append(s)
            keys.update(s["cites"])
            chars += add_chars
        if cur:
            batches.append((sec, cur, sorted(keys)))
    out_dir = os.path.join(review, "work", "factcheck")
    os.makedirs(out_dir, exist_ok=True)
    # replace old plans but never delete finished results (*.result.json)
    for f in glob.glob(os.path.join(out_dir, "batch-*.json")):
        if not f.endswith(".result.json"):
            os.remove(f)
    index = []
    for i, (sec, sents, keys) in enumerate(batches, 1):
        bid = f"batch-{i:02d}"
        sources = []
        for k in keys:
            p, kind, n = ensure_txt(review, k)
            sources.append({"key": k, "kind": kind, "text_file": os.path.relpath(p, review) if p else None, "chars": n})
        sec_title = next((s["title"] for s in ms["sections"] if s["id"] == sec), sec)
        write_json(os.path.join(out_dir, bid + ".json"), {
            "batch": bid, "section": sec, "section_title": sec_title,
            "output_file": f"work/factcheck/{bid}.result.json",
            "sentences": [{k: s[k] for k in ("id", "file", "line", "text", "raw", "cites")} for s in sents],
            "sources": sources,
        })
        index.append({"batch": bid, "section": sec_title, "claims": len(sents),
                      "citation_instances": sum(len(s["cites"]) for s in sents),
                      "sources": len(keys), "no_text": [s["key"] for s in sources if s["kind"] == "none"]})
    write_json(os.path.join(out_dir, "index.json"), {"generated": now_iso(), "batches": index,
                                                    "tasks": [{"id": b["batch"], "input": f"work/factcheck/{b['batch']}.json",
                                                               "output": f"work/factcheck/{b['batch']}.result.json"} for b in index],
                                                    "total_citing_sentences": len(citing),
                                                    "total_citation_instances": sum(len(s["cites"]) for s in citing)})
    for b in index:
        print(f"{b['batch']}  {b['claims']:>3} sentences  {b['citation_instances']:>3} citations  "
              f"{b['sources']:>2} sources  [{b['section']}]" + (f"  NO TEXT: {','.join(b['no_text'])}" if b["no_text"] else ""))
    print(f"{len(index)} batches, {len(citing)} citing sentences. One subagent per batch.")


# ------------------------------------------------------------------ verify-quotes
def tokens_with_spans(text):
    out = []
    # "re-\nsults" (line-break hyphenation) is one word
    for m in re.finditer(r"\S+-[ \t]*\n\s*\S+|\S+", text):
        t = norm(m.group(0))
        for piece in t.split():
            out.append((piece, m.start(), m.end()))
    return out


def locate(quote, text):
    """Find quote in text. Returns dict(match, score, start, end) on original text.
    A quote copied from a PDF may keep a line-break hyphen as "net- work"; that is joined before matching."""
    r = _locate(quote, text)
    if r["match"] != "exact" and re.search(r"\w-\s+\w", quote):
        r2 = _locate(re.sub(r"(\w)-\s+(\w)", r"\1\2", quote), text)
        if r2["match"] == "exact" or r2["score"] > r["score"]:
            return r2
    return r


def _locate(quote, text):
    q = norm(quote).split()
    if not q:
        return {"match": "not_found", "score": 0.0}
    toks = tokens_with_spans(text)
    words = [t[0] for t in toks]
    n = len(q)
    # exact token sequence
    for i in range(len(words) - n + 1):
        if words[i] == q[0] and words[i:i + n] == q:
            return {"match": "exact", "score": 1.0, "start": toks[i][1], "end": toks[i + n - 1][2]}
    sm = difflib.SequenceMatcher(None, words, q, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
    if not blocks:
        return {"match": "not_found", "score": 0.0}
    # best cluster of blocks within a window ~1.6x quote length
    best = (0, None, None)
    for bi, b in enumerate(blocks):
        start, matched, end = b.a, 0, b.a
        for b2 in blocks[bi:]:
            if b2.a + b2.size - start > n * 1.6 + 5:
                break
            matched += b2.size
            end = b2.a + b2.size
        if matched > best[0]:
            best = (matched, start, end)
    score = best[0] / n
    if score >= 0.85:
        return {"match": "close", "score": round(score, 3), "start": toks[best[1]][1], "end": toks[best[2] - 1][2]}
    return {"match": "not_found", "score": round(score, 3)}


def pdf_word_boxes(pdf_path, page_no, quote):
    """Return [x0,y0,x1,y1] boxes for the quote on a PDF page (1-based) plus page size."""
    import pymupdf
    with pymupdf.open(pdf_path) as doc:
        if page_no < 1 or page_no > len(doc):
            return None
        page = doc[page_no - 1]
        words = page.get_text("words")  # x0,y0,x1,y1,word,block,line,wno
        ntoks = []
        i = 0
        while i < len(words):
            w = words[i]
            text, boxes = w[4], [w]
            nxt = words[i + 1] if i + 1 < len(words) else None
            if text.endswith("-") and nxt and (nxt[5], nxt[6]) != (w[5], w[6]):
                text, boxes = text[:-1] + nxt[4], [w, nxt]  # hyphenated across lines
                i += 1
            for piece in norm(text).split():
                ntoks.append((piece, boxes))
            i += 1
        seq = [t[0] for t in ntoks]
        q = norm(quote).split()
        sm = difflib.SequenceMatcher(None, seq, q, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
        if not blocks:
            return None
        # take the densest cluster like locate()
        best = (0, 0)
        for bi, b in enumerate(blocks):
            matched, used = 0, []
            for b2 in blocks[bi:]:
                if b2.a + b2.size - b.a > len(q) * 1.6 + 5:
                    break
                matched += b2.size
                used.append(b2)
            if matched > best[0]:
                best = (matched, used)
        boxes = []
        for b in best[1]:
            for i in range(b.a, b.a + b.size):
                for w in ntoks[i][1]:
                    box = [round(w[0], 1), round(w[1], 1), round(w[2], 1), round(w[3], 1)]
                    if box not in boxes:
                        boxes.append(box)
        r = page.rect
        return {"boxes": merge_boxes(boxes), "page_w": r.width, "page_h": r.height}


def merge_boxes(boxes):
    """Merge word boxes on the same line into line boxes."""
    lines = []
    for b in sorted(boxes, key=lambda x: (round(x[1]), x[0])):
        if lines and abs(lines[-1][1] - b[1]) < 3 and b[0] - lines[-1][2] < 25:
            lines[-1][2] = max(lines[-1][2], b[2])
            lines[-1][3] = max(lines[-1][3], b[3])
        else:
            lines.append(list(b))
    return lines


def verify_evidence(review, ev):
    """Mutates and returns ev with match, page, context. Never trusts the agent's page number."""
    key = ev.get("source_key")
    js = src_text(review, key) if key else None
    ev["match"], ev["score"] = "not_found", 0.0
    if not js or not ev.get("quote"):
        ev["match_note"] = "no saved source text" if not js else "empty quote"
        return ev
    pages = js["pages"]
    order = list(range(len(pages)))
    hint = ev.get("page")
    if isinstance(hint, int) and 1 <= hint <= len(pages):
        order.remove(hint - 1)
        order.insert(0, hint - 1)
    best = None
    for i in order:
        r = locate(ev["quote"], pages[i])
        if r["match"] == "exact":
            best = (i, r)
            break
        if r["match"] == "close" and (not best or r["score"] > best[1]["score"]):
            best = (i, r)
    if js.get("abstract") and (not best or best[1]["match"] != "exact"):
        r = locate(ev["quote"], js["abstract"])
        if r["match"] != "not_found" and (not best or r["score"] > best[1]["score"]):
            best = (-1, r)
    if not best:
        partial = max((locate(ev["quote"], pg)["score"] for pg in pages), default=0.0)
        ev["score"] = partial
        ev["match_note"] = (f"quote not found in the saved source (best partial overlap {partial:.0%}); "
                            "the agent may have paraphrased or quoted from memory")
        return ev
    i, r = best
    text = js["abstract"] if i == -1 else pages[i]
    ev.update(match=r["match"], score=r["score"])
    ev["found_in"] = "abstract" if (i == -1 or js["kind"] == "abstract") else js["kind"]
    ev["page"] = None if i == -1 or js["kind"] != "fulltext" else i + 1
    a, b = r["start"], r["end"]
    flat = lambda t: re.sub(r"-\n(?=\w)", "", t).replace("\n", " ")  # noqa: E731  PDF line breaks -> spaces
    ev["context_before"] = re.sub(r"^\S*\s", "", flat(text[max(0, a - 320):a]), count=1) if a > 320 else flat(text[:a])
    ev["context_match"] = flat(text[a:b])
    ev["context_after"] = re.sub(r"\s\S*$", "", flat(text[b:b + 320]))
    if ev["page"] and js["kind"] == "fulltext":
        pdf = os.path.join(review, "sources", "fulltext", safe(key) + ".pdf")
        if os.path.exists(pdf):
            try:
                ev["pdf"] = os.path.relpath(pdf, review)
                ev["highlight"] = pdf_word_boxes(pdf, ev["page"], ev["context_match"])
            except Exception as e:  # pragma: no cover
                ev["highlight_error"] = str(e)
    return ev


def verify_quotes(review):
    path = os.path.join(review, "phases", "02-factcheck.json")
    ph = read_json(path)
    if not ph:
        sys.exit("phases/02-factcheck.json not found; run merge-factcheck first")
    bad = 0
    for it in ph.get("items", []):
        for ev in it.get("evidence", []):
            verify_evidence(review, ev)
        ok = [e for e in it.get("evidence", []) if e["match"] in ("exact", "close")]
        it["evidence_valid"] = bool(ok)
        if it["verdict"] in ("supported", "partial") and not ok:
            # the agent claimed support but the quote is not in the source: never pass it
            it["verdict_before_quote_check"] = it["verdict"]
            it["verdict"] = "cannot_verify"
            it["quote_check_failed"] = True
            bad += 1
    write_json(path, ph)
    n = len(ph.get("items", []))
    print(f"checked evidence for {n} claims; {bad} 'supported' verdicts downgraded because the quote was not in the source")


# ------------------------------------------------------------------ merge-factcheck
def merge_factcheck(review):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    idx = read_json(os.path.join(review, "work", "factcheck", "index.json"))
    if not idx:
        sys.exit("run plan-factcheck first")
    items, missing_batches = [], []
    for b in idx["batches"]:
        res = read_json(os.path.join(review, "work", "factcheck", b["batch"] + ".result.json"))
        if not res:
            missing_batches.append(b["batch"])
            continue
        items += res.get("items", [])
    citing = [s for s in ms["sentences"] if s["cites"]]
    have = {(it.get("sentence_id"), it.get("cite")) for it in items}
    missing = [{"sentence_id": s["id"], "cite": k, "file": s["file"], "line": s["line"], "text": s["text"]}
               for s in citing for k in s["cites"] if (s["id"], k) not in have]
    bad_verdicts = [it.get("id") for it in items if it.get("verdict") not in FACT_VERDICTS]
    unsecond = [it.get("id") for it in items
                if it.get("verdict") != "supported" and not (it.get("second_check") or {}).get("verdict")]
    total = sum(len(s["cites"]) for s in citing)
    checked = total - len(missing)
    status = "complete" if not missing and not missing_batches and not bad_verdicts and not unsecond else "incomplete"
    reasons = []
    if missing_batches:
        reasons.append(f"{len(missing_batches)} batch result file(s) missing: {', '.join(missing_batches)}")
    if missing:
        reasons.append(f"{len(missing)} sentence-citation pair(s) have no verdict")
    if bad_verdicts:
        reasons.append(f"{len(bad_verdicts)} item(s) have an invalid verdict value")
    if unsecond:
        reasons.append(f"{len(unsecond)} flagged item(s) have no independent second check yet")
    findings = []
    for it in items:
        if it.get("verdict") in ("not_supported", "contradicted", "partial", "cannot_verify"):
            sev = {"contradicted": "critical", "not_supported": "critical", "partial": "major", "cannot_verify": "major"}[it["verdict"]]
            sc = it.get("second_check") or {}
            if sc.get("verdict") == "supported" and it["verdict"] != "cannot_verify":
                sev = "minor"  # checkers disagree: keep visible, lower severity, show both
            findings.append({
                "id": "FC-" + it.get("id", "?"), "severity": sev,
                "title": f"{it['verdict'].replace('_', ' ').title()}: [{it.get('cite')}] {it.get('claim', '')[:90]}",
                "location": {"file": it.get("file"), "line": it.get("line"), "section": it.get("section")},
                "what": it.get("reasoning", ""), "fix": it.get("suggested_fix", ""), "claim_ref": it.get("id"),
            })
    old = read_json(os.path.join(review, "phases", "02-factcheck.json"), {})
    ph = {
        "phase": "02-factcheck", "title": "Fact check against sources", "status": status,
        "status_reason": "; ".join(reasons),
        "coverage": {"unit": "sentence-citation pairs", "total": total, "checked": checked,
                     "unverifiable": sum(1 for it in items if it.get("verdict") == "cannot_verify")},
        "summary": old.get("summary", ""),
        "findings": findings, "items": items, "missing": missing, "generated": now_iso(),
    }
    write_json(os.path.join(review, "phases", "02-factcheck.json"), ph)
    print(f"merged {len(items)} items; coverage {checked}/{total}; status={status}")
    for r in reasons:
        print("  NOT DONE:", r)


# ------------------------------------------------------------------ coverage
def coverage(review):
    """Same rules as the dashboard: coverage counts, minimum units, and code-backed calculations."""
    import build_dashboard  # lazy: build_dashboard imports this module
    exit_code = 0
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    manifest = read_json(os.path.join(review, "sources", "manifest.json"))
    for pid, title in PHASES:
        ph = read_json(os.path.join(review, "phases", pid + ".json"))
        if not ph and pid == "R-revision" and (read_json(os.path.join(review, "review.json"), {}) or {}).get("submission") != "revision":
            print(f"[SKIPPED   ] {pid:<22} {title}  (first submission)")
            continue
        if not ph:
            print(f"[NOT RUN   ] {pid:<22} {title}")
            exit_code = 1
            continue
        ph = build_dashboard.enforce_status(ph, ms, manifest, review)
        cov = ph.get("coverage") or {}
        st = ph.get("status", "?")
        if pid == "01-references" and ms:
            items = ph.get("items", [])
            keys = {i.get("key") for i in items if i.get("verdict")}
            miss = [r["ID"] for r in ms["references"] if r["ID"] not in keys]
            if miss:
                st = "incomplete"
                print(f"   references with no verdict: {', '.join(miss)}")
        if cov.get("total") is not None and cov.get("checked", 0) < cov["total"]:
            st = "incomplete"
        flag = {"complete": "DONE      ", "incomplete": "INCOMPLETE", "skipped": "SKIPPED   "}.get(st, st.upper()[:10].ljust(10))
        print(f"[{flag}] {pid:<22} {title}  {cov.get('checked', '-')}/{cov.get('total', '-')} {cov.get('unit', '')}"
              + (f"  ({ph.get('status_reason')})" if ph.get("status_reason") else ""))
        if st != "complete" and st != "skipped":
            exit_code = 1
    sys.exit(exit_code)


# ------------------------------------------------------------------ plan-sections
def plan_sections(review, max_words=2500):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    out_dir = os.path.join(review, "work", "sections")
    os.makedirs(out_dir, exist_ok=True)
    groups, cur, words = [], [], 0
    for sec in ms["sections"]:
        sents = [s for s in ms["sentences"] if s["section"] == sec["id"]]
        w = sum(len(s["text"].split()) for s in sents)
        if cur and words + w > max_words:
            groups.append(cur)
            cur, words = [], 0
        cur.append((sec, sents))
        words += w
    if cur:
        groups.append(cur)
    for i, g in enumerate(groups, 1):
        write_json(os.path.join(out_dir, f"part-{i:02d}.json"), {
            "part": f"part-{i:02d}", "sections": [s["title"] for s, _ in g],
            "sentences": [{"id": x["id"], "file": x["file"], "line": x["line"], "section": s["title"], "text": x["text"]}
                          for s, ss in g for x in ss]})
        print(f"part-{i:02d}: {', '.join(s['title'] for s, _ in g)}")
    words = sum(len(x["text"].split()) for x in ms["sentences"])
    write_json(os.path.join(out_dir, "plan.json"), {
        "generated": now_iso(), "words": words, "parts": len(groups),
        "tasks": [{"id": f"part-{i:02d}", "input": f"work/sections/part-{i:02d}.json"} for i in range(1, len(groups) + 1)]})


def attach_second(review):
    """Copy second-checker verdicts (work/factcheck/second-*.json) into the batch results as second_check,
    after verifying each second-check quote against the saved source like any other evidence."""
    sec = {}
    for f in sorted(glob.glob(os.path.join(review, "work", "factcheck", "second-*.json"))):
        if os.path.basename(f).startswith("second-input"):
            continue
        for it in (read_json(f) or {}).get("items", []):
            sec[it["id"]] = it
    n = dis = 0
    for f in glob.glob(os.path.join(review, "work", "factcheck", "batch-*.result.json")):
        d = read_json(f)
        changed = False
        for it in d.get("items", []):
            s2 = sec.get(it["id"])
            if not s2:
                continue
            ev = verify_evidence(review, {"source_key": it["cite"], "quote": s2.get("quote", ""), "page": s2.get("page")}) \
                if s2.get("quote") else {"match": "no quote"}
            agrees = s2.get("verdict") == it.get("verdict")
            old_adj = (it.get("second_check") or {}).get("adjudication")
            it["second_check"] = {"verdict": s2.get("verdict"), "agrees": agrees, "quote_match": ev["match"],
                                  "note": f"{s2.get('note', '')} Quote ({ev['match']}): \"{s2.get('quote', '')}\""}
            if old_adj:
                it["second_check"]["adjudication"] = old_adj
            n += 1
            dis += 0 if agrees else 1
            changed = True
            print(f"{it['id']:<8} {it['verdict']:<14} second: {s2.get('verdict'):<14} {'agree' if agrees else 'DISAGREE'}  quote {ev['match']}")
        if changed:
            write_json(f, d)
    print(f"attached {n} second checks; {dis} disagreement(s) need a decision by the main agent "
          "(add second_check.adjudication with the reason, then run merge-factcheck)")


def plan_refs(review, size=12):
    """Groups of reference keys (aliases share their original's verdict, so they are not checked twice)."""
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    keys = [r["ID"] for r in ms["references"] if not r.get("alias_of")]
    groups = [keys[i:i + size] for i in range(0, len(keys), size)]
    out_dir = os.path.join(review, "work", "refs")
    os.makedirs(out_dir, exist_ok=True)
    tasks = []
    for i, g in enumerate(groups, 1):
        gid = f"g{i:02d}"
        write_json(os.path.join(out_dir, f"{gid}.input.json"), {"group": gid, "keys": g, "output_file": f"work/refs/{gid}.json"})
        tasks.append({"id": gid, "input": f"work/refs/{gid}.input.json", "output": f"work/refs/{gid}.json", "keys": g})
    write_json(os.path.join(out_dir, "plan.json"), {"generated": now_iso(), "references": len(keys), "tasks": tasks})
    print(f"{len(tasks)} groups for {len(keys)} references")


def _batch_items(review):
    for f in sorted(glob.glob(os.path.join(review, "work", "factcheck", "batch-*.result.json"))):
        for it in (read_json(f) or {}).get("items", []):
            yield f, it


def plan_second(review, per_task=15):
    """Every item that is not supported, plus at least 10% (minimum 3) of supported ones, chosen by a stable
    hash so a rerun picks the same sample. The inputs leave out the first verdict, quote and reasoning."""
    import hashlib
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    sent = {s["id"]: s for s in ms["sentences"]}
    items = [it for _, it in _batch_items(review)]
    flagged = [it for it in items if it.get("verdict") != "supported"]
    supported = sorted((it for it in items if it.get("verdict") == "supported"),
                       key=lambda it: hashlib.sha1(str(it.get("id")).encode()).hexdigest())
    n_sample = min(len(supported), max(3, -(-len(supported) // 10)))
    # items checked in an earlier round keep their second check; only new ones (e.g. redone items) are sent
    chosen = [it for it in flagged + supported[:n_sample] if not (it.get("second_check") or {}).get("verdict")]
    out_dir = os.path.join(review, "work", "factcheck")
    for f in glob.glob(os.path.join(out_dir, "second-input-*.json")):
        os.remove(f)
    tasks = []
    for i in range(0, len(chosen), per_task):
        n = i // per_task + 1
        rows = []
        for it in chosen[i:i + per_task]:
            s = sent.get(it.get("sentence_id"), {})
            p, kind, _ = ensure_txt(review, it.get("cite"))
            rows.append({"id": it.get("id"), "sentence": s.get("text", ""), "claim": it.get("claim", ""), "cite": it.get("cite"),
                         "text_file": os.path.relpath(p, review) if p else None, "source_kind": kind})
        inp = f"work/factcheck/second-input-{n:02d}.json"
        write_json(os.path.join(review, inp), {"items": rows, "output_file": f"work/factcheck/second-{n:02d}.json"})
        tasks.append({"id": f"second-{n:02d}", "input": inp, "output": f"work/factcheck/second-{n:02d}.json"})
    write_json(os.path.join(out_dir, "second-plan.json"), {"generated": now_iso(), "flagged": len(flagged),
                                                          "sampled_supported": n_sample, "tasks": tasks})
    print(f"{len(chosen)} item(s) need a second check ({len(flagged)} flagged, {n_sample} supported in the sample), {len(tasks)} task(s)")


def plan_adjudication(review):
    """Items where the first and second checker disagree and no decision is recorded yet."""
    rows = []
    for _, it in _batch_items(review):
        sc = it.get("second_check") or {}
        if sc.get("verdict") and not sc.get("agrees") and not sc.get("adjudication"):
            rows.append({"id": it.get("id"), "cite": it.get("cite"), "claim": it.get("claim"), "sentence_id": it.get("sentence_id"),
                         "first": {"verdict": it.get("verdict"), "evidence": it.get("evidence", []), "reasoning": it.get("reasoning", "")},
                         "second": {"verdict": sc.get("verdict"), "note": sc.get("note", ""), "quote_match": sc.get("quote_match")}})
    out_dir = os.path.join(review, "work", "factcheck")
    tasks = []
    if rows:
        write_json(os.path.join(out_dir, "adjudication-input.json"), {"items": rows, "output_file": "work/factcheck/adjudication.json"})
        tasks.append({"id": "adjudication", "input": "work/factcheck/adjudication-input.json", "output": "work/factcheck/adjudication.json"})
    write_json(os.path.join(out_dir, "adjudication-plan.json"), {"generated": now_iso(), "disagreements": len(rows), "tasks": tasks})
    print(f"{len(rows)} disagreement(s) need a decision")


def apply_adjudication(review):
    """work/factcheck/adjudication.json: {"items": [{"id", "verdict", "reason"}]}. The decided verdict becomes the
    item's verdict (the first one is kept as first_verdict) and the reason is recorded as second_check.adjudication."""
    dec = {d["id"]: d for d in (read_json(os.path.join(review, "work", "factcheck", "adjudication.json")) or {}).get("items", [])}
    n = 0
    for f in sorted(glob.glob(os.path.join(review, "work", "factcheck", "batch-*.result.json"))):
        d = read_json(f)
        changed = False
        for it in d.get("items", []):
            x = dec.get(it.get("id"))
            if not x or not it.get("second_check") or x.get("verdict") not in FACT_VERDICTS:
                continue
            if x["verdict"] != it.get("verdict"):
                it.setdefault("first_verdict", it.get("verdict"))
                it["verdict"] = x["verdict"]
            it["second_check"]["adjudication"] = f"{x['verdict']}: {x.get('reason', '')}".strip()
            n += 1
            changed = True
        if changed:
            write_json(f, d)
    print(f"recorded {n} decision(s)")


def plan_redo(review, per_task=15):
    """Items 'supported' or 'partial' whose quote verify-quotes could not find, in batch-file shape, for a fresh agent."""
    ph = read_json(os.path.join(review, "phases", "02-factcheck.json")) or {}
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    sent = {s["id"]: s for s in ms["sentences"]}
    failed = [it for it in ph.get("items", []) if it.get("quote_check_failed")]
    out_dir = os.path.join(review, "work", "factcheck")
    for f in glob.glob(os.path.join(out_dir, "redo-*.json")):
        os.remove(f)
    tasks = []
    for i in range(0, len(failed), per_task):
        n = i // per_task + 1
        chunk = failed[i:i + per_task]
        keys = sorted({it["cite"] for it in chunk})
        sources = []
        for k in keys:
            p, kind, chars = ensure_txt(review, k)
            sources.append({"key": k, "kind": kind, "text_file": os.path.relpath(p, review) if p else None, "chars": chars})
        sents = []
        for it in chunk:  # one entry per (sentence, cite) so the agent re-checks only the failed pair
            s = sent.get(it.get("sentence_id"), {})
            sents.append({"id": s.get("id"), "file": s.get("file"), "line": s.get("line"), "text": s.get("text"),
                          "raw": s.get("raw"), "cites": [it["cite"]], "item_id": it.get("id")})
        bid = f"redo-{n:02d}"
        write_json(os.path.join(out_dir, bid + ".json"), {"batch": bid, "output_file": f"work/factcheck/{bid}.result.json",
                                                         "note": "Earlier quotes for these pairs were not found in the source. Check them afresh.",
                                                         "sentences": sents, "sources": sources})
        tasks.append({"id": bid, "input": f"work/factcheck/{bid}.json", "output": f"work/factcheck/{bid}.result.json"})
    write_json(os.path.join(out_dir, "redo-plan.json"), {"generated": now_iso(), "items": len(failed), "tasks": tasks})
    print(f"{len(failed)} item(s) to redo, {len(tasks)} task(s)")


def apply_redo(review):
    """Replace each redone (sentence_id, cite) pair in the batch results with the fresh verdict, keeping its id."""
    fresh = {}
    for f in sorted(glob.glob(os.path.join(review, "work", "factcheck", "redo-*.result.json"))):
        for it in (read_json(f) or {}).get("items", []):
            fresh[(it.get("sentence_id"), it.get("cite"))] = it
    n = 0
    for f in sorted(glob.glob(os.path.join(review, "work", "factcheck", "batch-*.result.json"))):
        d = read_json(f)
        changed = False
        for i, it in enumerate(d.get("items", [])):
            x = fresh.get((it.get("sentence_id"), it.get("cite")))
            if x:
                d["items"][i] = {**x, "id": it.get("id"), "redone": True}
                n += 1
                changed = True
        if changed:
            write_json(f, d)
    print(f"replaced {n} item(s) with fresh verdicts")


def merge_refs(review):
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    items, findings = {}, []
    for f in sorted(glob.glob(os.path.join(review, "work", "refs", "*.json"))):
        g = read_json(f)
        for it in g.get("items", []):
            items[it["key"]] = it
        findings += g.get("findings", [])
    # one source cited under several numbers ([1] [2] [5] ...): the alias shares the original's verdict
    for r in ms["references"]:
        if r.get("alias_of") and r["ID"] not in items and r["alias_of"] in items:
            items[r["ID"]] = {**items[r["alias_of"]], "key": r["ID"], "alias_of": r["alias_of"]}
    order = {r["ID"]: i for i, r in enumerate(ms["references"], 1)}
    for k, it in items.items():
        it.setdefault("number", order.get(k))
    rows = sorted(items.values(), key=lambda x: order.get(x["key"], 9999))
    missing = [r["ID"] for r in ms["references"] if r["ID"] not in items]
    old = read_json(os.path.join(review, "phases", "01-references.json"), {})
    extra = [f for f in old.get("findings", []) if f.get("id", "").startswith("REF-L")]  # list-level findings kept
    ph = {"phase": "01-references", "title": "Reference check",
          "status": "complete" if not missing else "incomplete",
          "status_reason": f"no verdict for: {', '.join(missing)}" if missing else "",
          "coverage": {"unit": "references", "total": len(ms["references"]), "checked": len(ms["references"]) - len(missing)},
          "summary": old.get("summary", ""), "items": rows, "findings": findings + extra, "generated": now_iso()}
    write_json(os.path.join(review, "phases", "01-references.json"), ph)
    print(f"merged {len(rows)} reference verdicts; coverage {ph['coverage']['checked']}/{ph['coverage']['total']}")
    if missing:
        print("  NOT DONE: no verdict for", ", ".join(missing))


def apply_ref_list(review):
    """work/refs/list.json: {"summary", "findings": [REF-L...]}. Replaces earlier list-level findings."""
    lst = read_json(os.path.join(review, "work", "refs", "list.json"))
    path = os.path.join(review, "phases", "01-references.json")
    ph = read_json(path)
    if not lst or not ph:
        sys.exit("need work/refs/list.json and phases/01-references.json (run merge-refs first)")
    extra = [f for f in lst.get("findings", []) if str(f.get("id", "")).startswith("REF-L")]
    ph["findings"] = [f for f in ph.get("findings", []) if not str(f.get("id", "")).startswith("REF-L")] + extra
    if lst.get("summary"):
        ph["summary"] = lst["summary"]
    write_json(path, ph)
    print(f"added {len(extra)} list-level finding(s)")


def apply_synthesis(review):
    """work/review/synthesis.json: {"summary", "synthesis", "findings": [PR-...]}. Written after every report is in."""
    syn = read_json(os.path.join(review, "work", "review", "synthesis.json"))
    path = os.path.join(review, "phases", "09-peer-review.json")
    ph = read_json(path)
    if not syn or not ph:
        sys.exit("need work/review/synthesis.json and phases/09-peer-review.json (run merge-review first)")
    ph["synthesis"] = syn.get("synthesis", "")
    ph["summary"] = syn.get("summary", ph.get("summary", ""))
    ph["findings"] = [f for f in syn.get("findings", []) if str(f.get("id", "")).startswith("PR-")]
    cov = ph.get("coverage") or {}
    ph["status"] = "complete" if ph["synthesis"] and cov.get("checked", 0) >= max(cov.get("total", 0), 1) else "incomplete"
    ph["status_reason"] = "" if ph["status"] == "complete" else (ph.get("status_reason") or "a reviewer report or the synthesis is missing")
    write_json(path, ph)
    print(f"synthesis added; status={ph['status']}")


def merge_review(review):
    revs = [read_json(f) for f in sorted(glob.glob(os.path.join(review, "work", "review", "R*.json")))]
    old = read_json(os.path.join(review, "phases", "09-peer-review.json"), {})
    ph = {"phase": "09-peer-review", "title": "Expert peer review", "status": old.get("status", "incomplete"),
          "coverage": {"unit": "reviewers", "total": max(len(revs), old.get("coverage", {}).get("total", 0)), "checked": len(revs)},
          "summary": old.get("summary", ""), "reviewers": revs, "synthesis": old.get("synthesis", ""),
          "findings": old.get("findings", []), "generated": now_iso()}
    if not ph["synthesis"]:
        ph["status"], ph["status_reason"] = "incomplete", "synthesis not written yet"
    write_json(os.path.join(review, "phases", "09-peer-review.json"), ph)
    print(f"merged {len(revs)} reviewer reports; status={ph['status']}")


def _toks(t):
    return {w for w in norm(t).split() if len(w) > 3}


def dedupe(review):
    """Group findings from all phases that describe the same underlying problem.

    Same issue_key -> same issue. Otherwise two findings merge when they point to the same file and line
    (within 2 lines) AND their titles share at least 40% of their content words, or when their titles share
    60%+ of content words and the same specific number. phases/_merge.json can force extra merges:
    {"merge": [["CON-002", "TAB-001"], ...]}. Result: phases/_issues.json (one entry per real problem)."""
    import json
    fs = []
    for pid, title in PHASES:
        ph = read_json(os.path.join(review, "phases", pid + ".json"))
        for f in (ph or {}).get("findings", []):
            fs.append({**f, "_phase": pid})
    parent = list(range(len(fs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    nums = [set(re.findall(r"\d+\.\d+|\d{3,}", f.get("title", "") + " " + f.get("what", ""))) for f in fs]
    toks = [_toks(f.get("title", "")) for f in fs]
    for i in range(len(fs)):
        for j in range(i + 1, len(fs)):
            a, b = fs[i], fs[j]
            if a.get("issue_key") and a.get("issue_key") == b.get("issue_key"):
                union(i, j)
                continue
            la, lb = a.get("location") or {}, b.get("location") or {}
            inter = len(toks[i] & toks[j]) / max(1, min(len(toks[i]), len(toks[j])))
            same_place = la.get("file") and la.get("file") == lb.get("file") and la.get("line") and lb.get("line") \
                and abs(int(la["line"]) - int(lb["line"])) <= 2
            if (same_place and inter >= 0.4) or (inter >= 0.6 and nums[i] & nums[j]):
                union(i, j)
    forced = read_json(os.path.join(review, "phases", "_merge.json"), {}).get("merge", [])
    idx = {f.get("id"): k for k, f in enumerate(fs)}
    for grp in forced:
        ks = [idx[g] for g in grp if g in idx]
        for k in ks[1:]:
            union(ks[0], k)
    groups = {}
    for k in range(len(fs)):
        groups.setdefault(find(k), []).append(k)
    sev = ["critical", "major", "minor", "info"]
    issues = []
    for ks in groups.values():
        members = sorted((fs[k] for k in ks), key=lambda f: sev.index(f.get("severity")) if f.get("severity") in sev else 9)
        lead = members[0]
        issues.append({"issue_id": f"I{len(issues) + 1:03d}", "severity": lead.get("severity"), "title": lead.get("title"),
                       "what": lead.get("what"), "fix": next((m.get("fix") for m in members if m.get("fix")), ""),
                       "issue_key": lead.get("issue_key"), "location": lead.get("location"),
                       "phases": sorted({m["_phase"] for m in members}),
                       "findings": [{"phase": m["_phase"], "id": m.get("id")} for m in members]})
    issues.sort(key=lambda i: (sev.index(i["severity"]) if i["severity"] in sev else 9, -len(i["findings"])))
    for n, i in enumerate(issues, 1):
        i["issue_id"] = f"I{n:03d}"
    write_json(os.path.join(review, "phases", "_issues.json"), {"generated": now_iso(), "findings": len(fs), "issues": issues})
    by = {s_: sum(1 for i in issues if i["severity"] == s_) for s_ in sev}
    print(f"{len(fs)} findings -> {len(issues)} distinct issues: {by}")
    for i in issues:
        if len(i["findings"]) > 1:
            print(f"  {i['issue_id']} [{i['severity']}] x{len(i['findings'])} {i['title'][:70]}  <- "
                  + ", ".join(f"{m['phase']}:{m['id']}" for m in i["findings"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan-factcheck", "verify-quotes", "merge-factcheck", "coverage", "plan-sections",
                                       "merge-refs", "merge-review", "dedupe", "attach-second", "plan-refs", "plan-second",
                                       "plan-adjudication", "apply-adjudication", "plan-redo", "apply-redo",
                                       "apply-ref-list", "apply-synthesis"])
    ap.add_argument("--review", required=True)
    ap.add_argument("--max-claims", type=int, default=15)
    a = ap.parse_args()
    if a.cmd == "plan-factcheck":
        plan_factcheck(a.review, a.max_claims)
    elif a.cmd == "verify-quotes":
        verify_quotes(a.review)
    elif a.cmd == "merge-factcheck":
        merge_factcheck(a.review)
    elif a.cmd == "coverage":
        coverage(a.review)
    elif a.cmd == "plan-sections":
        plan_sections(a.review)
    elif a.cmd == "merge-refs":
        merge_refs(a.review)
    elif a.cmd == "merge-review":
        merge_review(a.review)
    elif a.cmd == "dedupe":
        dedupe(a.review)
    elif a.cmd == "attach-second":
        attach_second(a.review)
    elif a.cmd == "plan-refs":
        plan_refs(a.review)
    elif a.cmd == "plan-second":
        plan_second(a.review)
    elif a.cmd == "plan-adjudication":
        plan_adjudication(a.review)
    elif a.cmd == "apply-adjudication":
        apply_adjudication(a.review)
    elif a.cmd == "plan-redo":
        plan_redo(a.review)
    elif a.cmd == "apply-redo":
        apply_redo(a.review)
    elif a.cmd == "apply-ref-list":
        apply_ref_list(a.review)
    elif a.cmd == "apply-synthesis":
        apply_synthesis(a.review)


if __name__ == "__main__":
    main()
