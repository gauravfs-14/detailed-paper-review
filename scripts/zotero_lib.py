#!/usr/bin/env python3
"""Zotero as the skill's paper library, through the Zotero desktop app (no Zotero API key needed).

Reads use Zotero's local API (http://localhost:23119/api/, Zotero 7+; enable it once in
Settings > Advanced > "Allow other applications on this computer to communicate with Zotero").
Writes use the desktop app's connector endpoints, the same ones the browser connector uses, so Zotero must
be open. The connector can create items, attach PDFs, and put new items in a collection with tags; it
cannot create collections or change items that already exist. So:

  - one collection (default "Detailed Paper Review", see config.json) is created automatically on first use;
  - a paper already in the library is reused, never duplicated, and never modified;
  - new items get metadata from the registry record the reference check verified (not the paper's own,
    possibly wrong, reference text), the PDF the review saved, and tags:
      detailed-paper-review, dpr:<review name>, dpr:fulltext (PDF attached), and dpr:verified (metadata from a
      registry record or confirmed by the agent) or dpr:needs-check (only the paper's reference text was available)

Commands:
  status                       Zotero installed / running / local API on / collection present
  find --doi D | --title T     look up a paper in the library (prints item key and PDF path)
  push --review RV [--dry-run] [--only k1,k2] add the review's verified references to the collection; writes RV/zotero.json
  tidy                         read-only report on the skill's collection: duplicates, missing fields, no PDF
"""
import argparse
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import clean_doi, http_get, load_config, norm, read_json, token_set_ratio, write_json  # noqa: E402

BASE = "http://localhost:23119"
LOCAL = BASE + "/api/users/0"
CONNECTOR_HEADERS = {"X-Zotero-Connector-API-Version": "3", "Content-Type": "application/json"}


def collection_name():
    return load_config().get("zotero_collection") or "Detailed Paper Review"


# ---------------------------------------------------------------- transport
def _post(path, data, headers=None, timeout=120):
    body = data if isinstance(data, (bytes, bytearray)) else json.dumps(data).encode("utf-8")
    hdrs = {"User-Agent": "detailed-paper-review/1.1"}
    hdrs.update(CONNECTOR_HEADERS)
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(BASE + path, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw and raw[:1] in b"[{" else raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def _get(path):
    st, body = http_get(LOCAL + path, timeout=20, retries=1)
    try:
        return st, json.loads(body) if st == 200 and body else body
    except ValueError:
        return st, body


def installed():
    return any(os.path.exists(p) for p in ("/Applications/Zotero.app", os.path.expanduser("~/Applications/Zotero.app"),
                                           "/usr/lib/zotero", "/opt/zotero")) or bool(shutil.which("zotero"))


def running():
    st, _ = http_get(BASE + "/connector/ping", accept="*/*", timeout=5, retries=1)
    return st == 200


def local_api_on():
    st, _ = _get("/collections?limit=1")
    return st == 200


def find_collection():
    st, js = _post("/connector/getSelectedCollection", {})
    if st != 200 or not isinstance(js, dict):
        return None, []
    targets = js.get("targets", [])
    want = collection_name().lower()
    hit = next((t for t in targets if t.get("name", "").lower() == want and str(t.get("id", "")).startswith("C")), None)
    return hit, targets


def ensure_collection():
    """Create the skill's collection at the top of My Library if it does not exist. The connector has no
    'create collection' endpoint, so this imports a one-collection Zotero RDF file (Zotero's own import path),
    after selecting My Library so the collection is not nested inside whatever the user had selected."""
    hit, targets = find_collection()
    if hit:
        return hit
    lib = next((t["id"] for t in targets if str(t.get("id", "")).startswith("L")), None)
    if not lib:
        return None
    sid = uuid.uuid4().hex
    if _post("/connector/saveItems", {"sessionID": sid, "uri": "", "items": []})[0] == 201:
        _post("/connector/updateSession", {"sessionID": sid, "target": lib, "tags": []})
    from xml.sax.saxutils import escape
    rdf = ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
           'xmlns:z="http://www.zotero.org/namespaces/export#" xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<z:Collection rdf:about="#collection_dpr"><dc:title>{escape(collection_name())}</dc:title></z:Collection>'
           '</rdf:RDF>')
    _post("/connector/import?session=" + uuid.uuid4().hex, rdf.encode("utf-8"), {"Content-Type": "application/rdf+xml"})
    hit, _ = find_collection()
    return hit


