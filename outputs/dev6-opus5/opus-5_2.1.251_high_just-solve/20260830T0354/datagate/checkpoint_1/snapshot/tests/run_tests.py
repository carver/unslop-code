"""End-to-end tests for datagate."""
import functools, http.server, json, os, socket, subprocess, sys, threading, time, urllib.parse
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")

PASS = FAILED = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAILED
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAILED += 1
        FAILURES.append(name)
        print("  FAIL %s  %s" % (name, detail))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/status/"):
            code = int(self.path.rsplit("/", 1)[1])
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"nope")
            return
        return super().do_GET()


def start_fixture_server(port):
    handler = functools.partial(Quiet, directory=FIXTURES)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def get(url):
    req = urllib.request.Request(url, headers={"Origin": "https://example.com"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {"_raw": body}
        return e.code, payload, dict(e.headers)


def main():
    fport = free_port()
    start_fixture_server(fport)
    base_fx = "http://127.0.0.1:%d" % fport

    dport = free_port()
    proc = subprocess.Popen(
        [os.path.join(ROOT, "venv", "bin", "python"), os.path.join(ROOT, "datagate.py"),
         "start", "--port", str(dport), "--address", "127.0.0.1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = "http://127.0.0.1:%d" % dport
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/", timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)

    def conv(src, **kw):
        q = {"source": src}
        q.update(kw)
        return get(base + "/convert?" + urllib.parse.urlencode(q))

    try:
        # --- basic happy path -------------------------------------------
        st, body, hdrs = conv(base_fx + "/basic.csv")
        check("convert 200", st == 200, (st, body))
        check("convert ok true", body.get("ok") is True, body)
        ep = body.get("endpoint", "")
        check("endpoint shape", ep.startswith("/datasets/"), body)
        check("cors on convert", hdrs.get("Access-Control-Allow-Origin") == "*", hdrs)

        st2, body2, _ = conv(base_fx + "/basic.csv")
        check("determinism same endpoint", body2.get("endpoint") == ep, (ep, body2))

        st3, ds, hdrs3 = get(base + ep)
        check("dataset 200", st3 == 200, (st3, ds))
        check("dataset ok", ds.get("ok") is True, ds)
        check("columns order", ds.get("columns") == ["name", "age", "score", "start"], ds)
        check("row0", ds["rows"][0] == ["Alice", 30, 91.5, "08:30"], ds["rows"][0])
        check("row1 time text", ds["rows"][1] == ["Bob", 25, 78.25, "9:15"], ds["rows"][1])
        check("row2 int", ds["rows"][2] == ["Carol", 41, 88, "12:00"], ds["rows"][2])
        check("query_ms present", isinstance(ds.get("query_ms"), (int, float)) and ds["query_ms"] >= 0, ds.get("query_ms"))
        check("cors on dataset", hdrs3.get("Access-Control-Allow-Origin") == "*", hdrs3)

        # --- delimiters --------------------------------------------------
        st, b, _ = conv(base_fx + "/semi.csv")
        _, ds, _ = get(base + b["endpoint"])
        check("semicolon delim", ds["columns"] == ["city", "pop", "ratio"] and ds["rows"][0] == ["Berlin", 3600000, 1.5], ds)

        st, b, _ = conv(base_fx + "/tab.csv")
        _, ds, _ = get(base + b["endpoint"])
        check("tab delim", ds["columns"] == ["a", "b", "c"] and ds["rows"][1] == [4, 5, "six"], ds)

        st, b, _ = conv(base_fx + "/quoted.csv")
        _, ds, _ = get(base + b["endpoint"])
        check("quoted fields", ds["rows"][0] == ["Smith, John", 'says "hi"', 3], ds["rows"])

        # --- encodings ----------------------------------------------------
        st, b, _ = conv(base_fx + "/latin1.csv", charset="latin-1")
        _, ds, _ = get(base + b["endpoint"])
        check("explicit latin-1", ds["rows"][0] == ["José", "Málaga"], ds["rows"])

        st, b, _ = conv(base_fx + "/latin1.csv")
        check("detect latin-1 convert ok", st == 200, (st, b))
        if st == 200:
            _, ds, _ = get(base + b["endpoint"])
            check("detect latin-1 values", ds["rows"][0] == ["José", "Málaga"], ds["rows"])

        st, b, _ = conv(base_fx + "/utf16.csv")
        check("detect utf-16", st == 200, (st, b))
        if st == 200:
            _, ds, _ = get(base + b["endpoint"])
            check("utf-16 values", ds["columns"] == ["name", "city"] and ds["rows"][0] == ["José", "Málaga"], ds)

        st, b, _ = conv(base_fx + "/bom.csv")
        _, ds, _ = get(base + b["endpoint"])
        check("utf-8 bom header clean", ds["columns"] == ["name", "age"], ds["columns"])

        st, b, _ = conv(base_fx + "/latin1.csv", charset="utf-8")
        check("wrong charset -> 400", st == 400 and b.get("ok") is False, (st, b))

        st, b, _ = conv(base_fx + "/basic.csv", charset="definitely-not-a-charset")
        check("unknown charset -> 400", st == 400 and b.get("ok") is False, (st, b))

        # --- errors --------------------------------------------------------
        st, b, _ = get(base + "/convert")
        check("missing source -> 400", st == 400 and b.get("ok") is False and "error" in b, (st, b))

        st, b, _ = conv("not a url")
        check("invalid url -> 400", st == 400, (st, b))
        st, b, _ = conv("ftp://example.com/x.csv")
        check("bad scheme -> 400", st == 400, (st, b))
        st, b, _ = conv("http:///x.csv")
        check("no host -> 400", st == 400, (st, b))

        st, b, _ = conv("http://127.0.0.1:%d/missing.csv" % fport)
        check("remote 404 -> 404", st == 404 and b.get("ok") is False, (st, b))
        st, b, _ = conv("http://127.0.0.1:%d/status/500" % fport)
        check("remote 500 -> 404", st == 404, (st, b))
        st, b, _ = conv("http://127.0.0.1:1/x.csv")
        check("unreachable -> 404", st == 404, (st, b))
        st, b, _ = conv("http://nonexistent.invalid.tld.example/x.csv")
        check("dns fail -> 404", st == 404, (st, b))

        for name in ("notcsv.html", "notcsv.json", "prose.txt", "binary.bin", "headeronly.csv"):
            st, b, _ = conv(base_fx + "/" + name)
            check("non-tabular %s -> 400" % name, st == 400 and b.get("ok") is False, (st, b))

        st, b, _ = get(base + "/datasets/deadbeefdeadbeef")
        check("unknown dataset -> 404", st == 404 and b.get("ok") is False, (st, b))
        st, b, _ = get(base + "/nope/nope")
        check("unknown route -> 404 json", st == 404 and b.get("ok") is False, (st, b))

        # --- limit ---------------------------------------------------------
        st, b, _ = conv(base_fx + "/big.csv")
        _, ds, _ = get(base + b["endpoint"])
        check("row limit 100", len(ds["rows"]) == 100, len(ds["rows"]))
        check("first row", ds["rows"][0] == [1, 2], ds["rows"][0])
        check("last row", ds["rows"][-1] == [100, 200], ds["rows"][-1])

        st, b, _ = conv(base_fx + "/ragged.csv")
        check("ragged parsed", st == 200, (st, b))
        if st == 200:
            _, ds, _ = get(base + b["endpoint"])
            check("ragged rectangular", all(len(r) == 3 for r in ds["rows"]), ds["rows"])

        # --- CORS preflight ---------------------------------------------------
        req = urllib.request.Request(base + "/convert", method="OPTIONS",
                                     headers={"Origin": "https://x.com",
                                              "Access-Control-Request-Method": "GET"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                h = dict(r.headers)
                st = r.status
        except urllib.error.HTTPError as e:
            h, st = dict(e.headers), e.code
        check("preflight cors", st in (200, 204) and h.get("Access-Control-Allow-Origin") == "*", (st, h))
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    print("\n%d passed, %d failed" % (PASS, FAILED))
    if FAILURES:
        print("failing: " + ", ".join(FAILURES))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
