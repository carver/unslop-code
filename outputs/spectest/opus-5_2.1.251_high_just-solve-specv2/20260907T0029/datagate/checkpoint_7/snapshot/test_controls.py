"""Checks for the pagination / sorting / response-control specification."""
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
    "/big.csv": (("n\n" + "".join("%d\n" % i for i in range(500))).encode(), "text/csv"),
    # stable-sort fixture: duplicate keys in 'k', distinct 'v'
    "/dup.csv": (b"k,v\nb,1\na,2\nb,3\na,4\nb,5\n", "text/csv"),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
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
        raise SystemExit("server never started")

    def conv(source):
        return requests.get(BASE + "/convert", params={"source": source}, timeout=20).json()["endpoint"]

    def ds(endpoint, query=""):
        return requests.get(BASE + endpoint + ("?" + query if query else ""), timeout=20)

    def is400(r):
        return r.status_code == 400 and r.json().get("ok") is False and isinstance(r.json().get("error"), str)

    try:
        basic = conv(FIX + "/basic.csv")
        big = conv(FIX + "/big.csv")
        dup = conv(FIX + "/dup.csv")

        # ---- total
        d = ds(basic).json()
        check("total present", d.get("total") == 2, d)
        check("total is int", isinstance(d.get("total"), int) and not isinstance(d["total"], bool), d)
        b = ds(big).json()
        check("total before pagination", b["total"] == 500 and len(b["rows"]) == 100, (b["total"], len(b["rows"])))

        # ---- _size
        check("_size limits", len(ds(big, "_size=5").json()["rows"]) == 5)
        check("_size total unchanged", ds(big, "_size=5").json()["total"] == 500)
        check("_size default 100", len(ds(big).json()["rows"]) == 100)
        check("_size exceeds rows", len(ds(basic, "_size=9999").json()["rows"]) == 2)
        check("_size=1", ds(big, "_size=1").json()["rows"] == [[0]])
        for bad in ["0", "-1", "abc", "", "1.5", "1e3", "+", "0x1", " ", "null"]:
            check("_size invalid %r" % bad, is400(ds(big, "_size=" + bad)), ds(big, "_size=" + bad).text[:120])

        # ---- _offset
        check("_offset skips", ds(big, "_offset=3&_size=2").json()["rows"] == [[3], [4]])
        check("_offset=0 default", ds(big, "_size=2").json()["rows"] == [[0], [1]])
        check("_offset past end", ds(big, "_offset=999").json()["rows"] == [])
        check("_offset past end total", ds(big, "_offset=999").json()["total"] == 500)
        for bad in ["-1", "abc", "", "1.5", "x"]:
            check("_offset invalid %r" % bad, is400(ds(big, "_offset=" + bad)))

        # ---- sorting
        check("_sort asc str", [r[0] for r in ds(basic, "_sort=name").json()["rows"]] == ["Alice", "Bob"])
        check("_sort asc num", [r[1] for r in ds(basic, "_sort=age").json()["rows"]] == [7, 30])
        check("_sort_desc num", [r[1] for r in ds(basic, "_sort_desc=age").json()["rows"]] == [30, 7])
        check("_sort_desc str", [r[0] for r in ds(basic, "_sort_desc=name").json()["rows"]] == ["Bob", "Alice"])
        check("_sort_desc wins",
              [r[1] for r in ds(basic, "_sort=age&_sort_desc=age").json()["rows"]] == [30, 7])
        check("_sort_desc wins (reversed order)",
              [r[1] for r in ds(basic, "_sort_desc=age&_sort=age").json()["rows"]] == [30, 7])
        # stable
        check("stable asc", [r[1] for r in ds(dup, "_sort=k").json()["rows"]] == [2, 4, 1, 3, 5],
              ds(dup, "_sort=k").json()["rows"])
        check("stable desc", [r[1] for r in ds(dup, "_sort_desc=k").json()["rows"]] == [1, 3, 5, 2, 4],
              ds(dup, "_sort_desc=k").json()["rows"])
        # sort before pagination
        check("sort before pagination",
              ds(big, "_sort_desc=n&_size=3").json()["rows"] == [[499], [498], [497]])
        check("sort+offset before pagination",
              ds(big, "_sort_desc=n&_size=2&_offset=2").json()["rows"] == [[497], [496]])
        for bad in ["", "nope", "NAME", "0", "rowid"]:
            check("_sort invalid %r" % bad, is400(ds(basic, "_sort=" + bad)))
            check("_sort_desc invalid %r" % bad, is400(ds(basic, "_sort_desc=" + bad)))

        # ---- shape
        d = ds(basic).json()
        check("default shape lists", d["rows"] == [["Alice", 30, 95.5, "08:30"], ["Bob", 7, -2.25, "9:15"]], d)
        check("explicit lists", ds(basic, "_shape=lists").json()["rows"] == d["rows"])
        o = ds(basic, "_shape=objects").json()
        check("objects rows", o["rows"] == [
            {"rowid": 2, "name": "Alice", "age": 30, "score": 95.5, "start": "08:30"},
            {"rowid": 3, "name": "Bob", "age": 7, "score": -2.25, "start": "9:15"},
        ], o["rows"])
        check("rowid not in columns", o["columns"] == ["name", "age", "score", "start"], o["columns"])
        check("objects has total", o.get("total") == 2, o)
        check("rowid tracks source rows after sort",
              [r["rowid"] for r in ds(basic, "_shape=objects&_sort_desc=age").json()["rows"]] == [2, 3])
        check("rowid with offset",
              [r["rowid"] for r in ds(big, "_shape=objects&_offset=2&_size=2").json()["rows"]] == [4, 5])
        for bad in ["", "list", "object", "dict", "LISTS", "arrays"]:
            check("_shape invalid %r" % bad, is400(ds(basic, "_shape=" + bad)))

        # ---- visibility toggles
        h = ds(basic, "_shape=objects&_rowid=hide").json()
        check("_rowid=hide", all("rowid" not in r for r in h["rows"]), h["rows"])
        check("_rowid=hide keeps cols", h["rows"][0] == {"name": "Alice", "age": 30, "score": 95.5, "start": "08:30"})
        check("_rowid=hide ok in lists", ds(basic, "_rowid=hide").status_code == 200)
        t = ds(basic, "_total=hide").json()
        check("_total=hide", "total" not in t, t)
        check("_total=hide keeps rows", len(t["rows"]) == 2 and t["ok"] is True)
        both = ds(basic, "_shape=objects&_rowid=hide&_total=hide").json()
        check("both toggles", "total" not in both and all("rowid" not in r for r in both["rows"]), both)
        for bad in ["", "show", "HIDE", "true", "1", "hidden", "no"]:
            check("_rowid invalid %r" % bad, is400(ds(basic, "_rowid=" + bad)))
            check("_total invalid %r" % bad, is400(ds(basic, "_total=" + bad)))

        # ---- repeated control params
        for name, val in [("_size", "5"), ("_offset", "1"), ("_shape", "lists"),
                          ("_sort", "name"), ("_sort_desc", "name"),
                          ("_rowid", "hide"), ("_total", "hide")]:
            q = "%s=%s&%s=%s" % (name, val, name, val)
            check("repeated %s 400" % name, is400(ds(basic, q)), ds(basic, q).text[:120])
        check("repeated _size differing values 400", is400(ds(basic, "_size=1&_size=2")))
        check("repeated with valid others 400", is400(ds(basic, "_shape=objects&_size=1&_size=1")))
        check("distinct params fine", ds(basic, "_size=1&_offset=1&_shape=objects").status_code == 200)

        # ---- combinations
        c = ds(big, "_sort_desc=n&_size=3&_offset=1&_shape=objects&_total=hide").json()
        check("combo", "total" not in c and [r["n"] for r in c["rows"]] == [498, 497, 496]
              and [r["rowid"] for r in c["rows"]] == [500, 499, 498], c)

        # ---- unknown dataset still 404 regardless of controls
        check("unknown dataset 404", ds("/datasets/nope", "_size=1").status_code == 404)
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