def status(quiet=False):
    s = {"installed": installed(), "running": False, "local_api": False, "collection": None,
         "collection_name": collection_name(), "files_editable": None}
    s["running"] = running()  # checked even if no install was found (e.g. a portable or custom install)
    if s["running"]:
        s["local_api"] = local_api_on()
        hit, _ = find_collection()
        if hit:
            s["collection"], s["files_editable"] = hit["id"], hit.get("filesEditable")
    todo = []
    if not s["installed"]:
        todo.append("Zotero is not installed. Install Zotero 7 or later from https://www.zotero.org/download/ , open it once, then rerun.")
    elif not s["running"]:
        todo.append("Zotero is installed but not open. Open the Zotero app, then rerun.")
    else:
        if not s["local_api"]:
            todo.append("Turn on Zotero's local API: Zotero Settings > Advanced > tick 'Allow other applications on "
                        "this computer to communicate with Zotero'.")
        if not s["collection"]:
            s["collection_missing"] = True  # created automatically on the first push (ensure_collection)
    s["ready"] = not todo
    s["todo"] = todo
    if not quiet:
        print(json.dumps(s, indent=1))
    return s


# ---------------------------------------------------------------- reading
def _item_doi(d):
    doi = d.get("DOI") or ""
    if not doi:
        m = re.search(r"^DOI:\s*(\S+)", d.get("extra", "") or "", re.M | re.I)
        doi = m.group(1) if m else ""
    return clean_doi(doi) if doi else None


def pdf_path(item_key):
    st, kids = _get(f"/items/{item_key}/children")
    if st != 200 or not isinstance(kids, list):
        return None
    for k in kids:
        d = k.get("data", {})
        if d.get("itemType") == "attachment" and d.get("contentType") == "application/pdf" \
                and d.get("linkMode") in ("imported_file", "imported_url", "linked_file"):
            st2, url = http_get(f"{LOCAL}/items/{d['key']}/file/view/url", accept="*/*", timeout=10, retries=1)
            if st2 == 200 and url.startswith("file://"):
                p = urllib.parse.unquote(urllib.parse.urlsplit(url.strip()).path)
                if os.path.exists(p):
                    return p
    return None


def find(doi=None, title=None, year=None):
    """An existing library item for this work, or None. DOI match first; else a near-identical title (and year)."""
    doi = clean_doi(doi) if doi else None
    cands = []
    for q, mode in ((doi, "everything"), (title, "titleCreatorYear")):
        if not q:
            continue
        st, js = _get("/items/top?" + urllib.parse.urlencode({"q": q[:200], "qmode": mode, "limit": 25}))
        if st == 200 and isinstance(js, list):
            cands += js
        if doi and cands:
            break
    for it in cands:
        d = it.get("data", {})
        if d.get("itemType") in ("attachment", "note", "annotation"):
            continue
        if doi and _item_doi(d) == doi:
            return {"key": d["key"], "title": d.get("title"), "doi": _item_doi(d), "match": "doi", "pdf": pdf_path(d["key"]),
                    "collections": d.get("collections", []), "tags": [t["tag"] for t in d.get("tags", [])]}
    if title:
        for it in cands:
            d = it.get("data", {})
            if d.get("itemType") in ("attachment", "note", "annotation"):
                continue
            same_title = norm(d.get("title")) == norm(title) or token_set_ratio(d.get("title"), title) >= 0.95
            y = re.search(r"\b(1[89]|20)\d\d\b", d.get("date", "") or "")
            if same_title and (not year or not y or abs(int(y.group(0)) - int(year)) <= 1):
                if doi and _item_doi(d) and _item_doi(d) != doi:
                    continue  # same title, different DOI: a different work (e.g. preprint vs article)
                return {"key": d["key"], "title": d.get("title"), "doi": _item_doi(d), "match": "title", "pdf": pdf_path(d["key"]),
                        "collections": d.get("collections", []), "tags": [t["tag"] for t in d.get("tags", [])]}
    return None


# ---------------------------------------------------------------- building items
CR_TYPES = {"journal-article": "journalArticle", "proceedings-article": "conferencePaper", "book": "book",
            "monograph": "book", "edited-book": "book", "book-chapter": "bookSection", "posted-content": "preprint",
            "report": "report", "dataset": "dataset", "dissertation": "thesis", "standard": "standard",
            "article": "journalArticle", "preprint": "preprint", "book-section": "bookSection"}
