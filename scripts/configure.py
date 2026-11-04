#!/usr/bin/env python3
"""Settings for detailed-paper-review: contact email, API keys, cache.

  status                     what is configured (keys are never printed), OpenAlex budget, Zotero, cache size
  set-email EMAIL            contact email sent to Crossref and OpenAlex (faster "polite" limits)
  openalex-key               save an OpenAlex API key in the system keychain (asks for it; run in your own terminal)
  semanticscholar-key        same for a Semantic Scholar API key (optional)
  forget KEYNAME             remove a saved key (openalex | semanticscholar)
  clear-cache                delete cached registry answers

API keys are stored in the macOS Keychain (or the Linux secret service) under the service name
'detailed-paper-review', never in project files or config.json. An environment variable
(OPENALEX_API_KEY, SEMANTIC_SCHOLAR_API_KEY) overrides the keychain.

Get an OpenAlex key: create a free account at https://openalex.org/signup, then copy the key from
https://openalex.org/settings/api-key and run:  python configure.py openalex-key
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dprlib  # noqa: E402

KEYNAMES = ("openalex", "semanticscholar")


def save_config(**kw):
    cfg = dict(dprlib.load_config())
    cfg.update(kw)
    os.makedirs(dprlib.CONFIG_DIR, exist_ok=True)
    path = os.path.join(dprlib.CONFIG_DIR, "config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    print(f"saved {path}")


def store_key(name):
    if not sys.stdin.isatty():
        sys.exit("Run this in your own terminal: it asks for the key so the key never appears in a chat or log.")
    if sys.platform == "darwin":
        print(f"macOS will ask for the {name} key (paste it, then press Return; it is not shown).")
        # -w as the last option makes `security` prompt for the value, so it never appears in the process list
        r = subprocess.run(["security", "add-generic-password", "-U", "-s", dprlib.KEYCHAIN_SERVICE, "-a", name, "-w"])
        sys.exit(r.returncode or print(f"saved the {name} key in the Keychain (service '{dprlib.KEYCHAIN_SERVICE}')"))
    if shutil.which("secret-tool"):
        print(f"Paste the {name} key, then press Return:")
        r = subprocess.run(["secret-tool", "store", "--label", f"detailed-paper-review {name}",
                            "service", dprlib.KEYCHAIN_SERVICE, "account", name])
        sys.exit(r.returncode)
    sys.exit(f"No keychain found. Set the environment variable {dprlib.SECRET_ENV[name]} in your shell profile instead.")


def forget(name):
    if sys.platform == "darwin":
        subprocess.run(["security", "delete-generic-password", "-s", dprlib.KEYCHAIN_SERVICE, "-a", name])
    elif shutil.which("secret-tool"):
        subprocess.run(["secret-tool", "clear", "service", dprlib.KEYCHAIN_SERVICE, "account", name])


def status():
    out = {"contact_email": dprlib.contact_email(), "config_file": os.path.join(dprlib.CONFIG_DIR, "config.json")}
    for name in KEYNAMES:
        out[f"{name}_key"] = "set" if dprlib.secret(name) else "not set"
    if dprlib.secret("openalex"):
        st, js = dprlib.get_json("https://api.openalex.org/rate-limit")
        out["openalex_key_check"] = (js if st == 200 else f"HTTP {st} (key rejected or network blocked)")
    db = os.path.join(dprlib.CACHE_DIR, "http-cache.sqlite")
    if os.path.exists(db):
        import sqlite3
        con = sqlite3.connect(db)
        out["cache"] = {"file": db, "entries": con.execute("SELECT COUNT(*) FROM responses").fetchone()[0],
                        "megabytes": round(os.path.getsize(db) / 1e6, 1)}
        con.close()
    try:
        import zotero_lib
        out["zotero"] = zotero_lib.status(quiet=True)
    except Exception as e:
        out["zotero"] = f"not checked: {e}"
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "set-email", "openalex-key", "semanticscholar-key", "forget", "clear-cache"])
    ap.add_argument("value", nargs="?")
    a = ap.parse_args()
    if a.cmd == "status":
        status()
    elif a.cmd == "set-email":
        if not a.value or "@" not in a.value:
            sys.exit("usage: configure.py set-email you@example.org")
        save_config(mailto=a.value.strip())
    elif a.cmd in ("openalex-key", "semanticscholar-key"):
        store_key(a.cmd.split("-")[0])
    elif a.cmd == "forget":
        if a.value not in KEYNAMES:
            sys.exit("usage: configure.py forget openalex|semanticscholar")
        forget(a.value)
    elif a.cmd == "clear-cache":
        db = os.path.join(dprlib.CACHE_DIR, "http-cache.sqlite")
        if os.path.exists(db):
            os.remove(db)
        print("cache cleared")


if __name__ == "__main__":
    main()
