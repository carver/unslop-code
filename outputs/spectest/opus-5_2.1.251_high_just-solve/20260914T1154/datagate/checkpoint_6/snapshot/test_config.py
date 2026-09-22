import json, threading, time, http.server, socketserver, urllib.parse, urllib.request, urllib.error, subprocess, sys, os, socket, tempfile, shutil, io

BIG = ("a,b\n" + "".join(f"{i},{i*i}\n" for i in range(200))).encode()
SMALL = b"name,age\nAlice,30\nBob,25\n"
EXACT = b"a,b\n1,2\n"   # len used as an exact limit

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        p = urllib.parse.urlsplit(self.path).path
        body = {"/small.csv": SMALL, "/big.csv": BIG, "/exact.csv": EXACT}.get(p)
        if body is None:
            body, code = b"nope", 404
        else:
            code = 200
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

BASE_ENV = {k: v for k, v in os.environ.items()
            if k not in ("MAX_SOURCE_SIZE", "ORIGIN_ALLOWLIST", "REQUIRE_TLS",
                         "STORAGE_DIR", "CACHE_ENABLED", "DATAGATE_CONFIG")}

def start(**env_extra):
    env = dict(BASE_ENV); env.update({k: str(v) for k, v in env_extra.items()})
    port = free_port()
    p = subprocess.Popen([sys.executable, "datagate.py", "start", "--port", str(port)],
                         cwd="/workspace", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/", headers={"Referer": "http://probe.invalid/"}), timeout=1); break
        except urllib.error.HTTPError: break
        except Exception:
            if p.poll() is not None: break
            time.sleep(0.1)
    return p, base

def req(base, path, headers=None, data=None, ctype=None):
    h = dict(headers or {})
    if ctype: h["Content-Type"] = ctype
    r = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try: return e.code, json.loads(raw)
        except ValueError: return e.code, raw

def conv(base, path="/small.csv", headers=None):
    return req(base, "/convert?source=" + urllib.parse.quote(FIX + path, safe=""), headers=headers)

def multipart(content, filename="d.csv"):
    b = "----x9"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: text/csv\r\n\r\n").encode() + content + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"

def upload(base, content, headers=None):
    body, ctype = multipart(content)
    return req(base, "/upload", headers=headers, data=body, ctype=ctype)

def envelope(b, ok=False):
    return isinstance(b, dict) and b.get("ok") is ok and isinstance(b.get("error"), str) and b["error"]

def write_config(text):
    fd, path = tempfile.mkstemp(suffix=".conf"); os.write(fd, text.encode()); os.close(fd)
    return path

# ------------------------------------------------------------------ size limit
p, B = start(MAX_SOURCE_SIZE=len(EXACT))
s, b = conv(B, "/exact.csv")
check("size == limit accepted", s == 200 and b["ok"] is True, (s, b))
s, b = conv(B, "/small.csv")
check("size > limit 400", s == 400 and envelope(b), (s, b))
s, b = upload(B, EXACT)
check("upload == limit accepted", s == 200 and b["ok"] is True, (s, b))
s, b = upload(B, EXACT + b"3,4\n")
check("upload > limit 400", s == 400 and envelope(b), (s, b))
p.terminate(); p.wait(timeout=10)

p, B = start()
s, b = conv(B, "/big.csv")
check("unset limit no max", s == 200 and b["ok"] is True, (s, b))
s, b = upload(B, BIG)
check("unset limit upload ok", s == 200 and b["ok"] is True, (s, b))
p.terminate(); p.wait(timeout=10)

# --------------------------------------------------------------- origin allowlist
p, B = start(ORIGIN_ALLOWLIST="example.com,foo.org")
s, b = req(B, "/")
check("missing referer 403", s == 403 and envelope(b), (s, b))
for ref, expect in [("http://example.com/", 200), ("https://EXAMPLE.COM/x", 200),
                    ("http://a.b.example.com/p", 200), ("http://foo.org/", 200),
                    ("http://notexample.com/", 403), ("http://example.com.evil.net/", 403),
                    ("http://evilexample.com/", 403), ("http://foo.org.uk/", 403),
                    ("garbage", 403), ("", 403)]:
    s, b = req(B, "/", headers={"Referer": ref})
    check(f"referer {ref!r} -> {expect}", s == expect and (expect == 200 or envelope(b)), (s, b))
s, b = req(B, "/nope", headers={"Referer": "http://bad.com/"})
check("allowlist checked before routing", s == 403 and envelope(b), (s, b))
s, b = conv(B, headers={"Referer": "http://example.com/"})
check("allowed convert works", s == 200 and b["ok"] is True, (s, b))
s, b = conv(B)
check("convert without referer 403", s == 403, (s, b))
p.terminate(); p.wait(timeout=10)

p, B = start()
s, b = req(B, "/")
check("no allowlist passes", s == 200 and b["ok"] is True, (s, b))
p.terminate(); p.wait(timeout=10)

# ------------------------------------------------------------------ require tls
p, B = start()
s, b = conv(B)
check("relative endpoint default", s == 200 and b["endpoint"].startswith("/datasets/"), b)
s2, b2 = upload(B, SMALL)
check("relative upload endpoint", b2["endpoint"].startswith("/datasets/"), b2)
p.terminate(); p.wait(timeout=10)

p, B = start(REQUIRE_TLS="true")
host = B.split("//", 1)[1]
s, b = conv(B)
check("tls convert endpoint absolute", s == 200 and b["endpoint"] == f"https://{host}/datasets/" + b["endpoint"].rsplit("/", 1)[1], b)
s, b2 = upload(B, SMALL)
check("tls upload endpoint absolute", b2["endpoint"].startswith(f"https://{host}/datasets/"), b2)
s, d = req(B, "/datasets/" + b["endpoint"].rsplit("/", 1)[1])
check("tls dataset still queryable", s == 200 and d["rows"] == [["Alice", 30], ["Bob", 25]], d)
p.terminate(); p.wait(timeout=10)

# ------------------------------------------------------------------- storage dir
tmp = tempfile.mkdtemp()
store = os.path.join(tmp, "nested", "store")
p, B = start(STORAGE_DIR=store)
check("storage dir created", os.path.isdir(store), store)
s, b = conv(B); ep = b["endpoint"]
s, b2 = upload(B, b"x,y\n7,8\n"); uep = b2["endpoint"]
p.terminate(); p.wait(timeout=10)
p, B2 = start(STORAGE_DIR=store)
s, d = req(B2, ep)
check("converted dataset survives restart", s == 200 and d["rows"] == [["Alice", 30], ["Bob", 25]], (s, d))
s, d = req(B2, uep)
check("uploaded dataset survives restart", s == 200 and d["rows"] == [[7, 8]], (s, d))
p.terminate(); p.wait(timeout=10)
p, B3 = start()
s, d = req(B3, ep)
check("fresh default store is empty", s == 404 and envelope(d), (s, d))
p.terminate(); p.wait(timeout=10)
shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------------------------------ config file
cfg = write_config("""
# datagate config
MAX_SOURCE_SIZE = %d

ORIGIN_ALLOWLIST=example.com, foo.org
REQUIRE_TLS=yes
CACHE_ENABLED=off
; semicolon comment
""" % len(EXACT))
p, B = start(DATAGATE_CONFIG=cfg)
host = B.split("//", 1)[1]
s, b = conv(B, "/exact.csv", headers={"Referer": "http://example.com/"})
check("file config: size ok + tls", s == 200 and b["endpoint"].startswith(f"https://{host}/"), (s, b))
s, b = conv(B, "/small.csv", headers={"Referer": "http://example.com/"})
check("file config: size limit", s == 400 and envelope(b), (s, b))
s, b = conv(B, "/exact.csv")
check("file config: allowlist", s == 403 and envelope(b), (s, b))
p.terminate(); p.wait(timeout=10)

# env overrides file
p, B = start(DATAGATE_CONFIG=cfg, REQUIRE_TLS="false", MAX_SOURCE_SIZE=10 ** 6, ORIGIN_ALLOWLIST="other.test")
s, b = conv(B, "/big.csv", headers={"Referer": "http://other.test/"})
check("env overrides file size+tls", s == 200 and b["endpoint"].startswith("/datasets/"), (s, b))
s, b = conv(B, "/big.csv", headers={"Referer": "http://example.com/"})
check("env overrides file allowlist", s == 403 and envelope(b), (s, b))
p.terminate(); p.wait(timeout=10)
os.unlink(cfg)

# ---------------------------------------------------------- invalid config exits
def startup_fails(label, **env_extra):
    env = dict(BASE_ENV); env.update({k: str(v) for k, v in env_extra.items()})
    r = subprocess.run([sys.executable, "datagate.py", "start", "--port", str(free_port())],
                       cwd="/workspace", env=env, capture_output=True, timeout=30)
    check(f"startup fails [{label}]", r.returncode != 0, (r.returncode, r.stderr[-200:]))

startup_fails("MAX_SOURCE_SIZE=abc", MAX_SOURCE_SIZE="abc")
startup_fails("MAX_SOURCE_SIZE=-1", MAX_SOURCE_SIZE="-1")
startup_fails("MAX_SOURCE_SIZE=1.5", MAX_SOURCE_SIZE="1.5")
startup_fails("MAX_SOURCE_SIZE empty", MAX_SOURCE_SIZE="")
startup_fails("REQUIRE_TLS=maybe", REQUIRE_TLS="maybe")
startup_fails("CACHE_ENABLED=2", CACHE_ENABLED="2")
startup_fails("missing config file", DATAGATE_CONFIG="/nonexistent/datagate.conf")
bad = write_config("MAX_SOURCE_SIZE=oops\n"); startup_fails("bad value in file", DATAGATE_CONFIG=bad); os.unlink(bad)
bad = write_config("this is not a pair\n"); startup_fails("malformed line", DATAGATE_CONFIG=bad); os.unlink(bad)
bad = write_config("REQUIRE_TLS=sometimes\n"); startup_fails("bad bool in file", DATAGATE_CONFIG=bad); os.unlink(bad)
d = tempfile.mkdtemp(); fpath = os.path.join(d, "afile"); open(fpath, "w").close()
startup_fails("storage dir is a file", STORAGE_DIR=fpath); shutil.rmtree(d, ignore_errors=True)

srv.shutdown()
print("\n%d failure(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
