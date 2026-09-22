"""End-to-end spec tests for mvault multi-version loading and `migrate`."""
import json, os, shutil, subprocess, sys, tempfile, threading, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MV = os.path.join(HERE, "mvault.py")
PY = sys.executable

STATE = {"payload": {"episodes": [], "streams": [], "clips": []}, "fail": False}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if STATE["fail"]:
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


def write_vault(name, catalog):
    shutil.rmtree(name, ignore_errors=True)
    os.makedirs(name)
    with open(os.path.join(name, "catalog.json"), "w") as fh:
        json.dump(catalog, fh, indent=2)
    return open(os.path.join(name, "catalog.json"), "rb").read()


def cat(name):
    return json.load(open(os.path.join(name, "catalog.json")))


def bak(name):
    return json.load(open(os.path.join(name, "catalog.bak")))


def entry(c, category, eid):
    return next(e for e in c[category] if e["id"] == eid)


def iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def is_ts(s):
    return (isinstance(s, str) and len(s) == 19 and s[4] == "-" and s[10] == "T"
            and s[13] == ":" and s[16] == ":")


E1, E2, E3 = 1718444400, 1718448000, 1718451600

V1 = {
    "version": 1,
    "source_id": "abc123",
    "entries": [
        {"id": "e1", "published": "2024-05-03T00:00:00", "width": 1920, "height": 1080,
         "title": {str(E1): "One", str(E2): "One v2"},
         "description": {str(E1): "D1"},
         "views": {str(E1): 10, str(E3): 30},
         "likes": {str(E1): None, str(E2): 5},
         "preview": {str(E1): "p1"}},
        {"id": "e2", "published": "2024-05-02T10:00:00", "width": 640, "height": 480,
         "title": {str(E2): "Two"}, "description": {str(E2): "D2"},
         "views": {str(E2): 1}, "likes": {str(E2): 0}, "preview": {str(E2): "p2"}},
    ],
}


def v2_catalog(url=URL):
    return {
        "version": 2,
        "source": url,
        "episodes": [
            {"id": "e1", "published": "2024-05-03T00:00:00", "width": 1920, "height": 1080,
             "title": {"2024-06-15T11:00:00": "One"},
             "description": {"2024-06-15T11:00:00": "D1"},
             "views": {"2024-06-15T11:00:00": 10},
             "likes": {"2024-06-15T11:00:00": None},
             "preview": {"2024-06-15T11:00:00": "p1"}},
        ],
        "streams": [
            {"id": "s1", "published": "2023-01-01T05:06:07", "width": 1280, "height": 720,
             "title": {"2024-06-15T11:00:00": "S"},
             "description": {"2024-06-15T11:00:00": "SD"},
             "views": {"2024-06-15T11:00:00": 3},
             "likes": {"2024-06-15T11:00:00": 4},
             "preview": {"2024-06-15T11:00:00": "sp"}},
        ],
        "clips": [],
    }


def ent(i, pub, t="T", d="D", v=1, l=2, p="ph", w=1920, h=1080):
    return {"id": i, "published": pub, "width": w, "height": h, "title": t,
            "description": d, "views": v, "likes": l, "preview": p}


# ----------------------------------------------------------------- migrate v1
original = write_vault("v1", V1)
rc, out, err = run("migrate", "v1")
check(rc == 0 and out.strip(), "migrate v1 exit 0 with stdout")
c = cat("v1")
check(c["version"] == 3, "v1 -> version field 3")
check(c["source"] == "https://media.example.com/channel/abc123", "v1 source derivation")
check("source_id" not in c and "entries" not in c, "v1 legacy root fields dropped")
check([e["id"] for e in c["episodes"]] == ["e1", "e2"], "v1 entries -> episodes")
check(c["streams"] == [] and c["clips"] == [], "v1 empty streams/clips created")
e1 = entry(c, "episodes", "e1")
check(list(e1["title"]) == [iso(E1), iso(E2)], "v1 epoch keys -> ISO (%s)" % list(e1["title"]))
check(e1["title"][iso(E2)] == "One v2" and e1["views"][iso(E3)] == 30, "v1 history values kept")
check(e1["likes"][iso(E1)] is None and e1["likes"][iso(E2)] == 5, "v1 null likes preserved")
check(iso(E1) == "2024-06-15T09:40:00", "epoch 1718444400 -> 2024-06-15T09:40:00 UTC")
check(isinstance(e1["removed"], dict) and list(e1["removed"].values()) == [False]
      and len(e1["removed"]) == 1, "v1 removed = single false entry")
