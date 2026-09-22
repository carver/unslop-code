import json, threading, time, http.server, socketserver, urllib.parse, urllib.request, subprocess, sys, socket

CSV = ("name,age,score\n"
       "Alice,30,9.5\n"
       "bob,25,8\n"
       "Carol,25,7.25\n"
       "dave,40,\n"
       "Eve,25,9.5\n")
BIG = "i,sq\n" + "".join(f"{i},{i*i}\n" for i in range(250))

FIXTURES = {
    "/t.csv": CSV.encode(),
    "/big.csv": BIG.encode(),
}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        p = urllib.parse.urlsplit(self.path).path
        body = FIXTURES.get(p, b"nope")
        code = 200 if p in FIXTURES else 404
        self.send_response(code); self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

FP = free_port()
srv = socketserver.ThreadingTCPServer(("127.0.0.1", FP), H); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
FIX = f"http://127.0.0.1:{FP}"

PORT = free_port()
proc = subprocess.Popen([sys.executable, "datagate.py", "start", "--port", str(PORT), "--address", "127.0.0.1"],
                        cwd="/workspace", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = f"http://127.0.0.1:{PORT}"
for _ in range(100):
    try: urllib.request.urlopen(BASE + "/", timeout=1); break
    except Exception: time.sleep(0.1)

fails = []
def get(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=30)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {extra}"))
    if not cond: fails.append(name)

def conv(src):
    return get("/convert?" + urllib.parse.urlencode({"source": src}))

_, b = conv(FIX + "/t.csv"); EP = b["endpoint"]
_, b = conv(FIX + "/big.csv"); BEP = b["endpoint"]

def q(ep, qs): return get(ep + ("?" + qs if qs else ""))

# total
s, b = q(EP, "")
check("total present", s == 200 and b["total"] == 5, b)
check("default shape lists", isinstance(b["rows"][0], list), b["rows"][0])
s, b = q(BEP, "")
check("default size 100", len(b["rows"]) == 100 and b["total"] == 250, (len(b["rows"]), b.get("total")))

# pagination
s, b = q(EP, "_size=2")
check("_size=2", s == 200 and b["rows"] == [["Alice",30,9.5],["bob",25,8]] and b["total"] == 5, b)
s, b = q(EP, "_size=999")
check("_size > rows returns all", len(b["rows"]) == 5, b)
s, b = q(EP, "_offset=3")
check("_offset=3", [r[0] for r in b["rows"]] == ["dave","Eve"], b)
s, b = q(EP, "_offset=2&_size=2")
check("offset+size", [r[0] for r in b["rows"]] == ["Carol","dave"], b)
s, b = q(EP, "_offset=99")
check("offset past end", b["rows"] == [] and b["total"] == 5, b)
s, b = q(EP, "_offset=0&_size=5")
check("explicit defaults", len(b["rows"]) == 5, b)

for bad in ["_size=0", "_size=-1", "_size=abc", "_size=", "_size=1.5", "_size=1e3", "_size=+0"]:
    s, b = q(EP, bad)
    check(f"bad [{bad}]", s == 400 and b["ok"] is False and isinstance(b.get("error"), str), (s,b))
for bad in ["_offset=-1", "_offset=abc", "_offset=", "_offset=2.0"]:
    s, b = q(EP, bad)
    check(f"bad [{bad}]", s == 400 and b["ok"] is False, (s,b))

# sorting
s, b = q(EP, "_sort=age")
check("_sort asc stable", [r[0] for r in b["rows"]] == ["bob","Carol","Eve","Alice","dave"], b["rows"])
s, b = q(EP, "_sort_desc=age")
check("_sort_desc stable", [r[0] for r in b["rows"]] == ["dave","Alice","bob","Carol","Eve"], b["rows"])
s, b = q(EP, "_sort=name")
check("_sort text", [r[0] for r in b["rows"]] == ["Alice","Carol","Eve","bob","dave"], b["rows"])
s, b = q(EP, "_sort=age&_sort_desc=name")
check("_sort_desc wins", [r[0] for r in b["rows"]] == ["dave","bob","Eve","Carol","Alice"], b["rows"])
s, b = q(EP, "_sort=age&_size=2")
check("sort before pagination", [r[0] for r in b["rows"]] == ["bob","Carol"] and b["total"] == 5, b)
s, b = q(EP, "_sort=age&_offset=1&_size=2")
check("sort+offset", [r[0] for r in b["rows"]] == ["Carol","Eve"], b["rows"])
for bad in ["_sort=", "_sort_desc=", "_sort=nope", "_sort_desc=nope", "_sort=AGE"]:
    s, b = q(EP, bad)
    check(f"bad sort [{bad}]", s == 400 and b["ok"] is False, (s,b))

# shape
s, b = q(EP, "_shape=objects&_size=2")
check("objects shape", s == 200 and b["rows"] == [
    {"rowid":1,"name":"Alice","age":30,"score":9.5},
    {"rowid":2,"name":"bob","age":25,"score":8}], b["rows"])
check("rowid not in columns", b["columns"] == ["name","age","score"], b["columns"])
s, b = q(EP, "_shape=lists&_size=1")
check("lists shape explicit", b["rows"] == [["Alice",30,9.5]], b["rows"])
s, b = q(EP, "_shape=objects&_sort_desc=age&_size=1")
check("rowid follows source row", b["rows"][0]["rowid"] == 4 and b["rows"][0]["name"] == "dave", b["rows"])
s, b = q(EP, "_shape=objects&_offset=4")
check("rowid after offset", b["rows"][0]["rowid"] == 5, b["rows"])
for bad in ["_shape=list", "_shape=", "_shape=object", "_shape=arrays", "_shape=OBJECTS"]:
    s, b = q(EP, bad)
    check(f"bad shape [{bad}]", s == 400 and b["ok"] is False, (s,b))

# toggles
s, b = q(EP, "_shape=objects&_rowid=hide&_size=1")
check("_rowid=hide", "rowid" not in b["rows"][0] and b["rows"][0] == {"name":"Alice","age":30,"score":9.5}, b["rows"])
s, b = q(EP, "_total=hide")
check("_total=hide", "total" not in b, b)
s, b = q(EP, "_shape=objects&_rowid=hide&_total=hide&_size=1")
check("both hidden", "total" not in b and "rowid" not in b["rows"][0], b)
s, b = q(EP, "_rowid=hide")
check("_rowid=hide on lists ok", s == 200 and b["rows"][0] == ["Alice",30,9.5], (s,b))
for bad in ["_rowid=show", "_rowid=", "_rowid=1", "_rowid=hidden", "_total=show", "_total=", "_total=HIDE"]:
    s, b = q(EP, bad)
    check(f"bad toggle [{bad}]", s == 400 and b["ok"] is False, (s,b))

# repeats
for p in ["_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total"]:
    vals = {"_size":"2","_offset":"1","_shape":"lists","_sort":"age","_sort_desc":"age","_rowid":"hide","_total":"hide"}[p]
    s, b = q(EP, f"{p}={vals}&{p}={vals}")
    check(f"repeat [{p}]", s == 400 and b["ok"] is False, (s,b))
s, b = q(EP, "_size=2&_size=3")
check("repeat differing _size", s == 400, (s,b))
s, b = q(EP, "_sort=age&_sort=name")
check("repeat _sort", s == 400, (s,b))

# unknown dataset still 404 even with bad params
s, b = q("/datasets/deadbeefdeadbeef", "_size=0")
check("unknown dataset wins", s == 404, (s,b))

proc.terminate(); proc.wait(timeout=10); srv.shutdown()
print("\n%d failure(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
