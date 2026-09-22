import json, threading, time, http.server, socketserver, urllib.parse, urllib.request, subprocess, sys, os, socket

FIXTURES = {
    "/basic.csv": (200, "text/csv", "name,age,score\nAlice,30,9.5\nBob,25,8\n".encode()),
    "/semi.csv": (200, "text/csv", "city;pop;ratio\nParis;2148000;1.5\nLyon;513000;0.9\n".encode()),
    "/tab.csv": (200, "text/csv", "a\tb\tc\n1\t2\t3\n4\t5\t6\n".encode()),
    "/times.csv": (200, "text/csv", "event,start,end,dur\nstandup,08:30,9:15,15\nlunch,12:00,13:00,60\n".encode()),
    "/latin.csv": (200, "text/csv", "name;ville\nJosé;Münchén\nRené;Köln\n".encode("latin-1")),
    "/utf16.csv": (200, "text/csv", "a,b\n1,2\n3,4\n".encode("utf-16")),
    "/big.csv": (200, "text/csv", ("i,sq\n" + "".join(f"{i},{i*i}\n" for i in range(250))).encode()),
    "/headeronly.csv": (200, "text/csv", "a,b,c\n".encode()),
    "/notcsv.html": (200, "text/html", b"<html><body><h1>Hello</h1><p>not a csv, really</p></body></html>"),
    "/prose.txt": (200, "text/plain", b"This is just some prose text.\nIt has multiple lines.\nNothing tabular here at all.\n"),
    "/binary.bin": (200, "application/octet-stream", bytes(range(256))*4),
    "/json.json": (200, "application/json", b'{"a": 1, "b": [1,2,3]}'),
    "/quoted.csv": (200, "text/csv", b'name,note,n\n"Smith, John","said ""hi""",3\n"Doe, Jane","line\nbreak",4\n'),
    "/boom": (500, "text/plain", b"server error"),
    "/missing": (404, "text/plain", b"nope"),
}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in FIXTURES:
            code, ctype, body = FIXTURES[path]
        else:
            code, ctype, body = 404, "text/plain", b"not found"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

FIX_PORT = free_port()
srv = socketserver.ThreadingTCPServer(("127.0.0.1", FIX_PORT), H)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
FIX = f"http://127.0.0.1:{FIX_PORT}"