check(is_ts(list(e1["removed"])[0]), "v1 removed timestamp is ISO 8601")
check(e1["annotations"] == [] and entry(c, "episodes", "e2")["annotations"] == [],
      "v1 annotations = [] on every entry")
check(all(len(e["removed"]) == 1 and list(e["removed"].values()) == [False]
          for e in c["episodes"]), "v1 removed added to every entry")
check(e1["published"] == "2024-05-03T00:00:00" and e1["width"] == 1920,
      "v1 static fields preserved")
check(bak("v1") == json.loads(original), "v1 backup holds pre-migration catalog")

# idempotence: re-migrating a v3 catalog is a no-op and writes no backup
after = open("v1/catalog.json", "rb").read()
os.remove("v1/catalog.bak")
rc, out, err = run("migrate", "v1")
check(rc == 0, "migrate v3 exit 0")
check(not os.path.exists("v1/catalog.bak"), "migrate v3 writes no backup")
check(open("v1/catalog.json", "rb").read() == after, "migrate v3 leaves catalog byte-identical")

# ----------------------------------------------------------------- migrate v2
original2 = write_vault("v2", v2_catalog())
rc, out, err = run("migrate", "v2")
check(rc == 0, "migrate v2 exit 0")
c = cat("v2")
check(c["version"] == 3, "v2 -> version field 3")
check(c["source"] == URL, "v2 source preserved")
check([e["id"] for e in c["episodes"]] == ["e1"] and [e["id"] for e in c["streams"]] == ["s1"]
      and c["clips"] == [], "v2 category placement preserved")
for cn in ("episodes", "streams"):
    for e in c[cn]:
        check(list(e["removed"].values()) == [False] and len(e["removed"]) == 1,
              "v2 removed added to %s/%s" % (cn, e["id"]))
        check(is_ts(list(e["removed"])[0]), "v2 removed timestamp ISO 8601 (%s)" % e["id"])
        check(e["annotations"] == [], "v2 annotations [] (%s)" % e["id"])
check(entry(c, "episodes", "e1")["title"] == {"2024-06-15T11:00:00": "One"},
      "v2 history keys untouched")
check(bak("v2") == json.loads(original2), "v2 backup holds pre-migration catalog")

# ------------------------------------------------------------- migrate errors
rc, out, err = run("migrate", "nosuchvault")
check(rc != 0 and "nosuchvault" in err and not out.strip(),
      "migrate missing vault -> stderr w/ name, non-zero")

cases = [
    ("noversion", {"source": URL, "episodes": [], "streams": [], "clips": []}, None),
    ("strversion", {"version": "2", "source": URL, "episodes": [], "streams": [], "clips": []}, "version"),
    ("floatversion", {"version": 2.0, "source": URL, "episodes": [], "streams": [], "clips": []}, "version"),
    ("future", {"version": 4, "source": URL, "episodes": [], "streams": [], "clips": []}, "version"),
]
for vname, catalog, needle in cases:
    raw = write_vault(vname, catalog)
    for cmd in ("migrate", "sync"):
        rc, out, err = run(cmd, vname)
        ok = rc != 0 and err.strip() and (needle is None or needle in err.lower())
        check(ok, "%s %s -> error on stderr, non-zero" % (cmd, vname))
        check(open(os.path.join(vname, "catalog.json"), "rb").read() == raw,
              "%s %s -> catalog unmodified" % (cmd, vname))
        check(not os.path.exists(os.path.join(vname, "catalog.bak")),
              "%s %s -> no backup written" % (cmd, vname))

os.makedirs("badjson", exist_ok=True)
open("badjson/catalog.json", "w").write("{not json")
rc, out, err = run("migrate", "badjson")
check(rc != 0 and err.strip(), "migrate invalid JSON -> error, non-zero")
check(not os.path.exists("badjson/catalog.bak"), "migrate invalid JSON -> no backup")

