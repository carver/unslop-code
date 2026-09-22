"""Checks for the sync download phase, digest command and post-sync summary."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
MVAULT = os.path.join(ROOT, "mvault.py")

STATE = {"payload": {"episodes": [], "streams": [], "clips": []},
         "status": 200, "asset_status": {}, "media_type": "video/mp4",
         "hits": {}}
FAILED = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        STATE["hits"][path] = STATE["hits"].get(path, 0) + 1
        if "/media/" in path or "/preview/" in path:
            kind, _, rest = path.partition("/media/")
            if rest:
                name = rest
            else:
                name = path.partition("/preview/")[2]
            status = STATE["asset_status"].get(name, 200)
            if status != 200:
                body = b"nope"
                self.send_response(status)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = ("bytes-for-" + name).encode()
            ctype = ("image/png" if "/preview/" in path else STATE["media_type"])
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        status = STATE["status"]
        body = json.dumps(STATE["payload"]).encode() if status == 200 else b"boom"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label
          + (" :: " + detail if detail and not condition else ""))
    if not condition:
        FAILED.append(label)


def run(*args):
    return subprocess.run([sys.executable, MVAULT] + list(args),
                          capture_output=True, text=True, cwd=os.getcwd())


def entry(eid, published, title="t", desc="d", views=1, likes=0, preview="p",
          width=1920, height=1080):
    return {"id": eid, "published": published, "width": width, "height": height,
            "title": title, "description": desc, "views": views, "likes": likes,
            "preview": preview}


def catalog(name="v"):
    with open(os.path.join(name, "catalog.json")) as fh:
        return json.load(fh)


def listing(path):
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


def write_catalog(name, doc):
    os.makedirs(name, exist_ok=True)
    with open(os.path.join(name, "catalog.json"), "w") as fh:
        json.dump(doc, fh, indent=2)


def main():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/feed.json" % server.server_address[1]

    workdir = tempfile.mkdtemp()
    os.chdir(workdir)

    # ---- option validation ------------------------------------------------ #
    run("init", "opt", url)
    snapshot = open("opt/catalog.json", "rb").read()
    for bad in ("--episodes=x", "--episodes=-1", "--streams=1.5", "--clips=",
                "--episodes= "):
        res = run("sync", "opt", bad)
        check("malformed limit %s exits non-zero" % bad, res.returncode != 0, res.stdout)
        check("malformed limit %s errors on stderr" % bad, res.stderr.strip() != "")
        check("malformed limit %s does no work" % bad,
              open("opt/catalog.json", "rb").read() == snapshot
              and not os.path.exists("opt/media"))

    for bad in ("--bogus", "--skip-meta", "-x", "--format", "--episodes"):
        res = run("sync", "opt", bad)
        check("unknown option %s exits non-zero" % bad, res.returncode != 0, res.stdout)
        check("unknown option %s errors on stderr" % bad, res.stderr.strip() != "")
        check("unknown option %s does no work" % bad,
              open("opt/catalog.json", "rb").read() == snapshot
              and not os.path.exists("opt/media"))

    # ---- download phase basics -------------------------------------------- #
    STATE["payload"] = {
        "episodes": [entry("e1", "2024-05-01T10:00:00"),
                     entry("e2", "2024-06-01")],
        "streams": [entry("s1", "2024-01-02T03:04:05")],
        "clips": [entry("c1", "2023-12-31T23:59:59")],
    }
    run("init", "v", url)
    res = run("sync", "v")
    check("sync with downloads exits 0", res.returncode == 0, res.stderr)
    check("media dir populated", listing("v/media") == ["c1.mp4", "e1.mp4", "e2.mp4",
                                                        "s1.mp4"], str(listing("v/media")))
    check("preview dir populated",
          listing("v/previews") == ["c1.png", "e1.png", "e2.png", "s1.png"],
          str(listing("v/previews")))
    check("media content stored",
          open("v/media/e1.mp4").read() == "bytes-for-e1")
    check("no partial artifacts left",
          not any(n.endswith(".part") for n in listing("v/media") + listing("v/previews")))
    check("post-sync summary printed",
          "added" in res.stdout and "removed" in res.stdout and "updated" in res.stdout,
          res.stdout)
    check("first sync counts 4 added", "4 added" in res.stdout, res.stdout)

    # already-downloaded entries are not candidates again
    before = STATE["hits"].get("/feed.json/media/e1", 0)
    res = run("sync", "v")
    check("existing media not re-downloaded",
          STATE["hits"].get("/feed.json/media/e1", 0) == before, res.stdout)
    check("no-change summary is all zeros",
          "0 added" in res.stdout and "0 removed" in res.stdout
          and "0 updated" in res.stdout, res.stdout)

    # ---- content-type derived extension ----------------------------------- #
    STATE["media_type"] = "audio/mpeg"
    STATE["payload"]["episodes"].append(entry("e3", "2024-07-01"))
    run("sync", "v")
    check("extension derives from Content-Type", "e3.mp3" in listing("v/media"),
          str(listing("v/media")))
    STATE["media_type"] = "video/mp4"

    # ---- format override --------------------------------------------------- #
    STATE["payload"]["episodes"].append(entry("e4", "2024-08-01"))
    res = run("sync", "v", "--format=webm")
    check("format override extension", "e4.webm" in listing("v/media"),
          str(listing("v/media")))
    check("format override remote path",
          STATE["hits"].get("/feed.json/media/e4.webm", 0) >= 1,
          str(sorted(STATE["hits"])))

    # ---- per-category limits ---------------------------------------------- #
    STATE["payload"] = {
        "episodes": [entry("a%d" % i, "2024-0%d-01" % (i + 1)) for i in range(4)],
        "streams": [entry("b%d" % i, "2024-0%d-01" % (i + 1)) for i in range(3)],
        "clips": [entry("c%d" % i, "2024-0%d-01" % (i + 1)) for i in range(3)],
    }
    run("init", "lim", url)
    res = run("sync", "lim", "--episodes=2", "--streams=0")
    check("episode limit honored", len([n for n in listing("lim/media")
                                        if n.startswith("a")]) == 2,
          str(listing("lim/media")))
    check("zero limit downloads nothing",
          not any(n.startswith("b") for n in listing("lim/media")),
          str(listing("lim/media")))
    check("omitted limit is unlimited",
          len([n for n in listing("lim/media") if n.startswith("c")]) == 3,
          str(listing("lim/media")))
    order = [e["id"] for e in catalog("lim")["episodes"]][:2]
    check("limit picks first candidates in catalog order",
          sorted(n.split(".")[0] for n in listing("lim/media")
                 if n.startswith("a")) == sorted(order), str(order))

    res = run("sync", "lim", "--episodes=1")
    check("next run continues with remaining candidates",
          len([n for n in listing("lim/media") if n.startswith("a")]) == 3,
          str(listing("lim/media")))

    # ---- stale partial artifacts ------------------------------------------ #
    run("init", "part", url)
    STATE["payload"] = {"episodes": [entry("p1", "2024-01-01")],
                        "streams": [], "clips": []}
    os.makedirs("part/media")
    with open("part/media/p1.mp4.part", "w") as fh:
        fh.write("truncated")
    res = run("sync", "part")
    check("stale partial does not block download",
          "p1.mp4" in listing("part/media")
          and open("part/media/p1.mp4").read() == "bytes-for-p1",
          str(listing("part/media")))

    # ---- skip flags -------------------------------------------------------- #
    run("init", "skip", url)
    STATE["payload"] = {"episodes": [entry("k1", "2024-01-01")],
                        "streams": [], "clips": []}
    res = run("sync", "skip", "--skip-download")
    check("--skip-download exits 0", res.returncode == 0, res.stderr)
    check("--skip-download writes metadata",
          [e["id"] for e in catalog("skip")["episodes"]] == ["k1"])
    check("--skip-download downloads nothing", listing("skip/media") == [])
    check("--skip-download still summarizes", "1 added" in res.stdout, res.stdout)

    STATE["status"] = 500  # metadata fetch would fail if it were attempted
    res = run("sync", "skip", "--skip-metadata")
    check("--skip-metadata exits 0 without fetching", res.returncode == 0, res.stderr)
    check("--skip-metadata downloads media", "k1.mp4" in listing("skip/media"),
          str(listing("skip/media")))
    check("--skip-metadata prints no counts", "added" not in res.stdout, res.stdout)
    STATE["status"] = 200

    res = run("sync", "skip", "--skip-metadata", "--skip-download")
    check("both skips exit 0", res.returncode == 0, res.stderr)

    # ---- download failures ------------------------------------------------- #
    run("init", "fail", url)
    STATE["payload"] = {"episodes": [entry("f1", "2024-01-01"),
                                     entry("f2", "2024-02-01"),
                                     entry("f3", "2024-03-01")],
                        "streams": [], "clips": []}
    STATE["asset_status"] = {"f1": 404, "f2": 500}
    STATE["hits"] = {}
    res = run("sync", "fail")
    check("download failures still exit 0", res.returncode == 0, res.stderr)
    check("permanent failure warns on stderr", "f1" in res.stderr, res.stderr)
    check("transient failure warns on stderr", "f2" in res.stderr, res.stderr)
    check("failures use the word warning", "warning" in res.stderr.lower(), res.stderr)
    check("other entries still downloaded", "f3.mp4" in listing("fail/media"),
          str(listing("fail/media")))
    check("failed entries store nothing",
          not any(n.startswith("f1") or n.startswith("f2")
                  for n in listing("fail/media")), str(listing("fail/media")))
    check("transient failure retried",
          STATE["hits"].get("/feed.json/media/f2", 0) >= 2,
          str(STATE["hits"]))
    check("permanent failure not retried",
          STATE["hits"].get("/feed.json/media/f1", 0) == 1, str(STATE["hits"]))
    check("metadata persisted despite download failures",
          sorted(e["id"] for e in catalog("fail")["episodes"]) == ["f1", "f2", "f3"])
    check("summary still printed on download failure", "3 added" in res.stdout,
          res.stdout)

    STATE["asset_status"] = {}
    res = run("sync", "fail")
    check("later run recovers failed downloads",
          "f1.mp4" in listing("fail/media") and "f2.mp4" in listing("fail/media"),
          str(listing("fail/media")))

    # ---- post-sync counts -------------------------------------------------- #
    run("init", "cnt", url)
    STATE["payload"] = {"episodes": [entry("x1", "2024-01-01"),
                                     entry("x2", "2024-02-01")],
                        "streams": [], "clips": []}
    run("sync", "cnt", "--skip-download")
    STATE["payload"] = {"episodes": [entry("x1", "2024-01-01", title="renamed"),
                                     entry("x3", "2024-03-01")],
                        "streams": [], "clips": []}
    res = run("sync", "cnt", "--skip-download")
    check("counts added/removed/updated",
          "1 added" in res.stdout and "1 removed" in res.stdout
          and "1 updated" in res.stdout, res.stdout)

    # ---- digest: v3 -------------------------------------------------------- #
    res = run("digest", "cnt")
    check("digest exits 0", res.returncode == 0, res.stderr)
    out = res.stdout
    check("digest groups by category", "Episodes" in out, out)
    check("digest lists removal", "t" in out and "Removed" in out, out)
    check("digest lists addition", "Added" in out, out)
    check("digest lists update with field", "renamed" in out and "title" in out, out)
    check("digest omits empty categories",
          "Streams" not in out and "Clips" not in out, out)
    check("digest trailing line carries source", url in out.splitlines()[-1],
          out)
    digest_before = open("cnt/catalog.json", "rb").read()
    backup_before = open("cnt/catalog.bak", "rb").read()
    run("digest", "cnt")
    check("digest never rewrites catalog.json",
          open("cnt/catalog.json", "rb").read() == digest_before)
    check("digest never rewrites catalog.bak",
          open("cnt/catalog.bak", "rb").read() == backup_before)

    # reappearance
    STATE["payload"] = {"episodes": [entry("x1", "2024-01-01", title="renamed"),
                                     entry("x2", "2024-02-01"),
                                     entry("x3", "2024-03-01")],
                        "streams": [], "clips": []}
    run("sync", "cnt", "--skip-download")
    out = run("digest", "cnt").stdout
    check("digest indicates reappearance", "reappear" in out.lower(), out)

    # no notable changes
    run("init", "quiet", url)
    out = run("digest", "quiet").stdout
    check("digest on empty vault reports no changes",
          "no notable changes" in out.lower(), out)
    check("digest on empty vault still has trailing line", url in out, out)

    # ---- digest: errors ---------------------------------------------------- #
    res = run("digest", "missing")
    check("digest missing vault exits non-zero", res.returncode != 0)
    check("digest missing vault names vault", "missing" in res.stderr, res.stderr)

    write_catalog("badver", {"version": 9, "source": url,
                             "episodes": [], "streams": [], "clips": []})
    res = run("digest", "badver")
    check("digest unsupported version exits non-zero", res.returncode != 0)
    check("digest unsupported version names version", "9" in res.stderr, res.stderr)

    # ---- digest: v1 -------------------------------------------------------- #
    v1 = {"version": 1, "source_id": "chan42", "entries": [
        {"id": "o1", "published": "2024-01-01T00:00:00", "width": 1, "height": 2,
         "title": {"900": "old", "1000": "new"}, "description": {"900": "d"},
         "views": {"900": 1, "1000": 5}, "likes": {"900": 0},
         "preview": {"900": "p"}},
        {"id": "o2", "published": "2024-01-02T00:00:00", "width": 1, "height": 2,
         "title": {"900": "fresh"}, "description": {"900": "d"},
         "views": {"900": 1}, "likes": {"900": 0}, "preview": {"900": "p"}},
    ]}
    write_catalog("one", v1)
    res = run("digest", "one")
    check("digest v1 exits 0", res.returncode == 0, res.stderr)
    out = res.stdout
    check("digest v1 uses single Entries group",
          "Entries" in out and "Episodes" not in out, out)
    check("digest v1 numeric epoch ordering picks 'new'",
          "new" in out and "\n    - old" not in out, out)
    check("digest v1 lists addition", "fresh" in out, out)
    check("digest v1 update fields", "title" in out and "views" in out, out)
    check("digest v1 source template",
          "https://media.example.com/channel/chan42" in out, out)
    check("digest v1 does not migrate", catalog("one")["version"] == 1)
    check("digest v1 makes no backup", not os.path.exists("one/catalog.bak"))

    # ---- digest: v2 -------------------------------------------------------- #
    v2 = {"version": 2, "source": url,
          "episodes": [{"id": "t1", "published": "2024-01-01T00:00:00",
                        "width": 1, "height": 2,
                        "title": {"2024-01-01T00:00:00": "a",
                                  "2024-02-01T00:00:00": "b"},
                        "description": {"2024-01-01T00:00:00": "d"},
                        "views": {"2024-01-01T00:00:00": 1},
                        "likes": {"2024-01-01T00:00:00": 0},
                        "preview": {"2024-01-01T00:00:00": "p"}}],
          "streams": [], "clips": []}
    write_catalog("two", v2)
    res = run("digest", "two")
    check("digest v2 exits 0", res.returncode == 0, res.stderr)
    check("digest v2 per-category groups", "Episodes" in res.stdout, res.stdout)
    check("digest v2 latest ISO value", "- b (title)" in res.stdout, res.stdout)
    check("digest v2 has no removals section", "Removed" not in res.stdout, res.stdout)
    check("digest v2 does not migrate", catalog("two")["version"] == 2)

    # digest determinism
    a = run("digest", "cnt").stdout.splitlines()[:-1]
    b = run("digest", "cnt").stdout.splitlines()[:-1]
    check("digest output deterministic", a == b, str(a) + str(b))

    # ---- legacy sync downloads -------------------------------------------- #
    write_catalog("legacy", {"version": 2, "source": url,
                             "episodes": [], "streams": [], "clips": []})
    STATE["payload"] = {"episodes": [entry("L1", "2024-01-01")],
                        "streams": [], "clips": []}
    res = run("sync", "legacy")
    check("legacy sync migrates and downloads",
          catalog("legacy")["version"] == 3 and "L1.mp4" in listing("legacy/media"),
          str(listing("legacy/media")))

    server.shutdown()
    os.chdir(ROOT)
    shutil.rmtree(workdir, ignore_errors=True)

    print("\n%s" % ("ALL CHECKS PASSED" if not FAILED
                    else "FAILURES: %s" % ", ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
