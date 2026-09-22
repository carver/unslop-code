"""End-to-end checks for datagate against a local fixture server."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

HERE = os.path.dirname(os.path.abspath(__file__))

FIXTURES = {
    "/basic.csv": (b"name,age,score,start\nAlice,30,95.5,08:30\nBob,7,-2.25,9:15\n", "text/csv"),
    "/semi.csv": (b"a;b;c\n1;2;3\n4;5;6\n", "text/csv"),
    "/tabs.tsv": (b"x\ty\n1\t2\n3\t4\n", "text/tab-separated-values"),
    "/pipe.csv": (b"p|q\n1|2\n3|4\n", "text/csv"),
    "/latin1.csv": ("naïve,ville\nrésumé,Genève\n".encode("latin-1"), "text/csv"),
    "/utf8.csv": ("naïve,ville\nrésumé,Genève\n".encode("utf-8"), "text/csv"),
    "/utf16.csv": ("a,b\n1,2\n".encode("utf-16"), "text/csv"),
    "/onecol.csv": (b"name\nAlice\nBob\n", "text/csv"),
    "/headeronly.csv": (b"a,b,c\n", "text/csv"),
    "/quoted.csv": (b'name,note\n"Smith, John","says ""hi"", ok"\n"multi\nline",2\n', "text/csv"),
    "/ragged.csv": (b"a,b,c\n1,2\n1,2,3,4\n", "text/csv"),
    "/page.html": (b"<!DOCTYPE html>\n<html><body><h1>Hello</h1><p>not a csv</p></body></html>\n", "text/html"),
    "/data.json": (b'{"a": [1, 2, 3], "b": {"c": 4}}\n', "application/json"),
    "/prose.txt": (b"The quick brown fox jumps over the lazy dog every single day.\nMeanwhile the cat sleeps quietly beside the warm fireplace all afternoon.\n", "text/plain"),
    "/binary.bin": (b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4, "application/octet-stream"),
    "/empty.csv": (b"", "text/csv"),
    "/bom.csv": (b"\xef\xbb\xbfa,b\n1,2\n", "text/csv"),
    "/big.csv": (("n\n" + "".join("%d\n" % i for i in range(500))).encode(), "text/csv"),
    "/types.csv": (b"s,i,f,neg,exp,t,t2,zip,pct,blank,bignum\nhello,42,3.14,-7,1e3,12:00,08:30,01234,50%,,00.5\n", "text/csv"),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/status500":
            self.send_error(500, "boom")
            return
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/basic.csv")
            self.end_headers()
            return
        if path not in FIXTURES:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"not found")
            return
        body, ctype = FIXTURES[path]
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


FAILURES = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s %s" % (name, detail))
        FAILURES.append(name)


def main():
    fixture_port = free_port()
    httpd = HTTPServer(("127.0.0.1", fixture_port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    FIX = "http://127.0.0.1:%d" % fixture_port

    app_port = free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "datagate.py"), "start",
         "--port", str(app_port), "--address", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    BASE = "http://127.0.0.1:%d" % app_port
    for _ in range(100):
        try:
            requests.get(BASE + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        out = proc.stdout.read().decode() if proc.stdout else ""
        raise SystemExit("server never started\n" + out)

    def conv(source, **kw):
        params = {"source": source}
        params.update(kw)
        return requests.get(BASE + "/convert", params=params, timeout=20)

    def ds(endpoint, **kw):
        return requests.get(BASE + endpoint, params=kw, timeout=20)

    try:
        # ---- basic happy path
        r = conv(FIX + "/basic.csv")
        j = r.json()
        check("convert 200", r.status_code == 200, r.text)
        check("convert ok true", j.get("ok") is True, j)
        check("convert endpoint shape", isinstance(j.get("endpoint"), str)
              and j["endpoint"].startswith("/datasets/"), j)

        r2 = ds(j["endpoint"])
        d = r2.json()
        check("dataset 200", r2.status_code == 200, r2.text)
        check("dataset ok", d.get("ok") is True, d)
        check("columns order", d["columns"] == ["name", "age", "score", "start"], d)
        check("rows content+types",
              d["rows"] == [["Alice", 30, 95.5, "08:30"], ["Bob", 7, -2.25, "9:15"]], d)
        check("query_ms present non-negative",
              isinstance(d.get("query_ms"), (int, float)) and d["query_ms"] >= 0, d)

        # ---- determinism
        r3 = conv(FIX + "/basic.csv")
        check("same source -> same endpoint", r3.json()["endpoint"] == j["endpoint"])
        r4 = conv(FIX + "/semi.csv")
        check("different source -> different endpoint", r4.json()["endpoint"] != j["endpoint"])

        # ---- delimiters
        check("semicolon delimiter", ds(r4.json()["endpoint"]).json()["columns"] == ["a", "b", "c"])
        e = conv(FIX + "/tabs.tsv").json()["endpoint"]
        t = ds(e).json()
        check("tab delimiter", t["columns"] == ["x", "y"] and t["rows"] == [[1, 2], [3, 4]], t)
        e = conv(FIX + "/pipe.csv").json()["endpoint"]
        check("pipe delimiter", ds(e).json()["columns"] == ["p", "q"])

        # ---- encodings
        e = conv(FIX + "/latin1.csv").json()["endpoint"]
        check("latin-1 fallback", ds(e).json()["columns"] == ["naïve", "ville"], ds(e).json())
        e = conv(FIX + "/latin1.csv", charset="latin-1").json()["endpoint"]
        check("explicit latin-1", ds(e).json()["rows"] == [["résumé", "Genève"]])
        e = conv(FIX + "/utf8.csv").json()["endpoint"]
        check("utf-8 detected", ds(e).json()["columns"] == ["naïve", "ville"])
        e = conv(FIX + "/utf8.csv", charset="UTF-8").json()["endpoint"]
        check("explicit utf-8", ds(e).json()["columns"] == ["naïve", "ville"])
        e = conv(FIX + "/utf16.csv").json()["endpoint"]
        check("utf-16 BOM detected", ds(e).json()["rows"] == [[1, 2]], ds(e).json())
        e = conv(FIX + "/bom.csv").json()["endpoint"]
        check("utf-8 BOM stripped", ds(e).json()["columns"] == ["a", "b"], ds(e).json())

        # ---- charset errors
        r = conv(FIX + "/basic.csv", charset="not-a-charset")
        check("bad charset 400", r.status_code == 400 and r.json()["ok"] is False, r.text)
        r = conv(FIX + "/basic.csv", charset="")
        check("empty charset 400", r.status_code == 400, r.text)
        r = conv(FIX + "/latin1.csv", charset="utf-8")
        check("undecodable charset 400", r.status_code == 400, r.text)

        # ---- source errors
        r = requests.get(BASE + "/convert", timeout=10)
        check("missing source 400", r.status_code == 400 and r.json()["ok"] is False, r.text)
        for bad in ["", "notaurl", "http://", "ftp://example.com/a.csv", "://x", "https://"]:
            r = conv(bad)
            check("invalid url 400 (%r)" % bad, r.status_code == 400, r.text)
        r = conv(FIX + "/missing.csv")
        check("remote 404 -> 404", r.status_code == 404 and r.json()["ok"] is False, r.text)
        r = conv(FIX + "/status500")
        check("remote 500 -> 404", r.status_code == 404, r.text)
        r = conv("http://127.0.0.1:%d/x.csv" % free_port())
        check("unreachable -> 404", r.status_code == 404, r.text)
        r = conv("http://nonexistent.invalid.example/a.csv")
        check("bad dns -> 404", r.status_code == 404, r.text)

        # ---- non tabular
        for path in ["/page.html", "/data.json", "/prose.txt", "/binary.bin",
                     "/empty.csv", "/headeronly.csv"]:
            r = conv(FIX + path)
            check("non-tabular 400 (%s)" % path,
                  r.status_code == 400 and r.json()["ok"] is False, r.text[:200])

        # ---- single column + quoting + ragged
        e = conv(FIX + "/onecol.csv").json()["endpoint"]
        o = ds(e).json()
        check("single column", o["columns"] == ["name"] and o["rows"] == [["Alice"], ["Bob"]], o)
        e = conv(FIX + "/quoted.csv").json()["endpoint"]
        q = ds(e).json()
        check("quoting", q["rows"][0] == ["Smith, John", 'says "hi", ok'], q)
        check("embedded newline", q["rows"][1] == ["multi\nline", 2], q)
        e = conv(FIX + "/ragged.csv").json()["endpoint"]
        rg = ds(e).json()
        check("ragged normalised", rg["rows"] == [[1, 2, ""], [1, 2, 3]], rg)

        # ---- row limit
        e = conv(FIX + "/big.csv").json()["endpoint"]
        b = ds(e).json()
        check("limit 100", len(b["rows"]) == 100 and b["rows"][0] == [0], len(b["rows"]))

        # ---- types
        e = conv(FIX + "/types.csv").json()["endpoint"]
        ty = ds(e).json()
        row = ty["rows"][0]
        check("types row", row == ["hello", 42, 3.14, -7, 1000.0, "12:00", "08:30",
                                   "01234", "50%", "", "00.5"], row)

        # ---- unknown dataset / routes
        r = ds("/datasets/deadbeefdeadbeef")
        check("unknown id 404", r.status_code == 404 and r.json()["ok"] is False, r.text)
        r = requests.get(BASE + "/nope", timeout=10)
        check("unknown route 404 json", r.status_code == 404
              and r.json()["ok"] is False
              and "application/json" in r.headers.get("Content-Type", ""), r.text[:200])
        r = requests.post(BASE + "/convert", timeout=10)
        check("bad method json", r.headers.get("Content-Type", "").startswith("application/json")
              and r.json()["ok"] is False, r.text[:200])

        # ---- CORS
        r = conv(FIX + "/basic.csv")
        check("cors on success", r.headers.get("Access-Control-Allow-Origin") is not None, dict(r.headers))
        r = requests.get(BASE + "/nope", timeout=10)
        check("cors on error", r.headers.get("Access-Control-Allow-Origin") is not None)
        r = requests.options(BASE + "/convert", timeout=10,
                             headers={"Origin": "http://x.test",
                                      "Access-Control-Request-Method": "GET"})
        check("cors preflight", r.status_code in (200, 204)
              and r.headers.get("Access-Control-Allow-Origin") is not None, r.status_code)

        # ---- redirect follow
        r = conv(FIX + "/redirect")
        check("redirect followed", r.status_code == 200, r.text)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        httpd.shutdown()

    print("\n%d checks, %d failures" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        print("failed: " + ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
