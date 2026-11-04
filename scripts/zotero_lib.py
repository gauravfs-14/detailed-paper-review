#!/usr/bin/env python3
"""Zotero as the skill's paper library, through the Zotero desktop app's local API (no zotero.org account).

Reads work in Zotero 7+; writes need Zotero 10+, whose local API can create collections, add items to them,
edit any item and upload PDFs. Turn the local API on once (Zotero Settings > Advanced > "Allow other
applications on this computer to communicate with Zotero"). The first write makes Zotero show an access
dialog; the user picks "Always Allow". The key Zotero returns is stored in the system keychain, never printed.

A push files every confirmed reference of a review:
  - finds the paper in the library (DOI first, then identical title and year) or creates it;
  - adds it to the skill's collection (default "Detailed Paper Review", created if missing), tag dpr:<review>;
  - cleans its metadata from the verified record: Crossref's citation data for DOIs (full date, page range,
    journal abbreviation, ISSN, language, abstract) or the metadata the reference-check agent confirmed on
    the source page, with authors' full given names where ORCID or OpenAlex has them (citation styles can
    abbreviate full names, but cannot expand initials). Empty fields are filled; a filled field is replaced
    only when it is substantively wrong (not for case or punctuation);
  - attaches the review's saved PDF when the item has none.
`clean` applies the same cleaning to every item already in the collection.
Every change is logged with the old value (RV/zotero.json or the clean log, and
~/.cache/detailed-paper-review/zotero-changes.jsonl), so `undo` restores it. References known only from the
paper's own reference text are never filed.

Settings for apps that run the skill (environment; see PIPELINE.md). Without them nothing changes:
  DPR_ZOTERO_COLLECTION      collection name (else config.json "zotero_collection", else "Detailed Paper Review")
  DPR_ZOTERO_EXISTING=link   papers already in the library are only linked: no collection, tag or field change
  DPR_ZOTERO_KEYCHAIN=0      use ZOTERO_LOCAL_API_KEY only; never read or store a key in the keychain
  DPR_ZOTERO=on|off          the app decided: off never writes (push, sync); on syncs even if setup skipped Zotero
Looking a paper up and creating it happens under a lock (zotero-write.lock in the cache folder), so two
programs filing at the same time cannot create the same paper twice.

Commands:
  status                                    Zotero version, local API, write access, collection
  find --doi D | --title T                  look up a paper (item key and PDF path)
  push --review RV [--dry-run] [--only k1,k2]
  sync --review RV                          file only what is new since the last push (runs automatically)
  clean [--dry-run]                         clean the metadata of every item in the collection
  undo --review RV | --log FILE             restore every field a push or clean changed
  tidy                                      read-only report: duplicates and missing fields in the collection
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dprlib import (CACHE_DIR, KEYCHAIN_SERVICE, clean_doi, get_json, http_get, load_config, norm,  # noqa: E402
                    read_json, token_set_ratio, write_json, zotero_lock)

BASE = (os.environ.get("DPR_ZOTERO_URL") or "http://localhost:23119").rstrip("/")  # override for tests
API = BASE + "/api/users/0"
APP_NAME = "Detailed Paper Review"
KEY_ACCOUNT = "zotero-local"
_STATE = {"server_id": None, "key": None, "fields": {}, "interactive": True}


class NoAccess(Exception):
    """Write access has not been granted yet, and this run may not show Zotero's dialog (background sync)."""


def collection_name():
    return (os.environ.get("DPR_ZOTERO_COLLECTION") or "").strip() or load_config().get("zotero_collection") \
        or "Detailed Paper Review"


def existing_mode():
    """What a push does with a paper the library already has. "update" (the default): file it in the collection,
    tag it and clean its metadata. "link": only record which item it is; the item is not changed at all."""
    return "link" if os.environ.get("DPR_ZOTERO_EXISTING", "").strip().lower() == "link" else "update"


def host_setting():
    """DPR_ZOTERO=on|off: an app running the skill (Lexiq Writer) decided whether this review files papers in Zotero.
    "off": push and sync never write. "on": sync runs even if this copy's own setup skipped Zotero. Unset: as usual."""
    v = os.environ.get("DPR_ZOTERO", "").strip().lower()
    return v if v in ("on", "off") else None


def use_keychain():
    """DPR_ZOTERO_KEYCHAIN=0: neither read nor store the Zotero key in the keychain (the caller passes
    ZOTERO_LOCAL_API_KEY instead), so a host app never uses or replaces the key of a separately installed copy."""
    return os.environ.get("DPR_ZOTERO_KEYCHAIN", "1").strip() not in ("0", "false", "no")


# ---------------------------------------------------------------- transport
def _request(method, url, body=None, headers=None, timeout=60):
    hdrs = {"User-Agent": "detailed-paper-review/1.2", "Zotero-API-Version": "3"}
    hdrs.update(headers or {})
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        elif hdrs.get("Content-Type") == "application/x-www-form-urlencoded":
            data = urllib.parse.urlencode(body).encode()
        else:
            data = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Zotero-Server-ID"):
                _STATE["server_id"] = r.headers["Zotero-Server-ID"]
            return r.status, r.headers, raw
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
    except Exception as e:
        return 0, {}, str(e).encode()


def get(path):
    st, _, raw = _request("GET", API + path if path.startswith("/") else path)
    try:
        return st, json.loads(raw) if st == 200 and raw[:1] in b"[{" else raw.decode("utf-8", "replace")
    except ValueError:
        return st, None