CONTAINER = {"journalArticle": "publicationTitle", "conferencePaper": "proceedingsTitle", "bookSection": "bookTitle",
             "preprint": "repository", "report": "institution", "thesis": "university"}


def _best_record(rec, cited):
    """The registry record that the reference check matched, or None."""
    for r in rec.get("records", []):
        if cited.get("doi") and r.get("doi") and clean_doi(r["doi"]) == clean_doi(cited["doi"]) \
                and token_set_ratio(r.get("title"), cited.get("title")) >= 0.6:
            return r
    for r in rec.get("records", []):
        if token_set_ratio(r.get("title"), cited.get("title")) >= 0.85:
            return r
    return None


ORG_WORDS = re.compile(r"\b(association|administration|department|organi[sz]ation|institute|agency|bureau|commission|"
                       r"council|office|foundation|society|university|federal|national|center|centre|board|ministry|"
                       r"authority|corporation|committee|program(?:me)?|service|group|inc|llc|ltd|government|"
                       r"world|nations|bank|fund)\b", re.I)


def _creators(authors):
    out = []
    for a in authors or []:
        if a.get("name"):
            out.append({"name": a["name"], "creatorType": "author"})
            continue
        fam, giv, raw = a.get("family") or a.get("display") or "", a.get("given") or "", a.get("raw") or ""
        whole = raw or (giv + " " + fam).strip()
        if whole and ORG_WORDS.search(whole) and "," not in raw:
            out.append({"name": whole, "creatorType": "author"})  # corporate author: never split into first/last
        elif giv:
            out.append({"firstName": giv, "lastName": fam, "creatorType": "author"})
        elif fam:
            out.append({"name": fam, "creatorType": "author"})
    return out


def build_item(key, rec, ref_item, pdf_rel, review_name):
    """Zotero item from, in order of trust: the registry record the check matched, the metadata the agent
    confirmed on the source page, or (last resort, tagged dpr:needs-check) the paper's own reference text."""
    cited = rec.get("cited", {})
    r = _best_record(rec, cited)
    meta = (ref_item or {}).get("metadata") or {}
    if r:
        origin, src = r.get("source", "registry"), r
        ztype = CR_TYPES.get((r.get("type") or "").lower()) or ("journalArticle" if r.get("journal") else "document")
        fields = {"title": r.get("title"), "authors": r.get("authors"), "date": r.get("print_year") or r.get("year"),
                  "container": r.get("journal"), "publisher": r.get("publisher"), "volume": r.get("volume"),
                  "issue": r.get("issue"), "pages": r.get("pages"), "doi": r.get("doi"), "url": r.get("url"),
                  "abstract": r.get("abstract")}
    elif meta.get("title"):
        origin, src = "metadata confirmed by the reference-check agent at " + (meta.get("source_url") or meta.get("url") or "the source page"), meta
        ztype = meta.get("type") or "document"
        fields = dict(meta)
    else:
        origin, src = "the paper's reference list (not confirmed against a record)", cited
        venue = cited.get("journal") or ""
        ztype = CR_TYPES.get((cited.get("type") or "").lower())
        if not ztype:
            ztype = ("report" if re.search(r"\breport\b|white paper|working paper", venue, re.I)
                     else "webpage" if cited.get("url") and not cited.get("doi") and not venue
                     else "journalArticle" if venue else "document")
        fields = {"title": cited.get("title"), "authors": cited.get("authors"), "date": cited.get("year"),
                  "container": None if ztype == "report" else venue, "volume": cited.get("volume"),
                  "issue": cited.get("issue"), "pages": cited.get("pages"), "doi": cited.get("doi"), "url": cited.get("url")}
        if ztype == "report":
            inst = re.sub(r"(?i)^\s*technical report\.?\s*", "", venue).strip(" .")
            fields["institution"] = inst.split(".")[0].strip() or None
    confirmed = not origin.startswith("the paper")
    item = {"id": key, "itemType": ztype, "title": fields.get("title") or key, "creators": _creators(fields.get("authors")),
            "date": str(fields.get("date") or ""), "url": fields.get("url") or "",
            "tags": [{"tag": "dpr:verified" if confirmed else "dpr:needs-check", "type": 1}]
                    + ([{"tag": "dpr:fulltext", "type": 1}] if pdf_rel else []),
            "extra": f"Citation Key: {key}\nFiled by detailed-paper-review ({review_name}); metadata from {origin}",
            "attachments": [], "notes": []}
    doi = fields.get("doi")
    if doi:
        if ztype in ("journalArticle", "conferencePaper", "preprint", "report", "book", "bookSection", "dataset",
                     "thesis", "standard", "computerProgram"):
            item["DOI"] = clean_doi(doi)
        else:
            item["extra"] += f"\nDOI: {clean_doi(doi)}"
    fld = CONTAINER.get(ztype) or {"webpage": "websiteTitle", "standard": "organization"}.get(ztype)
    if fld and fields.get("container"):
        item[fld] = fields["container"]
    if ztype == "report" and (fields.get("institution") or fields.get("publisher")):
        item["institution"] = fields.get("institution") or fields.get("publisher")
    if ztype == "report" and fields.get("number"):
        item["reportNumber"] = str(fields["number"])
    if ztype in ("book", "bookSection", "thesis") and fields.get("publisher"):
        item["publisher" if ztype != "thesis" else "university"] = fields["publisher"]
    for f in ("volume", "issue", "pages"):
        if fields.get(f) and ztype in ("journalArticle", "conferencePaper", "bookSection", "book", "report"):
            if f == "issue" and ztype != "journalArticle":
                continue
            if ztype == "report" and f != "pages":
                continue
            item[f] = str(fields[f])
    if fields.get("abstract"):
        item["abstractNote"] = fields["abstract"]
    return item, confirmed


