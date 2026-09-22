import json, threading, time, http.server, socketserver, urllib.parse, urllib.request, subprocess, sys, os, socket

STATE = {"body": b"name,age\nAlice,30\nBob,25\n", "code": 200, "hits": 0}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        p = urllib.parse.urlsplit(self.path).path
        if p == "/hits":
            body = str(STATE["hits"]).encode(); code = 200
        elif p == "/t.csv":
            STATE["hits"] += 1
            body, code = STATE["body"], STATE["code"]
        else:
            body, code = b"nope", 404
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

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {extra}"))
    if not cond: fails.append(name)

def start(env_value=None):
    env = dict(os.environ)
    env.pop("CACHE_ENABLED", None)
    if env_value is not None: env["CACHE_ENABLED"] = env_value
    port = free_port()
    p = subprocess.Popen([sys.executable, "datagate.py", "start", "--port", str(port), "--address", "127.0.0.1"],
                         cwd="/workspace", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try: urllib.request.urlopen(base + "/", timeout=1); break
        except Exception: time.sleep(0.1)
    return p, base

def get(base, path):
    try:
        r = urllib.request.urlopen(base + path, timeout=30)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def hits():
    return int(urllib.request.urlopen(FIX + "/hits", timeout=5).read())

def conv(base, extra=""):
    return get(base, "/convert?source=" + urllib.parse.quote(FIX + "/t.csv", safe="") + extra)

# ---- caching enabled (default)
proc, BASE = start()
STATE["hits"] = 0
s, b = conv(BASE)
ep = b["endpoint"]
check("first convert", s == 200 and b == {"ok": True, "endpoint": ep}, b)
check("one download", hits() == 1, hits())
s2, b2 = conv(BASE)
check("cache hit identical", (s2, b2) == (s, b), (s2, b2))
check("cache avoids download", hits() == 1, hits())

STATE["body"] = b"name,age\nZoe,41\n"
_, b3 = conv(BASE)
_, d = get(BASE, ep)
check("cached data served", d["rows"] == [["Alice", 30], ["Bob", 25]], d["rows"])

# force
s4, b4 = conv(BASE, "&force")
check("force response identical", (s4, b4) == (200, {"ok": True, "endpoint": ep}), (s4, b4))
check("force re-downloads", hits() == 2, hits())
_, d = get(BASE, ep)
check("force replaced dataset", d["rows"] == [["Zoe", 41]], d["rows"])
for flag in ["&force=", "&force=1", "&force=whatever", "&force=0"]:
    before = hits()
    s5, b5 = conv(BASE, flag)
    check(f"force value [{flag}]", s5 == 200 and hits() == before + 1, (s5, b5, hits()))
for dup in ["&force&force", "&force=1&force=2", "&force=1&force=1"]:
    before = hits()
    s6, b6 = conv(BASE, dup)
    check(f"duplicate force 400 [{dup}]", s6 == 400 and b6["ok"] is False and isinstance(b6.get("error"), str), (s6, b6))
    check(f"duplicate force no fetch [{dup}]", hits() == before, hits())

# forced failure keeps the prior dataset queryable
STATE["code"] = 500
before = hits()
s7, b7 = conv(BASE, "&force")
check("forced failure 404", s7 == 404 and b7["ok"] is False and isinstance(b7.get("error"), str), (s7, b7))
s8, d = get(BASE, ep)
check("prior dataset still queryable", s8 == 200 and d["rows"] == [["Zoe", 41]], (s8, d))
STATE["body"] = b"<html>not tabular</html>"
STATE["code"] = 200
s9, b9 = conv(BASE, "&force")
check("forced parse failure 400", s9 == 400 and b9["ok"] is False, (s9, b9))
s10, d = get(BASE, ep)
check("dataset survives parse failure", s10 == 200 and d["rows"] == [["Zoe", 41]], (s10, d))
STATE["body"] = b"name,age\nZoe,41\n"
proc.terminate(); proc.wait(timeout=10)

# ---- caching disabled
for value in ["0", "false", "no", "off", "OFF", "No"]:
    proc, BASE = start(value)
    STATE["hits"] = 0
    STATE["body"] = b"name,age\nAlice,30\n"
    s, b = conv(BASE); ep = b["endpoint"]
    STATE["body"] = b"name,age\nZoe,41\n"
    s, b2 = conv(BASE)
    check(f"disabled[{value}] same id", b2["endpoint"] == ep, (ep, b2))
    check(f"disabled[{value}] re-downloads", hits() == 2, hits())
    _, d = get(BASE, ep)
    check(f"disabled[{value}] data replaced", d["rows"] == [["Zoe", 41]], d["rows"])
    s, b = conv(BASE, "&force")
    check(f"disabled[{value}] force ok", s == 200 and b["endpoint"] == ep and hits() == 3, (s, b, hits()))
    s, b = conv(BASE, "&force&force")
    check(f"disabled[{value}] duplicate force 400", s == 400 and b["ok"] is False, (s, b))
    proc.terminate(); proc.wait(timeout=10)

# ---- enabled spellings
for value in ["1", "true", "yes", "on", "TRUE", "Yes"]:
    proc, BASE = start(value)
    STATE["hits"] = 0
    s, b = conv(BASE); s, b = conv(BASE)
    check(f"enabled[{value}] caches", s == 200 and hits() == 1, (s, b, hits()))
    proc.terminate(); proc.wait(timeout=10)

# ---- charset is part of what is cached
proc, BASE = start()
STATE["hits"] = 0
STATE["body"] = "name,ville\nJos\u00e9,M\u00fcnch\u00e9n\n".encode("latin-1")
s, b = conv(BASE, "&charset=latin-1"); ep = b["endpoint"]
check("charset convert", s == 200, (s, b))
s, b2 = conv(BASE, "&charset=latin-1")
check("same charset cached", b2 == b and hits() == 1, (b2, hits()))
s, b3 = conv(BASE, "&charset=LATIN-1")
check("charset alias cached", b3 == b and hits() == 1, (b3, hits()))
s, b4 = conv(BASE, "&charset=utf-8")
check("different charset re-parsed", s == 400 and b4["ok"] is False, (s, b4))
s, d = get(BASE, ep)
check("failed re-parse keeps dataset", s == 200 and d["rows"] == [["Jos\u00e9", "M\u00fcnch\u00e9n"]], d)
s, b5 = conv(BASE, "&charset=nonsense-9000")
check("bad charset name 400 despite cache", s == 400 and b5["ok"] is False, (s, b5))
proc.terminate(); proc.wait(timeout=10)
STATE["body"] = b"name,age\nZoe,41\n"

# ---- invalid values fail startup
for value in ["maybe", "", "2", "tru", "on off", "enabled", "-1", "None"]:
    env = dict(os.environ); env["CACHE_ENABLED"] = value
    p = subprocess.run([sys.executable, "datagate.py", "start", "--port", str(free_port())],
                       cwd="/workspace", env=env, capture_output=True, timeout=30)
    check(f"invalid startup fails [{value!r}]", p.returncode != 0, (p.returncode, p.stderr[-200:]))

srv.shutdown()
print("\n%d failure(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