def _keychain_get():
    if not use_keychain():
        return None
    try:
        if sys.platform == "darwin":
            r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEY_ACCOUNT, "-w"],
                               capture_output=True, text=True, timeout=10)
        elif shutil.which("secret-tool"):
            r = subprocess.run(["secret-tool", "lookup", "service", KEYCHAIN_SERVICE, "account", KEY_ACCOUNT],
                               capture_output=True, text=True, timeout=10)
        else:
            return None
        return (r.stdout.strip() or None) if r.returncode == 0 else None
    except Exception:
        return None


def _keychain_put(key):
    """Store without putting the key on a command line (it would show in the process list)."""
    if not use_keychain():
        return
    try:
        if sys.platform == "darwin":
            cmd = f'add-generic-password -U -s "{KEYCHAIN_SERVICE}" -a "{KEY_ACCOUNT}" -w "{key}"\n'
            subprocess.run(["security", "-i"], input=cmd, text=True, capture_output=True, timeout=20)
        elif shutil.which("secret-tool"):
            subprocess.run(["secret-tool", "store", "--label", "detailed-paper-review zotero local API",
                            "service", KEYCHAIN_SERVICE, "account", KEY_ACCOUNT], input=key, text=True, timeout=20)
    except Exception:
        pass  # the key still works for this run


def _authorize():
    print(f"Zotero is asking for permission: in the Zotero window, click 'Always Allow' for '{APP_NAME}'.",
          file=sys.stderr, flush=True)
    if not _STATE["server_id"]:
        _request("GET", BASE + "/api/")
    st, _, raw = _request("POST", BASE + "/api/local/authorize", {"appName": APP_NAME},
                          {"Zotero-Server-ID": _STATE["server_id"] or ""}, timeout=300)
    if st != 200:
        sys.exit(f"Zotero did not grant write access (HTTP {st}). Nothing was changed.")
    js = json.loads(raw)
    _STATE["key"] = js["key"]
    if js.get("remember"):
        _keychain_put(js["key"])
    return js["key"]


def write(method, path, body=None, headers=None, form=False):
    """A write to the local API with server ID and key; asks for access once if needed."""
    if not _STATE["server_id"]:
        _request("GET", BASE + "/api/")
    _STATE["key"] = _STATE["key"] or os.environ.get("ZOTERO_LOCAL_API_KEY") or _keychain_get()
    st = None
    for attempt in range(2):
        if not _STATE["key"]:
            if not _STATE["interactive"]:
                raise NoAccess("Zotero write access not granted yet; run `zotero_lib.py push --review RV` once")
            if not use_keychain():
                sys.exit("Zotero refused the key this program was given (ZOTERO_LOCAL_API_KEY). Nothing was changed.")
            _authorize()
        hdrs = {"Zotero-Server-ID": _STATE["server_id"] or "", "Zotero-API-Key": _STATE["key"]}
        if form:
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        hdrs.update(headers or {})
        st, h, raw = _request(method, API + path if path.startswith("/") else path, body, hdrs)
        if st == 401 and attempt == 0:
            _STATE["key"] = None
            continue
        try:
            return st, json.loads(raw) if raw[:1] in b"[{" else raw.decode("utf-8", "replace")
        except ValueError:
            return st, raw.decode("utf-8", "replace")
    return st, None


# ---------------------------------------------------------------- status
def zotero_version():
    st, h, _ = _request("GET", BASE + "/connector/ping")
    v = (h or {}).get("X-Zotero-Version") if st == 200 else None
    if not v and os.path.exists("/Applications/Zotero.app/Contents/Info.plist"):
        r = subprocess.run(["defaults", "read", "/Applications/Zotero.app/Contents/Info", "CFBundleShortVersionString"],
                           capture_output=True, text=True)
        v = r.stdout.strip() or None
    return v, st == 200


def installed():
    return any(os.path.exists(p) for p in ("/Applications/Zotero.app", os.path.expanduser("~/Applications/Zotero.app"),
                                           "/usr/lib/zotero", "/opt/zotero")) or bool(shutil.which("zotero"))


def find_collection():
    st, cols = get("/collections")
    if st != 200 or not isinstance(cols, list):
        return None
    want = collection_name().lower()
    return next((c for c in cols if c["data"]["name"].lower() == want and not c["data"].get("parentCollection")), None)


def status(quiet=False):
    ver, running = zotero_version()
    s = {"installed": installed(), "running": running, "version": ver, "local_api": False, "writable": False,
         "collection": None, "collection_name": collection_name()}
    if running:
        st, h, _ = _request("GET", BASE + "/api/")
        s["local_api"] = st == 200
        s["writable"] = s["local_api"] and bool((h or {}).get("Zotero-Server-ID"))
        c = find_collection() if s["local_api"] else None
        s["collection"] = c["key"] if c else None
    todo = []
    if not s["installed"] and not running:
        todo.append("Install Zotero 10 or later from https://www.zotero.org/download/ , open it, then rerun.")
    elif not running:
        todo.append("Open the Zotero app, then rerun.")
    elif not s["local_api"]:
        todo.append("Turn on Zotero's local API: Settings > Advanced > tick 'Allow other applications on this "
                    "computer to communicate with Zotero'.")
    elif not s["writable"]:
        todo.append(f"Zotero {ver or ''} can be read but not edited. Update to Zotero 10 or later "
                    "(Help > Check for Updates) so the skill can file and clean papers.")
    s["readable"] = s["local_api"]
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


def pdf_attachment(item_key):
    st, kids = get(f"/items/{item_key}/children")
    for k in (kids if st == 200 and isinstance(kids, list) else []):
        d = k.get("data", {})
        if d.get("itemType") == "attachment" and d.get("contentType") == "application/pdf" \
                and d.get("linkMode") in ("imported_file", "imported_url", "linked_file"):
            st2, _, url = _request("GET", f"{API}/items/{d['key']}/file/view/url")
            url = url.decode("utf-8", "replace").strip() if st2 == 200 else ""
            if url.startswith("file://"):
                p = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
                if os.path.exists(p):
                    return d["key"], p
            return d["key"], None
    return None, None


