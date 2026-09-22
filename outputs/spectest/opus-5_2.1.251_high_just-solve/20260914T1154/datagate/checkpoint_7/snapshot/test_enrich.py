import json, threading, time, http.server, socketserver, urllib.parse, urllib.request, urllib.error, subprocess, sys, os, socket, io

import openpyxl, xlwt

def xlsx_bytes():
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["city", "pop"]); ws.append(["Paris", 2148000]); ws.append(["Lyon", 513000])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

def xls_bytes():
    wb = xlwt.Workbook(); ws = wb.add_sheet("s")
    for r, row in enumerate([["city", "pop"], ["Paris", 2148000], ["Lyon", 513000]]):
        for c, v in enumerate(row): ws.write(r, c, v)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

CSV1 = b"name,age,score,note\nAlice,30,9.5,hi\nBob,25,8.25,\nAlice,40,7,x\n"
CSV2 = b"name,age,score,note\nZoe,41,1.5,q\n"

STATE = {"/t.csv": CSV1, "/x.xlsx": xlsx_bytes(), "/x.xls": xls_bytes(),
         "/bad.csv": b"<html>nope</html>"}
HITS = {"n": 0}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        p = urllib.parse.urlsplit(self.path).path
        if p in STATE:
            HITS["n"] += 1; body, code = STATE[p], 200
        else:
            body, code = b"nope", 404
        self.send_response(code); self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
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

