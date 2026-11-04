"""Shared helpers for the detailed-paper-review scripts (stdlib only)."""
import json
import os
import sys
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import sqlite3
import subprocess
import threading

CONFIG_DIR = os.environ.get("DPR_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".config", "detailed-paper-review")
CACHE_DIR = os.environ.get("DPR_CACHE_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "detailed-paper-review")
KEYCHAIN_SERVICE = "detailed-paper-review"


# ---------------------------------------------------------------- config and secrets
_CONFIG = None


def load_config():
    """Non-secret settings (contact email, Zotero collection name) from ~/.config/detailed-paper-review/config.json."""
    global _CONFIG
    if _CONFIG is None:
        try:
            with open(os.path.join(CONFIG_DIR, "config.json"), encoding="utf-8") as fh:
                _CONFIG = json.load(fh)
        except Exception:
            _CONFIG = {}
    return _CONFIG


_SECRETS = {}
SECRET_ENV = {"openalex": "OPENALEX_API_KEY", "semanticscholar": "SEMANTIC_SCHOLAR_API_KEY"}


def secret(name):
    """API key from the environment, else the macOS Keychain (service 'detailed-paper-review'), else Linux
    secret-tool. Never read from or written to project files. Returns None when not set."""
    if name in _SECRETS:
        return _SECRETS[name]
    val = os.environ.get(SECRET_ENV.get(name, ""), "").strip() or None
    if not val:
        cmds = []
        if sys.platform == "darwin":
            cmds.append(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"])
        cmds.append(["secret-tool", "lookup", "service", KEYCHAIN_SERVICE, "account", name])
        for cmd in cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    val = r.stdout.strip()
                    break
            except Exception:
                pass
    _SECRETS[name] = val
    return val


def contact_email():
    return (os.environ.get("DPR_MAILTO") or os.environ.get("OPENALEX_MAILTO") or load_config().get("mailto") or "").strip() or None


def user_agent():
    m = contact_email()
    return f"detailed-paper-review/1.1 (academic reference checker{'; mailto:' + m if m else ''})"


USER_AGENT = user_agent()


# ---------------------------------------------------------------- rate limits
# Published limits (checked Nov 2026): Crossref public pool 5/s single-record and 1/s list queries, concurrency 1;
# polite pool (mailto) 10/s single and 3/s list, concurrency 3. OpenAlex 10/s without a key, 30/s with a free key.
# Semantic Scholar: about 1/s. arXiv API: one request every 3 seconds, one connection. We stay below each.
def _host_rule(url):
    u = urllib.parse.urlsplit(url)
    host, q = u.netloc.lower(), u.query
    polite = bool(contact_email())
    if host == "api.crossref.org":
        listy = "query" in q or "filter=" in q or u.path.rstrip("/").endswith("/works")
        if listy:
            return ("crossref-list", 2.5 if polite else 0.8, 3 if polite else 1)
        return ("crossref", 8.0 if polite else 4.0, 3 if polite else 1)
    if host == "api.openalex.org":
        return ("openalex", 20.0 if secret("openalex") else 8.0, 5)
    if host == "api.semanticscholar.org":
        return ("semanticscholar", 0.9, 1)
    if host in ("export.arxiv.org", "arxiv.org", "www.arxiv.org"):
        return ("arxiv", 1 / 3.2, 1)
    if host in ("api.datacite.org", "doi.org", "dx.doi.org", "www.ebi.ac.uk"):
        return (host, 3.0, 2)
    if host in ("localhost:23119", "127.0.0.1:23119"):
        return ("zotero", 20.0, 2)
    return (host, 2.0, 2)


class _Limiter:
    def __init__(self, rate, conc):
        self.interval, self.sem, self.lock, self.next, self.pause_until = 1.0 / rate, threading.Semaphore(conc), threading.Lock(), 0.0, 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next, self.pause_until)
            self.next = start + self.interval
        if start > now:
            time.sleep(start - now)

    def pause(self, seconds):
        with self.lock:
            self.pause_until = max(self.pause_until, time.monotonic() + seconds)


_LIMITERS, _LIM_LOCK = {}, threading.Lock()


def _limiter(url):
    key, rate, conc = _host_rule(url)
    with _LIM_LOCK:
        if key not in _LIMITERS:
            _LIMITERS[key] = _Limiter(rate, conc)
        return _LIMITERS[key]


def _with_credentials(url, headers):
    """Add the OpenAlex key / contact email and Semantic Scholar key automatically, so every script uses them."""
    u = urllib.parse.urlsplit(url)
    host = u.netloc.lower()
    params = {}
    if host == "api.openalex.org":
        if secret("openalex"):
            headers["Authorization"] = "Bearer " + secret("openalex")
        if contact_email():
            params["mailto"] = contact_email()
    elif host == "api.crossref.org" and contact_email():
        params["mailto"] = contact_email()
    elif host == "api.semanticscholar.org" and secret("semanticscholar"):
        headers["x-api-key"] = secret("semanticscholar")
    if params:
        existing = dict(urllib.parse.parse_qsl(u.query))
        params = {k: v for k, v in params.items() if k not in existing}
        if params:
            url = url + ("&" if u.query else "?") + urllib.parse.urlencode(params)
    return url


# ---------------------------------------------------------------- response cache
# Registry answers are cached on disk so a reference is not looked up again on every run. Only metadata APIs
# are cached (never PDFs or web pages), only 200 and 404 answers, keyed by the URL without credentials.
CACHE_HOSTS = {"api.crossref.org", "api.openalex.org", "api.semanticscholar.org", "api.datacite.org",
               "export.arxiv.org", "www.ebi.ac.uk", "pub.orcid.org"}
CACHE_TTL = {200: float(os.environ.get("DPR_CACHE_DAYS", "30")) * 86400, 404: 7 * 86400}
CACHE_STATS = {"hits": 0, "misses": 0}
OPENALEX_BUDGET = {}
_CACHE_LOCK = threading.Lock()


def _cache_key(url):
    u = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if k not in ("api_key", "mailto")]
    return urllib.parse.urlunsplit((u.scheme, u.netloc.lower(), u.path, urllib.parse.urlencode(sorted(q)), ""))


def _cache_db():
    os.makedirs(CACHE_DIR, exist_ok=True)
    db = sqlite3.connect(os.path.join(CACHE_DIR, "http-cache.sqlite"), timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, status INTEGER, body BLOB, fetched REAL)")
    return db


def _cache_get(url):
    if os.environ.get("DPR_NO_CACHE") or urllib.parse.urlsplit(url).netloc.lower() not in CACHE_HOSTS:
        return None
    try:
        with _CACHE_LOCK:
            db = _cache_db()
            row = db.execute("SELECT status, body, fetched FROM responses WHERE key=?", (_cache_key(url),)).fetchone()
            db.close()
    except Exception:
        return None
    if row and time.time() - row[2] < CACHE_TTL.get(row[0], 0):
        CACHE_STATS["hits"] += 1
        return row[0], row[1]
    return None


def _cache_put(url, status, body):
    if status not in CACHE_TTL or urllib.parse.urlsplit(url).netloc.lower() not in CACHE_HOSTS:
        return
    try:
        with _CACHE_LOCK:
            db = _cache_db()
            db.execute("INSERT OR REPLACE INTO responses VALUES (?,?,?,?)", (_cache_key(url), status, body, time.time()))
            db.commit()
            db.close()
    except Exception:
        pass  # a read-only cache (e.g. a sandbox) only costs repeat requests


def network_summary():
    """One line for the end of a script run: cache use and the OpenAlex budget left."""
    parts = [f"cache: {CACHE_STATS['hits']} answered from cache, {CACHE_STATS['misses']} fetched"]
    if OPENALEX_BUDGET:
        parts.append("OpenAlex budget remaining: " + str(OPENALEX_BUDGET.get("remaining")))
    if not secret("openalex"):
        parts.append("no OpenAlex key (slower limits; see configure.py)")
    return "; ".join(parts)


# ---------------------------------------------------------------- Zotero write lock
class zotero_lock:
    """Held while looking a paper up in Zotero and creating it, so two programs filing the same paper at once
    (this skill in a terminal, another copy of it, or an app such as Lexiq Writer) cannot both create it.
    A directory in the shared cache folder, since mkdir is atomic everywhere; a lock older than `stale`
    seconds is from a crashed run and is taken over."""

    def __init__(self, wait=60.0, stale=120.0):
        self.path = os.path.join(CACHE_DIR, "zotero-write.lock")
        self.wait, self.stale, self.held = wait, stale, False

    def __enter__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        deadline = time.monotonic() + self.wait
        while True:
            try:
                os.mkdir(self.path)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.rmdir(self.path)
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    return self  # never block a review on a stuck lock; the DOI/title check still runs
                time.sleep(0.2)
            except OSError:
                return self  # read-only cache folder: work without the lock

    def __exit__(self, *exc):
        if self.held:
            try:
                os.rmdir(self.path)
            except OSError:
                pass
        return False


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
    """GET with per-host rate limiting, Retry-After/Backoff handling, automatic credentials and an on-disk cache
    for registry metadata. Returns (status, body) and never raises on HTTP errors. Status 0 = no connection."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": accept}
    if headers:
        hdrs.update(headers)
    if not binary:
        hit = _cache_get(url)
        if hit:
            return hit[0], hit[1].decode("utf-8", "replace") if isinstance(hit[1], bytes) else hit[1]
    full = _with_credentials(url, hdrs)
    lim = _limiter(url)
    last = None
    for attempt in range(retries):
        lim.sem.acquire()
        try:
            lim.wait()
            req = urllib.request.Request(full, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if "openalex.org" in url and resp.headers.get("X-RateLimit-Remaining"):
                    OPENALEX_BUDGET["remaining"] = resp.headers.get("X-RateLimit-Remaining")
                if resp.headers.get("Backoff"):
                    lim.pause(float(resp.headers["Backoff"]))
                CACHE_STATS["misses"] += 1
                if not binary:
                    _cache_put(url, resp.status, body)
                return resp.status, (body if binary else body.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            wait = e.headers.get("Retry-After") if e.headers else None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                try:
                    secs = float(wait) if wait else 2.0 * (2 ** attempt)
                except ValueError:
                    secs = 2.0 * (2 ** attempt)
                lim.pause(min(secs, 120))
                continue
            if e.code == 404 and not binary:
                _cache_put(url, 404, b"")
            return e.code, b"" if binary else ""
        except Exception as e:  # network error / timeout
            last = e
            time.sleep(1.5 * (attempt + 1))
        finally:
            lim.sem.release()
    return 0, (b"" if binary else f"ERROR: {last}")


NETWORK_HELP = """Network access is blocked, so registry lookups and downloads cannot run.
This is usually the agent's sandbox, not the internet. Fix it, then rerun this command:
  - Codex: approve running this command outside the sandbox when asked, or start Codex with network
    allowed in the workspace sandbox: `codex -s workspace-write -c sandbox_workspace_write.network_access=true`
  - Claude Code: allow the command (or network access) when the permission prompt appears.
  - Elsewhere: run the command in a normal terminal.
Nothing has been checked yet. Do NOT report any reference as verified or missing."""


def network_ok(hosts=("https://api.crossref.org/", "https://api.openalex.org/")):
    """True if at least one registry answers. Used to stop early instead of writing misleading results."""
    for h in hosts:
        st, _ = http_get(h, accept="*/*", timeout=10, retries=1)
        if st:
            return True
    return False


def require_network(hosts=("https://api.crossref.org/", "https://api.openalex.org/")):
    if not network_ok(hosts):
        print(NETWORK_HELP, file=sys.stderr)
        sys.exit(3)


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
