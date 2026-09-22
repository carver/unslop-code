import json, threading, time, http.server, socketserver, urllib.parse, urllib.request, subprocess, sys, socket

CSV = ("name,age,score,note\n"
       "Alice,30,9.5,hello world\n"
       "bob,25,8,Hello\n"
       "Carol,25,7.25,world\n"
       "dave,40,,n/a\n"
       "Eve,25,9.5,HELLO there\n")
ODD = ("id,my__col,mix\n"
       "1,x,10\n"
       "2,y,abc\n"
       "3,x,\n")

FIXTURES = {"/t.csv": CSV.encode(), "/odd.csv": ODD.encode()}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        p = urllib.parse.urlsplit(self.path).path
        body = FIXTURES.get(p, b"nope"); code = 200 if p in FIXTURES else 404
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

def conv(src): return get("/convert?" + urllib.parse.urlencode({"source": src}))
_, b = conv(FIX + "/t.csv"); EP = b["endpoint"]
_, b = conv(FIX + "/odd.csv"); OEP = b["endpoint"]
def q(ep, qs): return get(ep + ("?" + qs if qs else ""))
def names(b): return [r[0] for r in b["rows"]]

# --- exact
s, b = q(EP, "name__exact=Alice")
check("exact", s == 200 and names(b) == ["Alice"] and b["total"] == 1, b)
s, b = q(EP, "name__exact=alice")
check("exact case-sensitive", s == 200 and b["rows"] == [] and b["total"] == 0, b)
s, b = q(EP, "age__exact=25")
check("exact numeric cell", names(b) == ["bob","Carol","Eve"] and b["total"] == 3, b)
s, b = q(EP, "score__exact=9.5")
check("exact float cell", names(b) == ["Alice","Eve"], b)
s, b = q(EP, "score__exact=")
check("exact empty cell", names(b) == ["dave"], b)
s, b = q(EP, "name__exact=zzz")
check("exact no match", b["rows"] == [] and b["total"] == 0, b)

# --- contains
s, b = q(EP, "note__contains=world")
check("contains", names(b) == ["Alice","Carol"], b)
s, b = q(EP, "note__contains=Hello")
check("contains case-sensitive", names(b) == ["bob"], b)
s, b = q(EP, "name__contains=a")
check("contains substring", names(b) == ["Carol","dave"], b)
s, b = q(EP, "note__contains=")
check("contains empty matches all", b["total"] == 5, b)

# --- less / greater
s, b = q(EP, "age__less=30")
check("less", names(b) == ["bob","Carol","Eve"], b)
s, b = q(EP, "age__greater=25")
check("greater", names(b) == ["Alice","dave"], b)
s, b = q(EP, "age__less=25")
check("less strict", b["rows"] == [], b)
s, b = q(EP, "age__greater=40")
check("greater strict", b["rows"] == [], b)
s, b = q(EP, "age__less=27.5")
check("less float filter", names(b) == ["bob","Carol","Eve"], b)
s, b = q(EP, "score__greater=0")
check("non-numeric stored excluded", names(b) == ["Alice","bob","Carol","Eve"] and b["total"] == 4, b)
s, b = q(EP, "score__less=100")
check("non-numeric stored excluded (less)", names(b) == ["Alice","bob","Carol","Eve"], b)
s, b = q(OEP, "mix__greater=-1")
check("mixed column numeric only", [r[0] for r in b["rows"]] == [1] and b["total"] == 1, b)

# --- AND
s, b = q(EP, "age__exact=25&score__greater=7.5")
check("AND two filters", names(b) == ["bob","Eve"] and b["total"] == 2, b)
s, b = q(EP, "age__less=41&age__greater=26")
check("AND same column", names(b) == ["Alice","dave"], b)
s, b = q(EP, "name__contains=e&age__exact=25&score__exact=9.5")
check("AND three filters", names(b) == ["Eve"], b)
s, b = q(EP, "age__exact=25&age__exact=40".replace("age__exact=40","name__exact=zzz"))
check("AND empty result", b["rows"] == [] and b["total"] == 0, b)

