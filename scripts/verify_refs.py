#!/usr/bin/env python3
"""Phase 1 (mechanical part): look up every reference in Crossref + OpenAlex and compare fields.

This script does NOT decide the final verdict. It gathers registry records and flags field
differences so the reference-check agents can adjudicate each entry against real records.
Nothing here relies on model memory: every "found" value comes from an API response that is
saved next to the comparison (raw records in refcheck/records/<key>.json).

Usage:
  python verify_refs.py --review paper-review/main [--only key1,key2] [--workers 4]
Output:
  <review>/refcheck/auto_refs.json
"""
import argparse
import concurrent.futures as cf
import os
import re
import time
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import (bib_authors, clean_doi, family_key, get_json, http_get, norm, now_iso, require_network, parse_reference_text, read_json,  # noqa: E402
                    token_set_ratio, write_json)

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"


def crossref_record(item):
    if not item:
        return None
    dt = item.get("issued", {}).get("date-parts", [[None]])[0]
    pub = item.get("published-print", item.get("published-online", {})).get("date-parts", [[None]])[0]
    return {
        "source": "crossref",
        "doi": (item.get("DOI") or "").lower(),
        "title": (item.get("title") or [""])[0] + ((": " + item["subtitle"][0]) if item.get("subtitle") else ""),
        "authors": [{"family": a.get("family") or a.get("name", ""), "given": a.get("given", "")}
                    for a in item.get("author", [])],
        "year": dt[0] if dt else None,
        "print_year": pub[0] if pub else None,
        "journal": (item.get("container-title") or [""])[0],
        "volume": item.get("volume"),
        "issue": item.get("issue"),
        "pages": item.get("page") or item.get("article-number"),
        "type": item.get("type"),
        "publisher": item.get("publisher"),
        "url": item.get("URL"),
        "updates": [u.get("type") for u in item.get("update-to", [])] + \
                   [r for r in (item.get("relation") or {}).keys()],
        "abstract": re.sub(r"<[^>]+>", " ", item.get("abstract", "")).strip() or None,
    }


def openalex_record(w):
    if not w:
        return None
    bib = w.get("biblio") or {}
    pages = None
    if bib.get("first_page"):
        pages = bib["first_page"] + (f"-{bib['last_page']}" if bib.get("last_page") and bib["last_page"] != bib["first_page"] else "")
    src = ((w.get("primary_location") or {}).get("source") or {})
    abstract = None
    inv = w.get("abstract_inverted_index")
    if inv:
        pos = sorted((p, word) for word, ps in inv.items() for p in ps)
        abstract = " ".join(word for _, word in pos)
    authors = []
    for a in w.get("authorships", []):
        name = (a.get("author") or {}).get("display_name") or a.get("raw_author_name") or ""
        if "," in name:
            fam, _, giv = name.partition(",")
        else:
            parts = name.split()
            fam, giv = (parts[-1], " ".join(parts[:-1])) if parts else ("", "")
        authors.append({"family": fam.strip(), "given": giv.strip(), "display": name})
    return {
        "source": "openalex",
        "id": w.get("id"),
        "doi": clean_doi(w.get("doi") or ""),
        "title": w.get("title") or w.get("display_name") or "",
        "authors": authors,
        "year": w.get("publication_year"),
        "journal": src.get("display_name"),
        "volume": bib.get("volume"),
        "issue": bib.get("issue"),
        "pages": pages,
        "type": w.get("type"),
        "is_retracted": w.get("is_retracted"),
        "oa_status": (w.get("open_access") or {}).get("oa_status"),
        "oa_pdf": (w.get("best_oa_location") or {}).get("pdf_url"),
        "oa_locations": [l.get("pdf_url") for l in w.get("locations", []) if l.get("pdf_url")],
        "abstract": abstract,
    }


def lookup_doi(doi):
    status, js = get_json(f"{CROSSREF}/{urllib.parse.quote(doi)}")
    return status, crossref_record(js.get("message")) if js else None


def search_crossref(title, author):
    q = urllib.parse.urlencode({"query.bibliographic": f"{title} {author}".strip(), "rows": 5})
    _, js = get_json(f"{CROSSREF}?{q}")
    items = (js or {}).get("message", {}).get("items", [])
    return [crossref_record(i) for i in items]


FAILED = {}  # registry -> HTTP status, when a lookup could not be done (rate limit, outage)


