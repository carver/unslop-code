"""End-to-end spec tests for mvault."""
import json, os, shutil, subprocess, sys, tempfile, threading, time
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

def cat(name="v"):
    return json.load(open(os.path.join(name, "catalog.json")))

def entry(c, cat_name, eid):
    return next(e for e in c[cat_name] if e["id"] == eid)

def cur(h):
    return h[max(h)]

# --- global CLI ---
rc, out, err = run("--help")
check(rc == 0 and "init" in out and "sync" in out and out.strip(), "--help -> stdout, exit 0, lists subcommands")
rc, out, err = run()
check(rc != 0 and err.strip() and not out.strip(), "no subcommand -> usage on stderr, non-zero")

# --- init ---
rc, out, err = run("init", "v", URL)
check(rc == 0, "init exit 0")
c = cat()
check(c == {"version": 3, "source": URL, "episodes": [], "streams": [], "clips": []},
      "init catalog exact layout")
check(os.path.isdir("v") and os.path.isfile("v/catalog.json"), "vault dir + catalog path")
check(not os.path.exists("v/catalog.bak"), "no backup on fresh init")

rc, out, err = run("init", "v", URL)
check(rc != 0 and "v" in err, "init existing dir -> stderr w/ name, non-zero")
check(cat() == c, "existing data untouched")

# --- sync errors ---
rc, out, err = run("sync", "missing")
check(rc != 0 and "missing" in err, "sync non-existent vault -> stderr w/ name")
os.makedirs("bad"); open("bad/catalog.json", "w").write("{not json")
rc, out, err = run("sync", "bad")
check(rc != 0 and "bad" in err, "sync invalid vault -> stderr w/ name")

STATE["fail"] = True
before = open("v/catalog.json", "rb").read()
rc, out, err = run("sync", "v")
check(rc != 0 and err.strip(), "fetch failure -> stderr, non-zero")
check(open("v/catalog.json", "rb").read() == before, "vault unchanged on fetch failure")
STATE["fail"] = False

def ent(i, pub, t="T", d="D", v=1, l=2, p="ph", w=1920, h=1080):
    return {"id": i, "published": pub, "width": w, "height": h, "title": t,
            "description": d, "views": v, "likes": l, "preview": p}

# --- first sync ---
STATE["payload"] = {
    "episodes": [ent("e2", "2024-05-02T10:00:00"), ent("e1", "2024-05-03"),
                 ent("a3", "2024-05-03T00:00:00")],
    "streams": [ent("s1", "2023-01-01T05:06:07", l=None)],
    "clips": [ent("c1", "2022-12-31T23:59:59")],
}
rc, out, err = run("sync", "v")
check(rc == 0, "first sync exit 0")
c = cat()
check(open("v/catalog.bak", "rb").read() == before, "catalog.bak = byte-for-byte pre-write copy")
e = entry(c, "episodes", "e1")
check(e["published"] == "2024-05-03T00:00:00", "date-only normalized to 00:00:00")
check(set(e) == {"id","published","width","height","title","description","views","likes","preview","removed"},
      "entry has static + 6 tracked fields")
for f in ("title","description","views","likes","preview","removed"):
    check(isinstance(e[f], dict) and len(e[f]) == 1, "initial history for %s" % f)
ts = list(e["title"])[0]
check(len(ts) == 19 and ts[10] == "T" and ts[4] == "-" and "+" not in ts and not ts.endswith("Z"),
      "timestamp format YYYY-MM-DDTHH:MM:SS")
check(cur(e["removed"]) is False, "removed=false at first observation")
check(cur(entry(c, "streams", "s1")["likes"]) is None, "null likes stored")
check([x["id"] for x in c["episodes"]] == ["a3", "e1", "e2"],
      "order: newest published first, ties by smaller id (got %s)" % [x["id"] for x in c["episodes"]])
check(c["version"] == 3 and c["source"] == URL, "root fields preserved")

# --- no-change sync ---
time.sleep(1.1)
rc, out, err = run("sync", "v")
c2 = cat()
e2 = entry(c2, "episodes", "e1")
check(all(len(e2[f]) == 1 for f in ("title","description","views","likes","preview","removed")),
      "unchanged values append nothing")

# --- change + removal ---
time.sleep(1.1)
STATE["payload"]["episodes"] = [ent("e1", "2024-05-03", t="NEW", v=99)]
STATE["payload"]["streams"] = [ent("s1", "2023-01-01T05:06:07", l=7)]
rc, out, err = run("sync", "v")
c3 = cat()
e3 = entry(c3, "episodes", "e1")
check(len(e3["title"]) == 2 and cur(e3["title"]) == "NEW", "changed title appended")
check(len(e3["views"]) == 2 and cur(e3["views"]) == 99, "changed views appended")
check(len(e3["description"]) == 1, "unchanged description not appended")
s1 = entry(c3, "streams", "s1")
check(len(s1["likes"]) == 2 and cur(s1["likes"]) == 7, "null -> number is a change")
gone = entry(c3, "episodes", "e2")
check(cur(gone["removed"]) is True and len(gone["removed"]) == 2, "absent entry -> removed:true")
check(len(c3["episodes"]) == 3, "removed entries never deleted")

time.sleep(1.1)
rc, out, err = run("sync", "v")
check(len(entry(cat(), "episodes", "e2")["removed"]) == 2, "removed stays true, no duplicate")

# --- restore ---
time.sleep(1.1)
STATE["payload"]["episodes"] = [ent("e1", "2024-05-03", t="NEW", v=99), ent("e2", "2024-05-02T10:00:00")]
run("sync", "v")
back = entry(cat(), "episodes", "e2")
check(cur(back["removed"]) is False and len(back["removed"]) == 3, "reappeared entry -> removed:false")

# --- strictly increasing timestamps across rapid syncs ---
time.sleep(1.1)
STATE["payload"]["episodes"][0]["title"] = "A1"
run("sync", "v")
STATE["payload"]["episodes"][0]["title"] = "A2"
run("sync", "v")
STATE["payload"]["episodes"][0]["title"] = "A3"
run("sync", "v")
h = entry(cat(), "episodes", "e1")["title"]
keys = sorted(h)
check(len(set(keys)) == len(keys) and len(h) >= 5, "no key collisions across rapid syncs")
check(keys == sorted(keys) and all(keys[i] < keys[i+1] for i in range(len(keys)-1)),
      "history keys strictly increasing")
check(h[keys[-1]] == "A3", "latest key holds current value")

# --- malformed source entries ---
before = open("v/catalog.json", "rb").read()
for bad in [{"id": "x"},
            dict(ent("x", "2024-01-01"), views="12"),
            dict(ent("x", "2024-01-01"), likes="5"),
            {k: v for k, v in ent("x", "2024-01-01").items() if k != "preview"},
            dict(ent("x", "2024-01-01"), width=1.5)]:
    STATE["payload"]["clips"] = [bad]
    rc, out, err = run("sync", "v")
    check(rc != 0 and err.strip(), "malformed entry -> fetch failure (%s)" % list(bad)[:3])
    check(open("v/catalog.json", "rb").read() == before, "vault unchanged on malformed source")

print()
print("FAILURES: %d" % len(fails))
for f in fails: print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