# malformed legacy entry data
malformed = [
    ("v1 bad epoch key", 1, {"version": 1, "source_id": "x", "entries": [
        dict(V1["entries"][1], title={"not-a-number": "T"})]}),
    ("v1 missing field", 1, {"version": 1, "source_id": "x", "entries": [
        {k: v for k, v in V1["entries"][1].items() if k != "preview"}]}),
    ("v1 bad views value", 1, {"version": 1, "source_id": "x", "entries": [
        dict(V1["entries"][1], views={str(E1): "12"})]}),
    ("v1 entry not object", 1, {"version": 1, "source_id": "x", "entries": ["nope"]}),
    ("v1 missing entries", 1, {"version": 1, "source_id": "x"}),
    ("v1 missing source_id", 1, {"version": 1, "entries": []}),
    ("v1 bad width", 1, {"version": 1, "source_id": "x", "entries": [
        dict(V1["entries"][1], width=1.5)]}),
    ("v2 bad iso key", 2, dict(v2_catalog(), episodes=[
        dict(v2_catalog()["episodes"][0], title={"nope": "T"})])),
    ("v2 history not object", 2, dict(v2_catalog(), episodes=[
        dict(v2_catalog()["episodes"][0], views=5)])),
    ("v2 bad likes value", 2, dict(v2_catalog(), episodes=[
        dict(v2_catalog()["episodes"][0], likes={"2024-06-15T11:00:00": "5"})])),
    ("v2 missing category", 2, {"version": 2, "source": URL, "episodes": [], "streams": []}),
]
for label, _ver, catalog in malformed:
    raw = write_vault("bad", catalog)
    rc, out, err = run("migrate", "bad")
    check(rc != 0 and err.strip(), "malformed %s -> error, non-zero" % label)
    check(open("bad/catalog.json", "rb").read() == raw,
          "malformed %s -> catalog unchanged" % label)
    check(not os.path.exists("bad/catalog.bak"), "malformed %s -> no backup" % label)

# backup failure aborts the migration
raw = write_vault("bakfail", V1)
os.makedirs("bakfail/catalog.bak")
rc, out, err = run("migrate", "bakfail")
check(rc != 0 and err.strip(), "backup write failure -> error, non-zero")
check(open("bakfail/catalog.json", "rb").read() == raw,
      "backup write failure -> original catalog intact")

# --------------------------------------------------------------- sync on v1/v2
STATE["payload"] = {
    "episodes": [ent("e1", "2024-05-03T00:00:00", t="One", d="D1", v=30, l=None, p="p1", w=1920, h=1080),
                 ent("e9", "2024-07-01T00:00:00")],
    "streams": [ent("s1", "2023-01-01T05:06:07", t="S", d="SD", v=3, l=4, p="sp",
                    w=1280, h=720)],
    "clips": [],
}
original2 = write_vault("sv2", v2_catalog())
rc, out, err = run("sync", "sv2")
check(rc == 0, "sync on v2 exit 0")
c = cat("sv2")
check(c["version"] == 3, "sync on v2 writes version 3")
check(bak("sv2") == json.loads(original2), "sync on v2 backup = original pre-migration catalog")
e1 = entry(c, "episodes", "e1")
check(len(e1["title"]) == 1 and e1["title"]["2024-06-15T11:00:00"] == "One",
      "sync on v2: unchanged migrated value appends nothing")
check(len(e1["views"]) == 2 and e1["views"][max(e1["views"])] == 30,
      "sync on v2: changed value appended")
check(list(e1["removed"].values())[-1] is False and e1["annotations"] == [],
      "sync on v2: migration fields survive sync")
new = entry(c, "episodes", "e9")
check(new["removed"][max(new["removed"])] is False, "sync on v2: new entry recorded")
gone = entry(c, "streams", "s1")
check(gone["removed"][max(gone["removed"])] is False, "sync on v2: still-present stream kept")

# second sync is a plain v3 sync
time.sleep(1.1)
rc, out, err = run("sync", "sv2")
check(rc == 0 and cat("sv2")["version"] == 3, "post-migration sync behaves as native v3")
check(len(entry(cat("sv2"), "episodes", "e1")["views"]) == 2,
      "post-migration sync appends nothing when unchanged")

# v1 sync derives its source URL from source_id
raw = write_vault("sv1", V1)
rc, out, err = run("sync", "sv1")
check(rc != 0 and "https://media.example.com/channel/abc123" in err,
      "sync on v1 fetches the derived source URL")
check(open("sv1/catalog.json", "rb").read() == raw,
      "sync on v1 with unreachable source leaves catalog unchanged")

# read-only load of a legacy catalog must not rewrite the catalog
raw = write_vault("ro", v2_catalog("http://127.0.0.1:1/none.json"))
rc, out, err = run("sync", "ro")
check(rc != 0 and open("ro/catalog.json", "rb").read() == raw,
      "failed read of legacy vault does not rewrite catalog.json")

# --help lists migrate
rc, out, err = run("--help")
check(rc == 0 and "migrate" in out, "--help lists migrate")
rc, out, err = run("migrate")
check(rc != 0 and err.strip(), "migrate without name -> error")

print()
print("FAILURES: %d" % len(fails))
for f in fails: print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
