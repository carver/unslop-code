"""End-to-end spec tests for mvault download phase, digest, and post-summary."""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MV = os.path.join(HERE, "mvault.py")
PY = sys.executable

STATE = {
    "payload": {"episodes": [], "streams": [], "clips": []},
    "feed_fail": False,
    "media_status": {},     # entry id (or "media:<id>") -> status code
    "hits": [],             # every requested path
}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        STATE["hits"].append(self.path)
        if self.path.startswith("/feed.json/media/") or \
           self.path.startswith("/feed.json/preview/"):
            kind, ident = self.path[len("/feed.json/"):].split("/", 1)
            status = STATE["media_status"].get("%s:%s" % (kind, ident))
            if status is None:
                status = STATE["media_status"].get(ident)
            if status is None and "." in ident:
                status = STATE["media_status"].get(ident.split(".")[0])
            if status:
                self.send_response(status); self.end_headers()
                self.wfile.write(b"err"); return
            body = b"BINARYDATA-" + ident.encode()
            ctype = "video/mp4" if kind == "media" else "image/jpeg"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if STATE["feed_fail"]:
            self.send_response(500); self.end_headers(); self.wfile.write(b"nope"); return
        body = json.dumps(STATE["payload"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, *a): pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/feed.json" % srv.server_address[1]

tmp = tempfile.mkdtemp()
os.chdir(tmp)
fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: fails.append(msg)


def run(*args):
    p = subprocess.run([PY, MV] + list(args), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def cat(name):
    return json.load(open(os.path.join(name, "catalog.json")))


def ls(*parts):
    try: return sorted(os.listdir(os.path.join(*parts)))
    except OSError: return []


def ent(i, pub, t="T", d="D", v=1, l=2, p="ph", w=1920, h=1080):
    return {"id": i, "published": pub, "width": w, "height": h, "title": t,
            "description": d, "views": v, "likes": l, "preview": p}


def fresh(name=None):
    STATE["media_status"] = {}
    STATE["hits"] = []
    if name:
        shutil.rmtree(name, ignore_errors=True)
        run("init", name, URL)


# ======================================================================= sync
STATE["payload"] = {
    "episodes": [ent("e1", "2024-05-03T00:00:00"), ent("e2", "2024-05-02T00:00:00"),
                 ent("e3", "2024-05-01T00:00:00")],
    "streams": [ent("s1", "2023-01-01T00:00:00")],
    "clips": [ent("c1", "2022-01-01T00:00:00")],
}

# --- default sync downloads everything ---
fresh("v")
rc, out, err = run("sync", "v")
check(rc == 0, "sync with downloads exit 0")
check(ls("v", "media") == ["c1.mp4", "e1.mp4", "e2.mp4", "e3.mp4", "s1.mp4"],
      "media downloaded to <vault>/media with Content-Type extension (%s)" % ls("v", "media"))
check(ls("v", "previews") == ["c1.jpg", "e1.jpg", "e2.jpg", "e3.jpg", "s1.jpg"],
      "previews downloaded to <vault>/previews (%s)" % ls("v", "previews"))
check(open("v/media/e1.mp4", "rb").read() == b"BINARYDATA-e1", "media body written verbatim")
check("/feed.json/media/e1" in STATE["hits"], "media remote path <source>/media/<id>")
check("/feed.json/preview/e1" in STATE["hits"], "preview remote path <source>/preview/<id>")
check(not any(f.endswith(".part") for f in ls("v", "media")), "no partial artifacts left")

# --- post-sync summary ---
check(re.search(r"5 added", out) and "removed" in out and "updated" in out,
      "post-sync summary reports added/removed/updated (%r)" % out.strip().splitlines()[-1])

# --- already-present media is not a candidate ---
STATE["hits"] = []
rc, out, err = run("sync", "v")
check(rc == 0 and not any("/media/" in h for h in STATE["hits"]),
      "entries with existing media are not candidates")

# --- summary counts on a real change ---
time.sleep(1.1)
STATE["payload"]["episodes"][0]["title"] = "CHANGED"
STATE["payload"]["clips"] = []
rc, out, err = run("sync", "v")
m = re.search(r"(\d+) added, (\d+) removed, (\d+) updated", out)
check(bool(m), "summary line parseable: %r" % out.strip().splitlines()[-1:])
if m:
    check(m.group(1) == "0" and m.group(2) == "1" and m.group(3) == "1",
          "summary counts 0 added / 1 removed / 1 updated (got %s)" % (m.groups(),))

# --- --format override ---
fresh("f")
STATE["payload"]["episodes"][0]["title"] = "T"
STATE["payload"]["clips"] = [ent("c1", "2022-01-01T00:00:00")]
rc, out, err = run("sync", "f", "--format=mp3")
check(rc == 0 and "e1.mp3" in ls("f", "media"), "format override sets extension (%s)" % ls("f", "media"))
check("/feed.json/media/e1.mp3" in STATE["hits"], "format override changes remote path")
check("e1.jpg" in ls("f", "previews"), "format override does not affect previews")

# --- per-category limits ---
fresh("l")
rc, out, err = run("l" and "sync", "l", "--episodes=2", "--streams=0")
check(rc == 0, "limits exit 0")
check(ls("l", "media") == ["c1.mp4", "e1.mp4", "e2.mp4"],
      "limits: first N per category in catalog order, 0 = none, omitted = all (%s)"
      % ls("l", "media"))
c = cat("l")
check([e["id"] for e in c["episodes"]][:2] == ["e1", "e2"], "candidate order = catalog order")

# limits apply to remaining candidates on a later run
rc, out, err = run("sync", "l", "--episodes=1")
check(ls("l", "media") == ["c1.mp4", "e1.mp4", "e2.mp4", "e3.mp4", "s1.mp4"],
      "later run downloads next candidates (%s)" % ls("l", "media"))

# --- skip flags ---
fresh("sd")
rc, out, err = run("sync", "sd", "--skip-download")
check(rc == 0 and ls("sd", "media") == [] and not os.path.exists("sd/media"),
      "--skip-download performs no downloads")
check(len(cat("sd")["episodes"]) == 3, "--skip-download still persists metadata")
check("added" in out, "--skip-download still prints summary")

STATE["hits"] = []
time.sleep(1.1)
rc, out, err = run("sync", "sd", "--skip-metadata")
check(rc == 0 and ls("sd", "media") == ["c1.mp4", "e1.mp4", "e2.mp4", "e3.mp4", "s1.mp4"],
      "--skip-metadata runs the download phase against existing state")
check("/feed.json" not in STATE["hits"], "--skip-metadata does not fetch source metadata")
check("added" not in out, "--skip-metadata prints no post-sync summary")

fresh("both")
before = open("both/catalog.json", "rb").read()
rc, out, err = run("sync", "both", "--skip-metadata", "--skip-download")
check(rc == 0 and open("both/catalog.json", "rb").read() == before,
      "both skips -> no-op, exit 0")

# --- permanent download failure ---
fresh("perm")
STATE["media_status"] = {"e2": 404}
rc, out, err = run("sync", "perm")
check(rc == 0, "permanent download failure -> exit 0")
check("e2" in err and err.strip(), "permanent failure warns on stderr with entry id")
check("e2.mp4" not in ls("perm", "media") and "e1.mp4" in ls("perm", "media"),
      "permanent failure: other entries still downloaded")
check(len(cat("perm")["episodes"]) == 3, "metadata saved despite download failures")
check(sum(1 for h in STATE["hits"] if h == "/feed.json/media/e2") == 1,
      "permanent failure is not retried (%d hits)"
      % sum(1 for h in STATE["hits"] if h == "/feed.json/media/e2"))

# --- transient download failure is retried ---
fresh("tran")
STATE["media_status"] = {"media:e1": 503}
rc, out, err = run("sync", "tran")
tries = sum(1 for h in STATE["hits"] if h == "/feed.json/media/e1")
check(rc == 0 and "e1" in err, "transient failure -> exit 0 with warning")
check(tries > 1, "transient failure retried (%d attempts)" % tries)
check("e1.mp4" not in ls("tran", "media"), "failed transfer leaves no media file")
check(not any(f.endswith(".part") for f in ls("tran", "media")),
      "failed transfer leaves no partial artifact")

# --- stale partial artifact must not block a later download ---
STATE["media_status"] = {}
os.makedirs("tran/media", exist_ok=True)
open("tran/media/e1.mp4.part", "wb").write(b"stale")
rc, out, err = run("sync", "tran")
check("e1.mp4" in ls("tran", "media"), "stale partial artifact does not block later download")
check(open("tran/media/e1.mp4", "rb").read() == b"BINARYDATA-e1", "re-download overwrites stale data")

# --- source fetch failure aborts ---
fresh("ff")
STATE["feed_fail"] = True
rc, out, err = run("sync", "ff")
check(rc != 0 and err.strip(), "source fetch failure -> non-zero, stderr")
STATE["feed_fail"] = False

# --- CLI errors abort before any sync work ---
fresh("cli")
STATE["hits"] = []
for bad in ("--episodes=abc", "--episodes=-1", "--episodes=1.5", "--clips=x", "--streams="):
    rc, out, err = run("sync", "cli", bad)
    check(rc != 0 and err.strip() and not out.strip(), "malformed limit %s -> stderr, non-zero" % bad)
check(not STATE["hits"], "malformed limit aborts before any sync work")
rc, out, err = run("sync", "cli", "--bogus")
check(rc != 0 and err.strip(), "unrecognized option -> stderr, non-zero")
check(not STATE["hits"], "unrecognized option aborts before any sync work")
check(ls("cli", "media") == [], "no downloads happened for aborted runs")

# ===================================================================== digest
def write_vault(name, catalog):
    shutil.rmtree(name, ignore_errors=True)
    os.makedirs(name)
    with open(os.path.join(name, "catalog.json"), "w") as fh:
        json.dump(catalog, fh, indent=2)
    return open(os.path.join(name, "catalog.json"), "rb").read()


T1, T2 = "2024-06-15T09:00:00", "2024-06-16T09:00:00"
E1, E2 = "900", "1000"      # epoch strings: numerically ordered, NOT lexicographic


def v3_entry(i, t, extra=None, removed=None):
    e = {"id": i, "published": "2024-05-03T00:00:00", "width": 1, "height": 1,
         "title": {T1: t}, "description": {T1: "D"}, "views": {T1: 1},
         "likes": {T1: 1}, "preview": {T1: "p"},
         "removed": removed if removed is not None else {T1: False},
         "annotations": []}
    if extra: e.update(extra)
    return e


V3 = {
    "version": 3, "source": URL,
    "episodes": [
        v3_entry("a1", "Added One"),
        v3_entry("u1", "Updated Title", {"title": {T1: "Old", T2: "Updated Title"},
                                         "views": {T1: 1, T2: 9}}),
        v3_entry("r1", "Removed One", removed={T1: False, T2: True}),
        v3_entry("q1", "Quiet One", {"title": {T1: "Quiet One", T2: "Quiet One"}}),
        v3_entry("b1", "Back One", {"views": {T1: 1, T2: 4}},
                 removed={T1: False, "2024-06-15T10:00:00": True, T2: False}),
    ],
    "streams": [v3_entry("s1", "Stream Added")],
    "clips": [],
}
write_vault("d3", V3)
raw3 = open("d3/catalog.json", "rb").read()
rc, out, err = run("digest", "d3")
check(rc == 0 and out.strip(), "digest v3 exit 0 with stdout")
check(open("d3/catalog.json", "rb").read() == raw3, "digest never writes catalog.json")
check(not os.path.exists("d3/catalog.bak"), "digest never writes catalog.bak")
check("Episodes" in out and "Streams" in out, "digest groups by category")
check("Clips" not in out, "digest omits empty categories")
check("Removed One" in out and "Added One" in out and "Updated Title" in out,
      "digest lists removals, additions and updates")
check("Quiet One" not in out, "unchanged entry is not notable")
check(re.search(r"Updated Title \([^)]*title[^)]*views[^)]*\)", out),
      "field-update suffix lists changed field names")
check(re.search(r"Back One \([^)]*reappear", out), "reappearance indicated with other fields")
check(re.search(r"Back One \([^)]*views", out), "reappearance lists other changed fields too")
idx = [out.index(x) for x in ("Removed One", "Added One", "Updated Title")]
check(idx == sorted(idx), "group order: removals, additions, updates")
check(out.index("Episodes") < out.index("Streams"), "category order deterministic")
check(URL in out.strip().splitlines()[-1], "trailing line includes resolved source URL")
rc2, out2, err2 = run("digest", "d3")
check(re.sub(r"generated at \S+", "", out) == re.sub(r"generated at \S+", "", out2),
      "digest output deterministic across runs")

# v2: no removals group, lexicographic ISO keys, source field
V2 = {
    "version": 2, "source": "http://example.com/v2feed",
    "episodes": [
        {"id": "e1", "published": "2024-05-03T00:00:00", "width": 1, "height": 1,
         "title": {T1: "Old2", T2: "New2"}, "description": {T1: "D"},
         "views": {T1: 1}, "likes": {T1: 1}, "preview": {T1: "p"},
         "removed": {T1: False, T2: True}},
        {"id": "e2", "published": "2024-05-02T00:00:00", "width": 1, "height": 1,
         "title": {T1: "Fresh2"}, "description": {T1: "D"}, "views": {T1: 1},
         "likes": {T1: 1}, "preview": {T1: "p"}},
    ],
    "streams": [], "clips": [],
}
write_vault("d2", V2)
raw2 = open("d2/catalog.json", "rb").read()
rc, out, err = run("digest", "d2")
check(rc == 0, "digest v2 exit 0")
check(open("d2/catalog.json", "rb").read() == raw2, "digest v2 does not migrate the catalog")
check("New2" in out, "digest v2 current title from lexicographically latest key")
check("Removal" not in out and "Removed" not in out, "digest v2 omits removals group entirely")
check(re.search(r"New2 \([^)]*title", out), "digest v2 classifies as field update")
check("Fresh2" in out and "Episodes" in out, "digest v2 additions + per-category grouping")
check("http://example.com/v2feed" in out.strip().splitlines()[-1], "digest v2 source field used")

# v1: single Entries group, numeric epoch ordering, derived source URL
V1 = {
    "version": 1, "source_id": "abc123",
    "entries": [
        {"id": "e1", "published": "2024-05-03T00:00:00", "width": 1, "height": 1,
         "title": {E1: "LATE-lexicographic", E2: "Newest"},
         "description": {E1: "D"}, "views": {E1: 1}, "likes": {E1: None},
         "preview": {E1: "p"}},
        {"id": "e2", "published": "2024-05-02T00:00:00", "width": 1, "height": 1,
         "title": {E1: "Only One"}, "description": {E1: "D"}, "views": {E1: 1},
         "likes": {E1: 1}, "preview": {E1: "p"}},
    ],
}
write_vault("d1", V1)
raw1 = open("d1/catalog.json", "rb").read()
rc, out, err = run("digest", "d1")
check(rc == 0, "digest v1 exit 0")
check(open("d1/catalog.json", "rb").read() == raw1, "digest v1 does not migrate the catalog")
check("Entries" in out and "Episodes" not in out, "digest v1 single Entries group")
check("Newest" in out and "LATE-lexicographic" not in out,
      "digest v1 latest value by NUMERIC epoch comparison")
check("Only One" in out, "digest v1 additions")
check("https://media.example.com/channel/abc123" in out.strip().splitlines()[-1],
      "digest v1 derived source URL in trailing line")

# no notable changes
write_vault("dq", {"version": 3, "source": URL, "episodes": [v3_entry("q", "Q")],
                   "streams": [], "clips": []})
# an entry with only initial observations is an addition, so use a fully quiet one
write_vault("dq", {"version": 3, "source": URL,
                   "episodes": [v3_entry("q", "Q", {"title": {T1: "Q", T2: "Q"}})],
                   "streams": [], "clips": []})
rc, out, err = run("digest", "dq")
check(rc == 0 and "no notable changes" in out.lower(), "no notable changes indicated")
check(URL in out.strip().splitlines()[-1], "trailing line present when nothing changed")

# digest errors
rc, out, err = run("digest", "nosuchvault")
check(rc != 0 and "nosuchvault" in err and not out.strip(),
      "digest missing vault -> stderr w/ name, non-zero")
write_vault("dv", {"version": 7, "source": URL, "episodes": [], "streams": [], "clips": []})
rc, out, err = run("digest", "dv")
check(rc != 0 and "7" in err, "digest unsupported version -> stderr including version value")
rc, out, err = run("digest")
check(rc != 0 and err.strip(), "digest without name -> error")
rc, out, err = run("--help")
check(rc == 0 and "digest" in out, "--help lists digest")

# digest on a vault produced by sync
rc, out, err = run("digest", "v")
check(rc == 0 and out.strip(), "digest works on a synced vault")

print()
print("FAILURES: %d" % len(fails))
for f in fails: print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
