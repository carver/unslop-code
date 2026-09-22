"""End-to-end checks of the mvault CLI against a live local HTTP server."""

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

STATE = {"payload": {"episodes": [], "streams": [], "clips": []}, "status": 200}
FAILED = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
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
    print(("PASS " if condition else "FAIL ") + label + (" :: " + detail if detail and not condition else ""))
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


def current(hist):
    return hist[sorted(hist)[-1]]


def main():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/feed.json" % server.server_address[1]

    workdir = tempfile.mkdtemp()
    os.chdir(workdir)

    # ---- global surface -------------------------------------------------- #
    res = run("--help")
    check("--help exits 0", res.returncode == 0, str(res.returncode))
    check("--help prints usage to stdout",
          "usage" in res.stdout.lower() and "init" in res.stdout and "sync" in res.stdout,
          res.stdout)

    res = run()
    check("no subcommand exits non-zero", res.returncode != 0)
    check("no subcommand usage on stderr", "usage" in res.stderr.lower(), res.stderr)
    check("no subcommand prints nothing to stdout", res.stdout == "", res.stdout)

    # ---- init ------------------------------------------------------------- #
    res = run("init", "v", url)
    check("init exits 0", res.returncode == 0, res.stderr)
    check("init creates vault dir", os.path.isdir("v"))
    check("init creates catalog.json", os.path.isfile("v/catalog.json"))
    check("init catalog exact layout",
          catalog() == {"version": 3, "source": url,
                        "episodes": [], "streams": [], "clips": []},
          json.dumps(catalog()))
    check("init makes no backup", not os.path.exists("v/catalog.bak"))

    before = open("v/catalog.json", "rb").read()
    res = run("init", "v", url)
    check("init on existing dir exits non-zero", res.returncode != 0)
    check("init on existing dir names vault on stderr", "v" in res.stderr, res.stderr)
    check("init on existing dir leaves data untouched",
          open("v/catalog.json", "rb").read() == before)

    # ---- sync errors ------------------------------------------------------ #
    res = run("sync", "nope")
    check("sync missing vault exits non-zero", res.returncode != 0)
    check("sync missing vault names vault", "nope" in res.stderr, res.stderr)

    os.makedirs("broken")
    res = run("sync", "broken")
    check("sync vault without catalog fails", res.returncode != 0)
    check("sync vault without catalog names vault", "broken" in res.stderr, res.stderr)
    with open("broken/catalog.json", "w") as fh:
        fh.write("{not json")
    res = run("sync", "broken")
    check("sync invalid catalog fails", res.returncode != 0)
    check("sync invalid catalog names vault", "broken" in res.stderr, res.stderr)

    # ---- first sync ------------------------------------------------------- #
    STATE["payload"] = {
        "episodes": [entry("e1", "2024-05-01T10:00:00"),
                     entry("e2", "2024-06-01")],
        "streams": [entry("s1", "2024-01-02T03:04:05", likes=None)],
        "clips": [entry("c1", "2023-12-31T23:59:59")],
    }
    res = run("sync", "v")
    check("first sync exits 0", res.returncode == 0, res.stderr)
    cat = catalog()
    check("backup created on sync", os.path.isfile("v/catalog.bak"))
    check("backup is pre-write bytes", open("v/catalog.bak", "rb").read() == before)
    check("version preserved", cat["version"] == 3)
    check("source preserved", cat["source"] == url)
    check("entries placed per category",
          [e["id"] for e in cat["episodes"]] == ["e2", "e1"]
          and [e["id"] for e in cat["streams"]] == ["s1"]
          and [e["id"] for e in cat["clips"]] == ["c1"],
          json.dumps(cat))

    e1 = [e for e in cat["episodes"] if e["id"] == "e1"][0]
    e2 = [e for e in cat["episodes"] if e["id"] == "e2"][0]
    s1 = cat["streams"][0]
    check("date-only published normalized", e2["published"] == "2024-06-01T00:00:00",
          e2["published"])
    check("static fields stored raw",
          e1["published"] == "2024-05-01T10:00:00" and e1["width"] == 1920
          and e1["height"] == 1080 and isinstance(e1["id"], str))
    check("six tracked fields are history objects",
          all(isinstance(e1[f], dict) and len(e1[f]) == 1
              for f in ("title", "description", "views", "likes", "preview", "removed")),
          json.dumps(e1))
    check("removed false at first observation", current(e1["removed"]) is False)
    check("null likes recorded as null", current(s1["likes"]) is None)
    stamp = list(e1["title"])[0]
    check("history key format YYYY-MM-DDTHH:MM:SS",
          len(stamp) == 19 and stamp[4] == "-" and stamp[10] == "T" and stamp[13] == ":",
          stamp)
    check("all first-sync stamps identical",
          len({k for e in (e1, e2, s1) for f in ("title", "removed") for k in e[f]}) == 1)
    first_stamp = stamp

    # ---- no-op sync ------------------------------------------------------- #
    res = run("sync", "v")
    check("unchanged sync exits 0", res.returncode == 0, res.stderr)
    cat = catalog()
    e1 = [e for e in cat["episodes"] if e["id"] == "e1"][0]
    check("unchanged fields gain no history",
          all(len(e1[f]) == 1 for f in
              ("title", "description", "views", "likes", "preview", "removed")),
          json.dumps(e1))

    # ---- changes, removal, restore, null transitions ---------------------- #
    STATE["payload"]["episodes"] = [entry("e1", "2024-05-01T10:00:00",
                                          title="new", views=42)]
    STATE["payload"]["streams"] = [entry("s1", "2024-01-02T03:04:05", likes=7)]
    res = run("sync", "v")
    check("changing sync exits 0", res.returncode == 0, res.stderr)
    cat = catalog()
    e1 = [e for e in cat["episodes"] if e["id"] == "e1"][0]
    e2 = [e for e in cat["episodes"] if e["id"] == "e2"][0]
    s1 = cat["streams"][0]
    check("changed title appended", len(e1["title"]) == 2 and current(e1["title"]) == "new")
    check("changed views appended", current(e1["views"]) == 42)
    check("unchanged description not appended", len(e1["description"]) == 1)
    check("null -> number is a change", len(s1["likes"]) == 2 and current(s1["likes"]) == 7)
    check("absent entry marked removed",
          len(e2["removed"]) == 2 and current(e2["removed"]) is True, json.dumps(e2))
    check("removed entry retained", e2 in cat["episodes"])
    check("timestamps strictly increase", sorted(e1["title"])[-1] > first_stamp)

    STATE["payload"]["episodes"] = [entry("e1", "2024-05-01T10:00:00",
                                          title="new", views=42),
                                    entry("e2", "2024-06-01")]
    STATE["payload"]["streams"] = [entry("s1", "2024-01-02T03:04:05", likes=None)]
    run("sync", "v")
    cat = catalog()
    e2 = [e for e in cat["episodes"] if e["id"] == "e2"][0]
    s1 = cat["streams"][0]
    check("restored entry marked not removed",
          len(e2["removed"]) == 3 and current(e2["removed"]) is False, json.dumps(e2))
    check("number -> null is a change",
          len(s1["likes"]) == 3 and current(s1["likes"]) is None, json.dumps(s1["likes"]))

    # ---- rapid syncs never collide --------------------------------------- #
    seen = set()
    for i in range(4):
        STATE["payload"]["episodes"] = [entry("e1", "2024-05-01T10:00:00",
                                              title="rapid%d" % i)]
        run("sync", "v")
        cat = catalog()
        e1 = [e for e in cat["episodes"] if e["id"] == "e1"][0]
        seen.add(sorted(e1["title"])[-1])
    check("rapid syncs produce strictly increasing distinct stamps",
          len(seen) == 4 and sorted(e1["title"]) == list(sorted(e1["title"])),
          json.dumps(sorted(e1["title"])))
    check("history keys remain unique & sorted chronologically",
          len(set(e1["title"])) == len(e1["title"]))

    # ---- ordering --------------------------------------------------------- #
    STATE["payload"] = {
        "episodes": [entry("b", "2024-01-01T00:00:00"),
                     entry("a", "2024-01-01T00:00:00"),
                     entry("z", "2025-01-01T00:00:00")],
        "streams": [], "clips": [],
    }
    run("init", "ord", url)
    run("sync", "ord")
    ids = [e["id"] for e in catalog("ord")["episodes"]]
    check("ordering: newest published first, id tiebreak", ids == ["z", "a", "b"], str(ids))

    # ---- malformed source / fetch failures -------------------------------- #
    snapshot = open("ord/catalog.json", "rb").read()
    bad_cases = {
        "missing field": {"episodes": [{k: v for k, v in entry("x", "2024-01-01").items()
                                        if k != "views"}], "streams": [], "clips": []},
        "wrong type": {"episodes": [entry("x", "2024-01-01", views="lots")],
                       "streams": [], "clips": []},
        "bool as int": {"episodes": [entry("x", "2024-01-01", views=True)],
                        "streams": [], "clips": []},
        "likes wrong type": {"episodes": [entry("x", "2024-01-01", likes="9")],
                             "streams": [], "clips": []},
        "missing category": {"episodes": [], "streams": []},
        "category not a list": {"episodes": {}, "streams": [], "clips": []},
        "entry not an object": {"episodes": ["nope"], "streams": [], "clips": []},
    }
    for label, payload in bad_cases.items():
        STATE["payload"] = payload
        res = run("sync", "ord")
        check("malformed source (%s) fails" % label, res.returncode != 0, res.stdout)
        check("malformed source (%s) errors on stderr" % label,
              res.stderr.strip() != "", res.stderr)
        check("malformed source (%s) leaves vault unchanged" % label,
              open("ord/catalog.json", "rb").read() == snapshot)

    STATE["status"] = 500
    res = run("sync", "ord")
    check("http error fails", res.returncode != 0)
    check("http error leaves vault unchanged",
          open("ord/catalog.json", "rb").read() == snapshot)
    STATE["status"] = 200

    run("init", "unreach", "http://127.0.0.1:1/none.json")
    res = run("sync", "unreach")
    check("unreachable source fails", res.returncode != 0)
    check("unreachable source errors on stderr", res.stderr.strip() != "")

    # ---- local-only fields preserved -------------------------------------- #
    STATE["payload"] = {"episodes": [entry("k", "2024-02-02T00:00:00")],
                        "streams": [], "clips": []}
    run("init", "ann", url)
    run("sync", "ann")
    cat = catalog("ann")
    cat["episodes"][0]["annotations"] = {"note": "keep me"}
    with open("ann/catalog.json", "w") as fh:
        json.dump(cat, fh)
    STATE["payload"]["episodes"][0]["title"] = "changed"
    run("sync", "ann")
    check("local-only annotations preserved",
          catalog("ann")["episodes"][0].get("annotations") == {"note": "keep me"},
          json.dumps(catalog("ann")["episodes"][0]))

    server.shutdown()
    os.chdir(ROOT)
    shutil.rmtree(workdir, ignore_errors=True)

    print("\n%s" % ("ALL CHECKS PASSED" if not FAILED
                    else "FAILURES: %s" % ", ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