def _oa(url):
    key, mail = os.environ.get("OPENALEX_API_KEY"), os.environ.get("OPENALEX_MAILTO")
    if key or mail:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in (("api_key", key), ("mailto", mail)) if v})
    status, js = get_json(url)
    if status in (0, 429) or status >= 500:
        FAILED["openalex"] = status
    return status, js


def lookup_openalex(doi=None, title=None):
    """Returns (records, ok). ok=False means the registry could not be asked (rate limit/outage), which is
    different from 'not found'."""
    if doi:
        st, js = _oa(f"{OPENALEX}/doi:{urllib.parse.quote(doi)}")
        if js:
            return [openalex_record(js)], True
        if st in (0, 429) or st >= 500:
            return [], False
    if title:
        q = urllib.parse.urlencode({"search": title[:250], "per_page": 5})
        st, js = _oa(f"{OPENALEX}?{q}")
        if st in (0, 429) or st >= 500:
            return [], False
        return [openalex_record(w) for w in (js or {}).get("results", [])], True
    return [], True


_S2_LOCK = __import__("threading").Lock()


def lookup_s2(title):
    """Semantic Scholar title search: second open registry, strong on conference and arXiv papers.
    Unauthenticated use allows about one request per second, so calls are serialised and paced."""
    with _S2_LOCK:
        time.sleep(1.2)
        return _lookup_s2(title)


def _lookup_s2(title):
    q = urllib.parse.urlencode({"query": title[:250], "limit": 5,
                                "fields": "title,year,venue,authors,externalIds,publicationVenue,isOpenAccess"})
    st, js = get_json(f"https://api.semanticscholar.org/graph/v1/paper/search?{q}")
    if st in (0, 429) or st >= 500:
        FAILED["semanticscholar"] = st
        return [], False
    out = []
    for w in (js or {}).get("data", []):
        authors = []
        for a in w.get("authors", []):
            parts = (a.get("name") or "").split()
            authors.append({"family": parts[-1] if parts else "", "given": " ".join(parts[:-1]), "display": a.get("name")})
        ext = w.get("externalIds") or {}
        out.append({"source": "semanticscholar", "doi": clean_doi(ext.get("DOI") or ""), "title": w.get("title") or "",
                    "authors": authors, "year": w.get("year"), "journal": w.get("venue") or (w.get("publicationVenue") or {}).get("name"),
                    "volume": None, "issue": None, "pages": None, "type": None, "arxiv": ext.get("ArXiv")})
    return out, True


def cited_fields(r):
    authors = r.get("_authors") or bib_authors(r.get("author", ""))
    if not r.get("title") and r.get("raw"):  # reference read from a document, not from BibTeX
        p = parse_reference_text(r["raw"])
        r = {**r, "title": p["title"], "year": r.get("year") or p["year"], "journal": p["venue"],
             "volume": p["volume"], "number": p["issue"], "pages": p["pages"],
             "url": r.get("url") or p["url"], "doi": r.get("doi") or p["doi"]}
        authors = authors or p["authors"]
    return {
        "key": r.get("ID"), "type": r.get("ENTRYTYPE"),
        "title": r.get("title") or "", "authors": authors,
        "year": r.get("year"), "journal": r.get("journal") or r.get("booktitle") or r.get("institution") or r.get("publisher"),
        "volume": r.get("volume"), "issue": r.get("number") or r.get("issue"),
        "pages": r.get("pages"), "doi": clean_doi(r.get("doi") or "") or None, "url": r.get("url"),
        "raw": r.get("raw"), "has_others": "others" in (r.get("author") or "").lower(),
    }


def page_tuple(p):
    nums = re.findall(r"[A-Za-z]*\d+[A-Za-z]*", str(p or ""))
    return nums


