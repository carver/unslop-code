"""Checks for datagate pagination, sorting and response-shape controls."""

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

    FIXTURES["/basic.csv"] = (200, "text/csv",
        b"name,age,score\nAlice,30,1.5\nBob,25,2\nCarol,25,9\n")
    FIXTURES["/big.csv"] = (200, "text/csv",
        b"n\n" + b"".join(b"%d\n" % i for i in range(500)))
    FIXTURES["/mixed.csv"] = (200, "text/csv",
        b"k,v\na,10\nb,zebra\nc,2\nd,apple\ne,\n")
    FIXTURES["/small.csv"] = (200, "text/csv", b"a,b\n1,2\n3,4\n")

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

    def endpoint(path):
        r = requests.get(base + "/convert?source=" +
                         quote(origin_base + path, safe=""), timeout=20)
        return r.json()["endpoint"]

    def q(ep, query=""):
        return requests.get(base + ep + ("?" + query if query else ""), timeout=20)

    def err(ep, query):
        r = q(ep, query)
        j = {}
        try:
            j = r.json()
        except Exception:
            pass
        return (r.status_code == 400 and j.get("ok") is False
                and isinstance(j.get("error"), str) and bool(j.get("error")))

    try:
        basic = endpoint("/basic.csv")
        big = endpoint("/big.csv")
        mixed = endpoint("/mixed.csv")
        small = endpoint("/small.csv")

        print("\n[total]")
        j = q(basic).json()
        check("total present", j.get("total") == 3, j)
        check("total is int", isinstance(j.get("total"), int) and not isinstance(j.get("total"), bool), j)
        j = q(big, "_size=10").json()
        check("total is pre-pagination count", j["total"] == 500 and len(j["rows"]) == 10, j["total"])
        j = q(big, "_offset=480").json()
        check("total unaffected by offset", j["total"] == 500 and len(j["rows"]) == 20, (j["total"], len(j["rows"])))

        print("\n[_size]")
        check("default 100", len(q(big).json()["rows"]) == 100)
        check("_size=5", [r[0] for r in q(big, "_size=5").json()["rows"]] == [0, 1, 2, 3, 4])
        check("_size=1", len(q(big, "_size=1").json()["rows"]) == 1)
        check("_size beyond available returns all", len(q(basic, "_size=999").json()["rows"]) == 3)
        check("_size=500 full", len(q(big, "_size=500").json()["rows"]) == 500)
        check("_size huge ok", q(big, "_size=100000000000").status_code == 200)
        for bad in ["0", "-1", "abc", "", "1.5", "1e3", " ", "0x10", "５", "nan", "-0"]:
            check("_size=%r -> 400" % bad, err(big, "_size=" + quote(bad, safe="")))

        print("\n[_offset]")
        check("_offset=0 default", [r[0] for r in q(big, "_size=3").json()["rows"]] == [0, 1, 2])
        check("_offset=2", [r[0] for r in q(big, "_size=3&_offset=2").json()["rows"]] == [2, 3, 4])
        check("_offset past end -> empty", q(big, "_offset=1000").json()["rows"] == [])
        check("_offset past end keeps total", q(big, "_offset=1000").json()["total"] == 500)
        check("_offset=0 valid", q(big, "_offset=0").status_code == 200)
        for bad in ["-1", "abc", "", "1.5", "-0.0", " x"]:
            check("_offset=%r -> 400" % bad, err(big, "_offset=" + quote(bad, safe="")))

        print("\n[_sort / _sort_desc]")
        j = q(basic, "_sort=age").json()
        check("_sort asc", [r[0] for r in j["rows"]] == ["Bob", "Carol", "Alice"], j["rows"])
        j = q(basic, "_sort_desc=age").json()
        check("_sort_desc", [r[0] for r in j["rows"]] == ["Alice", "Bob", "Carol"], j["rows"])
        check("asc stable on ties",
              [r[0] for r in q(basic, "_sort=age").json()["rows"]][:2] == ["Bob", "Carol"])
        check("desc stable on ties",
              [r[0] for r in q(basic, "_sort_desc=age").json()["rows"]][1:] == ["Bob", "Carol"])
        j = q(basic, "_sort=age&_sort_desc=name").json()
        check("_sort_desc wins", [r[0] for r in j["rows"]] == ["Carol", "Bob", "Alice"], j["rows"])
        j = q(basic, "_sort_desc=name&_sort=age").json()
        check("_sort_desc wins regardless of order",
              [r[0] for r in j["rows"]] == ["Carol", "Bob", "Alice"], j["rows"])
        j = q(basic, "_sort=name").json()
        check("sort by text", [r[0] for r in j["rows"]] == ["Alice", "Bob", "Carol"], j["rows"])
        j = q(mixed, "_sort=v").json()
        check("mixed types sort deterministically", j["total"] == 5 and len(j["rows"]) == 5, j)
        j = q(big, "_sort_desc=n&_size=3").json()
        check("sort before pagination", [r[0] for r in j["rows"]] == [499, 498, 497], j["rows"])
        j = q(big, "_sort=n&_size=3&_offset=5").json()
        check("sort then offset", [r[0] for r in j["rows"]] == [5, 6, 7], j["rows"])
        check("sort keeps total", q(big, "_sort=n&_size=3").json()["total"] == 500)
        for bad_q in ["_sort=", "_sort_desc=", "_sort=nope", "_sort_desc=nope",
                      "_sort=%20", "_sort=Age", "_sort_desc=%20", "_sort=0"]:
            check("%s -> 400" % bad_q, err(basic, bad_q))

        print("\n[_shape]")
        j = q(small).json()
        check("default lists", j["rows"] == [[1, 2], [3, 4]], j["rows"])
        j = q(small, "_shape=lists").json()
        check("_shape=lists", j["rows"] == [[1, 2], [3, 4]], j["rows"])
        j = q(small, "_shape=objects").json()
        check("_shape=objects rows",
              j["rows"] == [{"rowid": 2, "a": 1, "b": 2}, {"rowid": 3, "a": 3, "b": 4}], j["rows"])
        check("columns exclude rowid", j["columns"] == ["a", "b"], j["columns"])
        j = q(basic, "_shape=objects&_sort_desc=age").json()
        check("rowid follows the row through sorting",
              [r["rowid"] for r in j["rows"]] == [2, 3, 4], j["rows"])
        j = q(big, "_shape=objects&_offset=3&_size=2").json()
        check("rowid is source row, not page index",
              [r["rowid"] for r in j["rows"]] == [5, 6], j["rows"])
        check("lists shape has no rowid",
              all(isinstance(r, list) for r in q(small, "_shape=lists").json()["rows"]))
        for bad in ["list", "object", "arrays", "", "LISTS", "objects2"]:
            check("_shape=%r -> 400" % bad, err(small, "_shape=" + quote(bad, safe="")))

        print("\n[_rowid / _total]")
        j = q(small, "_shape=objects&_rowid=hide").json()
        check("_rowid=hide removes rowid",
              j["rows"] == [{"a": 1, "b": 2}, {"a": 3, "b": 4}], j["rows"])
        check("_rowid=hide keeps total", j.get("total") == 2, j)
        j = q(small, "_rowid=hide").json()
        check("_rowid=hide valid with lists", j["rows"] == [[1, 2], [3, 4]], j)
        j = q(small, "_total=hide").json()
        check("_total=hide removes total", "total" not in j, j)
        check("_total=hide keeps rows", j["rows"] == [[1, 2], [3, 4]], j)
        j = q(small, "_shape=objects&_total=hide&_rowid=hide").json()
        check("both toggles", "total" not in j and j["rows"] == [{"a": 1, "b": 2}, {"a": 3, "b": 4}], j)
        for name in ["_rowid", "_total"]:
            for bad in ["show", "", "HIDE", "true", "1", "hidden", "no"]:
                check("%s=%r -> 400" % (name, bad),
                      err(small, name + "=" + quote(bad, safe="")))

        print("\n[repeated control parameters]")
        for dup in ["_size=1&_size=2", "_size=1&_size=1", "_offset=0&_offset=1",
                    "_shape=lists&_shape=objects", "_shape=lists&_shape=lists",
                    "_sort=a&_sort=b", "_sort_desc=a&_sort_desc=b",
                    "_rowid=hide&_rowid=hide", "_total=hide&_total=hide",
                    "_size=2&_sort=a&_size=2"]:
            check("%s -> 400" % dup, err(small, dup))
        check("_sort + _sort_desc is not a repeat",
              q(small, "_sort=a&_sort_desc=b").status_code == 200)
        check("unknown params ignored", q(small, "foo=1&foo=2").status_code == 200)

        print("\n[combinations & envelope]")
        j = q(big, "_sort_desc=n&_size=4&_offset=2&_shape=objects").json()
        check("all controls together",
              [r["n"] for r in j["rows"]] == [497, 496, 495, 494] and j["total"] == 500, j["rows"])
        check("rowid with sort+offset",
              [r["rowid"] for r in j["rows"]] == [499, 498, 497, 496], j["rows"])
        j = q(small).json()
        check("envelope keys", set(j) == {"ok", "columns", "rows", "total", "query_ms"}, sorted(j))
        check("ok true", j["ok"] is True)
        r = q(small, "_size=bad")
        check("error content-type json", "application/json" in r.headers.get("Content-Type", ""))
        check("error has CORS", r.headers.get("Access-Control-Allow-Origin") == "*")
        r = q("/datasets/deadbeefdeadbeef", "_size=bad")
        check("unknown dataset still 404 with bad control", r.status_code == 404, r.text)
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
