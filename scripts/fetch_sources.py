#!/usr/bin/env python3
"""Phase 1 (source collection): save full text, or at least the abstract, for every reference.

Legal sources only: the user's own PDFs (--local-pdfs), OpenAlex open-access locations,
Semantic Scholar openAccessPdf, arXiv, Europe PMC, and the reference's own URL when it is the
document itself (government reports, standards). No paywall bypass, no CAPTCHA solving.

Every downloaded PDF is checked: it must start with %PDF and its first pages must contain the
reference's title words. A file that fails is quarantined, never used as evidence.

Writes into <review>/sources/:
  fulltext/<key>.pdf         the PDF (when found)
  abstracts/<key>.txt        the abstract (when found)
  text/<key>.json            {"kind": fulltext|abstract|webpage|none, "pages": [...], "origin": url}
                             page-split text that fact-check agents search and quote from
  manifest.json              one row per reference with what was obtained and from where
  _quarantine/               downloads that failed validation (kept for transparency)

Usage:
  python fetch_sources.py --review paper-review/main [--local-pdfs ~/papers/pdfs] [--only k1,k2]
  python fetch_sources.py --review paper-review/main --add key=https://author.site/paper.pdf
      (an agent found a legal copy by web search: download it with the same validation)
"""
import argparse
import concurrent.futures as cf
import html
import os
import re
import shutil
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import clean_doi, get_json, http_get, norm, now_iso, parse_reference_text, read_json, token_set_ratio, write_json  # noqa: E402

MIN_PDF_BYTES = 8000


def safe(key):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", key)


def pdf_pages(path):
    import pymupdf
    with pymupdf.open(path) as doc:
        return [p.get_text("text") for p in doc]


def title_in_pages(title, pages):
    if not title:
        return True
    head = " ".join(pages[:2])
    # first content words only: parsed titles can carry trailing notes ("presented at ...", "Technical Report")
    tw = [w for w in norm(re.split(r"[.?!]\s", title)[0]).split() if len(w) > 3][:12]
    if not tw:
        return True
    hn = norm(head)
    hit = sum(1 for w in tw if w in hn)
    return hit / len(tw) >= 0.7


def html_to_text(s):
    s = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def try_pdf(url, dest, title, log, quarantine):
    status, body = http_get(url, accept="application/pdf,*/*", binary=True, timeout=60, retries=2)
    if status != 200 or not body:
        log(f"pdf {url} -> HTTP {status}")
        return None
    if not body[:5].startswith(b"%PDF") or len(body) < MIN_PDF_BYTES:
        log(f"pdf {url} -> not a PDF (landing page or login wall)")
        return None
    tmp = dest + ".part"
    with open(tmp, "wb") as fh:
        fh.write(body)
    try:
        pages = pdf_pages(tmp)
    except Exception as e:  # corrupt pdf
        log(f"pdf {url} -> unreadable ({e})")
        os.remove(tmp)
        return None
    if not title_in_pages(title, pages):
        os.makedirs(quarantine, exist_ok=True)
        shutil.move(tmp, os.path.join(quarantine, os.path.basename(dest)))
        log(f"pdf {url} -> title not found on first pages: QUARANTINED (wrong paper?)")
        return None
    os.replace(tmp, dest)
    log(f"pdf {url} -> OK ({len(pages)} pages)")
    return pages


def local_match(ref, local_dir, log):
    """User-supplied PDFs: match by DOI in file name, key in file name, or title on first page."""
    if not local_dir or not os.path.isdir(local_dir):
        return None
    doi = (ref.get("doi") or "").replace("/", "_")
    for fn in os.listdir(local_dir):
        if not fn.lower().endswith(".pdf"):
            continue
        p = os.path.join(local_dir, fn)
        low = fn.lower()
        if (doi and doi.lower() in low.replace("/", "_")) or ref["ID"].lower() in low:
            return p
    for fn in os.listdir(local_dir):
        if fn.lower().endswith(".pdf"):
            p = os.path.join(local_dir, fn)
            try:
                if title_in_pages(ref.get("title"), pdf_pages(p)[:2]):
                    return p
            except Exception:
                continue
    return None