PORT = free_port()
proc = subprocess.Popen([sys.executable, "datagate.py", "start", "--port", str(PORT), "--address", "127.0.0.1"],
                        cwd="/workspace", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = f"http://127.0.0.1:{PORT}"
for _ in range(100):
    try:
        urllib.request.urlopen(BASE + "/", timeout=1); break
    except Exception: time.sleep(0.1)

fails = []
def get(path):
    req = urllib.request.Request(BASE + path, headers={"Origin": "http://example.com"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()), dict(e.headers)

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {extra}"))
    if not cond: fails.append(name)

def conv(src, charset=None):
    q = {"source": src}
    if charset is not None: q["charset"] = charset
    return get("/convert?" + urllib.parse.urlencode(q))

# --- happy path
s, b, h = conv(FIX + "/basic.csv")
check("convert 200", s == 200 and b.get("ok") is True and b["endpoint"].startswith("/datasets/"), (s, b))
check("cors on convert", h.get("Access-Control-Allow-Origin") == "*", h)
ep = b["endpoint"]
s2, b2, _ = conv(FIX + "/basic.csv")
check("deterministic id", b2["endpoint"] == ep, (ep, b2))

s, b, h = get(ep)
check("dataset 200", s == 200 and b["ok"] is True, (s, b))
check("columns", b["columns"] == ["name", "age", "score"], b.get("columns"))
check("rows+types", b["rows"] == [["Alice", 30, 9.5], ["Bob", 25, 8]], b.get("rows"))
check("query_ms", isinstance(b.get("query_ms"), (int, float)) and b["query_ms"] >= 0, b.get("query_ms"))
check("cors on dataset", h.get("Access-Control-Allow-Origin") == "*", h)

# --- delimiters
for name, path, cols, row0 in [
    ("semicolon", "/semi.csv", ["city","pop","ratio"], ["Paris", 2148000, 1.5]),
    ("tab", "/tab.csv", ["a","b","c"], [1,2,3]),
]:
    _, b, _ = conv(FIX + path); _, d, _ = get(b["endpoint"])
    check(f"delim {name}", d["columns"] == cols and d["rows"][0] == row0, d)

# --- time-like
_, b, _ = conv(FIX + "/times.csv"); _, d, _ = get(b["endpoint"])
check("time stays text", d["rows"] == [["standup","08:30","9:15",15],["lunch","12:00","13:00",60]], d["rows"])

# --- limit
_, b, _ = conv(FIX + "/big.csv"); _, d, _ = get(b["endpoint"])
check("row limit 100", len(d["rows"]) == 100 and d["rows"][0] == [0,0] and d["rows"][99] == [99, 99*99], len(d["rows"]))

# --- quoted / embedded
_, b, _ = conv(FIX + "/quoted.csv"); _, d, _ = get(b["endpoint"])
check("quoted fields", d["rows"][0] == ["Smith, John", 'said "hi"', 3], d["rows"])

# --- charset
_, b, _ = conv(FIX + "/latin.csv", charset="latin-1"); _, d, _ = get(b["endpoint"])
check("explicit charset", d["rows"][0] == ["José","Münchén"], d["rows"])
_, b, _ = conv(FIX + "/latin.csv"); _, d, _ = get(b["endpoint"])
check("detected charset", d["rows"][0][0].startswith("Jos"), d["rows"])
_, b, _ = conv(FIX + "/utf16.csv"); _, d, _ = get(b["endpoint"])
check("utf16 bom detect", d["columns"] == ["a","b"] and d["rows"][0] == [1,2], d)
s, b, _ = conv(FIX + "/basic.csv", charset="nonsense-9000")
check("bad charset 400", s == 400 and b["ok"] is False and "error" in b, (s,b))
s, b, _ = conv(FIX + "/utf16.csv", charset="utf-8")
check("undecodable charset 400", s == 400, (s,b))
s, b, _ = conv(FIX + "/basic.csv", charset="")
check("empty charset 400", s == 400, (s,b))

# --- errors
s, b, _ = get("/convert")
check("missing source 400", s == 400 and b["ok"] is False, (s,b))
for bad in ["not a url", "ftp://x/y.csv", "http://", "/relative.csv", "htp:/x"]:
    s, b, _ = conv(bad)
    check(f"invalid url 400 [{bad}]", s == 400, (s,b))
s, b, _ = conv(FIX + "/missing")
check("remote 404 -> 404", s == 404 and b["ok"] is False, (s,b))
s, b, _ = conv(FIX + "/boom")
check("remote 500 -> 404", s == 404, (s,b))
s, b, _ = conv("http://127.0.0.1:1/never.csv")
check("unreachable -> 404", s == 404, (s,b))
s, b, _ = conv("http://nonexistent.invalid.example/x.csv")
check("dns fail -> 404", s == 404, (s,b))
for name, path in [("html","/notcsv.html"),("prose","/prose.txt"),("binary","/binary.bin"),
                   ("json","/json.json"),("header only","/headeronly.csv")]:
    s, b, _ = conv(FIX + path)
    check(f"non-tabular 400 [{name}]", s == 400 and b["ok"] is False, (s,b))

s, b, _ = get("/datasets/deadbeefdeadbeef")
check("unknown dataset 404", s == 404 and b["ok"] is False and isinstance(b.get("error"), str), (s,b))
s, b, _ = get("/nope/route")
check("unknown route 404 json", s == 404 and b["ok"] is False, (s,b))

proc.terminate(); proc.wait(timeout=10); srv.shutdown()
print("\n%d failure(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