# --- with sort / pagination
s, b = q(EP, "age__exact=25&_sort=score")
check("filter then sort", names(b) == ["Carol","bob","Eve"], b)
s, b = q(EP, "age__exact=25&_sort=score&_size=1")
check("filter+sort+size", names(b) == ["Carol"] and b["total"] == 3, b)
s, b = q(EP, "age__exact=25&_sort=score&_offset=1&_size=1")
check("filter+sort+offset", names(b) == ["bob"] and b["total"] == 3, b)
s, b = q(EP, "age__exact=25&_size=2")
check("total is filtered pre-pagination", len(b["rows"]) == 2 and b["total"] == 3, b)
s, b = q(EP, "age__exact=25&_shape=objects&_size=1")
check("filter+objects rowid", b["rows"][0] == {"rowid":2,"name":"bob","age":25,"score":8,"note":"Hello"}, b["rows"])
s, b = q(EP, "age__exact=25&_total=hide")
check("filter+_total=hide", "total" not in b and len(b["rows"]) == 3, b)

# --- errors
for bad in ["name__nope=x", "name__EXACT=Alice", "name__Contains=x", "name__=x",
            "age__lessthan=1", "name__exact__x=1"]:
    s, b = q(EP, bad)
    check(f"bad comparator [{bad}]", s == 400 and b["ok"] is False and isinstance(b.get("error"), str), (s,b))
for bad in ["nope__exact=x", "NAME__exact=Alice", "Age__less=1", "name __exact=x"]:
    s, b = q(EP, urllib.parse.quote(bad, safe="=&"))
    check(f"unknown column [{bad}]", s == 400 and b["ok"] is False, (s,b))
for bad in ["age__less=abc", "age__greater=abc", "age__less=", "age__greater=",
            "age__less=1,5", "age__greater=ten", "age__less=%20"]:
    s, b = q(EP, bad)
    check(f"non-numeric filter value [{bad}]", s == 400 and b["ok"] is False, (s,b))
for bad in ["name__exact=a&name__exact=b", "name__exact=a&name__exact=a",
            "age__less=30&age__less=20", "note__contains=x&note__contains=y"]:
    s, b = q(EP, bad)
    check(f"duplicate filter key [{bad}]", s == 400 and b["ok"] is False, (s,b))

# --- ignored params
s, b = q(EP, "foo=bar")
check("no-__ param ignored", s == 200 and b["total"] == 5, b)
s, b = q(EP, "name=Alice")
check("bare column ignored", s == 200 and b["total"] == 5, b)
s, b = q(EP, "foo=bar&foo=baz")
check("duplicate non-filter ignored", s == 200 and b["total"] == 5, b)
s, b = q(EP, "name__exact=Alice&foo=bar")
check("ignored alongside filter", names(b) == ["Alice"], b)
s, b = q(EP, "_unknown=1")
check("unknown control ignored", s == 200 and b["total"] == 5, b)
s, b = q(EP, "_x__exact=Alice")
check("underscore-prefixed not a filter", s == 200 and b["total"] == 5, b)
s, b = q(EP, "__exact=x")
check("leading-underscore key not a filter", s == 200 and b["total"] == 5, b)

# --- column names containing __
s, b = q(OEP, "my__col__exact=x")
check("column with __ in name", [r[0] for r in b["rows"]] == [1,3] and b["total"] == 2, b)
s, b = q(OEP, "my__col__contains=y")
check("column with __ contains", [r[0] for r in b["rows"]] == [2], b)

# --- unknown dataset still wins
s, b = q("/datasets/deadbeefdeadbeef", "nope__exact=1")
check("unknown dataset wins over filter error", s == 404, (s,b))

proc.terminate(); proc.wait(timeout=10); srv.shutdown()
print("\n%d failure(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
