#!/usr/bin/env python3
"""Phase 2c (mechanical part): find possibly missing literature and profile reference age.

Searches OpenAlex (open scholarly index) for each query, twice: the most relevant works overall, and the most
relevant from the last few years (title and abstract match). Every candidate comes with its registry record (DOI, title, year, venue, citation count)
and is marked as already cited or not. Agents decide relevance from the candidate's abstract and the
manuscript; nothing here is a verdict.

  python lit_search.py --review $RV --query "pedestrian crash news framing" --query "news frame classification transformer"
  python lit_search.py --review $RV            # no --query: uses the manuscript title

Output: work/literature_auto.json  {"age_profile": {...}, "queries": [{"query", "top_cited": [...], "recent": [...]}]}
"""
import argparse
import os
import re
import statistics
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import clean_doi, get_json, norm, now_iso, read_json, token_set_ratio, write_json  # noqa: E402

OPENALEX = "https://api.openalex.org/works"


def abstract_of(w):
    inv = w.get("abstract_inverted_index")
    if not inv:
        return None
    pos = sorted((p, word) for word, ps in inv.items() for p in ps)
    return " ".join(word for _, word in pos)


def search(query, since=None, n=15):
    """Most relevant works whose title or abstract match the query (OpenAlex relevance ranking)."""
    filt = f"title_and_abstract.search:{query}"
    if since:
        filt += f",from_publication_date:{since}-01-01"
    params = {"filter": filt, "per_page": n, "sort": "relevance_score:desc"}
    st, js = get_json(f"{OPENALEX}?{urllib.parse.urlencode(params)}")
    if st in (0, 429) or st >= 500:
        print(f"WARNING: OpenAlex search failed (HTTP {st}); results for '{query[:50]}' are missing, not empty. Rerun later.")
    out = []
    for w in (js or {}).get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {})
        out.append({"doi": clean_doi(w.get("doi") or ""), "title": w.get("title"), "year": w.get("publication_year"),
                    "venue": src.get("display_name"), "cited_by": w.get("cited_by_count"), "type": w.get("type"),
                    "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:6] if a.get("author")],
                    "is_retracted": w.get("is_retracted"), "openalex": w.get("id"), "abstract": abstract_of(w)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--review", required=True)
    ap.add_argument("--query", action="append", default=[])
    ap.add_argument("--recent-years", type=int, default=4)
    ap.add_argument("--year", type=int, default=int(time.strftime("%Y")), help="submission year for age profile")
    a = ap.parse_args()
    ms = read_json(os.path.join(a.review, "manuscript", "manuscript.json"))
    refs = ms["references"]
    cited_dois = {clean_doi(r.get("doi") or "") for r in refs} - {None, ""}
    cited_titles = [r.get("title") or r.get("raw") or "" for r in refs]

    years = []
    for r in refs:
        m = re.search(r"(19|20)\d\d", str(r.get("year") or r.get("raw") or ""))
        if m:
            years.append(int(m.group(0)))
    profile = {}
    if years:
        ages = [a.year - y for y in years]
        profile = {"n_with_year": len(years), "n_references": len(refs), "oldest": min(years), "newest": max(years),
                   "median_year": statistics.median(years), "median_age_years": statistics.median(ages),
                   "share_last_5_years": round(sum(1 for x in ages if x <= 5) / len(ages), 3),
                   "share_older_than_10_years": round(sum(1 for x in ages if x > 10) / len(ages), 3),
                   "by_year": {str(y): years.count(y) for y in sorted(set(years))}}

    queries = a.query or [re.sub(r"[^\w\s-]", " ", (read_json(os.path.join(a.review, "phases", "00-summary.json"), {}) or {})
                                 .get("paper_title") or next((s["text"] for s in ms["sentences"]), ""))[:200]]
    out = []
    for q in queries:
        res = {"query": q, "top_cited": search(q), "recent": search(q, since=a.year - a.recent_years)}
        for lst in (res["top_cited"], res["recent"]):
            for c in lst:
                c["already_cited"] = bool((c["doi"] and c["doi"] in cited_dois) or
                                          any(token_set_ratio(c["title"] or "", t) > 0.85 for t in cited_titles))
        out.append(res)
        n_new = sum(1 for c in res["top_cited"] + res["recent"] if not c["already_cited"])
        print(f"query '{q[:60]}': {len(res['top_cited'])} most relevant + {len(res['recent'])} recent, {n_new} not cited")
    write_json(os.path.join(a.review, "work", "literature_auto.json"),
               {"generated": now_iso(), "age_profile": profile, "queries": out})
    if profile:
        print(f"references: median year {profile['median_year']}, {profile['share_last_5_years']:.0%} from the last 5 years, "
              f"{profile['share_older_than_10_years']:.0%} older than 10 years")


if __name__ == "__main__":
    main()