def find(doi=None, title=None, year=None):
    """An existing library item for this work, or None. DOI match first; else an identical title (and year)."""
    doi = clean_doi(doi) if doi else None
    cands = []
    for q, mode in ((doi, "everything"), (title, "titleCreatorYear")):
        if not q:
            continue
        st, js = get("/items/top?" + urllib.parse.urlencode({"q": q[:200], "qmode": mode}))
        if st == 200 and isinstance(js, list):
            cands += js
        if doi and cands:
            break
    pick = None
    for it in cands:
        d = it.get("data", {})
        if d.get("itemType") in ("attachment", "note", "annotation") or d.get("deleted"):
            continue
        if doi and _item_doi(d) == doi:
            pick = (it, "doi")
            break
    if not pick and title:
        for it in cands:
            d = it.get("data", {})
            if d.get("itemType") in ("attachment", "note", "annotation") or d.get("deleted"):
                continue
            y = re.search(r"\b(1[89]|20)\d\d\b", d.get("date", "") or "")
            same = norm(d.get("title")) == norm(title) or token_set_ratio(d.get("title"), title) >= 0.95
            if same and (not year or not y or abs(int(y.group(0)) - int(year)) <= 1) \
                    and not (doi and _item_doi(d) and _item_doi(d) != doi):
                pick = (it, "title")
                break
    if not pick:
        return None
    it, how = pick
    att, path = pdf_attachment(it["data"]["key"])
    return {"key": it["data"]["key"], "title": it["data"].get("title"), "doi": _item_doi(it["data"]), "match": how,
            "pdf": path, "pdf_attachment": att, "data": it["data"]}


# ---------------------------------------------------------------- full author names
def _initials(given):
    return [p[0].lower() for p in re.split(r"[\s.\-]+", unicodedata.normalize("NFKD", given or "")) if p and p[0].isalpha()]


def _is_abbrev(given):
    parts = [p for p in re.split(r"[\s.]+", given or "") if p]
    return not parts or all(len(p.replace("-", "")) <= 2 for p in parts)


def _consistent(abbrev, full):
    a, f = _initials(abbrev), _initials(full)
    return bool(a) and len(f) >= len(a) and f[:len(a)] == a and not _is_abbrev(full)