# ---------------------------------------------------------------- push
def push(rv, dry_run=False, only=None):
    if not dry_run and running() and local_api_on():
        if not ensure_collection():
            sys.exit(f"Could not create the '{collection_name()}' collection; create it by hand in Zotero and rerun.")
    st = status(quiet=True)
    if not st["ready"] and not (dry_run and st["running"] and st["local_api"]):
        print("Zotero is not ready:\n- " + "\n- ".join(st["todo"]))
        sys.exit(3)
    ph = read_json(os.path.join(rv, "phases", "01-references.json"))
    if not ph:
        sys.exit("phases/01-references.json not found: run the reference check first")
    man = {r["key"]: r for r in (read_json(os.path.join(rv, "sources", "manifest.json"), {}) or {}).get("rows", [])}
    review_name = os.path.basename(os.path.normpath(rv))
    out, new = {"collection": st["collection_name"], "items": {}}, []
    for it in ph.get("items", []):
        key, verdict = it["key"], it.get("verdict")
        if only and key not in only:
            continue
        if verdict in ("unverifiable", "not_found", "fabricated") or not verdict:
            out["items"][key] = {"status": "skipped", "reason": f"reference verdict is '{verdict}': the work itself is not confirmed"}
            continue
        rec = read_json(os.path.join(rv, "refcheck", "records", re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json"), {}) or {}
        cited = rec.get("cited", {})
        best = _best_record(rec, cited) or {}
        hit = find(best.get("doi") or cited.get("doi"), best.get("title") or cited.get("title"), best.get("year") or cited.get("year"))
        if hit:
            out["items"][key] = {"status": "existing", "zotero_key": hit["key"], "match": hit["match"],
                                 "has_pdf": bool(hit["pdf"]), "select": f"zotero://select/library/items/{hit['key']}"}
            continue
        row = man.get(key, {})
        pdf_rel = row.get("fulltext_pdf") if row.get("kind") == "fulltext" else None
        item, from_registry = build_item(key, rec, it, pdf_rel, review_name)
        new.append((key, item, pdf_rel))
        out["items"][key] = {"status": "to_add", "metadata_from": "confirmed record" if from_registry else "reference list (tagged dpr:needs-check)",
                             "pdf": pdf_rel}
    if dry_run:
        print(json.dumps(out, indent=1))
        return out
    sid = None
    for i in range(0, len(new), 20):
        batch = new[i:i + 20]
        sid = uuid.uuid4().hex
        code, msg = _post("/connector/saveItems", {"sessionID": sid, "uri": "", "items": [b[1] for b in batch]})
        if code != 201:
            for key, _, _ in batch:
                out["items"][key] = {"status": "failed", "reason": f"saveItems HTTP {code}: {str(msg)[:200]}"}
            continue
        for key, item, pdf_rel in batch:
            out["items"][key]["status"] = "added"
            if pdf_rel and os.path.exists(os.path.join(rv, pdf_rel)):
                data = open(os.path.join(rv, pdf_rel), "rb").read()
                meta = {"sessionID": sid, "parentItemID": key, "title": "Full Text PDF", "url": item.get("url") or ""}
                c2, m2 = _post("/connector/saveAttachment", data, {"Content-Type": "application/pdf",
                                                                 "X-Metadata": json.dumps(meta), "Content-Length": str(len(data))})
                out["items"][key]["pdf_attached"] = c2 == 201
                if c2 != 201:
                    out["items"][key]["pdf_error"] = f"HTTP {c2}: {str(m2)[:200]}"
        c3, m3 = _post("/connector/updateSession", {"sessionID": sid, "target": st["collection"],
                                                    "tags": ["detailed-paper-review", f"dpr:{review_name}"]})
        if c3 != 200:
            for key, _, _ in batch:
                out["items"][key]["warning"] = f"added, but filing into the collection failed (HTTP {c3}); it is in the selected collection"
    # resolve the keys Zotero assigned
    for key, item, _ in new:
        if out["items"][key]["status"] == "added":
            hit = find(item.get("DOI"), item.get("title"), (item.get("date") or "")[:4] or None)
            if hit:
                out["items"][key].update(zotero_key=hit["key"], select=f"zotero://select/library/items/{hit['key']}")
            else:
                out["items"][key]["warning"] = "saved, but not found again by search; check Zotero"
    write_json(os.path.join(rv, "zotero.json"), out)
    from collections import Counter
    print("Zotero:", dict(Counter(v["status"] for v in out["items"].values())), "->", os.path.join(rv, "zotero.json"))
    return out


# ---------------------------------------------------------------- tidy (read-only)
def tidy():
    st = status(quiet=True)
    if not st["ready"]:
        print("Zotero is not ready:\n- " + "\n- ".join(st["todo"]))
        sys.exit(3)
    code, cols = _get("/collections?limit=100")
    col = next((c for c in (cols if isinstance(cols, list) else []) if c["data"]["name"].lower() == collection_name().lower()), None)
    if not col:
        sys.exit("collection not found through the local API")
    items, start = [], 0
    while True:
        code, page = _get(f"/collections/{col['key']}/items/top?limit=100&start={start}")
        if code != 200 or not page:
            break
        items += page
        start += len(page)
        if len(page) < 100:
            break
    by_doi, by_title, problems = {}, {}, []
    for it in items:
        d = it["data"]
        doi = _item_doi(d)
        if doi:
            by_doi.setdefault(doi, []).append(d["key"])
        by_title.setdefault(norm(d.get("title")), []).append(d["key"])
        miss = [f for f in ("title", "date") if not d.get(f)]
        if not d.get("creators"):
            miss.append("creators")
        if d.get("itemType") in ("journalArticle", "conferencePaper") and not doi:
            miss.append("DOI")
        if miss:
            problems.append({"key": d["key"], "title": d.get("title"), "missing": miss})
    dups = [v for v in list(by_doi.values()) + list(by_title.values()) if len(v) > 1]
    rep = {"collection": collection_name(), "items": len(items),
           "duplicates": [sorted(set(v)) for v in {tuple(sorted(set(v))) for v in dups}],
           "missing_fields": problems,
           "note": "Read-only report. Merge duplicates in Zotero (Duplicate Items) and fill missing fields by hand; "
                   "the connector cannot edit existing items."}
    print(json.dumps(rep, indent=1))
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "find", "push", "tidy", "create-collection"])
    ap.add_argument("--doi")
    ap.add_argument("--title")
    ap.add_argument("--review")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="comma-separated reference keys (e.g. for a first small test)")
    a = ap.parse_args()
    if a.cmd == "status":
        s = status()
        sys.exit(0 if s["ready"] else 3)
    if a.cmd == "create-collection":
        hit = ensure_collection()
        print(json.dumps(hit) if hit else "could not create the collection")
        sys.exit(0 if hit else 3)
    if a.cmd == "find":
        print(json.dumps(find(a.doi, a.title), indent=1))
    elif a.cmd == "push":
        if not a.review:
            sys.exit("--review is required")
        push(a.review, a.dry_run, set(a.only.split(",")) if a.only else None)
    elif a.cmd == "tidy":
        tidy()


if __name__ == "__main__":
    main()
