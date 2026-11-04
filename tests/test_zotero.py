"""Zotero filing: the default behaviour is unchanged, and the settings an app passes work as documented."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, HERE)
import zotero_mock  # noqa: E402

REF = {"key": "smith2020", "verdict": "verified",
       "metadata": {"type": "report", "title": "Quokka Commuting Patterns in Perth", "date": "2020",
                    "authors": [{"family": "Smith", "given": "Jane"}], "url": "https://example.org/quokka"}}


def make_review(root, name="paper"):
    rv = os.path.join(root, name)
    for d in ("phases", "refcheck/records", "sources"):
        os.makedirs(os.path.join(rv, d), exist_ok=True)
    with open(os.path.join(rv, "phases", "01-references.json"), "w") as fh:
        json.dump({"phase": "01-references", "items": [REF]}, fh)
    with open(os.path.join(rv, "sources", "manifest.json"), "w") as fh:
        json.dump({"rows": []}, fh)
    return rv


class ZoteroFiling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.srv, self.lib, self.url = zotero_mock.serve()

    def tearDown(self):
        self.srv.shutdown()
        self.tmp.cleanup()

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("DPR_", "ZOTERO_"))}
        e.update(DPR_ZOTERO_URL=self.url, DPR_CACHE_DIR=os.path.join(self.tmp.name, "cache"),
                 DPR_CONFIG_DIR=os.path.join(self.tmp.name, "config"), DPR_NO_CACHE="1",
                 ZOTERO_LOCAL_API_KEY="test-key", DPR_ZOTERO_KEYCHAIN="0")
        e.update(extra)
        return e

    def push(self, rv, **extra):
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "zotero_lib.py"), "push", "--review", rv],
                           env=self.env(**extra), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(rv, "zotero.json")) as fh:
            return json.load(fh)

    def collection(self, name):
        return next((k for k, c in self.lib.collections.items() if c["name"] == name), None)

    def test_default_collection_and_new_item(self):
        out = self.push(make_review(self.tmp.name))
        col = self.collection("Detailed Paper Review")
        self.assertIsNotNone(col)
        self.assertEqual(out["items"]["smith2020"]["status"], "added")
        item = self.lib.items[out["items"]["smith2020"]["zotero_key"]]
        self.assertEqual(item["collections"], [col])
        self.assertIn({"tag": "dpr:paper"}, item["tags"])

    def test_collection_from_environment(self):
        out = self.push(make_review(self.tmp.name), DPR_ZOTERO_COLLECTION="Lexiq Writer")
        self.assertIsNone(self.collection("Detailed Paper Review"))
        self.assertEqual(self.lib.items[out["items"]["smith2020"]["zotero_key"]]["collections"], [self.collection("Lexiq Writer")])

    def test_existing_item_default_is_filed_and_tagged(self):
        k = self.lib.add_item({"itemType": "report", "title": "Quokka Commuting Patterns in Perth", "date": "2020"})
        out = self.push(make_review(self.tmp.name))
        self.assertIn(out["items"]["smith2020"]["status"], ("updated", "existing"))
        self.assertEqual(out["items"]["smith2020"]["zotero_key"], k)
        self.assertIn(self.collection("Detailed Paper Review"), self.lib.items[k]["collections"])
        self.assertEqual(len(self.lib.items), 1)

    def test_existing_item_link_mode_is_untouched(self):
        k = self.lib.add_item({"itemType": "report", "title": "Quokka Commuting Patterns in Perth", "date": "2020"})
        before = json.dumps(self.lib.items[k], sort_keys=True)
        out = self.push(make_review(self.tmp.name), DPR_ZOTERO_EXISTING="link")
        self.assertEqual(out["items"]["smith2020"]["status"], "linked")
        self.assertEqual(out["items"]["smith2020"]["zotero_key"], k)
        self.assertEqual(json.dumps(self.lib.items[k], sort_keys=True), before)
        self.assertFalse([w for w in self.lib.writes if w[0] == "PATCH"])

    def test_wrong_key_without_keychain_stops_cleanly(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "zotero_lib.py"), "push", "--review",
                            make_review(self.tmp.name)], env=self.env(ZOTERO_LOCAL_API_KEY="wrong"),
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused the key", r.stdout + r.stderr)
        self.assertFalse(self.lib.items)

    def test_two_programs_at_once_create_one_item(self):
        self.srv.shutdown()
        self.srv, self.lib, self.url = zotero_mock.serve(delay=0.4)
        rvs = [make_review(self.tmp.name, f"paper{i}") for i in range(3)]
        procs = [subprocess.Popen([sys.executable, "-I", os.path.join(SCRIPTS, "zotero_lib.py"), "push", "--review", rv],
                                  env=self.env(DPR_ZOTERO_EXISTING="link"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for rv in rvs]
        for p in procs:
            p.wait(timeout=90)
            self.assertEqual(p.returncode, 0, p.stderr.read().decode())
        papers = [d for d in self.lib.items.values() if d.get("title") == REF["metadata"]["title"]]
        self.assertEqual(len(papers), 1)
        self.assertEqual(len([c for c in self.lib.collections.values() if c["name"] == "Detailed Paper Review"]), 1)


    def run_cmd(self, cmd, rv, **extra):
        return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "zotero_lib.py"), cmd, "--review", rv],
                              env=self.env(**extra), capture_output=True, text=True, timeout=60)

    def test_sync_follows_the_host_settings(self):
        rv = make_review(self.tmp.name)
        host = dict(DPR_ZOTERO="on", DPR_ZOTERO_EXISTING="link", DPR_ZOTERO_COLLECTION="Lexiq Writer")
        self.push(rv, **host)
        # a second, newly confirmed reference appears later; one the library already has appears too
        k = self.lib.add_item({"itemType": "report", "title": "Wombat Burrows of Tasmania", "date": "2021", "collections": ["MINE0001"]})
        with open(os.path.join(rv, "phases", "01-references.json")) as fh:
            ph = json.load(fh)
        ph["items"] += [{"key": "jones2022", "verdict": "verified", "metadata": {"type": "report", "title": "Koala Sleep in the Wild", "date": "2022", "authors": [{"family": "Jones", "given": "Ann"}]}},
                        {"key": "lee2021", "verdict": "verified", "metadata": {"type": "report", "title": "Wombat Burrows of Tasmania", "date": "2021", "authors": [{"family": "Lee", "given": "Bo"}]}}]
        with open(os.path.join(rv, "phases", "01-references.json"), "w") as fh:
            json.dump(ph, fh)
        # the user's own copy skipped Zotero in its setup; the host said "on", so sync still runs
        os.makedirs(os.path.join(self.tmp.name, "config"), exist_ok=True)
        with open(os.path.join(self.tmp.name, "config", "config.json"), "w") as fh:
            json.dump({"skipped_setup": ["zotero"]}, fh)
        r = self.run_cmd("sync", rv, **host)
        self.assertIn("synced 2", r.stdout, r.stdout + r.stderr)
        z = json.load(open(os.path.join(rv, "zotero.json")))
        self.assertEqual(set(z["items"]), {"smith2020", "jones2022", "lee2021"})  # merged, nothing dropped
        self.assertEqual(z["items"]["lee2021"]["status"], "linked")
        self.assertEqual(self.lib.items[k]["collections"], ["MINE0001"])  # the user's item untouched
        col = self.collection("Lexiq Writer")
        self.assertIn(col, self.lib.items[z["items"]["jones2022"]["zotero_key"]]["collections"])
        self.assertIn("up to date", self.run_cmd("sync", rv, **host).stdout)  # nothing left to do, linked items included

    def test_host_off_never_writes(self):
        rv = make_review(self.tmp.name)
        r = self.run_cmd("push", rv, DPR_ZOTERO="off")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("off for this review", r.stdout + r.stderr)
        self.push(rv)  # an earlier push, then the host turns Zotero off
        writes = len(self.lib.writes)
        self.assertIn("off for this review", self.run_cmd("sync", rv, DPR_ZOTERO="off").stdout)
        self.assertEqual(len(self.lib.writes), writes)


class Defaults(unittest.TestCase):
    """With no settings, the functions report today's behaviour."""

    def test_defaults(self):
        code = ("import zotero_lib as z; print(z.collection_name(), '|', z.existing_mode(), '|', z.use_keychain(), '|', z.BASE)")
        with tempfile.TemporaryDirectory() as t:
            env = {k: v for k, v in os.environ.items() if not k.startswith(("DPR_", "ZOTERO_"))}
            env["DPR_CONFIG_DIR"] = t
            r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {SCRIPTS!r}); " + code],
                               env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout.strip(), "Detailed Paper Review | update | True | http://localhost:23119", r.stderr)


if __name__ == "__main__":
    unittest.main()