def _split_name(display, family):
    """Given name from 'Armitage, Peter 1924-2024' or 'Peter Armitage' when the family name matches."""
    s = re.sub(r"\b\d{4}(-\d{4})?\b|\b(prof|dr|phd|ma|msc|md)\b\.?", " ", display or "", flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    fam = norm(family)
    if not fam:
        return None
    if "," in s:
        last, first = s.split(",", 1)
        return first.strip() if norm(last) == fam else None
    words = s.split(" ")
    if len(words) >= 2 and norm(words[-1]) == fam:
        return " ".join(words[:-1])
    return None


def full_given_names(doi, creators, csl_authors=()):
    """Replace initials-only given names with full ones when a verified source has them: ORCID (when Crossref
    links the author to an iD), then OpenAlex's authorship for this work, then the OpenAlex author profile's
    name variants, used only if exactly one full name fits the surname and initials."""
    notes = []
    if not doi or not any(c.get("firstName") and _is_abbrev(c["firstName"]) for c in creators):
        return creators, notes
    orcids = {norm(a["family"]): a["ORCID"].rsplit("/", 1)[-1] for a in csl_authors or [] if a.get("ORCID") and a.get("family")}
    st, w = get_json(f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}")
    ships = (w or {}).get("authorships", []) if st == 200 else []
    for c in creators:
        fam, giv = c.get("lastName"), c.get("firstName")
        if not fam or not giv or not _is_abbrev(giv):
            continue
        found, src = None, None
        oid = orcids.get(norm(fam))
        if oid:
            s2, p = get_json(f"https://pub.orcid.org/v3.0/{oid}/person")
            nm = (p or {}).get("name") or {}
            g, f2 = (nm.get("given-names") or {}).get("value", ""), (nm.get("family-name") or {}).get("value", "")
            if s2 == 200 and norm(f2) == norm(fam) and _consistent(giv, g):
                found, src = g, f"ORCID {oid}"
        if not found:
            for sh in ships:
                cand = _split_name((sh.get("author") or {}).get("display_name"), fam)
                if cand and _consistent(giv, cand):
                    found, src = cand, "OpenAlex authorship"
                    break
        if not found:
            for sh in ships:
                au = sh.get("author") or {}
                if _split_name(au.get("display_name"), fam) is None:
                    continue
                aid = (au.get("id") or "").rsplit("/", 1)[-1]
                s3, prof = get_json(f"https://api.openalex.org/authors/{aid}")
                names = {(_split_name(n, fam) or "").strip() for n in (prof or {}).get("display_name_alternatives", [])}
                fits = {n for n in names if n and _consistent(giv, n)}
                longest = {n for n in fits if not any(m != n and norm(m).startswith(norm(n) + " ") for m in fits)}
                distinct = {norm(n) for n in longest}
                if len(distinct) == 1:
                    found = sorted(longest, key=lambda n: (not n.isupper(), len(n)))[-1]  # prefer proper case
                    found, src = _name_case(found), f"OpenAlex author profile {aid}"
                break
        if found:
            found = _name_case(found)
            notes.append(f"{giv} {fam} -> {found} {fam} ({src})")
            c["firstName"] = found
    return creators, notes


# ---------------------------------------------------------------- clean metadata
CSL_TYPES = {"article-journal": "journalArticle", "journal-article": "journalArticle", "paper-conference": "conferencePaper",
             "proceedings-article": "conferencePaper", "book": "book", "monograph": "book", "edited-book": "book",
             "chapter": "bookSection", "book-chapter": "bookSection", "report": "report", "thesis": "thesis",
             "dissertation": "thesis", "webpage": "webpage", "post-weblog": "blogPost", "dataset": "dataset",
             "posted-content": "preprint", "article": "preprint", "standard": "standard", "software": "computerProgram",
             "article-newspaper": "newspaperArticle", "article-magazine": "magazineArticle"}


def item_fields(item_type):
    if item_type not in _STATE["fields"]:
        st, js = get(BASE + f"/api/itemTypeFields?itemType={item_type}")
        _STATE["fields"][item_type] = {f["field"] for f in js} if st == 200 and isinstance(js, list) else set()
    return _STATE["fields"][item_type]


def _rich(s):
    """Keep Zotero's rich-text tags (<i>, <b>, <sub>, <sup>), drop other markup (JATS, MathML)."""
    if not s:
        return s
    s = re.sub(r"<(/?)(?:jats:|mml:)?(italic|i)>", r"<\1i>", s)
    s = re.sub(r"<(/?)(?:jats:)?(bold|b)>", r"<\1b>", s)
    s = re.sub(r"<(/?)(?:jats:)?(sub|sup)>", r"<\1\2>", s)
    s = re.sub(r"<(?!/?(?:i|b|sub|sup)>)[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"^(abstract|summary)\s*[:.]?\s+", "", s, flags=re.I)


def _name_case(n):
    if n and n.isupper() and len(n.replace(".", "").replace(" ", "")) > 2:
        return " ".join(w if re.fullmatch(r"[A-Z]\.?", w) else w.capitalize() for w in n.split(" "))
    return n


def _date(parts):
    p = (parts or {}).get("date-parts", [[None]])[0] if isinstance(parts, dict) else None
    if not p or not p[0]:
        return ""
    return "-".join([f"{int(p[0]):04d}"] + [f"{int(x):02d}" for x in p[1:3] if x])


def csl_for_doi(doi):
    """Crossref's citation data for a DOI (cached), else doi.org content negotiation (DataCite and others)."""
    st, js = get_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}/transform/application/vnd.citationstyles.csl+json")
    if st != 200 or not js:
        st, body = http_get(f"https://doi.org/{doi}", accept="application/vnd.citationstyles.csl+json", retries=2)
        try:
            js = json.loads(body) if st == 200 else None
        except ValueError:
            js = None
    return js


def _first(v):
    return (v[0] if v else "") if isinstance(v, list) else (v or "")


def from_csl(csl, records=()):
    ztype = CSL_TYPES.get((csl.get("type") or "").lower(), "journalArticle" if csl.get("container-title") else "document")
    title = _first(csl.get("title"))
    sub = _first(csl.get("subtitle"))
    if sub and sub.lower() not in title.lower():
        title = f"{title}: {sub}"
    ct, cts = _first(csl.get("container-title")), _first(csl.get("container-title-short"))
    creators = []
    for role in ("author", "editor"):
        for a in csl.get(role) or []:
            if a.get("literal") or (a.get("name") and not a.get("family")):
                creators.append({"name": a.get("literal") or a.get("name"), "creatorType": role})
            elif a.get("family"):
                creators.append({"firstName": _name_case(a.get("given", "")), "lastName": _name_case(a["family"]), "creatorType": role})
    pages = str(csl.get("page") or csl.get("article-number") or "").replace("–", "-")
    if pages and "-" not in pages and pages.isdigit():
        for r in records:  # Crossref sometimes has only the first page; another verified record may have the range
            rp = str(r.get("pages") or "").replace("–", "-").replace(" ", "")
            if re.fullmatch(rf"{re.escape(pages)}-\d+", rp):
                pages = rp
                break
    issn, isbn = csl.get("ISSN") or [], csl.get("ISBN") or []
    ev = csl.get("event")
    return {"itemType": ztype, "title": _rich(title), "creators": creators, "date": _date(csl.get("issued")),
            "publicationTitle": ct, "proceedingsTitle": ct, "bookTitle": ct,
            "journalAbbreviation": cts if cts and cts != ct else "", "volume": str(csl.get("volume") or ""),
            "issue": str(csl.get("issue") or ""), "pages": pages,
            "DOI": clean_doi(csl["DOI"]) if csl.get("DOI") else "",
            "ISSN": ", ".join(issn) if isinstance(issn, list) else issn,
            "ISBN": ", ".join(isbn) if isinstance(isbn, list) else isbn,
            "publisher": csl.get("publisher") or "", "institution": csl.get("publisher") or "",
            "place": csl.get("publisher-place") or "", "language": csl.get("language") or "",
            "abstractNote": _rich(csl.get("abstract") or ""),
            "conferenceName": csl.get("event-title") or (ev.get("name", "") if isinstance(ev, dict) else (ev or "")),
            "libraryCatalog": "DOI.org (Crossref)" if csl.get("source") == "Crossref" else "DOI.org", "url": ""}


def from_agent_metadata(m):
    ztype = m.get("type") or "document"
    creators = [{"name": a["name"], "creatorType": "author"} if a.get("name") else
                {"firstName": a.get("given", ""), "lastName": a.get("family", ""), "creatorType": "author"}
                for a in m.get("authors") or []]
    c = m.get("container") or ""
    return {"itemType": ztype, "title": m.get("title", ""), "creators": creators, "date": str(m.get("date") or ""),
            "publicationTitle": c, "proceedingsTitle": c, "bookTitle": c, "websiteTitle": c,
            "publisher": m.get("publisher") or "", "institution": m.get("institution") or m.get("publisher") or "",
            "reportNumber": m.get("number") or "", "number": m.get("number") or "", "volume": m.get("volume") or "",
            "issue": m.get("issue") or "", "pages": m.get("pages") or "", "DOI": clean_doi(m["doi"]) if m.get("doi") else "",
            "url": m.get("url") or "", "place": m.get("place") or "",
            "accessDate": datetime.date.today().isoformat() if ztype == "webpage" else ""}


def metadata_for_doi(doi, records=()):
    csl = csl_for_doi(doi)
    if not csl:
        return None, None, []
    fields = from_csl(csl, records)
    if fields["itemType"] == "journalArticle":
        fields["publisher"] = ""  # Crossref's "publisher" is often the depositor (e.g. JSTOR), not the journal's publisher
    fields["creators"], notes = full_given_names(doi, fields["creators"], csl.get("author"))
    return fields, f"Crossref citation data for {doi}", notes


def clean_metadata(rv, key, ref_item):
    """(fields, origin, name_notes) from the most trusted source, or (None, reason, [])."""
    rec = read_json(os.path.join(rv, "refcheck", "records", re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json"), {}) or {}
    cited, records = rec.get("cited", {}), rec.get("records", [])
    match = next((r for r in records if r.get("doi") and token_set_ratio(r.get("title"), cited.get("title")) >= 0.6
                  and (not cited.get("doi") or clean_doi(cited["doi"]) == clean_doi(r["doi"]))), None) or \
        next((r for r in records if r.get("doi") and token_set_ratio(r.get("title"), cited.get("title")) >= 0.85), None)
    if match:
        fields, origin, notes = metadata_for_doi(clean_doi(match["doi"]), records)
        if fields:
            return fields, origin, notes
    meta = (ref_item or {}).get("metadata") or {}
    if meta.get("title"):
        fields = from_agent_metadata(meta)
        notes = []
        if fields.get("DOI"):
            fields["creators"], notes = full_given_names(fields["DOI"], fields["creators"])
        return fields, "metadata confirmed by the reference-check agent at " + (meta.get("source_url") or meta.get("url") or "the source page"), notes
    return None, "no registry record and no agent-confirmed metadata: not filed (only the paper's own reference text is known)", []


def to_item(fields, key=None):
    """Keep only fields valid for the item type in this Zotero; drop empties."""
    valid = item_fields(fields["itemType"])
    item = {"itemType": fields["itemType"], "creators": fields.get("creators", [])}
    for k, v in fields.items():
        if k not in ("itemType", "creators") and v not in (None, "") and k in valid:
            item[k] = v
    if key and "citationKey" in valid:
        item["citationKey"] = key
    return item


# ---------------------------------------------------------------- comparing and editing
LEGACY_TAGS = {"detailed-paper-review", "dpr:verified", "dpr:fulltext", "dpr:needs-check"}


def _creators_better(old, new):
    """Replace the author list when names differ, or when the new one has fuller given names for the same people."""
    fam = lambda cs: [norm(c.get("lastName") or c.get("name")) for c in cs if c.get("creatorType", "author") == "author"]
    if fam(old) != fam(new):
        return True
    for o, n in zip([c for c in old if c.get("creatorType", "author") == "author"],
                    [c for c in new if c.get("creatorType", "author") == "author"]):
        og, ng = o.get("firstName") or "", n.get("firstName") or ""
        if ng and _is_abbrev(og) and not _is_abbrev(ng) and _consistent(og or ng, ng):
            return True
    return False


def _differs(field, old, new):
    if field == "date":
        yo, yn = re.search(r"\d{4}", old or ""), re.search(r"\d{4}", new or "")
        if yo and yn and yo.group(0) != yn.group(0):
            return True
        return len(re.sub(r"\D", "", new or "")) > len(re.sub(r"\D", "", old or ""))  # more precise date
    if field == "pages":
        o, n = norm(old), norm(new)
        return o.split(" ")[0] != n.split(" ")[0] or (" " not in o and " " in n)  # wrong, or range now known
    if field == "url":  # replace only a cut-off URL with the full one
        bare = lambda u: re.sub(r"^https?://(www\.)?", "", u or "").rstrip("/")
        return bool(old and new and bare(new).startswith(bare(old)) and len(bare(new)) > len(bare(old)))
    if field in ("abstractNote", "language", "libraryCatalog", "journalAbbreviation", "extra", "accessDate"):
        return False  # never overwrite these when the user has them
    return norm(old) != norm(new)


def plan_changes(existing, new_item, key, review_tag, collection_key):
    """Changes for an item already in the library: fill empties, fix substantive errors, file it."""
    ch = {}
    for f, v in new_item.items():
        if f in ("itemType", "citationKey", "collections", "tags"):
            continue
        old = existing.get(f)
        if f == "creators":
            if not old or _creators_better(old, v):
                ch[f] = (old, v)
        elif not old or _differs(f, old, v):
            ch[f] = (old, v)
    if new_item.get("citationKey") and not existing.get("citationKey") and key:
        ch["citationKey"] = (existing.get("citationKey", ""), key)
    if existing.get("url") and existing.get("DOI") and re.fullmatch(
            r"https?://(dx\.)?doi\.org/" + re.escape(existing["DOI"]), existing["url"], re.I):
        ch["url"] = (existing["url"], "")  # a DOI link in url makes many styles print the DOI twice
    if (existing.get("extra") or "").startswith("Filed by detailed-paper-review"):
        ch["extra"] = (existing["extra"], "")  # note left by an earlier version of this skill
    tags = [t for t in existing.get("tags", []) if t["tag"] not in LEGACY_TAGS]
    if review_tag and review_tag not in [t["tag"] for t in tags]:
        tags.append({"tag": review_tag})
    if tags != existing.get("tags", []):
        ch["tags"] = (existing.get("tags", []), tags)
    cols = existing.get("collections", [])
    if collection_key and collection_key not in cols:
        ch["collections"] = (cols, cols + [collection_key])
    return ch


def apply_changes(item_key, version, ch, run, source):
    body = {f: n for f, (o, n) in ch.items()}
    body["version"] = version
    st, r = write("PATCH", f"/items/{item_key}", body)
    if st == 204:
        _log_change({"run": run, "source": source, "item": item_key, "old": {f: o for f, (o, n) in ch.items()}})
        return None
    return f"HTTP {st}: {str(r)[:200]}"


def upload_pdf(parent_key, path):
    data = open(path, "rb").read()
    md5 = hashlib.md5(data).hexdigest()
    fname = os.path.basename(path)
    st, js = write("POST", "/items", [{"itemType": "attachment", "parentItem": parent_key, "linkMode": "imported_file",
                                       "title": "Full Text PDF", "contentType": "application/pdf", "filename": fname}])
    if st != 200 or not isinstance(js, dict) or not js.get("successful"):
        return None, f"create attachment HTTP {st}: {str(js)[:200]}"
    att = list(js["successful"].values())[0]["key"]
    st, auth = write("POST", f"/items/{att}/file", {"md5": md5, "filename": fname, "filesize": len(data),
                                                    "mtime": int(os.path.getmtime(path) * 1000)},
                     headers={"If-None-Match": "*"}, form=True)
    if st != 200 or not isinstance(auth, dict):
        return att, f"upload authorization HTTP {st}: {str(auth)[:200]}"
    if auth.get("exists"):
        return att, None
    st2, _, raw = _request("POST", auth["url"], (auth.get("prefix") or "").encode() + data + (auth.get("suffix") or "").encode(),
                           {"Content-Type": auth.get("contentType") or "application/pdf"})
    if st2 not in (200, 201):
        return att, f"upload HTTP {st2}: {raw[:200]!r}"
    st3, reg = write("POST", f"/items/{att}/file", {"upload": auth["uploadKey"]}, headers={"If-None-Match": "*"}, form=True)
    return att, (None if st3 == 204 else f"register upload HTTP {st3}: {str(reg)[:200]}")


def _log_change(entry):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, "zotero-changes.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- push
def ensure_collection():
    with zotero_lock():
        c = find_collection()
        if c:
            return c["key"]
        st, js = write("POST", "/collections", [{"name": collection_name()}])
    if st == 200 and isinstance(js, dict) and js.get("successful"):
        return list(js["successful"].values())[0]["key"]
    sys.exit(f"Could not create the '{collection_name()}' collection (HTTP {st}: {str(js)[:200]}).")


def _ready(dry_run):
    st = status(quiet=True)
    if not st["readable"] or (not dry_run and not st["writable"]):
        print("Zotero is not ready:\n- " + "\n- ".join(st["todo"]))
        sys.exit(3)
    return st


def push(rv, dry_run=False, only=None, interactive=True, quiet=False):
    if host_setting() == "off":
        sys.exit("Zotero is off for this review (DPR_ZOTERO=off).")
    _STATE["interactive"] = interactive
    st = _ready(dry_run)
    ph = read_json(os.path.join(rv, "phases", "01-references.json"))
    if not ph:
        sys.exit("phases/01-references.json not found: run the reference check first")
    man = {r["key"]: r for r in (read_json(os.path.join(rv, "sources", "manifest.json"), {}) or {}).get("rows", [])}
    review_tag = "dpr:" + os.path.basename(os.path.normpath(rv))
    prev = read_json(os.path.join(rv, "zotero.json"), {}) or {}
    col = (st["collection"] or "(created on the real run)") if dry_run else ensure_collection()
    run = datetime.datetime.now().isoformat(timespec="seconds")
    link_only = existing_mode() == "link"
    out = {"collection": collection_name(), "collection_key": col, "run": run, "dry_run": dry_run,
           "existing": existing_mode(), "items": {}}
    for it in ph.get("items", []):
        key, verdict = it["key"], it.get("verdict")
        if only and key not in only:
            continue
        if verdict in ("unverifiable", "not_found", "fabricated") or not verdict:
            out["items"][key] = {"status": "skipped", "reason": f"reference verdict '{verdict}': the work is not confirmed"}
            continue
        fields, origin, notes = clean_metadata(rv, key, it)
        if not fields:
            out["items"][key] = {"status": "skipped", "reason": origin}
            continue
        new_item = to_item(fields, key)
        row = man.get(key, {})
        pdf = os.path.join(rv, row["fulltext_pdf"]) if row.get("kind") == "fulltext" and row.get("fulltext_pdf") else None
        hit = None
        prev_key = ((prev.get("items") or {}).get(key) or {}).get("zotero_key")
        if prev_key:  # the item this reference was filed as before, even if its title has since been corrected
            s0, cur = get(f"/items/{prev_key}")
            if s0 == 200 and not cur["data"].get("deleted"):
                att, path = pdf_attachment(prev_key)
                hit = {"key": prev_key, "data": cur["data"], "match": "earlier push", "pdf": path, "pdf_attachment": att}
        with zotero_lock():  # no other program can file the same paper between this lookup and the create
            hit = hit or find(new_item.get("DOI"), new_item.get("title"), (new_item.get("date") or "")[:4] or None)
            rec = _file_one(hit, new_item, key, review_tag, st, col, dry_run, link_only, origin, notes, run, rv)
        if hit and not link_only:  # attach the saved PDF when the item has none (outside the lock: uploads are slow)
            if pdf and not hit["pdf_attachment"]:
                rec["pdf"] = "would attach" if dry_run else (upload_pdf(hit["key"], pdf)[1] or "attached")
            rec["has_pdf"] = bool(hit["pdf_attachment"]) or rec.get("pdf") == "attached"
        elif not hit and dry_run:
            rec["pdf"] = "would attach" if pdf else None
        elif not hit and rec["status"] == "added":
            if pdf:
                rec["pdf"] = upload_pdf(rec["zotero_key"], pdf)[1] or "attached"
            rec["has_pdf"] = rec.get("pdf") == "attached"
        if rec.get("zotero_key"):
            rec["select"] = f"zotero://select/library/items/{rec['zotero_key']}"
        old = (prev.get("items") or {}).get(key) or {}
        if "history" not in old and old.get("status") == "updated" and old.get("changes"):
            old["history"] = [{"run": prev.get("run"), "changes": old["changes"]}]  # records from before history existed
        rec["history"] = old.get("history", []) + ([{"run": run, "changes": rec["changes"]}]
                                                  if rec.get("status") == "updated" else [])
        out["items"][key] = rec
    if not dry_run:  # merge with earlier runs, so a partial or incremental push never drops what was filed before
        merged = dict(prev, collection=out["collection"], collection_key=col, run=run, dry_run=False)
        merged["items"] = {**(prev.get("items") or {}), **out["items"]}
        write_json(os.path.join(rv, "zotero.json"), merged)
    from collections import Counter
    if not quiet:
        print(json.dumps(out, indent=1, ensure_ascii=False) if dry_run else
              f"Zotero: {dict(Counter(v['status'] for v in out['items'].values()))} -> {os.path.join(rv, 'zotero.json')}")
    return out


CONFIRMED = lambda v: v and v not in ("unverifiable", "not_found", "fabricated")


def sync(rv, quiet=False):
    """Incremental push, safe to run any time (after downloads, after every dashboard build): files references
    that are new or newly confirmed, and attaches PDFs saved since the last push. Runs only after the review's
    first push, never shows Zotero's access dialog, and returns a one-line status."""
    if host_setting() == "off":
        return "Zotero: off for this review"
    prev = read_json(os.path.join(rv, "zotero.json"))
    if not prev:
        return "Zotero: not filed yet (the first push happens at the end of phase 1)"
    if host_setting() != "on" and "zotero" in set(load_config().get("skipped_setup", [])):
        return "Zotero: skipped by the user"
    st = status(quiet=True)
    if not st["writable"]:
        return "Zotero: not synced (" + "; ".join(st["todo"] or ["not writable"]) + ")"
    ph = read_json(os.path.join(rv, "phases", "01-references.json"), {}) or {}
    man = {r["key"]: r for r in (read_json(os.path.join(rv, "sources", "manifest.json"), {}) or {}).get("rows", [])}
    items = prev.get("items") or {}
    todo = []
    for it in ph.get("items", []):
        k, rec = it["key"], items.get(it["key"])
        if not CONFIRMED(it.get("verdict")):
            continue
        if rec is None or rec.get("status") in ("skipped", "add_failed", "update_failed"):
            if rec and rec.get("status") == "skipped" and not it.get("metadata") and "no registry record" in rec.get("reason", ""):
                continue  # still nothing confirmed to file
            todo.append(k)
        elif rec.get("status") != "linked" and man.get(k, {}).get("kind") == "fulltext" and not rec.get("has_pdf"):
            todo.append(k)
    if not todo:
        return "Zotero: up to date"
    try:
        out = push(rv, only=set(todo), interactive=False, quiet=True)
    except NoAccess as e:
        return f"Zotero: {e}"
    except SystemExit as e:
        return f"Zotero: not synced ({e})"
    from collections import Counter
    msg = f"Zotero: synced {len(todo)} reference(s): {dict(Counter(v['status'] for v in out['items'].values()))}"
    if not quiet:
        print(msg)
    return msg


def _file_one(hit, new_item, key, review_tag, st, col, dry_run, link_only, origin, notes, run, rv):
    """File one confirmed reference: link or update the item the library has, or create it (no PDF here)."""
    rec = {"metadata_from": origin, "full_names": notes}
    if hit and link_only:
        rec.update(status="linked", zotero_key=hit["key"], match=hit["match"])
    elif hit:
        ch = plan_changes(hit["data"], new_item, key, review_tag, None if dry_run and not st["collection"] else col)
        rec.update(status="existing", zotero_key=hit["key"], match=hit["match"],
                   changes={f: {"old": o, "new": n} for f, (o, n) in ch.items()})
        if not dry_run and ch:
            err = apply_changes(hit["key"], hit["data"]["version"], ch, run, rv)
            rec["status"] = "updated" if not err else "update_failed"
            if err:
                rec["error"] = err
    else:
        new_item["tags"] = [{"tag": review_tag}]
        if dry_run:
            rec.update(status="to_add", item=new_item)
        else:
            new_item["collections"] = [col]
            s2, r2 = write("POST", "/items", [new_item])
            if s2 == 200 and isinstance(r2, dict) and r2.get("successful"):
                zk = list(r2["successful"].values())[0]["key"]
                rec.update(status="added", zotero_key=zk)
                _log_change({"run": run, "source": rv, "item": zk, "created": True})
            else:
                rec.update(status="add_failed", error=f"HTTP {s2}: {str(r2)[:300]}")
    return rec


# ---------------------------------------------------------------- clean the whole collection
def clean(dry_run=False):
    """Apply the same cleaning to every item in the collection (also ones filed by hand or by older runs)."""
    _ready(dry_run)
    c = find_collection()
    if not c:
        sys.exit("The collection does not exist yet.")
    st, items = get(f"/collections/{c['key']}/items/top")
    run = datetime.datetime.now().isoformat(timespec="seconds")
    out = {"collection": collection_name(), "run": run, "dry_run": dry_run, "items": {}}
    for it in items if isinstance(items, list) else []:
        d = it["data"]
        if d.get("itemType") in ("attachment", "note", "annotation"):
            continue
        rec = {"title": d.get("title")}
        doi = _item_doi(d)
        fields, origin, notes = metadata_for_doi(doi) if doi else (None, None, [])
        if fields:
            new_item = to_item(fields, None)
            rec["metadata_from"], rec["full_names"] = origin, notes
        else:
            # no DOI record: only tidy what is clearly wrong; ask for a confirmed record otherwise
            new_item = {"itemType": d["itemType"]}
            creators, notes = (d.get("creators", []), [])
            rec["metadata_from"] = "none (no DOI): checked for legacy notes and tags only"
        if new_item.get("itemType") != d.get("itemType") and fields:
            rec["note"] = f"record says {new_item['itemType']}, item is {d['itemType']}: type left unchanged; fix by hand if wrong"
            new_item = {k: v for k, v in new_item.items() if k in item_fields(d["itemType"]) or k in ("itemType", "creators")}
            new_item["itemType"] = d["itemType"]
        ch = plan_changes(d, new_item, None, None, None)
        rec["changes"] = {f: {"old": o, "new": n} for f, (o, n) in ch.items()}
        if not dry_run and ch:
            err = apply_changes(d["key"], d["version"], ch, run, "clean")
            rec["status"] = "updated" if not err else "update_failed"
            if err:
                rec["error"] = err
        else:
            rec["status"] = "would update" if ch else "clean"
        out["items"][d["key"]] = rec
    path = os.path.join(CACHE_DIR, f"zotero-clean-{run.replace(':', '')}.json")
    if not dry_run:
        write_json(path, out)
    print(json.dumps(out, indent=1, ensure_ascii=False) if dry_run else
          f"cleaned {sum(1 for v in out['items'].values() if v.get('status') == 'updated')} of {len(out['items'])} items -> {path}")
    return out


def undo(path):
    """Restore every field changed by the push or clean runs recorded in this file, newest first."""
    z = read_json(path)
    if not z:
        sys.exit(f"nothing to undo: {path} not found")
    n = 0
    for k, rec in z["items"].items():
        key = rec.get("zotero_key") or k
        runs = rec.get("history") or ([{"changes": rec["changes"]}] if rec.get("status") == "updated" else [])
        for h in reversed(runs):
            st, cur = get(f"/items/{key}")
            if st != 200:
                break
            body = {f: (c["old"] if c["old"] is not None else ([] if f in ("tags", "collections", "creators") else ""))
                    for f, c in h["changes"].items()}
            body["version"] = cur["data"]["version"]
            s2, _ = write("PATCH", f"/items/{key}", body)
            n += s2 == 204
    print(f"restored {n} change set(s). Items the push created were left in place (delete them in Zotero if unwanted).")


# ---------------------------------------------------------------- tidy (read-only)
def tidy():
    c = find_collection()
    if not c:
        sys.exit("The collection does not exist yet.")
    st, items = get(f"/collections/{c['key']}/items/top")
    items = items if isinstance(items, list) else []
    by_doi, by_title, problems = {}, {}, []
    for it in items:
        d = it["data"]
        doi = _item_doi(d)
        if doi:
            by_doi.setdefault(doi, []).append(d["key"])
        by_title.setdefault(norm(d.get("title")), []).append(d["key"])
        miss = [f for f in ("title", "date") if not d.get(f)] + ([] if d.get("creators") else ["creators"])
        if d.get("itemType") in ("journalArticle", "conferencePaper") and not doi:
            miss.append("DOI")
        if d.get("itemType") == "journalArticle" and not d.get("pages"):
            miss.append("pages")
        initials = [f"{c.get('firstName')} {c.get('lastName')}" for c in d.get("creators", []) if c.get("firstName") and _is_abbrev(c["firstName"])]
        if miss or initials:
            problems.append({"key": d["key"], "title": d.get("title"), "missing": miss, "initials_only": initials})
    dups = {tuple(sorted(set(v))) for v in list(by_doi.values()) + list(by_title.values()) if len(set(v)) > 1}
    rep = {"collection": collection_name(), "items": len(items), "duplicates": [list(d) for d in dups],
           "problems": problems,
           "note": "Merge duplicates in Zotero (Duplicate Items pane). Initials remain only where no verified source "
                   "gave a full name."}
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "find", "push", "sync", "clean", "undo", "tidy"])
    ap.add_argument("--doi")
    ap.add_argument("--title")
    ap.add_argument("--review")
    ap.add_argument("--log", help="for undo: a zotero-clean-*.json file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="comma-separated reference keys")
    a = ap.parse_args()
    if a.cmd == "status":
        sys.exit(0 if status()["ready"] else 3)
    if a.cmd == "find":
        r = find(a.doi, a.title)
        if r:
            r.pop("data", None)
        print(json.dumps(r, indent=1))
    elif a.cmd == "push":
        if not a.review:
            sys.exit("--review is required")
        push(a.review, a.dry_run, set(a.only.split(",")) if a.only else None)
    elif a.cmd == "sync":
        if not a.review:
            sys.exit("--review is required")
        print(sync(a.review, quiet=True))
    elif a.cmd == "clean":
        clean(a.dry_run)
    elif a.cmd == "undo":
        undo(a.log or os.path.join(a.review or "", "zotero.json"))
    elif a.cmd == "tidy":
        tidy()


if __name__ == "__main__":
    main()
