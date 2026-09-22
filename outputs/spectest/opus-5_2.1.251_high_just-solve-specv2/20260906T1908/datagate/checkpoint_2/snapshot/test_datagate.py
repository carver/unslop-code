"""End-to-end checks for datagate against a live origin server."""

import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

import requests

FIXTURES = {}


class Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path not in FIXTURES:
            self.send_response(404)
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"not found")
            return
        status, ctype, body = FIXTURES[path]
        self.send_response(status)
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


PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (name, extra))


def main():
    origin_port = free_port()
    app_port = free_port()

    FIXTURES["/basic.csv"] = (200, "text/csv", b"name,age,score\nAlice,30,1.5\nBob,25,2\n")
    FIXTURES["/semi.csv"] = (200, "text/csv", b"a;b;c\n1;2;3\n4;5;6\n")
    FIXTURES["/tab.csv"] = (200, "text/csv", b"a\tb\tc\n1\t2\t3\n")
    FIXTURES["/times.csv"] = (200, "text/csv", b"event,start\nstandup,08:30\nreview,9:15\nlunch,12:00\n")
    FIXTURES["/big.csv"] = (200, "text/csv", b"n\n" + b"".join(b"%d\n" % i for i in range(500)))
    FIXTURES["/latin.csv"] = (200, "text/csv", "name,city\nJosé,Málaga\n".encode("latin-1"))
    FIXTURES["/utf8.csv"] = (200, "text/csv", "name,city\nJosé,Málaga\n".encode("utf-8"))
    FIXTURES["/bom.csv"] = (200, "text/csv", "﻿name,city\nA,B\n".encode("utf-8"))
    FIXTURES["/html"] = (200, "text/html", b"<!DOCTYPE html><html><body><p>hi</p></body></html>")
    FIXTURES["/json"] = (200, "application/json", b'{"a": [1, 2, 3], "b": {"c": 4}}')
    FIXTURES["/prose"] = (200, "text/plain", b"The quick brown fox jumps over the lazy dog.\nIt was a bright cold day in April and the clocks struck.\n")
    FIXTURES["/headeronly.csv"] = (200, "text/csv", b"a,b,c\n")
    FIXTURES["/empty.csv"] = (200, "text/csv", b"")
    FIXTURES["/binary"] = (200, "application/pdf", b"%PDF-1.4\n\x00\x01\x02\x03binary\x00stuff")
    FIXTURES["/err500"] = (500, "text/plain", b"boom")
    FIXTURES["/single.csv"] = (200, "text/csv", b"id\n1\n2\n3\n")
    FIXTURES["/ragged.csv"] = (200, "text/csv", b"a,b,c\n1,2\n3,4,5,6\n")
    FIXTURES["/quoted.csv"] = (200, "text/csv", b'name,note\n"Smith, John","said ""hi"""\n')
    FIXTURES["/nums.csv"] = (200, "text/csv", b"i,f,neg,exp,zero,pad,txt,pct\n42,3.14,-7,1e3,0,007,abc,50%\n")
    FIXTURES["/utf16.csv"] = (200, "text/csv", "a,b\n1,2\n".encode("utf-16"))

    origin = ThreadingHTTPServer(("127.0.0.1", origin_port), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()

    proc = subprocess.Popen(
        [sys.executable, "datagate.py", "start", "--port", str(app_port),
         "--address", "127.0.0.1"],
        cwd="/workspace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = "http://127.0.0.1:%d" % app_port
    origin_base = "http://127.0.0.1:%d" % origin_port

    for _ in range(100):
        try:
            requests.get(base + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        print("server did not start")
        print(proc.stdout.read().decode())
        return 1

    def convert(src, charset=None):
        url = base + "/convert?source=" + quote(src, safe="")
        if charset is not None:
            url += "&charset=" + quote(charset, safe="")
        return requests.get(url, timeout=20)

    def dataset(endpoint):
        return requests.get(base + endpoint, timeout=20)

    try:
        print("\n[convert: success + determinism]")
        r = convert(origin_base + "/basic.csv")
        check("200", r.status_code == 200, r.text)
        j = r.json()
        check("ok true", j.get("ok") is True, j)
        check("endpoint shape", j.get("endpoint", "").startswith("/datasets/"), j)
        r2 = convert(origin_base + "/basic.csv")
        check("same id for same source", r2.json()["endpoint"] == j["endpoint"])
        r3 = convert(origin_base + "/semi.csv")
        check("different id for different source", r3.json()["endpoint"] != j["endpoint"])
        check("only ok+endpoint keys", set(j) == {"ok", "endpoint"}, j)

        print("\n[dataset query]")
        d = dataset(j["endpoint"])
        check("200", d.status_code == 200, d.text)
        dj = d.json()
        check("ok true", dj["ok"] is True)
        check("columns order", dj["columns"] == ["name", "age", "score"], dj["columns"])
        check("rows", dj["rows"] == [["Alice", 30, 1.5], ["Bob", 25, 2]], dj["rows"])
        check("query_ms present", "query_ms" in dj)
        check("query_ms non-negative number",
              isinstance(dj["query_ms"], (int, float)) and dj["query_ms"] >= 0, dj["query_ms"])
        check("json content-type", "application/json" in d.headers.get("Content-Type", ""))

        print("\n[delimiters]")
        dj = dataset(convert(origin_base + "/semi.csv").json()["endpoint"]).json()
        check("semicolon", dj["columns"] == ["a", "b", "c"] and dj["rows"] == [[1, 2, 3], [4, 5, 6]], dj)
        dj = dataset(convert(origin_base + "/tab.csv").json()["endpoint"]).json()
        check("tab", dj["columns"] == ["a", "b", "c"] and dj["rows"] == [[1, 2, 3]], dj)
        dj = dataset(convert(origin_base + "/single.csv").json()["endpoint"]).json()
        check("single column", dj["columns"] == ["id"] and dj["rows"] == [[1], [2], [3]], dj)

        print("\n[types]")
        dj = dataset(convert(origin_base + "/times.csv").json()["endpoint"]).json()
        check("times stay text",
              dj["rows"] == [["standup", "08:30"], ["review", "9:15"], ["lunch", "12:00"]], dj["rows"])
        dj = dataset(convert(origin_base + "/nums.csv").json()["endpoint"]).json()
        row = dj["rows"][0]
        check("int", row[0] == 42 and isinstance(row[0], int), row)
        check("decimal", row[1] == 3.14 and isinstance(row[1], float), row)
        check("negative", row[2] == -7, row)
        check("exponent", row[3] == 1000.0, row)
        check("zero", row[4] == 0, row)
        check("zero-padded stays text", row[5] == "007", row)
        check("text", row[6] == "abc", row)
        check("percent stays text", row[7] == "50%", row)

        print("\n[row limit]")
        dj = dataset(convert(origin_base + "/big.csv").json()["endpoint"]).json()
        check("at most 100 rows", len(dj["rows"]) == 100, len(dj["rows"]))
        check("first rows in source order", dj["rows"][:3] == [[0], [1], [2]], dj["rows"][:3])
        dj = dataset(convert(origin_base + "/tab.csv").json()["endpoint"]).json()
        check("fewer rows returns all", len(dj["rows"]) == 1)

        print("\n[encoding]")
        dj = dataset(convert(origin_base + "/latin.csv").json()["endpoint"]).json()
        check("latin-1 fallback", dj["rows"] == [["José", "Málaga"]], dj["rows"])
        dj = dataset(convert(origin_base + "/latin.csv", "latin-1").json()["endpoint"]).json()
        check("explicit latin-1", dj["rows"] == [["José", "Málaga"]], dj["rows"])
        dj = dataset(convert(origin_base + "/utf8.csv").json()["endpoint"]).json()
        check("utf-8 detected", dj["rows"] == [["José", "Málaga"]], dj["rows"])
        dj = dataset(convert(origin_base + "/utf8.csv", "utf-8").json()["endpoint"]).json()
        check("explicit utf-8", dj["rows"] == [["José", "Málaga"]], dj["rows"])
        dj = dataset(convert(origin_base + "/bom.csv").json()["endpoint"]).json()
        check("bom stripped", dj["columns"] == ["name", "city"], dj["columns"])
        dj = dataset(convert(origin_base + "/utf16.csv").json()["endpoint"]).json()
        check("utf-16", dj["columns"] == ["a", "b"] and dj["rows"] == [[1, 2]], dj)

        print("\n[quoting / ragged]")
        dj = dataset(convert(origin_base + "/quoted.csv").json()["endpoint"]).json()
        check("quoted fields", dj["rows"] == [["Smith, John", 'said "hi"']], dj["rows"])
        dj = dataset(convert(origin_base + "/ragged.csv").json()["endpoint"]).json()
        check("ragged normalized",
              len(dj["columns"]) == 3 and all(len(r) == 3 for r in dj["rows"]), dj)

        print("\n[errors]")
        r = requests.get(base + "/convert", timeout=10)
        check("missing source -> 400", r.status_code == 400, r.text)
        check("error envelope", r.json().get("ok") is False and isinstance(r.json().get("error"), str), r.text)
        for bad in ["not a url", "ftp://example.com/a.csv", "://x", "", "http://", "justtext"]:
            r = convert(bad)
            check("invalid url %r -> 400" % bad, r.status_code == 400, r.text)
        r = convert(origin_base + "/basic.csv", "no-such-charset")
        check("bad charset -> 400", r.status_code == 400, r.text)
        r = convert(origin_base + "/basic.csv", "")
        check("empty charset -> 400", r.status_code == 400, r.text)
        r = convert(origin_base + "/latin.csv", "utf-8")
        check("undecodable charset -> 400", r.status_code == 400, r.text)
        r = convert(origin_base + "/missing.csv")
        check("remote 404 -> 404", r.status_code == 404, r.text)
        r = convert(origin_base + "/err500")
        check("remote 500 -> 404", r.status_code == 404, r.text)
        r = convert("http://127.0.0.1:%d/x.csv" % free_port())
        check("unreachable -> 404", r.status_code == 404, r.text)
        r = convert("http://nonexistent-host-datagate.invalid/a.csv")
        check("bad dns -> 404", r.status_code == 404, r.text)
        for path in ["/html", "/json", "/prose", "/headeronly.csv", "/empty.csv", "/binary"]:
            r = convert(origin_base + path)
            check("non-tabular %s -> 400" % path, r.status_code == 400, r.text)
        r = dataset("/datasets/deadbeefdeadbeef")
        check("unknown dataset -> 404", r.status_code == 404, r.text)
        check("unknown dataset json", r.json().get("ok") is False, r.text)
        r = requests.get(base + "/nope", timeout=10)
        check("unknown route -> 404", r.status_code == 404, r.text)
        check("unknown route json", r.json().get("ok") is False, r.text)
        check("unknown route content-type", "application/json" in r.headers.get("Content-Type", ""))
        r = requests.post(base + "/convert", timeout=10)
        check("bad method is json", "application/json" in r.headers.get("Content-Type", ""), r.text)
        check("bad method ok:false", r.json().get("ok") is False, r.text)

        print("\n[cors]")
        r = convert(origin_base + "/basic.csv")
        check("ACAO on success", r.headers.get("Access-Control-Allow-Origin") == "*", dict(r.headers))
        r = requests.get(base + "/nope", timeout=10)
        check("ACAO on error", r.headers.get("Access-Control-Allow-Origin") == "*", dict(r.headers))
        r = requests.options(base + "/convert", timeout=10,
                             headers={"Origin": "http://example.com",
                                      "Access-Control-Request-Method": "GET"})
        check("preflight ok", r.status_code < 400, r.status_code)
        check("preflight ACAO", r.headers.get("Access-Control-Allow-Origin") in ("*", "http://example.com"),
              dict(r.headers))
        check("preflight methods", "GET" in (r.headers.get("Access-Control-Allow-Methods") or ""),
              dict(r.headers))
        r = requests.get(base + "/convert?source=" + quote(origin_base + "/basic.csv"),
                         headers={"Origin": "http://example.com"}, timeout=10)
        check("ACAO with Origin header",
              r.headers.get("Access-Control-Allow-Origin") in ("*", "http://example.com"),
              dict(r.headers))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        origin.shutdown()

    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