def gather(ref, auto, review, local_dir, extra_urls=()):
    key = ref["ID"]
    src = os.path.join(review, "sources")
    dest = os.path.join(src, "fulltext", safe(key) + ".pdf")
    quarantine = os.path.join(src, "_quarantine")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    row = {"key": key, "title": ref.get("title") or ref.get("raw", "")[:200], "doi": None, "kind": "none",
           "fulltext_pdf": None, "abstract_file": None, "origin": None, "abstract_origin": None, "log": []}
    log = row["log"].append
    recs = (auto or {}).get("records", [])
    doi = clean_doi(ref.get("doi") or "") or next((r.get("doi") for r in recs if r.get("doi")), None)
    row["doi"] = doi
    parsed = parse_reference_text(ref.get("raw", "")) if (ref.get("raw") and not ref.get("title")) else {}
    if parsed.get("url") and not ref.get("url"):
        ref = {**ref, "url": parsed["url"]}
    title = ref.get("title") or parsed.get("title") or next((r.get("title") for r in recs if r.get("title")), "")
    pages, abstract = None, None

    # 1. user's own PDFs
    lp = local_match({**ref, "doi": doi}, local_dir, log)
    if lp:
        shutil.copyfile(lp, dest)
        pages = pdf_pages(dest)
        row.update(origin="local:" + lp)
        log(f"local PDF {lp}")

    # 2. open-access locations
    urls = list(extra_urls)
    oa = next((r for r in recs if r.get("source") == "openalex"), None)
    if oa:
        urls += [u for u in [oa.get("oa_pdf")] + (oa.get("oa_locations") or []) if u]
        abstract = abstract or oa.get("abstract")
        if oa.get("abstract"):
            row["abstract_origin"] = "openalex"
    xr = next((r for r in recs if r.get("source") == "crossref"), None)
    if xr and xr.get("abstract") and not abstract:
        abstract, row["abstract_origin"] = xr["abstract"], "crossref"
    s2 = None
    if doi or title:
        ident = f"DOI:{doi}" if doi else None
        if ident:
            _, s2 = get_json(f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(ident)}"
                             "?fields=title,abstract,openAccessPdf,externalIds")
        if s2:
            if (s2.get("openAccessPdf") or {}).get("url"):
                urls.append(s2["openAccessPdf"]["url"])
            if s2.get("abstract") and not abstract:
                abstract, row["abstract_origin"] = s2["abstract"], "semanticscholar"
            arx = (s2.get("externalIds") or {}).get("ArXiv")
            if arx:
                urls.append(f"https://arxiv.org/pdf/{arx}")
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?$", ref.get("url") or "") or \
        re.search(r"(?:arXiv:|arxiv\.)\s*(\d{4}\.\d{4,5})", " ".join(str(v) for v in ref.values()), re.I)
    if m:
        urls.append(f"https://arxiv.org/pdf/{m.group(1)}")
    if doi:
        _, ep = get_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" +
                         urllib.parse.urlencode({"query": f'DOI:"{doi}"', "format": "json", "resultType": "core"}))
        hits = ((ep or {}).get("resultList") or {}).get("result", [])
        if hits:
            h = hits[0]
            if h.get("abstractText") and not abstract:
                abstract, row["abstract_origin"] = h["abstractText"], "europepmc"
            if h.get("pmcid") and h.get("isOpenAccess") == "Y":
                urls.append(f"https://europepmc.org/articles/{h['pmcid']}?pdf=render")
    if ref.get("url") and ref["url"] not in urls:
        urls.append(ref["url"])  # the document itself (reports, standards, web pages)

    seen = set()
    for u in urls:
        if pages or u in seen:
            break
        seen.add(u)
        got = try_pdf(u, dest, title, log, quarantine)
        if got:
            pages, row["origin"] = got, u

    # 3. web page as the source itself (only for the reference's own URL)
    if not pages and ref.get("url"):
        st, body = http_get(ref["url"], accept="text/html", timeout=40, retries=1)
        if st == 200 and body and "<html" in body[:2000].lower():
            txt = html_to_text(body)
            if len(txt) > 800 and title_in_pages(title, [txt[:6000]]):
                row["kind"], row["origin"] = "webpage", ref["url"]
                pages = [txt[i:i + 6000] for i in range(0, len(txt), 6000)]
                log(f"webpage {ref['url']} saved as text ({len(txt)} chars)")
            else:
                log(f"webpage {ref['url']} -> title not on page or too short")

    if abstract and len(re.sub(r"<[^>]+>", " ", abstract).split()) < 40:
        # registries sometimes return a citation string or a one-line blurb as the "abstract"
        log(f"abstract from {row['abstract_origin']} rejected: only {len(abstract.split())} words (not a real abstract)")
        abstract, row["abstract_origin"] = None, None
    if abstract:
        abstract = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", abstract)).strip()
        ap = os.path.join(src, "abstracts", safe(key) + ".txt")
        os.makedirs(os.path.dirname(ap), exist_ok=True)
        with open(ap, "w", encoding="utf-8") as fh:
            fh.write(abstract + "\n")
        row["abstract_file"] = os.path.relpath(ap, review)

    if pages and row["kind"] == "none":
        row["kind"] = "fulltext"
        row["fulltext_pdf"] = os.path.relpath(dest, review)
    elif not pages and abstract:
        row["kind"] = "abstract"
    text = {"key": key, "kind": row["kind"], "origin": row["origin"] or row["abstract_origin"],
            "pages": pages or ([abstract] if abstract else []), "abstract": abstract}
    write_json(os.path.join(src, "text", safe(key) + ".json"), text)
    row["n_pages"] = len(pages or [])
    return row