def compare(c, f):
    """Return list of issues: {field, severity, cited, found, note}."""
    issues = []

    def add(field, sev, note, cited=None, found=None):
        issues.append({"field": field, "severity": sev, "note": note, "cited": cited, "found": found})

    tr = token_set_ratio(c["title"], f.get("title"))
    if c["title"]:
        if tr < 0.8:
            add("title", "critical", f"Title words differ (overlap {tr:.0%}).", c["title"], f.get("title"))
        elif norm(c["title"]) != norm(f.get("title")):
            add("title", "minor", f"Small title difference (overlap {tr:.0%}). Check wording/subtitle.", c["title"], f.get("title"))

    cf_ = [family_key(a["family"]) for a in c["authors"] if not a.get("corporate")]
    ff = [family_key(a["family"]) for a in f.get("authors") or []]
    if cf_ and ff:
        if cf_[0] != ff[0] and cf_[0] not in ff[:1]:
            add("authors", "critical", "First author differs.", c["authors"][0]["raw"], f["authors"][0].get("display") or f["authors"][0]["family"])
        if len(cf_) < len(ff) and not c["has_others"]:
            missing = [a for a in ff if a not in cf_]
            add("authors", "critical", f"Author list has {len(cf_)} names; record has {len(ff)}. Missing: {', '.join(missing[:6])}",
                len(cf_), len(ff))
        elif len(cf_) > len(ff):
            add("authors", "major", f"Entry lists {len(cf_)} authors; record has {len(ff)}.", len(cf_), len(ff))
        common = [a for a in cf_ if a in ff]
        if common and [a for a in ff if a in common] != common:
            add("authors", "critical", "Author order differs from the record.", cf_, ff)
        unknown = [a for a in cf_ if a not in ff]
        if unknown and len(cf_) <= len(ff):
            add("authors", "major", f"Names not in record: {', '.join(unknown[:6])} (spelling or wrong person).", unknown, ff)

    cy, fy = str(c.get("year") or "").strip()[:4], str(f.get("year") or "")
    if cy and fy and cy != fy:
        py = str(f.get("print_year") or "")
        close = cy.isdigit() and fy.isdigit() and abs(int(cy) - int(fy)) <= 1
        sev = "major" if close else "critical"
        if py and py == cy:
            sev = "info"
        add("year", sev, f"Year {cy} vs record {fy}" + (f" (print year {py})" if py else "") + ".", cy, fy)

    for fld in ("volume", "issue"):
        cv, fv = str(c.get(fld) or "").strip(), str(f.get(fld) or "").strip()
        if cv and fv and norm(cv) != norm(fv):
            add(fld, "critical" if fld == "volume" else "major", f"{fld.title()} {cv} vs record {fv}.", cv, fv)
        elif fv and not cv and c["type"] in ("article", None, "unknown"):
            add(fld, "minor", f"{fld.title()} missing; record has {fv}.", None, fv)

    cp, fp = page_tuple(c.get("pages")), page_tuple(f.get("pages"))
    if cp and fp and cp != fp:
        try:
            diff = abs(int(re.sub(r"\D", "", cp[0])) - int(re.sub(r"\D", "", fp[0])))
        except ValueError:
            diff = 99
        add("pages", "critical" if diff >= 5 or len(cp) != len(fp) else "major", f"Pages {c.get('pages')} vs record {f.get('pages')}.",
            c.get("pages"), f.get("pages"))
    elif fp and not cp and c["type"] in ("article", "inproceedings", None, "unknown"):
        add("pages", "minor", f"Pages/article number missing; record has {f.get('pages')}.", None, f.get("pages"))

    if c.get("journal") and f.get("journal"):
        jr = token_set_ratio(c["journal"], f["journal"])
        a_, b_ = norm(c["journal"]), norm(f["journal"])
        if a_ in b_ or b_ in a_:
            jr = 1.0
        if "arxiv" in b_ and "arxiv" not in a_:
            add("venue", "major", "Registry record is the arXiv version; confirm the cited venue (and its pages) on the publisher site.",
                c["journal"], f["journal"])
        elif jr < 0.5:
            add("venue", "major", "Venue name differs (could be abbreviation; confirm).", c["journal"], f["journal"])
    return issues


def best_match(c, candidates):
    scored = []
    for f in candidates:
        if not f:
            continue
        s = token_set_ratio(c["title"], f.get("title"))
        if c["authors"] and f.get("authors") and not c["authors"][0].get("corporate"):
            if family_key(c["authors"][0]["family"]) == family_key(f["authors"][0]["family"]):
                s += 0.15
            else:
                s -= 0.25  # same title, different first author: often a review of the book, not the book
        book_like = {"book", "monograph", "edited-book", "reference-book", "book-chapter", "inbook", "incollection"}
        if c.get("type") in ("book", "inbook", "incollection") and f.get("type") and f["type"] not in book_like:
            s -= 0.3
        if c.get("year") and str(f.get("year")) == str(c["year"])[:4]:
            s += 0.05
        scored.append((s, f))
    scored.sort(key=lambda x: -x[0])
    return scored[0] if scored else (0, None)


