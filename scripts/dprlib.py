"""Shared helpers for the detailed-paper-review scripts (stdlib only)."""
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "detailed-paper-review/1.0 (academic reference checker; mailto:none)"


# ---------------------------------------------------------------- JSON io
def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------- text
def norm(s):
    """Lowercase, strip accents/latex/punctuation, collapse spaces. For fuzzy comparison."""
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"\\[\'\"`^~=.uvHckr]\s*\{?([a-zA-Z])\}?", r"\1", s)  # LaTeX accents: {\"o} -> o
    s = re.sub(r"\\[a-zA-Z]+\s*", " ", s)
    s = s.replace("{", "").replace("}", "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = s.replace("\u00ad", "")  # soft hyphen
    s = re.sub(r"-\s*\n\s*", "", s)  # hyphenated line breaks
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def token_set_ratio(a, b):
    ta, tb = set(norm(a).split()), set(norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


# ---------------------------------------------------------------- http
def http_get(url, accept="application/json", timeout=30, retries=3, binary=False, headers=None):
    """GET with polite retry/backoff. Returns (status, body) and never raises on HTTP errors."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": accept}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                return resp.status, (body if binary else body.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return e.code, b"" if binary else ""
        except Exception as e:  # network error / timeout
            last = e
            time.sleep(1.5 * (attempt + 1))
    return 0, (b"" if binary else f"ERROR: {last}")


def get_json(url, **kw):
    status, body = http_get(url, **kw)
    if status == 200:
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None
    return status, None


# ---------------------------------------------------------------- bibtex
def _read_braced(s, i):
    """s[i] is '{' or '"'. Return (content, next_index)."""
    if s[i] == '"':
        j = i + 1
        depth = 0
        while j < len(s):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
            elif s[j] == '"' and depth == 0:
                return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    depth = 0
    j = i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


def parse_bibtex(text):
    """Small brace-aware BibTeX parser. Returns list of dicts with ENTRYTYPE, ID, fields, _line."""
    # drop % comment lines (bib comments are line-level)
    lines = text.split("\n")
    clean = "\n".join("" if l.lstrip().startswith("%") else l for l in lines)
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{", clean):
        etype = m.group(1).lower()
        if etype in ("comment", "string", "preamble"):
            continue
        start = m.end() - 1
        body, end = _read_braced(clean, start)
        key, _, rest = body.partition(",")
        e = {"ENTRYTYPE": etype, "ID": key.strip(), "_line": clean.count("\n", 0, m.start()) + 1}
        i = 0
        while i < len(rest):
            fm = re.compile(r"\s*([A-Za-z][\w\-]*)\s*=\s*").match(rest, i)
            if not fm:
                i += 1
                continue
            name = fm.group(1).lower()
            j = fm.end()
            if j < len(rest) and rest[j] in '{"':
                val, j = _read_braced(rest, j)
            else:
                vm = re.compile(r"[^,\n]+").match(rest, j)
                val = vm.group(0).strip() if vm else ""
                j = vm.end() if vm else j
            e[name] = re.sub(r"\s+", " ", val).strip()
            i = j
        entries.append(e)
    return entries


def bib_authors(field):
    """Split a BibTeX author field into [{'family','given','raw'}]."""
    if not field:
        return []
    out = []
    parts, depth, buf = [], 0, ""
    for tok in re.split(r"(\s+and\s+|[{}])", field):
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
        if depth == 0 and re.fullmatch(r"\s+and\s+", tok or ""):
            parts.append(buf)
            buf = ""
        else:
            buf += tok or ""
    parts.append(buf)
    for a in parts:
        a = a.strip()
        if not a:
            continue
        if a.startswith("{") and a.endswith("}"):
            out.append({"family": a.strip("{}"), "given": "", "raw": a, "corporate": True})
            continue
        if "," in a:
            fam, _, giv = a.partition(",")
        else:
            parts = a.split()
            fam, giv = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (a, "")
        out.append({"family": fam.strip("{} "), "given": giv.strip("{} "), "raw": a})
    return out


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>{}]+", re.I)


def clean_doi(s):
    if not s:
        return None
    m = DOI_RE.search(str(s))
    if not m:
        return None
    return m.group(0).rstrip(".,;)]").lower()


def slug(s, n=60):
    s = norm(s).replace(" ", "-")
    return (s[:n] or "item").strip("-")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def family_key(name):
    """Comparable surname key: last token of the normalised family name ('von Schneidemesser' -> 'schneidemesser')."""
    toks = norm(name).split()
    return toks[-1] if toks else ""


def parse_reference_text(raw):
    """Best-effort fields from a written-out reference (no BibTeX). Handles author-year (Elsevier/Harvard),
    APA "(2020)", IEEE/ACM with a quoted title, and web references "Title https://...". Returns a dict with
    authors (list of {family, given, raw}), year, title, venue, url, doi. Fields that cannot be found are ""."""
    out = {"authors": [], "year": "", "title": "", "venue": "", "volume": "", "issue": "", "pages": "",
           "url": "", "doi": clean_doi(raw) or ""}
    r = re.sub(r"\s+", " ", raw or "").strip()
    u = re.search(r"https?://\S+", r)
    if u:
        out["url"] = u.group(0).rstrip(".,;)")
    body = re.sub(r"https?://\S+|doi:\s*\S+|arXiv:\s*\S+", " ", r).strip(" .")
    q = re.search(r"[\"“]([^\"”]{8,300}?)[,.]?[\"”]", body)
    m_apa = re.match(r"^(.*?)\s*\(((?:19|20)\d\d[a-z]?)\)\.?\s*(.*)$", body)
    m_ay = re.match(r"^(.*?),\s*((?:19|20)\d\d[a-z]?)\.\s+(.*)$", body)
    if q:  # IEEE / ACM: Authors, "Title," Venue, year
        out["title"] = q.group(1).strip()
        auth = body[:q.start()].strip(" ,")
        rest = body[q.end():]
        y = re.search(r"\b(19|20)\d\d[a-z]?\b", rest) or re.search(r"\b(19|20)\d\d[a-z]?\b", body)
        out["year"] = y.group(0) if y else ""
        out["venue"] = re.split(r",|\.", rest.strip(" ,."), maxsplit=1)[0].strip()
    elif m_apa:
        auth, out["year"], rest = m_apa.group(1), m_apa.group(2), m_apa.group(3)
        out["title"] = re.split(r"(?<=[a-z0-9?!)])\.\s", rest, maxsplit=1)[0].strip()
        out["venue"] = (re.split(r"(?<=[a-z0-9?!)])\.\s", rest, maxsplit=1) + [""])[1].split(",")[0].strip()
    elif m_ay:
        auth, out["year"], rest = m_ay.group(1), m_ay.group(2), m_ay.group(3)
        # title ends at ". " or at "? " / "! " followed by a capital (the venue)
        parts = re.split(r"(?<=[a-z0-9)\]])\.\s+(?=[A-Z0-9])|(?<=[?!])\s+(?=[A-Z])", rest, maxsplit=1)
        out["title"] = parts[0].strip()
        out["venue"] = parts[1].strip() if len(parts) > 1 else ""
        if out["title"].endswith(", in:") or ", in:" in out["title"]:
            out["title"], _, ven = out["title"].partition(", in:")
            out["venue"] = ven.strip() or out["venue"]
    else:  # web reference or bare title
        auth = ""
        out["title"] = body.split(" | ")[0].strip()
        y = re.search(r"\b(19|20)\d\d\b", body)
        out["year"] = y.group(0) if y else ""
    # "Journal Name 50(2), 237–291" / "Journal 3, 100073" / "..., pp. 1321–1330"
    vm = re.match(r"^(.*?)\s+(\d{1,4})(?:\s*\((\w+)\))?\s*,\s*(?:pp\.\s*)?([A-Za-z]?\d+(?:\s*[–-]\s*[A-Za-z]?\d+)?)", out["venue"])
    if vm:
        out["venue"], out["volume"], out["issue"], out["pages"] = vm.group(1).strip(" ,"), vm.group(2), vm.group(3) or "", vm.group(4).replace(" ", "")
    else:
        pm = re.search(r"pp\.\s*(\d+\s*[–-]\s*\d+)", body)
        if pm:
            out["pages"] = pm.group(1).replace(" ", "")
        out["venue"] = re.split(r",\s*pp\.|\.\s", out["venue"])[0].strip(" ,.")
    if auth:
        auth = re.sub(r",?\s*et al\.?", "", auth)
        initials_first = re.match(r"^(?:[A-Z]\.(?:\s?-?[A-Z]\.)*)\s+[A-Z]", auth)  # J. Devlin, M.-W. Chang (IEEE/ACM)
        if not initials_first and re.search(r"[A-Z][a-zà-ÿ'’\-]+,\s*(?:[A-Z]\.\s*)+", auth):  # Surname, I.I., Surname, I.
            for fam, giv in re.findall(r"([A-ZÀ-Þ][\w'’\-]+(?:\s[a-z]{1,3}\s[\w'’\-]+)?(?:\s[A-Z][\w'’\-]+)?),\s*((?:[A-ZÀ-Þ][a-z]?\.\s*-?)+)", auth):
                out["authors"].append({"family": fam.strip(), "given": giv.strip(), "raw": f"{fam}, {giv}".strip()})
        else:  # I. Surname, I. Surname and I. Surname / corporate author
            for a in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", auth):
                a = a.strip()
                if not a:
                    continue
                toks = a.split()
                corp = len(toks) > 3 or not re.match(r"[A-Z]", toks[0])
                out["authors"].append({"family": a if corp else toks[-1], "given": " ".join(toks[:-1]) if not corp else "",
                                       "raw": a, **({"corporate": True} if corp else {})})
    return out