def start(env=None):
    e = dict(os.environ); e.pop("CACHE_ENABLED", None); e.update(env or {})
    port = free_port()
    p = subprocess.Popen([sys.executable, "datagate.py", "start", "--port", str(port), "--address", "127.0.0.1"],
                         cwd="/workspace", env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

def conv(base, path="/t.csv", extra=""):
    return get(base, "/convert?source=" + urllib.parse.quote(FIX + path, safe="") + extra)

proc, BASE = start()

# ---- trigger ----
s, b = conv(BASE, extra="&enrich=yes")
ep = b["endpoint"]
check("enrich response shape", s == 200 and b == {"ok": True, "endpoint": ep}, b)
s, d = get(BASE, ep)
check("summary present", d.get("dataset_summary") == {"filetype": "csv", "row_count": 3, "column_count": 4}, d.get("dataset_summary"))
cd = d.get("column_details") or {}
check("details keys", set(cd) == {"name", "age", "score", "note"}, list(cd))
check("name col", cd.get("name") == {"type": "text", "distinct_count": 2, "missing_count": 0}, cd.get("name"))
check("age col", cd.get("age") == {"type": "integer", "distinct_count": 3, "missing_count": 0}, cd.get("age"))
check("score col", cd.get("score") == {"type": "number", "distinct_count": 3, "missing_count": 0}, cd.get("score"))
check("note col", cd.get("note") == {"type": "text", "distinct_count": 2, "missing_count": 1}, cd.get("note"))
check("core keys unchanged", d["ok"] is True and d["total"] == 3 and len(d["rows"]) == 3 and isinstance(d["query_ms"], float), d)
# metadata unaffected by query controls
s, d2 = get(BASE, ep + "?_size=1&name__exact=Alice")
check("metadata stable under query", d2["dataset_summary"] == d["dataset_summary"] and d2["column_details"] == cd and d2["total"] == 2, d2)

# ---- non-trigger spellings keep enrichment off ----
for extra in ["", "&enrich", "&enrich=", "&enrich=YES", "&enrich=Yes", "&enrich=%20yes", "&enrich=yes%20",
              "&enrich=1", "&enrich=true", "&enrich=no", "&enrich=yess", "&enrich=yes&enrich=yes"]:
    s, b = conv(BASE, "/t.csv", extra + "&force")
    s2, d = get(BASE, b["endpoint"])
    ok = s == 200 and "dataset_summary" not in d and "column_details" not in d
    check(f"no enrich [{extra!r}]", ok, (s, list(d)))

# ---- excel ----
for path, name in [("/x.xlsx", "xlsx"), ("/x.xls", "xls")]:
    s, b = conv(BASE, path, "&enrich=yes")
    s, d = get(BASE, b["endpoint"])
    summary = d.get("dataset_summary") or {}
    check(f"{name} filetype excel", summary.get("filetype") == "excel", summary)
    check(f"{name} no column_details", "column_details" not in d, list(d))
    s, b = conv(BASE, path, "&force")
    s, d = get(BASE, b["endpoint"])
    check(f"{name} non-enriched plain", "dataset_summary" not in d and "column_details" not in d, list(d))

# ---- cache interaction ----
proc.terminate(); proc.wait(timeout=10)
proc, BASE = start()
HITS["n"] = 0
s, b = conv(BASE); ep = b["endpoint"]
check("plain convert 1 hit", HITS["n"] == 1, HITS["n"])
s, b = conv(BASE)
check("plain cached", HITS["n"] == 1, HITS["n"])
s, b = conv(BASE, extra="&enrich=yes")
check("enrich forces re-ingest", HITS["n"] == 2 and b == {"ok": True, "endpoint": ep}, (HITS["n"], b))
s, d = get(BASE, ep)
check("upgraded stored state", "dataset_summary" in d, list(d))
s, b = conv(BASE, extra="&enrich=yes")
check("enriched cache hit", HITS["n"] == 2, HITS["n"])
s, b = conv(BASE)
check("plain request cached on enriched", HITS["n"] == 2, HITS["n"])
s, d = get(BASE, ep)
check("no downgrade without re-ingest", "dataset_summary" in d, list(d))
# recompute from current bytes
STATE["/t.csv"] = CSV2
s, b = conv(BASE, extra="&enrich=yes&force")
s, d = get(BASE, ep)
check("recomputed metadata", d["dataset_summary"]["row_count"] == 1 and d["rows"] == [["Zoe", 41, 1.5, "q"]], d)
# forced plain re-ingestion downgrades
s, b = conv(BASE, extra="&force")
s, d = get(BASE, ep)
check("forced plain re-ingest drops metadata", "dataset_summary" not in d, list(d))
STATE["/t.csv"] = CSV1

# ---- failures do not downgrade ----
s, b = conv(BASE, extra="&enrich=yes&force")
s, d = get(BASE, ep)
check("enriched again", "dataset_summary" in d, list(d))
s, b = conv(BASE, "/bad.csv", "&enrich=yes")
check("bad source json error", s == 400 and b["ok"] is False and isinstance(b.get("error"), str), (s, b))
s, b = conv(BASE, "/nothere.csv", "&enrich=yes")
check("missing source json error", s == 404 and b["ok"] is False, (s, b))
s, d = get(BASE, ep)
check("still enriched after failures", "dataset_summary" in d, list(d))

# ---- enrich only on /convert ----
s, d = get(BASE, ep + "?enrich=yes")
check("enrich ignored on datasets (enriched)", "dataset_summary" in d and d["ok"] is True, list(d))
s, b = conv(BASE, extra="&force")   # back to plain
s, d = get(BASE, ep + "?enrich=yes")
check("enrich on datasets adds nothing", s == 200 and "dataset_summary" not in d, list(d))

# upload ignores enrich
boundary = "----b"
body = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.csv\"\r\n"
        "Content-Type: text/csv\r\n\r\n" % boundary).encode() + CSV1 + ("\r\n--%s--\r\n" % boundary).encode()
req = urllib.request.Request(BASE + "/upload?enrich=yes", data=body,
                             headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
r = urllib.request.urlopen(req, timeout=30); ub = json.loads(r.read().decode())
s, d = get(BASE, ub["endpoint"])
check("upload ignores enrich", s == 200 and "dataset_summary" not in d and "column_details" not in d, list(d))
proc.terminate(); proc.wait(timeout=10)

# ---- persistence across restart ----
import tempfile, shutil
store = tempfile.mkdtemp()
proc, BASE = start({"STORAGE_DIR": store})
s, b = conv(BASE, extra="&enrich=yes&force"); ep = b["endpoint"]
proc.terminate(); proc.wait(timeout=10)
proc, BASE = start({"STORAGE_DIR": store})
s, d = get(BASE, ep)
check("metadata survives restart", s == 200 and d.get("dataset_summary", {}).get("row_count") == 3 and "column_details" in d, d.get("dataset_summary"))
s, b = conv(BASE, extra="&enrich=yes")
check("restored enriched cache hit", s == 200, (s, b))
proc.terminate(); proc.wait(timeout=10)
shutil.rmtree(store, ignore_errors=True)

srv.shutdown()
print("\n%d failure(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
