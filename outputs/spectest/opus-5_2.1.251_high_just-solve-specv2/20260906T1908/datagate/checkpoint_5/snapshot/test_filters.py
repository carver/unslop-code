"""Checks for datagate column-level filtering."""

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
        b"name,age,score\nAlice,30,1.5\nBob,25,2\nCarol,25,9\nalice,40,3\n")
    FIXTURES["/big.csv"] = (200, "text/csv",
        b"n\n" + b"".join(b"%d\n" % i for i in range(500)))
    FIXTURES["/mixed.csv"] = (200, "text/csv",
        b"k,v\na,10\nb,zebra\nc,2\nd,apple\ne,\nf,-3.5\n")
    FIXTURES["/under.csv"] = (200, "text/csv",
        b"first__name,tag\nAda,x\nGrace,y\n")

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

    def rows(ep, query=""):
        return q(ep, query).json()["rows"]

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
        under = endpoint("/under.csv")

        print("\n[exact]")
        check("text exact", rows(basic, "name__exact=Alice") == [["Alice", 30, 1.5]],
              rows(basic, "name__exact=Alice"))
        check("exact is case-sensitive", rows(basic, "name__exact=alice") == [["alice", 40, 3]],
              rows(basic, "name__exact=alice"))
        check("exact no match -> empty", rows(basic, "name__exact=ALICE") == [])
        check("exact on integer column",
              rows(basic, "age__exact=25") == [["Bob", 25, 2], ["Carol", 25, 9]],
              rows(basic, "age__exact=25"))
        check("exact on float column", rows(basic, "score__exact=1.5") == [["Alice", 30, 1.5]],
              rows(basic, "score__exact=1.5"))
        check("exact is not substring", rows(basic, "name__exact=Ali") == [])
        check("exact empty value matches empty cell",
              rows(mixed, "v__exact=") == [["e", ""]], rows(mixed, "v__exact="))

        print("\n[contains]")
        check("substring", rows(basic, "name__contains=li") == [["Alice", 30, 1.5], ["alice", 40, 3]],
              rows(basic, "name__contains=li"))
        check("contains is case-sensitive", rows(basic, "name__contains=LI") == [])
        check("contains matches whole value", rows(basic, "name__contains=Bob") == [["Bob", 25, 2]])
        check("contains on numbers", rows(basic, "age__contains=5") == [["Bob", 25, 2], ["Carol", 25, 9]],
              rows(basic, "age__contains=5"))
        check("contains empty matches all", len(rows(basic, "name__contains=")) == 4)
        check("contains no match", rows(basic, "name__contains=zzz") == [])

        print("\n[less / greater]")
        check("less", rows(basic, "age__less=30") == [["Bob", 25, 2], ["Carol", 25, 9]],
              rows(basic, "age__less=30"))
        check("less is strict", rows(basic, "age__less=25") == [], rows(basic, "age__less=25"))
        check("greater", rows(basic, "age__greater=30") == [["alice", 40, 3]],
              rows(basic, "age__greater=30"))
        check("greater is strict", rows(basic, "age__greater=40") == [])
        check("float compare", rows(basic, "score__less=2") == [["Alice", 30, 1.5]],
              rows(basic, "score__less=2"))
        check("float filter value", rows(basic, "score__greater=2.5") == [["Carol", 25, 9], ["alice", 40, 3]],
              rows(basic, "score__greater=2.5"))
        check("negative filter value", rows(mixed, "v__less=0") == [["f", -3.5]],
              rows(mixed, "v__less=0"))
        check("exponent filter value", len(rows(big, "n__less=1e1")) == 10,
              rows(big, "n__less=1e1"))
        check("non-numeric stored not matched (less)",
              rows(mixed, "v__less=1000") == [["a", 10], ["c", 2], ["f", -3.5]],
              rows(mixed, "v__less=1000"))
        check("non-numeric stored not matched (greater)",
              rows(mixed, "v__greater=-1000") == [["a", 10], ["c", 2], ["f", -3.5]],
              rows(mixed, "v__greater=-1000"))
        check("empty cell not numeric", all(r[0] != "e" for r in rows(mixed, "v__greater=-99999")))

        print("\n[non-numeric filter values -> 400]")
        for bad in ["abc", "", " ", "1.2.3", "12abc", "nan", "inf", "0x10", "１",
                    "1,5", "true", "None", "--1", "+"]:
            for cmp in ["less", "greater"]:
                check("age__%s=%r -> 400" % (cmp, bad),
                      err(basic, "age__%s=" % cmp + quote(bad, safe="")))
        check("valid numeric forms accepted", all(
            q(basic, "age__less=" + quote(v, safe="")).status_code == 200
            for v in ["30", "+30", "-30", "3.0", ".5", "5.", "1e3", "1E3", "3e-2"]))

        print("\n[AND of multiple filters]")
        check("two filters ANDed",
              rows(basic, "age__exact=25&score__greater=5") == [["Carol", 25, 9]],
              rows(basic, "age__exact=25&score__greater=5"))
        check("range on one column",
              rows(basic, "age__greater=25&age__less=40") == [["Alice", 30, 1.5]],
              rows(basic, "age__greater=25&age__less=40"))
        check("contradictory filters -> empty",
              rows(basic, "age__less=10&age__greater=100") == [])
        check("three filters",
              rows(basic, "name__contains=o&age__less=30&score__greater=1") ==
              [["Bob", 25, 2], ["Carol", 25, 9]],
              rows(basic, "name__contains=o&age__less=30&score__greater=1"))

        print("\n[duplicate filter keys -> 400]")
        for dup in ["age__less=1&age__less=2", "age__less=1&age__less=1",
                    "name__exact=a&name__exact=b", "name__contains=a&name__contains=a",
                    "age__greater=1&age__greater=2",
                    "name__exact=a&age__less=3&name__exact=a"]:
            check("%s -> 400" % dup, err(basic, dup))
        check("different comparators on one column is not a repeat",
              q(basic, "age__less=100&age__greater=0").status_code == 200)
        check("different columns is not a repeat",
              q(basic, "age__less=100&score__less=100").status_code == 200)

        print("\n[unknown column -> 400]")
        for bad in ["nope__exact=x", "Age__less=3", "AGE__exact=30", "name___exact=x",
                    "age __less=3", "ag__less=3", "namex__exact=x"]:
            check("%s -> 400" % bad, err(basic, bad))
        check("column match is exact/case-sensitive",
              err(basic, "Name__exact=Alice"))
        check("column containing the separator resolves",
              rows(under, "first__name__exact=Ada") == [["Ada", "x"]],
              rows(under, "first__name__exact=Ada"))
        check("unknown column with separator -> 400", err(under, "last__name__exact=Ada"))

        print("\n[invalid comparator -> 400]")
        for bad in ["name__equals=x", "name__EXACT=x", "name__Contains=x", "name__lt=3",
                    "name__gt=3", "name__lessthan=3", "name__=x", "name__exact2=x",
                    "name__contains__=x", "age__less_=3"]:
            check("%s -> 400" % bad, err(basic, bad))

        print("\n[error envelope]")
        r = q(basic, "name__equals=x")
        check("status 400", r.status_code == 400, r.text)
        j = r.json()
        check("ok false", j.get("ok") is False, j)
        check("error is a non-empty string", isinstance(j.get("error"), str) and j["error"], j)
        check("no rows key on error", "rows" not in j, j)
        check("error content-type json", "application/json" in r.headers.get("Content-Type", ""))
        check("error has CORS", r.headers.get("Access-Control-Allow-Origin") == "*")
        check("unknown dataset still 404 with bad filter",
              q("/datasets/deadbeefdeadbeef", "nope__zz=1").status_code == 404)

        print("\n[ignored params]")
        check("plain param ignored", q(basic, "foo=1").status_code == 200)
        check("repeated plain param ignored", q(basic, "foo=1&foo=2").status_code == 200)
        check("plain param does not filter", len(rows(basic, "foo=1")) == 4)
        check("param named like a column ignored", len(rows(basic, "name=Alice")) == 4)
        check("unknown control param ignored", q(basic, "_nope=1").status_code == 200)
        check("control-looking param with __ ignored",
              q(basic, "_sort__exact=1").status_code == 200)
        check("leading-underscore name is a control param, not a filter",
              q(basic, "__exact=x").status_code == 200)
        check("ignored params coexist with filters",
              rows(basic, "foo=1&name__exact=Bob") == [["Bob", 25, 2]],
              rows(basic, "foo=1&name__exact=Bob"))

        print("\n[filter + sort + paginate + total]")
        j = q(big, "n__less=10&_sort_desc=n").json()
        check("filter precedes sort", [r[0] for r in j["rows"]] == list(range(9, -1, -1)), j["rows"])
        j = q(big, "n__less=10&_sort_desc=n&_size=3").json()
        check("paginate filtered+sorted", [r[0] for r in j["rows"]] == [9, 8, 7], j["rows"])
        check("total is filtered pre-pagination count", j["total"] == 10, j["total"])
        j = q(big, "n__greater=100&n__less=110&_size=2&_offset=1").json()
        check("offset on filtered rows", [r[0] for r in j["rows"]] == [102, 103], j["rows"])
        check("total ignores offset/size", j["total"] == 9, j["total"])
        j = q(big, "n__greater=1000").json()
        check("no matches -> empty rows", j["rows"] == [], j["rows"])
        check("no matches -> total 0", j["total"] == 0, j["total"])
        check("no matches keeps columns", j["columns"] == ["n"], j["columns"])
        j = q(basic, "age__exact=25&_shape=objects").json()
        check("objects shape keeps rowid through filtering",
              j["rows"] == [{"rowid": 3, "name": "Bob", "age": 25, "score": 2},
                            {"rowid": 4, "name": "Carol", "age": 25, "score": 9}], j["rows"])
        j = q(basic, "age__exact=25&_total=hide").json()
        check("_total=hide with filter", "total" not in j and len(j["rows"]) == 2, j)
        j = q(basic, "age__exact=25").json()
        check("envelope keys unchanged", set(j) == {"ok", "columns", "rows", "total", "query_ms"},
              sorted(j))
        check("filtered default page cap",
              len(q(big, "n__greater=-1").json()["rows"]) == 100)
        check("filtered sort stability",
              [r[0] for r in q(basic, "score__greater=0&_sort=age").json()["rows"]] ==
              ["Bob", "Carol", "Alice", "alice"],
              q(basic, "score__greater=0&_sort=age").json()["rows"])

        print("\n[filters do not disturb controls]")
        for bad in ["_size=0&name__exact=Bob", "_shape=bad&name__exact=Bob",
                    "_sort=nope&name__exact=Bob", "_size=1&_size=2&name__exact=Bob"]:
            check("%s -> 400" % bad, err(basic, bad))
        check("query_ms still present", "query_ms" in q(basic, "age__less=100").json())
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
