"""Checks for the column-level filtering specification."""
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
    # mixed: numeric and non-numeric values inside one column
    "/mixed.csv": (b"city,pop,tag\nOslo,10,a\nOsaka,2,b\nLima,n/a,c\nOslo,,d\nlima,-5,e\n", "text/csv"),
    "/weird.csv": (b"a__b,c d,exp\n1,x,1e3\n2,y,4\n", "text/csv"),
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
        try:
            j = r.json()
        except Exception:
            return False
        return r.status_code == 400 and j.get("ok") is False and isinstance(j.get("error"), str)

    try:
        basic = conv(FIX + "/basic.csv")
        big = conv(FIX + "/big.csv")
        mixed = conv(FIX + "/mixed.csv")
        weird = conv(FIX + "/weird.csv")

        # ---- exact
        d = ds(basic, "name__exact=Alice").json()
        check("exact matches", d["rows"] == [["Alice", 30, 95.5, "08:30"]], d)
        check("exact total", d["total"] == 1, d)
        check("exact case-sensitive", ds(basic, "name__exact=alice").json()["rows"] == [])
        check("exact case-sensitive total", ds(basic, "name__exact=ALICE").json()["total"] == 0)
        check("exact no substring", ds(basic, "name__exact=Ali").json()["rows"] == [])
        check("exact on numeric cell", ds(basic, "age__exact=30").json()["total"] == 1)
        check("exact on float cell", ds(basic, "score__exact=95.5").json()["total"] == 1)
        check("exact on text-typed cell", ds(basic, "start__exact=08:30").json()["total"] == 1)
        check("exact empty value", ds(mixed, "pop__exact=").json()["total"] == 1,
              ds(mixed, "pop__exact=").json())
        check("exact no match", ds(basic, "name__exact=Zed").json()["rows"] == [])

        # ---- contains
        c = ds(mixed, "city__contains=Os").json()
        check("contains matches", [r[0] for r in c["rows"]] == ["Oslo", "Osaka", "Oslo"], c)
        check("contains case-sensitive", [r[0] for r in ds(mixed, "city__contains=li").json()["rows"]] == ["lima"])
        check("contains full value", ds(mixed, "city__contains=Lima").json()["total"] == 1)
        check("contains empty matches all", ds(basic, "name__contains=").json()["total"] == 2)
        check("contains on numeric cell", ds(basic, "score__contains=5.5").json()["total"] == 1)
        check("contains no match", ds(basic, "name__contains=zz").json()["rows"] == [])

        # ---- less / greater
        check("less", [r[0] for r in ds(basic, "age__less=10").json()["rows"]] == ["Bob"])
        check("greater", [r[0] for r in ds(basic, "age__greater=10").json()["rows"]] == ["Alice"])
        check("less strict", ds(basic, "age__less=7").json()["total"] == 0)
        check("greater strict", ds(basic, "age__greater=30").json()["total"] == 0)
        check("less float value", ds(basic, "score__less=0").json()["total"] == 1)
        check("greater negative", ds(basic, "score__greater=-3").json()["total"] == 2)
        check("less float precision", ds(basic, "age__less=30.5").json()["total"] == 2)
        check("numeric skips non-numeric cells",
              [r[0] for r in ds(mixed, "pop__less=1000").json()["rows"]] == ["Oslo", "Osaka", "lima"],
              ds(mixed, "pop__less=1000").json())
        check("numeric skips blank cells", ds(mixed, "pop__greater=-100").json()["total"] == 3)
        check("numeric on text column", ds(basic, "name__less=100").json()["total"] == 0)
        check("numeric comparator on big", ds(big, "n__greater=497").json()["rows"] == [[498], [499]])
        check("numeric exponent filter value", ds(big, "n__greater=4.98e2").json()["rows"] == [[499]])

        # ---- AND
        a = ds(mixed, "city__contains=Os&pop__greater=5").json()
        check("AND of two filters", a["rows"] == [["Oslo", 10, "a"]], a)
        check("AND same column", ds(big, "n__greater=10&n__less=13").json()["rows"] == [[11], [12]])
        check("AND same column same comparator family",
              ds(mixed, "city__exact=Oslo&city__contains=slo").json()["total"] == 2)
        check("AND unsatisfiable", ds(basic, "name__exact=Alice&age__less=10").json()["total"] == 0)
        check("three filters",
              ds(mixed, "city__contains=O&pop__greater=1&pop__less=100").json()["total"] == 2)

        # ---- interaction with sorting / pagination / shape
        s = ds(big, "n__greater=100&_sort_desc=n&_size=3").json()
        check("filter then sort then page", s["rows"] == [[499], [498], [497]], s)
        check("total is filtered count pre-pagination", s["total"] == 399, s["total"])
        check("filter + offset",
              ds(big, "n__less=10&_offset=2&_size=3").json()["rows"] == [[2], [3], [4]])
        check("filter + default size caps rows",
              len(ds(big, "n__greater=-1").json()["rows"]) == 100)
        check("filter + total hidden", "total" not in ds(big, "n__less=5&_total=hide").json())
        o = ds(basic, "name__exact=Bob&_shape=objects").json()
        check("filter + objects shape",
              o["rows"] == [{"rowid": 3, "name": "Bob", "age": 7, "score": -2.25, "start": "9:15"}], o)
        check("filter keeps columns", ds(basic, "name__exact=Bob").json()["columns"]
              == ["name", "age", "score", "start"])
        check("filter + sort asc",
              [r[0] for r in ds(mixed, "pop__less=1000&_sort=city").json()["rows"]]
              == ["Osaka", "Oslo", "lima"],
              ds(mixed, "pop__less=1000&_sort=city").json()["rows"])
        check("empty filter result with sort",
              ds(basic, "name__exact=zz&_sort=age").json()["rows"] == [])
        check("query_ms still present", isinstance(ds(basic, "name__exact=Alice").json()["query_ms"], (int, float)))

        # ---- ignored params
        check("param without __ ignored", ds(basic, "name=Alice").json()["total"] == 2)
        check("param without __ ignored (unknown col)", ds(basic, "nope=1").json()["total"] == 2)
        check("repeated non-filter param ignored", ds(basic, "q=1&q=2").status_code == 200)
        check("control params still not filters", ds(basic, "_size=1").json()["total"] == 2)

        # ---- errors: invalid comparator
        for bad in ["name__eq=Alice", "name__EXACT=Alice", "name__like=Alice", "name__=x",
                    "name__lt=1", "name__Contains=x", "age__lessthan=1", "name__exactly=x"]:
            check("invalid comparator 400 (%s)" % bad, is400(ds(basic, bad)), ds(basic, bad).text[:140])

        # ---- errors: unknown column
        for bad in ["nope__exact=1", "NAME__exact=Alice", "Age__less=3", "rowid__exact=2",
                    "name2__contains=x", " name__exact=Alice"]:
            check("unknown column 400 (%s)" % bad, is400(ds(basic, bad)), ds(basic, bad).text[:140])

        # ---- errors: non-numeric comparator target
        for bad in ["abc", "", "x", "1,5", "null", "true", "+", "0x1", "%20", "N/A", "1.2.3"]:
            q = "age__less=" + bad
            check("less non-numeric 400 (%r)" % bad, is400(ds(basic, q)), ds(basic, q).text[:140])
            q = "age__greater=" + bad
            check("greater non-numeric 400 (%r)" % bad, is400(ds(basic, q)), ds(basic, q).text[:140])
        check("exact accepts non-numeric", ds(basic, "age__exact=abc").status_code == 200)
        check("contains accepts non-numeric", ds(basic, "age__contains=abc").status_code == 200)

        # ---- errors: duplicate filter key
        for q in ["name__exact=Alice&name__exact=Bob", "name__exact=Alice&name__exact=Alice",
                  "age__less=5&age__less=9", "name__contains=A&name__contains=B"]:
            check("duplicate filter 400 (%s)" % q, is400(ds(basic, q)), ds(basic, q).text[:140])
        check("different comparators same column ok",
              ds(basic, "name__exact=Alice&name__contains=A").status_code == 200)
        check("different columns ok",
              ds(basic, "name__exact=Alice&age__less=99").status_code == 200)

        # ---- errors: still 400 combined with valid controls
        check("bad filter with valid controls 400", is400(ds(basic, "_size=1&nope__exact=1")))
        check("bad control with valid filter 400", is400(ds(basic, "_size=0&name__exact=Alice")))

        # ---- unknown dataset wins over filter errors
        check("unknown dataset 404", ds("/datasets/nope", "bad__zz=1").status_code == 404)

        # ---- timeout
        check("timeout 400", is400(ds(big, "_timeout=0&n__greater=1")), ds(big, "_timeout=0").text[:140])
        check("generous timeout ok", ds(big, "_timeout=10000&n__greater=1").status_code == 200)

        # ---- odd column names
        w = ds(weird, "a__b__exact=1").json()
        check("column containing __", w["rows"] == [[1, "x", 1000.0]], w)
        check("column containing __ (numeric)", ds(weird, "a__b__greater=1").json()["total"] == 1)
        check("column with space", ds(weird, "c d__exact=y").json()["total"] == 1,
              ds(weird, "c d__exact=y").text[:140])
        check("exact matches source text form", ds(weird, "exp__exact=1e3").json()["total"] == 1,
              ds(weird, "exp__exact=1e3").json())
        check("numeric on exponent column", ds(weird, "exp__greater=500").json()["total"] == 1)
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