def check_one(r, review):
    c = cited_fields(r)
    out = {"key": c["key"], "cited": c, "records": [], "issues": [], "lookup_log": []}
    log = out["lookup_log"].append
    xr = None
    if c.get("url") and not c["doi"] and not c["authors"]:
        # a web document (agency page, manual, report landing page): scholarly registries do not index it
        st, body = http_get(c["url"], accept="text/html,application/pdf", retries=2)
        log(f"web document: url {c['url'][:90]} -> HTTP {st}")
        if st != 200:
            out["issues"].append({"field": "url", "severity": "major", "note": f"URL did not load (HTTP {st}).",
                                  "cited": c["url"], "found": None})
        if re.search(r"utm_source=chatgpt|utm_source=openai", c["url"]):
            out["issues"].append({"field": "url", "severity": "minor",
                                  "note": "URL carries a ChatGPT tracking parameter (utm_source=chatgpt.com): the source was found "
                                          "through ChatGPT. Confirm the page says what the text claims, and remove the parameter.",
                                  "cited": c["url"], "found": None})
        out["needs_manual"] = "Web document: open the page and confirm title, issuing body, date and that it supports the citing text."
        sev = {i["severity"] for i in out["issues"]}
        out["auto_status"] = "needs_fix" if "critical" in sev else "check" if "major" in sev else "manual"
        write_json(os.path.join(review, "refcheck", "records", f"{re.sub(r'[^A-Za-z0-9_.-]', '_', c['key'])}.json"), out)
        return out
    if c["doi"]:
        status, xr = lookup_doi(c["doi"])
        log(f"crossref doi {c['doi']} -> HTTP {status}")
        if status == 404:
            # DataCite (Zenodo, arXiv DOIs, datasets)
            st2, dc = get_json(f"https://api.datacite.org/dois/{urllib.parse.quote(c['doi'])}")
            log(f"datacite doi -> HTTP {st2}")
            if dc and dc.get("data"):
                a = dc["data"]["attributes"]
                xr = {"source": "datacite", "doi": c["doi"], "title": (a.get("titles") or [{}])[0].get("title", ""),
                      "authors": [{"family": p.get("familyName") or p.get("name", ""), "given": p.get("givenName", "")}
                                  for p in a.get("creators", [])],
                      "year": a.get("publicationYear"), "journal": a.get("publisher"), "type": (a.get("types") or {}).get("resourceTypeGeneral")}
            else:
                st3, _ = http_get(f"https://doi.org/{c['doi']}", accept="text/html", retries=1)
                log(f"doi.org resolve -> HTTP {st3}")
                if st3 == 0:
                    FAILED["doi.org"] = 0
                    out["lookup_failed"] = sorted(set(out.get("lookup_failed", []) + ["doi.org"]))
                elif st3 not in (200, 301, 302, 303):
                    out["issues"].append({"field": "doi", "severity": "critical", "note": "DOI does not resolve (wrong DOI).",
                                          "cited": c["doi"], "found": None})
        if xr:
            out["records"].append(xr)
            if c["title"] and token_set_ratio(c["title"], xr["title"]) < 0.6:
                out["issues"].append({"field": "doi", "severity": "critical",
                                      "note": "DOI resolves to a different work (title mismatch).",
                                      "cited": c["title"], "found": xr["title"]})
                xr = None  # do not compare fields against the wrong paper
    if not xr and c["title"]:
        cands = search_crossref(c["title"], c["authors"][0]["family"] if c["authors"] else "")
        score, m = best_match(c, cands)
        log(f"crossref search best score {score:.2f}")
        if m and score >= 0.85:
            xr = m
            out["records"].append(m)
            if not c["doi"] and m.get("doi"):
                out["issues"].append({"field": "doi", "severity": "minor", "note": "No DOI in entry; registry has one.",
                                      "cited": None, "found": m["doi"]})
    oa, oa_ok = lookup_openalex(xr["doi"] if xr and xr.get("doi") else c["doi"], None if (xr or c["doi"]) else c["title"])
    if not oa_ok:
        log("openalex: LOOKUP FAILED (rate limit or outage) - not the same as 'not found'; rerun later")
        out["lookup_failed"] = sorted(set(out.get("lookup_failed", []) + ["openalex"]))
    score, oam = best_match(c, oa) if oa else (0, None)
    if oam and (xr or score >= 0.85):
        out["records"].append(oam)
        log(f"openalex match score {score:.2f}")
        if oam.get("is_retracted"):
            out["issues"].append({"field": "status", "severity": "critical", "note": "Work is flagged RETRACTED in OpenAlex.",
                                  "cited": None, "found": "retracted"})
    else:
        if oa_ok:
            log("openalex: no confident match")
        oam = None
    s2m = None
    if not xr and not oam and c["title"]:
        s2, s2_ok = lookup_s2(c["title"])
        sc, s2m = best_match(c, s2) if s2 else (0, None)
        if s2m and sc >= 0.85:
            out["records"].append(s2m)
            log(f"semanticscholar match score {sc:.2f}")
        else:
            s2m = None
            log("semanticscholar: " + ("LOOKUP FAILED (rate limit or outage)" if not s2_ok else "no confident match"))
            if not s2_ok:
                out["lookup_failed"] = sorted(set(out.get("lookup_failed", []) + ["semanticscholar"]))
    primary = xr or oam or s2m
    if primary:
        out["issues"] += compare(c, primary)
        if xr and any(u in ("retraction", "expression_of_concern") for u in (xr.get("updates") or [])):
            out["issues"].append({"field": "status", "severity": "critical", "note": "Crossref lists a retraction/concern notice.",
                                  "cited": None, "found": xr["updates"]})
        if xr and "is-preprint-of" in (xr.get("updates") or []):
            out["issues"].append({"field": "status", "severity": "major", "note": "Cited version is a preprint; a published version exists.",
                                  "cited": None, "found": "is-preprint-of"})
        # second source agreement
        if xr and oam:
            dis = [i for i in compare(c, oam) if i["severity"] == "critical" and i["field"] in ("title", "authors", "year")]
            if dis and not [i for i in out["issues"] if i["field"] == dis[0]["field"]]:
                out["issues"].append({"field": dis[0]["field"], "severity": "major",
                                      "note": "Crossref and OpenAlex disagree; check the publisher page. " + dis[0]["note"],
                                      "cited": dis[0]["cited"], "found": dis[0]["found"]})
    elif c.get("url"):
        st, _ = http_get(c["url"], accept="text/html,application/pdf", retries=2)
        log(f"url {c['url']} -> HTTP {st}")
        if st != 200:
            out["issues"].append({"field": "url", "severity": "major", "note": f"URL did not load (HTTP {st}).",
                                  "cited": c["url"], "found": None})
        out["needs_manual"] = "No registry record (report/webpage/book). Verify against the publisher or issuing body page."
    else:
        out["needs_manual"] = "Not found in Crossref/OpenAlex and no URL. Search the web/library catalog by hand."

    sev = {i["severity"] for i in out["issues"]}
    if "needs_manual" in out and out.get("lookup_failed"):
        out["needs_manual"] = ("Registry lookup FAILED (" + ", ".join(out["lookup_failed"]) + "): rerun verify_refs.py later "
                               "(or set OPENALEX_API_KEY / OPENALEX_MAILTO), then check by hand if still unmatched.")
    out["auto_status"] = ("lookup_failed" if out.get("lookup_failed") and not out["records"] else
                          "needs_fix" if "critical" in sev else
                          "check" if "major" in sev else
                          "manual" if "needs_manual" in out else
                          "likely_ok")
    write_json(os.path.join(review, "refcheck", "records", f"{re.sub(r'[^A-Za-z0-9_.-]', '_', c['key'])}.json"), out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    ap.add_argument("--only", help="comma-separated keys")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    require_network()
    ms = read_json(os.path.join(a.review, "manuscript", "manuscript.json"))
    refs = ms["references"]
    if a.only:
        keep = set(a.only.split(","))
        refs = [r for r in refs if r["ID"] in keep]
    results = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for res in ex.map(lambda r: check_one(r, a.review), refs):
            results.append(res)
            n_i = len([i for i in res["issues"] if i["severity"] in ("critical", "major")])
            print(f"{res['auto_status']:<10} {res['key']:<32} issues={n_i}")
    path = os.path.join(a.review, "refcheck", "auto_refs.json")
    prev = read_json(path, {"results": []}) if a.only else {"results": []}
    merged = {r["key"]: r for r in prev["results"]}
    merged.update({r["key"]: r for r in results})
    write_json(path, {"generated": now_iso(), "count": len(merged), "results": list(merged.values())})
    print(f"wrote {path} ({len(merged)} references)")
    if FAILED:
        print("WARNING: some registry lookups could not be done: " + ", ".join(f"{k} (HTTP {v})" for k, v in FAILED.items())
              + ". References marked 'lookup_failed' are NOT checked; rerun later or set OPENALEX_API_KEY / OPENALEX_MAILTO.")


if __name__ == "__main__":
    main()