def write_download_list(review):
    """sources/TO_DOWNLOAD.md: papers with no full text, and the manuscript sentences that depend on each."""
    man = read_json(os.path.join(review, "sources", "manifest.json"))
    ms = read_json(os.path.join(review, "manuscript", "manuscript.json"))
    if not man or not ms:
        return []
    rows = []
    for r in man["rows"]:
        if r["kind"] in ("fulltext", "webpage"):
            continue
        sents = [s for s in ms["sentences"] if r["key"] in s["cites"]]
        rows.append({"key": r["key"], "title": r.get("title"), "doi": r.get("doi"), "have": r["kind"],
                     "link": f"https://doi.org/{r['doi']}" if r.get("doi") else None,
                     "claims": [{"file": s["file"], "line": s["line"], "text": s["text"][:220]} for s in sents]})
    rows.sort(key=lambda x: -len(x["claims"]))
    write_json(os.path.join(review, "sources", "to_download.json"), {"generated": now_iso(), "papers": rows})
    with open(os.path.join(review, "sources", "TO_DOWNLOAD.md"), "w", encoding="utf-8") as fh:
        fh.write("# Papers to download yourself\n\nNo legal full text could be fetched for these. Put the PDFs in one "
                 "folder and run `fetch_sources.py --review <review> --local-pdfs <folder>`; the claims listed under each "
                 "paper can then be checked against the full text instead of an abstract.\n\n")
        for x in rows:
            have = "only an abstract" if x["have"] == "abstract" else "nothing"
            fh.write(f"## {x['key']} ({have} available)\n\n")
            fh.write(f"{x['title'] or ''}  \n{x['link'] or 'no DOI: search by title'}\n\n")
            for c in x["claims"]:
                fh.write(f"- {c['file']}:{c['line']}: {c['text']}\n")
            fh.write("\n")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    ap.add_argument("--local-pdfs", help="folder of PDFs the user already has (used first)")
    ap.add_argument("--only")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--add", action="append", default=[], help="key=url of a legal copy found by hand")
    a = ap.parse_args()
    extra = {}
    for kv in a.add:
        k, _, u = kv.partition("=")
        extra.setdefault(k.strip(), []).append(u.strip())
    if extra:
        a.only = ",".join(extra)
    ms = read_json(os.path.join(a.review, "manuscript", "manuscript.json"))
    auto = {r["key"]: r for r in read_json(os.path.join(a.review, "refcheck", "auto_refs.json"), {"results": []})["results"]}
    refs = ms["references"]
    if a.only:
        keep = set(a.only.split(","))
        refs = [r for r in refs if r["ID"] in keep]
    rows = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for row in ex.map(lambda r: gather(r, auto.get(r["ID"]), a.review, a.local_pdfs, extra.get(r["ID"], ())), refs):
            rows.append(row)
            print(f"{row['kind']:<9} {row['key']:<32} {row['origin'] or row['abstract_origin'] or '-'}")
    mpath = os.path.join(a.review, "sources", "manifest.json")
    prev = read_json(mpath, {"rows": []}) if a.only else {"rows": []}
    merged = {r["key"]: r for r in prev["rows"]}
    merged.update({r["key"]: r for r in rows})
    allrows = list(merged.values())
    counts = {k: sum(1 for r in allrows if r["kind"] == k) for k in ("fulltext", "webpage", "abstract", "none")}
    write_json(mpath, {"generated": now_iso(), "counts": counts, "rows": allrows})
    print("summary:", counts)
    todo = write_download_list(a.review)
    if todo:
        print(f"{len(todo)} papers to download by hand: see sources/TO_DOWNLOAD.md")
    if counts["none"]:
        print("NO TEXT FOR:", ", ".join(r["key"] for r in allrows if r["kind"] == "none"),
              "\n-> claims citing these cannot be fact-checked until the user supplies the PDF (--local-pdfs).")


if __name__ == "__main__":
    main()
