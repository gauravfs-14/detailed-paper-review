"""A small in-memory stand-in for the Zotero 10 desktop app's local API, for tests.

Serves only what zotero_lib.py uses. Writes need the key "test-key". `delay` slows searches and item
creation so tests can provoke two programs filing the same paper at once."""
import json
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIELDS = {
    "report": ["title", "date", "institution", "reportNumber", "url", "pages", "place", "abstractNote", "citationKey", "DOI"],
    "journalArticle": ["title", "date", "publicationTitle", "volume", "issue", "pages", "DOI", "url", "ISSN",
                       "journalAbbreviation", "language", "abstractNote", "citationKey", "extra"],
}


class Library:
    def __init__(self, delay=0.0):
        self.items, self.collections, self.n, self.delay = {}, {}, 0, delay
        self.writes = []  # (method, path) of every write, for assertions
        self.lock = threading.Lock()

    def key(self):
        with self.lock:
            self.n += 1
            return f"K{self.n:07d}"

    def add_item(self, data):
        k = self.key()
        d = {"key": k, "version": 1, "collections": [], "tags": [], "creators": [], **data}
        d["key"] = k
        self.items[k] = d
        return k


def make_handler(lib):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=None, headers=None):
            raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
            self.send_response(code)
            for k, v in {"Zotero-Server-ID": "mock-server", **(headers or {})}.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw) if raw[:1] in (b"[", b"{") else raw

        def _authed(self):
            return self.headers.get("Zotero-API-Key") == "test-key"

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            p = u.path
            if p == "/_state":  # tests in other programs (Lexiq) inspect the library through this
                return self._send(200, {"items": list(lib.items.values()), "collections": list(lib.collections.values()),
                                        "writes": lib.writes})
            if p == "/connector/ping":
                return self._send(200, b"ok", {"X-Zotero-Version": "10.0.7"})
            if p == "/api/":
                return self._send(200, b"Nothing to see here.")
            if p == "/api/itemTypeFields":
                return self._send(200, [{"field": f} for f in FIELDS.get(q.get("itemType"), ["title", "date", "url"])])
            if p == "/api/users/0/collections":
                return self._send(200, [{"key": k, "data": c} for k, c in lib.collections.items()])
            m = re.fullmatch(r"/api/users/0/collections/(\w+)/items/top", p)
            if m:
                return self._send(200, [{"key": k, "data": d} for k, d in lib.items.items() if m.group(1) in d["collections"]])
            if p == "/api/users/0/items":
                return self._send(200, [{"key": k, "data": d} for k, d in lib.items.items()][: int(q.get("limit") or 50)])
            if p == "/api/users/0/items/top":
                time.sleep(lib.delay)
                needle = (q.get("q") or "").lower()
                hits = [{"key": k, "data": d} for k, d in lib.items.items()
                        if needle and (needle in (d.get("title") or "").lower() or needle in (d.get("DOI") or "").lower())]
                return self._send(200, hits)
            m = re.fullmatch(r"/api/users/0/items/(\w+)/children", p)
            if m:
                return self._send(200, [])
            m = re.fullmatch(r"/api/users/0/items/(\w+)", p)
            if m:
                d = lib.items.get(m.group(1))
                return self._send(200, {"key": d["key"], "data": d}) if d else self._send(404, b"Not found")
            return self._send(404, b"Not found")

        def do_POST(self):
            p = urllib.parse.urlsplit(self.path).path
            body = self._body()
            if p == "/_seed":  # add items directly (not a Zotero endpoint)
                return self._send(200, {"keys": [lib.add_item(it) for it in body]})
            if p == "/api/local/authorize":
                return self._send(200, {"key": "test-key", "remember": True})
            if not self._authed():
                return self._send(401, b"Unauthorized")
            lib.writes.append(("POST", p))
            if p == "/api/users/0/collections":
                out = {}
                for i, c in enumerate(body):
                    k = lib.key()
                    lib.collections[k] = {"key": k, "name": c["name"], "parentCollection": False}
                    out[str(i)] = {"key": k}
                return self._send(200, {"successful": out, "failed": {}})
            if p == "/api/users/0/items":
                time.sleep(lib.delay)
                out = {}
                for i, it in enumerate(body):
                    out[str(i)] = {"key": lib.add_item(it)}
                return self._send(200, {"successful": out, "failed": {}})
            return self._send(404, b"Not found")

        def do_PATCH(self):
            p = urllib.parse.urlsplit(self.path).path
            body = self._body()
            if not self._authed():
                return self._send(401, b"Unauthorized")
            lib.writes.append(("PATCH", p))
            m = re.fullmatch(r"/api/users/0/items/(\w+)", p)
            d = lib.items.get(m.group(1)) if m else None
            if not d:
                return self._send(404, b"Not found")
            body.pop("version", None)
            d.update(body)
            d["version"] += 1
            return self._send(204)

    return H


def serve(delay=0.0):
    lib = Library(delay)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(lib))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, lib, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Run the simulated Zotero until killed; prints its URL.")
    ap.add_argument("--delay", type=float, default=0.0)
    a = ap.parse_args()
    srv, _, url = serve(a.delay)
    print(url, flush=True)
    threading.Event().wait()
