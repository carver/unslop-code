"""End-to-end tests for datagate."""
import csv, functools, http.server, io, json, os, shutil, socket, subprocess, sys
import tempfile, threading, time
import urllib.parse, urllib.request, urllib.error

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


# path -> number of GETs the fixture server has served, so a test can tell a
# cache hit (no download) from a re-ingestion (one more download).
HITS = {}
# path -> body bytes, or None to answer 404; lets a test change what a stable
# url serves between requests.
DYNAMIC = {}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        HITS[self.path] = HITS.get(self.path, 0) + 1
        if self.path in DYNAMIC:
            body = DYNAMIC[self.path]
            if body is None:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", "4")
                self.end_headers()
                self.wfile.write(b"gone")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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


def get_raw(url):
    """Like get(), but keeps the body as bytes (used by /export)."""
    req = urllib.request.Request(url, headers={"Origin": "https://example.com"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def post(url, body, content_type=None):
    headers = {"Origin": "https://example.com"}
    if content_type is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"_raw": raw}
        return e.code, payload, dict(e.headers)


BOUNDARY = "----datagate-test-boundary"


def multipart(parts):
    """Build (content_type, body) for parts of (name, filename or None, bytes)."""
    body = b""
    for name, filename, data in parts:
        body += ("--%s\r\n" % BOUNDARY).encode()
        if filename is None:
            body += ('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode()
        else:
            body += ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                     % (name, filename)).encode()
            body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += data + b"\r\n"
    body += ("--%s--\r\n" % BOUNDARY).encode()
    return "multipart/form-data; boundary=%s" % BOUNDARY, body


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def read_csv(body):
    return [row for row in csv.reader(io.StringIO(body.decode("utf-8"), newline=""))]


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

        # --- total ------------------------------------------------------------
        st, b, _ = conv(base_fx + "/big.csv")
        big_ep = b["endpoint"]
        _, ds, _ = get(base + big_ep)
        check("total present", ds.get("total") == 250, ds.get("total"))
        check("total independent of page", len(ds["rows"]) == 100, len(ds["rows"]))

        # --- _size / _offset ----------------------------------------------------
        _, ds, _ = get(base + big_ep + "?_size=5")
        check("_size limits", len(ds["rows"]) == 5 and ds["rows"][0] == [1, 2], ds["rows"])
        check("_size keeps total", ds["total"] == 250, ds.get("total"))

        _, ds, _ = get(base + big_ep + "?_size=99999")
        check("_size over-large returns all", len(ds["rows"]) == 250, len(ds["rows"]))

        _, ds, _ = get(base + big_ep + "?_offset=3&_size=2")
        check("_offset skips", ds["rows"] == [[4, 8], [5, 10]], ds["rows"])

        _, ds, _ = get(base + big_ep + "?_offset=0&_size=1")
        check("_offset 0 default", ds["rows"] == [[1, 2]], ds["rows"])

        _, ds, _ = get(base + big_ep + "?_offset=9999")
        check("_offset past end", ds["rows"] == [] and ds["total"] == 250, ds)

        for bad in ("0", "-1", "abc", "", "1.5", "1e3", " "):
            st, b, _ = get(base + big_ep + "?_size=" + urllib.parse.quote(bad))
            check("_size=%r -> 400" % bad, st == 400 and b.get("ok") is False and "error" in b, (st, b))

        for bad in ("-1", "abc", "", "2.5"):
            st, b, _ = get(base + big_ep + "?_offset=" + urllib.parse.quote(bad))
            check("_offset=%r -> 400" % bad, st == 400 and b.get("ok") is False and "error" in b, (st, b))

        # --- sorting ------------------------------------------------------------
        st, b, _ = conv(base_fx + "/sortable.csv")
        sep = b["endpoint"]
        _, ds, _ = get(base + sep)
        check("sortable unsorted", [r[0] for r in ds["rows"]] == ["delta", "alpha", "charlie", "bravo"], ds["rows"])

        _, ds, _ = get(base + sep + "?_sort=name")
        check("_sort asc text", [r[0] for r in ds["rows"]] == ["alpha", "bravo", "charlie", "delta"], ds["rows"])

        _, ds, _ = get(base + sep + "?_sort_desc=name")
        check("_sort_desc text", [r[0] for r in ds["rows"]] == ["delta", "charlie", "bravo", "alpha"], ds["rows"])

        _, ds, _ = get(base + sep + "?_sort=score")
        check("_sort asc numeric stable", [r[0] for r in ds["rows"]] == ["delta", "charlie", "bravo", "alpha"], ds["rows"])

        _, ds, _ = get(base + sep + "?_sort_desc=score")
        check("_sort_desc numeric stable", [r[0] for r in ds["rows"]] == ["alpha", "bravo", "delta", "charlie"], ds["rows"])

        _, ds, _ = get(base + sep + "?_sort=name&_sort_desc=score")
        check("_sort_desc wins", [r[0] for r in ds["rows"]] == ["alpha", "bravo", "delta", "charlie"], ds["rows"])

        _, ds, _ = get(base + sep + "?_sort=name&_size=2")
        check("sort before pagination", [r[0] for r in ds["rows"]] == ["alpha", "bravo"], ds["rows"])

        _, ds, _ = get(base + sep + "?_sort=name&_size=2&_offset=2")
        check("sort before pagination offset", [r[0] for r in ds["rows"]] == ["charlie", "delta"], ds["rows"])
        check("sort keeps total", ds["total"] == 4, ds.get("total"))

        for param in ("_sort", "_sort_desc"):
            st, b, _ = get(base + sep + "?%s=nope" % param)
            check("%s unknown column -> 400" % param, st == 400 and b.get("ok") is False, (st, b))
            st, b, _ = get(base + sep + "?%s=" % param)
            check("%s empty -> 400" % param, st == 400 and b.get("ok") is False, (st, b))

        # --- _shape --------------------------------------------------------------
        _, ds, _ = get(base + sep + "?_shape=lists")
        check("_shape=lists arrays", all(isinstance(r, list) for r in ds["rows"]), ds["rows"])
        check("_shape=lists no rowid", all("rowid" not in str(c) for c in ds["columns"]), ds["columns"])

        _, ds, _ = get(base + sep + "?_shape=objects")
        check("_shape=objects dicts", all(isinstance(r, dict) for r in ds["rows"]), ds["rows"])
        check("objects rowid 1-based", [r["rowid"] for r in ds["rows"]] == [1, 2, 3, 4], ds["rows"])
        check("objects values", ds["rows"][0] == {"rowid": 1, "name": "delta", "score": 10, "city": "Zurich"}, ds["rows"][0])
        check("rowid not in columns", ds["columns"] == ["name", "score", "city"], ds["columns"])

        _, ds, _ = get(base + sep + "?_shape=objects&_sort=name")
        check("rowid follows source row after sort", [r["rowid"] for r in ds["rows"]] == [2, 4, 3, 1], ds["rows"])

        _, ds, _ = get(base + sep + "?_shape=objects&_offset=2&_size=1")
        check("rowid with offset", [r["rowid"] for r in ds["rows"]] == [3], ds["rows"])

        for bad in ("list", "object", "", "LISTS", "dicts"):
            st, b, _ = get(base + sep + "?_shape=" + urllib.parse.quote(bad))
            check("_shape=%r -> 400" % bad, st == 400 and b.get("ok") is False, (st, b))

        # --- visibility toggles ---------------------------------------------------
        _, ds, _ = get(base + sep + "?_shape=objects&_rowid=hide")
        check("_rowid=hide removes rowid", all("rowid" not in r for r in ds["rows"]), ds["rows"])
        check("_rowid=hide keeps values", ds["rows"][0] == {"name": "delta", "score": 10, "city": "Zurich"}, ds["rows"][0])

        _, ds, _ = get(base + sep + "?_total=hide")
        check("_total=hide removes total", "total" not in ds, ds)
        check("_total=hide keeps rows", len(ds["rows"]) == 4, ds)

        _, ds, _ = get(base + sep + "?_shape=objects&_rowid=hide&_total=hide")
        check("both toggles", "total" not in ds and all("rowid" not in r for r in ds["rows"]), ds)

        _, ds, _ = get(base + sep + "?_rowid=hide")
        check("_rowid=hide with lists ok", len(ds["rows"]) == 4 and ds.get("total") == 4, ds)

        for param in ("_rowid", "_total"):
            for bad in ("show", "", "HIDE", "true", "1"):
                st, b, _ = get(base + sep + "?%s=%s" % (param, urllib.parse.quote(bad)))
                check("%s=%r -> 400" % (param, bad), st == 400 and b.get("ok") is False, (st, b))

        # --- repeated control parameters ------------------------------------------
        repeats = {
            "_size": "2&_size=3", "_offset": "0&_offset=1", "_shape": "lists&_shape=objects",
            "_sort": "name&_sort=score", "_sort_desc": "name&_sort_desc=score",
            "_rowid": "hide&_rowid=hide", "_total": "hide&_total=hide",
        }
        for param, qs in repeats.items():
            st, b, _ = get(base + sep + "?%s=%s" % (param, qs))
            check("repeated %s -> 400" % param, st == 400 and b.get("ok") is False and "error" in b, (st, b))

        # --- unknown dataset still 404 even with controls --------------------------
        st, b, _ = get(base + "/datasets/deadbeefdeadbeef?_size=5")
        check("unknown dataset with controls -> 404", st == 404, (st, b))

        # --- filtering ------------------------------------------------------------
        st, b, _ = conv(base_fx + "/filter.csv")
        fep = b["endpoint"]

        def names(qs):
            _, d, _ = get(base + fep + ("?" + qs if qs else ""))
            return [r[0] for r in d["rows"]], d

        base_names, ds = names("")
        check("filter fixture loaded",
              base_names == ["Alice", "bob", "Carol", "Dave", "Erin", "Frank"], ds)

        got, ds = names("name__exact=Alice")
        check("__exact matches", got == ["Alice"] and ds["total"] == 1, ds)
        got, ds = names("name__exact=alice")
        check("__exact case-sensitive", got == [] and ds["total"] == 0, ds)
        got, ds = names("name__exact=Ali")
        check("__exact is not a prefix", got == [], ds)
        got, ds = names("score__exact=30")
        check("__exact on numeric cell", got == ["Alice"], ds)
        got, ds = names("score__exact=7.5")
        check("__exact on float cell", got == ["bob"], ds)
        got, ds = names("score__exact=")
        check("__exact empty matches blank cell", got == ["Carol"], ds)

        got, ds = names("city__contains=Ber")
        check("__contains substring", got == ["Alice", "bob", "Carol", "Frank"], ds)
        got, ds = names("city__contains=ber")
        check("__contains case-sensitive", got == ["Dave"], ds)
        got, ds = names("tag__contains=")
        check("__contains empty matches all", len(got) == 6, ds)
        got, ds = names("tag__contains=" + urllib.parse.quote("alpha beta"))
        check("__contains with space", got == ["Frank"], ds)

        got, ds = names("score__less=30")
        check("__less strict + skips non-numeric", got == ["bob", "Frank"], ds)
        got, ds = names("score__greater=30")
        check("__greater strict", got == ["Erin"], ds)
        got, ds = names("score__greater=-5")
        check("__greater negative bound", got == ["Alice", "bob", "Erin", "Frank"], ds)
        got, ds = names("score__less=7.5")
        check("__less float bound", got == ["Frank"], ds)
        got, ds = names("score__greater=99999")
        check("__greater matching nothing", got == [] and ds["total"] == 0, ds)

        got, ds = names("city__contains=Ber&score__greater=0")
        check("filters are ANDed", got == ["Alice", "bob"] and ds["total"] == 2, ds)
        got, ds = names("score__greater=0&score__less=100")
        check("two filters same column", got == ["Alice", "bob"], ds)
        got, ds = names("name__exact=Alice&city__exact=Bern")
        check("AND with no overlap", got == [] and ds["total"] == 0, ds)

        got, ds = names("city__contains=Ber&_sort=name")
        check("filter before sort", got == ["Alice", "Carol", "Frank", "bob"], ds)
        got, ds = names("city__contains=Ber&_sort=name&_size=2")
        check("paginate filtered+sorted", got == ["Alice", "Carol"] and ds["total"] == 4, ds)
        got, ds = names("city__contains=Ber&_sort=name&_size=2&_offset=2")
        check("paginate filtered+sorted offset", got == ["Frank", "bob"] and ds["total"] == 4, ds)
        got, ds = names("city__contains=Ber&_sort_desc=score&_size=1")
        check("filter + desc sort", got == ["Alice"] and ds["total"] == 4, ds)
        got, ds = names("city__contains=Ber&_total=hide")
        check("filter + _total=hide", "total" not in ds, ds)

        _, ds, _ = get(base + fep + "?city__contains=Ber&_shape=objects")
        check("filter keeps source rowid", [r["rowid"] for r in ds["rows"]] == [1, 2, 3, 6], ds["rows"])
        check("filter objects values",
              ds["rows"][0] == {"rowid": 1, "name": "Alice", "city": "Berlin",
                                "score": 30, "tag": "alpha"}, ds["rows"][0])
        check("filter keeps columns", ds["columns"] == ["name", "city", "score", "tag"], ds)

        # non-filter parameters are ignored, legacy paging still works
        got, ds = names("foo=bar")
        check("param without __ ignored", len(got) == 6, ds)
        got, ds = names("name=Alice")
        check("column name without comparator ignored", len(got) == 6, ds)
        got, ds = names("limit=2")
        check("legacy limit still works", got == ["Alice", "bob"], ds)
        got, ds = names("_nope__exact=zzz")
        check("leading underscore is not a filter", len(got) == 6, ds)
        got, ds = names("__exact=Alice")
        check("bare separator is a control param, not a filter", len(got) == 6, ds)

        # --- filter errors ----------------------------------------------------------
        bad_filters = [
            ("name__like=Alice", "invalid comparator"),
            ("name__EXACT=Alice", "comparator case-sensitive"),
            ("name__=Alice", "empty comparator"),
            ("name__exact__exact=Alice", "trailing comparator"),
            ("nope__exact=1", "unknown column"),
            ("NAME__exact=Alice", "column case-sensitive"),
            ("name__contains__=x", "malformed key"),
            ("score__less=abc", "less non-numeric"),
            ("score__greater=abc", "greater non-numeric"),
            ("score__less=", "less empty"),
            ("score__greater=", "greater empty"),
            ("name__less=Alice", "less on text value"),
            ("score__less=" + urllib.parse.quote("1,5"), "less comma decimal"),
            ("name__exact=a&name__exact=b", "duplicate filter key"),
            ("score__less=1&score__less=1", "duplicate identical filter key"),
            ("_timeout_ms=0", "query timeout"),
        ]
        for qs, label in bad_filters:
            st, b, _ = get(base + fep + "?" + qs)
            check("%s -> 400" % label,
                  st == 400 and b.get("ok") is False and isinstance(b.get("error"), str) and b["error"],
                  (qs, st, b))

        st, b, _ = get(base + "/datasets/deadbeefdeadbeef?name__exact=x")
        check("unknown dataset with filter -> 404", st == 404, (st, b))


        # --- CSV export ---------------------------------------------------------
        st, raw, hdrs = get_raw(base + ep + "/export")
        ident = ep.rsplit("/", 1)[1]
        check("export 200", st == 200, (st, raw[:80]))
        check("export content-type", hdrs.get("Content-Type") == "text/csv", hdrs)
        check("export content-disposition",
              hdrs.get("Content-Disposition") == 'attachment; filename="%s.csv"' % ident, hdrs)
        check("export cors", hdrs.get("Access-Control-Allow-Origin") == "*", hdrs)
        rows = read_csv(raw)
        check("export header is source column order",
              rows[0] == ["name", "age", "score", "start"], rows)
        check("export rows", rows[1:] == [["Alice", "30", "91.5", "08:30"],
                                          ["Bob", "25", "78.25", "9:15"],
                                          ["Carol", "41", "88", "12:00"]], rows)

        st, raw, _ = get_raw(base + "/datasets/" + ident + "/export?_shape=objects&_rowid=hide&_total=hide")
        check("export ignores shape params", st == 200 and read_csv(raw) == rows, (st, raw))

        st, raw, _ = get_raw(base + big_ep + "/export")
        check("export paginates like dataset", len(read_csv(raw)) == 101, len(read_csv(raw)))
        st, raw, _ = get_raw(base + big_ep + "/export?_size=3&_offset=2")
        check("export _size/_offset",
              read_csv(raw) == [["id", "val"], ["3", "6"], ["4", "8"], ["5", "10"]], read_csv(raw))
        st, raw, _ = get_raw(base + big_ep + "/export?_size=99999")
        check("export _size over-large", len(read_csv(raw)) == 251, len(read_csv(raw)))

        st, raw, _ = get_raw(base + sep + "/export?_sort=name")
        check("export sorted",
              [r[0] for r in read_csv(raw)[1:]] == ["alpha", "bravo", "charlie", "delta"], raw)
        st, raw, _ = get_raw(base + sep + "/export?_sort_desc=score&_size=2")
        check("export sort then paginate",
              [r[0] for r in read_csv(raw)[1:]] == ["alpha", "bravo"], raw)

        st, raw, _ = get_raw(base + fep + "/export?city__contains=Ber")
        check("export filtered",
              [r[0] for r in read_csv(raw)[1:]] == ["Alice", "bob", "Carol", "Frank"], raw)
        st, raw, _ = get_raw(base + fep + "/export?city__contains=Ber&_sort=name&_size=2&_offset=2")
        check("export filter -> sort -> paginate",
              read_csv(raw)[1:] == [["Frank", "Berlin", "-4", "alpha beta"],
                                    ["bob", "Bern", "7.5", "beta"]], read_csv(raw))

        _, b_q, _ = conv(base_fx + "/quoted.csv")
        st, raw, _ = get_raw(base + b_q["endpoint"] + "/export")
        check("export re-quotes correctly",
              read_csv(raw) == [["name", "note", "qty"],
                                ["Smith, John", 'says "hi"', "3"],
                                ["Doe, Jane", "plain", "4"]], read_csv(raw))

        st, b, _ = get(base + "/datasets/deadbeefdeadbeef/export")
        check("export unknown dataset -> 404", st == 404 and b.get("ok") is False, (st, b))
        st, b, _ = get(base + fep + "/export?nope__exact=1")
        check("export bad filter -> 400 json", st == 400 and b.get("ok") is False, (st, b))
        st, b, _ = get(base + fep + "/export?_size=0")
        check("export bad _size -> 400 json", st == 400 and b.get("ok") is False, (st, b))

        # --- spreadsheet ingestion via /convert ---------------------------------
        expected_rows = [["Alice", 30, 91.5, "08:30"], ["Bob", 25, 78.25, "9:15"],
                         ["Carol", 41, 88, "12:00"]]
        for name in ("basic.xlsx", "basic.xls"):
            st, b, _ = conv(base_fx + "/" + name)
            check("convert %s 200" % name, st == 200, (st, b))
            if st == 200:
                _, ds, _ = get(base + b["endpoint"])
                check("%s columns" % name, ds["columns"] == ["name", "age", "score", "start"], ds)
                check("%s rows (first sheet only)" % name, ds["rows"] == expected_rows, ds["rows"])

        st, b, _ = conv(base_fx + "/basic.xlsx", charset="latin-1")
        check("charset ignored for spreadsheets", st == 200, (st, b))

        typed_rows = [["2024-03-05", "08:30", True, 42],
                      ["2024-03-05 14:02:03", "09:15:07", False, 1.25]]
        for name in ("typed.xlsx", "typed.xls"):
            st, b, _ = conv(base_fx + "/" + name)
            check("convert %s 200" % name, st == 200, (st, b))
            if st == 200:
                _, ds, _ = get(base + b["endpoint"])
                check("%s typed cells" % name,
                      ds["columns"] == ["when", "at", "flag", "n"] and ds["rows"] == typed_rows,
                      ds)
                st, raw, _ = get_raw(base + b["endpoint"] + "/export")
                check("%s exports" % name,
                      read_csv(raw) == [["when", "at", "flag", "n"],
                                        ["2024-03-05", "08:30", "true", "42"],
                                        ["2024-03-05 14:02:03", "09:15:07", "false", "1.25"]],
                      read_csv(raw))

        for name in ("headeronly.xlsx", "headeronly.xls", "emptysheet.xlsx", "notsheet.zip"):
            st, b, _ = conv(base_fx + "/" + name)
            check("convert %s -> 400" % name, st == 400 and b.get("ok") is False, (st, b))

        # --- upload --------------------------------------------------------------
        ct, body = multipart([("file", "basic.csv", fixture("basic.csv"))])
        st, b, hdrs = post(base + "/upload", body, ct)
        check("upload 200", st == 200 and b.get("ok") is True, (st, b))
        up_ep = b.get("endpoint", "")
        check("upload endpoint shape", up_ep.startswith("/datasets/"), b)
        check("upload cors", hdrs.get("Access-Control-Allow-Origin") == "*", hdrs)
        _, ds, _ = get(base + up_ep)
        check("uploaded dataset rows", ds["rows"] == expected_rows, ds)

        st, b2, _ = post(base + "/upload", body, ct)
        check("upload determinism", b2.get("endpoint") == up_ep, (up_ep, b2))

        ct2, body2 = multipart([("file", "renamed.csv", fixture("basic.csv"))])
        st, b3, _ = post(base + "/upload", body2, ct2)
        check("upload id follows bytes not name", b3.get("endpoint") == up_ep, (up_ep, b3))

        ct3, body3 = multipart([("attachment", "basic.csv", fixture("basic.csv"))])
        st, b4, _ = post(base + "/upload", body3, ct3)
        check("upload via attachment field", st == 200 and b4.get("endpoint") == up_ep, (st, b4))

        ct4, body4 = multipart([("file", None, b"a,b\n1,2\n")])
        st, b5, _ = post(base + "/upload", body4, ct4)
        check("upload plain form field", st == 200 and b5.get("ok") is True, (st, b5))

        for name in ("basic.xlsx", "basic.xls"):
            ct5, body5 = multipart([("file", name, fixture(name))])
            st, b6, _ = post(base + "/upload", body5, ct5)
            check("upload %s 200" % name, st == 200 and b6.get("ok") is True, (st, b6))
            if st == 200:
                _, ds, _ = get(base + b6["endpoint"])
                check("upload %s rows" % name, ds["rows"] == expected_rows, ds["rows"])

        ct6, body6 = multipart([("file", "latin1.csv", fixture("latin1.csv"))])
        st, b7, _ = post(base + "/upload?charset=latin-1", body6, ct6)
        check("upload honours charset", st == 200, (st, b7))
        if st == 200:
            _, ds, _ = get(base + b7["endpoint"])
            check("upload charset values", ds["rows"][0] == ["Jos\u00e9", "M\u00e1laga"], ds["rows"])

        st, raw, hdrs = get_raw(base + up_ep + "/export")
        check("uploaded dataset exports", st == 200 and read_csv(raw)[0] == ["name", "age", "score", "start"], (st, raw))

        # --- upload errors --------------------------------------------------------
        st, b, _ = post(base + "/upload", b'{"file": "a,b\n1,2"}', "application/json")
        check("non-multipart -> 415", st == 415 and b.get("ok") is False, (st, b))
        st, b, _ = post(base + "/upload", b"file=a,b", "application/x-www-form-urlencoded")
        check("urlencoded upload -> 415", st == 415 and b.get("ok") is False, (st, b))
        st, b, _ = post(base + "/upload", b"a,b\n1,2\n", "text/csv")
        check("raw csv body -> 415", st == 415 and b.get("ok") is False, (st, b))
        st, b, _ = post(base + "/upload", b"a,b\n1,2\n", None)
        check("upload without content-type -> 415", st == 415 and b.get("ok") is False, (st, b))

        ct7, body7 = multipart([("other", "basic.csv", fixture("basic.csv"))])
        st, b, _ = post(base + "/upload", body7, ct7)
        check("missing file field -> 400", st == 400 and b.get("ok") is False, (st, b))
        ct8, body8 = multipart([])
        st, b, _ = post(base + "/upload", body8, ct8)
        check("empty multipart -> 400", st == 400 and b.get("ok") is False, (st, b))

        st, b, _ = post(base + "/upload", b"not a multipart body at all",
                        "multipart/form-data; boundary=" + BOUNDARY)
        check("malformed multipart -> 400", st == 400 and b.get("ok") is False, (st, b))
        st, b, _ = post(base + "/upload", b"whatever", "multipart/form-data")
        check("multipart without boundary -> 400", st == 400 and b.get("ok") is False, (st, b))
        st, b, _ = post(base + "/upload", body[: len(body) // 2],
                        "multipart/form-data; boundary=" + BOUNDARY)
        check("truncated multipart -> 400", st == 400 and b.get("ok") is False, (st, b))

        ct9, body9 = multipart([("file", "notsheet.zip", fixture("notsheet.zip"))])
        st, b, _ = post(base + "/upload", body9, ct9)
        check("upload unsupported format -> 400", st == 400 and b.get("ok") is False, (st, b))
        ct10, body10 = multipart([("file", "headeronly.csv", fixture("headeronly.csv"))])
        st, b, _ = post(base + "/upload", body10, ct10)
        check("upload non-tabular -> 400", st == 400 and b.get("ok") is False, (st, b))
        ct11, body11 = multipart([("file", "empty.csv", b"")])
        st, b, _ = post(base + "/upload", body11, ct11)
        check("upload empty file -> 400", st == 400 and b.get("ok") is False, (st, b))

        st, b, _ = get(base + "/upload")
        check("GET /upload -> 405 json", st == 405 and b.get("ok") is False, (st, b))

        # --- caching ----------------------------------------------------------
        V1 = b"name,age\nAlice,30\nBob,25\n"
        V2 = b"name,age\nCarol,41\nDave,52\nErin,19\n"
        DYNAMIC["/dyn.csv"] = V1
        dyn = base_fx + "/dyn.csv"

        st, b, _ = conv(dyn)
        check("cache first convert 200", st == 200, (st, b))
        dyn_ep = b.get("endpoint", "")
        check("cache first download happened", HITS.get("/dyn.csv") == 1, HITS)

        st, b2, _ = conv(dyn)
        check("cache hit 200", st == 200, (st, b2))
        check("cache hit identical body", b2 == b, (b, b2))
        check("cache hit skipped download", HITS.get("/dyn.csv") == 1, HITS)

        _, ds, _ = get(base + dyn_ep)
        check("cached rows", ds.get("rows") == [["Alice", 30], ["Bob", 25]], ds)

        DYNAMIC["/dyn.csv"] = V2
        st, b3, _ = conv(dyn)
        check("cache serves stale after source change", st == 200 and b3 == b, (st, b3))
        check("cache still skipped download", HITS.get("/dyn.csv") == 1, HITS)
        _, ds, _ = get(base + dyn_ep)
        check("cached rows unchanged", ds.get("rows") == [["Alice", 30], ["Bob", 25]], ds)

        def conv_force(baseurl, src, times=1):
            q = "source=" + urllib.parse.quote(src, safe="") + "&force" * times
            return get(baseurl + "/convert?" + q)

        st, b4, _ = conv_force(base, dyn)
        check("force 200", st == 200, (st, b4))
        check("force re-downloads", HITS.get("/dyn.csv") == 2, HITS)
        check("force keeps endpoint", b4.get("endpoint") == dyn_ep, (b4, dyn_ep))
        _, ds, _ = get(base + dyn_ep)
        check("force replaced dataset",
              ds.get("rows") == [["Carol", 41], ["Dave", 52], ["Erin", 19]], ds)

        st, b5, _ = conv(dyn)
        check("cache refreshed after force",
              st == 200 and HITS.get("/dyn.csv") == 2, (st, b5, HITS))

        st, b6, _ = conv_force(base, dyn, times=2)
        check("repeated force -> 400", st == 400 and b6.get("ok") is False, (st, b6))
        check("repeated force did not download", HITS.get("/dyn.csv") == 2, HITS)

        st, b7, _ = get(base + "/convert?source=" + urllib.parse.quote(dyn, safe="")
                        + "&force=1&force=1")
        check("repeated force values -> 400", st == 400 and b7.get("ok") is False, (st, b7))

        # a forced re-ingestion that fails leaves the previous dataset in place
        DYNAMIC["/dyn.csv"] = None
        st, b8, _ = conv_force(base, dyn)
        check("forced failure -> 404 envelope",
              st == 404 and b8.get("ok") is False and "error" in b8, (st, b8))
        _, ds, _ = get(base + dyn_ep)
        check("prior dataset still queryable after forced failure",
              ds.get("ok") is True
              and ds.get("rows") == [["Carol", 41], ["Dave", 52], ["Erin", 19]], ds)

        DYNAMIC["/dyn.csv"] = b"<html><body>not a table</body></html>\n"
        st, b9, _ = conv_force(base, dyn)
        check("forced non-tabular keeps 400 envelope",
              st == 400 and b9.get("ok") is False, (st, b9))
        _, ds, _ = get(base + dyn_ep)
        check("prior dataset survives a forced 400",
              ds.get("rows") == [["Carol", 41], ["Dave", 52], ["Erin", 19]], ds)
        DYNAMIC["/dyn.csv"] = V2

        # --- CACHE_ENABLED ------------------------------------------------------
        for bad in ("maybe", "2", "", "truthy", "true false"):
            env = dict(os.environ, CACHE_ENABLED=bad)
            p = subprocess.run(
                [os.path.join(ROOT, "venv", "bin", "python"),
                 os.path.join(ROOT, "datagate.py"), "start",
                 "--port", str(free_port()), "--address", "127.0.0.1"],
                env=env, capture_output=True, timeout=30,
            )
            check("CACHE_ENABLED=%r fails startup" % bad, p.returncode != 0,
                  (p.returncode, p.stderr[-200:]))

        off_port = free_port()
        off = subprocess.Popen(
            [os.path.join(ROOT, "venv", "bin", "python"), os.path.join(ROOT, "datagate.py"),
             "start", "--port", str(off_port), "--address", "127.0.0.1"],
            env=dict(os.environ, CACHE_ENABLED="OFF"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        off_base = "http://127.0.0.1:%d" % off_port
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(off_base + "/", timeout=1).read()
                    break
                except Exception:
                    time.sleep(0.1)

            DYNAMIC["/off.csv"] = V1
            off_src = base_fx + "/off.csv"
            st, ob, _ = get(off_base + "/convert?source="
                            + urllib.parse.quote(off_src, safe=""))
            check("cache off convert 200", st == 200, (st, ob))
            off_ep = ob.get("endpoint", "")
            check("cache off first download", HITS.get("/off.csv") == 1, HITS)

            DYNAMIC["/off.csv"] = V2
            st, ob2, _ = get(off_base + "/convert?source="
                             + urllib.parse.quote(off_src, safe=""))
            check("cache off re-downloads", st == 200 and HITS.get("/off.csv") == 2,
                  (st, ob2, HITS))
            check("cache off identical body", ob2 == ob, (ob, ob2))
            _, ds, _ = get(off_base + off_ep)
            check("cache off replaced stored data",
                  ds.get("rows") == [["Carol", 41], ["Dave", 52], ["Erin", 19]], ds)

            st, ob3, _ = conv_force(off_base, off_src)
            check("cache off force still works",
                  st == 200 and ob3.get("endpoint") == off_ep and HITS.get("/off.csv") == 3,
                  (st, ob3, HITS))
            st, ob4, _ = conv_force(off_base, off_src, times=2)
            check("cache off repeated force -> 400",
                  st == 400 and ob4.get("ok") is False, (st, ob4))

            DYNAMIC["/off.csv"] = None
            st, ob5, _ = get(off_base + "/convert?source="
                             + urllib.parse.quote(off_src, safe=""))
            check("cache off failure keeps codes", st == 404 and ob5.get("ok") is False,
                  (st, ob5))
            _, ds, _ = get(off_base + off_ep)
            check("cache off failure keeps dataset queryable",
                  ds.get("ok") is True
                  and ds.get("rows") == [["Carol", 41], ["Dave", 52], ["Erin", 19]], ds)
        finally:
            off.terminate()
            off.wait(timeout=10)

        # --- configuration, size limits and access control --------------------
        SMALL = b"name,age\r\nAlice,30\r\n"
        DYNAMIC["/limited.csv"] = SMALL
        limited_src = base_fx + "/limited.csv"
        exact = len(SMALL)

        def start_server(env):
            """Start a second datagate with extra environment; return proc, base."""
            port = free_port()
            child = subprocess.Popen(
                [os.path.join(ROOT, "venv", "bin", "python"),
                 os.path.join(ROOT, "datagate.py"), "start",
                 "--port", str(port), "--address", "127.0.0.1"],
                env=dict(os.environ, **env),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            url = "http://127.0.0.1:%d" % port
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + "/", timeout=1).read()
                    break
                except urllib.error.HTTPError:
                    break  # answering at all (even 403) means it is listening
                except Exception:
                    time.sleep(0.1)
            return child, url

        def stop_server(child):
            child.terminate()
            child.wait(timeout=10)

        def call(url, headers=None, data=None, content_type=None):
            head = dict(headers or {})
            if content_type is not None:
                head["Content-Type"] = content_type
            req = urllib.request.Request(
                url, data=data, headers=head,
                method="POST" if data is not None else "GET")
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.status, json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                raw = e.read().decode()
                try:
                    return e.code, json.loads(raw)
                except ValueError:
                    return e.code, {"_raw": raw}

        def convert_on(url, src, headers=None):
            return call(url + "/convert?source=" + urllib.parse.quote(src, safe=""),
                        headers)

        def upload_on(url, data, headers=None):
            ctype, body = multipart([("file", "small.csv", data)])
            return call(url + "/upload", headers, body, ctype)

        def envelope(body):
            return body.get("ok") is False and isinstance(body.get("error"), str) \
                and bool(body["error"])

        work = tempfile.mkdtemp(prefix="datagate-config-tests-")
        try:
            # --- MAX_SOURCE_SIZE ------------------------------------------
            child, url = start_server({"MAX_SOURCE_SIZE": str(exact),
                                       "STORAGE_DIR": os.path.join(work, "size-eq")})
            try:
                st, b = convert_on(url, limited_src)
                check("size equal to limit converts", st == 200 and b.get("ok") is True,
                      (st, b))
                st, b = upload_on(url, SMALL)
                check("size equal to limit uploads", st == 200 and b.get("ok") is True,
                      (st, b))
            finally:
                stop_server(child)

            child, url = start_server({"MAX_SOURCE_SIZE": str(exact - 1),
                                       "STORAGE_DIR": os.path.join(work, "size-lt")})
            try:
                st, b = convert_on(url, limited_src)
                check("convert over limit -> 400", st == 400 and envelope(b), (st, b))
                st, b = upload_on(url, SMALL)
                check("upload over limit -> 400", st == 400 and envelope(b), (st, b))
            finally:
                stop_server(child)

            child, url = start_server({"STORAGE_DIR": os.path.join(work, "size-unset")})
            try:
                st, b = convert_on(url, base_fx + "/big.csv")
                check("unset limit has no maximum", st == 200 and b.get("ok") is True,
                      (st, b))
            finally:
                stop_server(child)

            # --- ORIGIN_ALLOWLIST -----------------------------------------
            child, url = start_server({
                "ORIGIN_ALLOWLIST": "example.com, cdn.trusted.org",
                "STORAGE_DIR": os.path.join(work, "allow"),
            })
            try:
                st, b = convert_on(url, limited_src)
                check("missing referer -> 403", st == 403 and envelope(b), (st, b))

                allowed = [
                    ("https://example.com/page", "exact host"),
                    ("https://app.example.com/page", "subdomain"),
                    ("https://APP.Example.COM/page", "case-insensitive"),
                    ("http://cdn.trusted.org/x?y=1#z", "second entry"),
                ]
                for referer, label in allowed:
                    st, b = convert_on(url, limited_src, {"Referer": referer})
                    check("referer allowed: %s" % label,
                          st == 200 and b.get("ok") is True, (referer, st, b))

                refused = [
                    ("https://notexample.com/page", "suffix needs a dot boundary"),
                    ("https://example.com.evil.net/page", "suffix is not a prefix"),
                    ("https://trusted.org/page", "parent of an allowed host"),
                    ("https://evil.net/?u=https://example.com", "host is not the query"),
                    ("example.com/page", "referer without a host"),
                    ("", "empty referer"),
                ]
                for referer, label in refused:
                    st, b = convert_on(url, limited_src, {"Referer": referer})
                    check("referer refused: %s" % label,
                          st == 403 and envelope(b), (referer, st, b))

                st, b = call(url + "/nope/nope", {"Referer": "https://evil.net/"})
                check("allowlist runs before routing", st == 403 and envelope(b),
                      (st, b))
                st, b = upload_on(url, SMALL, {"Referer": "https://evil.net/"})
                check("allowlist covers upload", st == 403 and envelope(b), (st, b))

                st, b = convert_on(url, limited_src, {"Referer": "https://example.com/"})
                ident_ep = b.get("endpoint", "")
                st, b = call(url + ident_ep, {"Referer": "https://example.com/"})
                check("allowed referer reaches datasets", st == 200 and b.get("ok") is True,
                      (st, b))
                st, b = call(url + ident_ep)
                check("datasets also need a referer", st == 403 and envelope(b), (st, b))
            finally:
                stop_server(child)

            st, b = convert_on(base, limited_src)
            check("no allowlist means no referer needed", st == 200, (st, b))

            # --- REQUIRE_TLS ----------------------------------------------
            child, url = start_server({"REQUIRE_TLS": "true",
                                       "STORAGE_DIR": os.path.join(work, "tls")})
            try:
                host = url.split("//", 1)[1]
                st, b = convert_on(url, limited_src)
                ep = b.get("endpoint", "")
                check("tls convert endpoint is absolute https",
                      st == 200 and ep.startswith("https://%s/datasets/" % host), (st, b))
                st, b2 = upload_on(url, SMALL)
                check("tls upload endpoint is absolute https",
                      st == 200 and b2.get("endpoint", "").startswith(
                          "https://%s/datasets/" % host), (st, b2))
                st, b3 = call(url + "/datasets/" + ep.rsplit("/", 1)[1])
                check("tls dataset still reachable", st == 200 and b3.get("ok") is True,
                      (st, b3))
                st, b4 = convert_on(url, limited_src)
                check("tls cached endpoint is absolute too",
                      b4.get("endpoint") == ep, (b4, ep))
            finally:
                stop_server(child)

            st, b = convert_on(base, limited_src)
            check("without tls the endpoint is relative",
                  b.get("endpoint", "").startswith("/datasets/"), b)

            # --- STORAGE_DIR ----------------------------------------------
            nested = os.path.join(work, "made", "up", "dirs")
            child, url = start_server({"STORAGE_DIR": nested})
            try:
                check("storage dir is created", os.path.isdir(nested), nested)
                st, b = convert_on(url, base_fx + "/basic.csv")
                persisted_ep = b.get("endpoint", "")
                st, before = call(url + persisted_ep)
                check("persisted dataset readable", st == 200, (st, before))
            finally:
                stop_server(child)

            child, url = start_server({"STORAGE_DIR": nested})
            try:
                st, after = call(url + persisted_ep)
                check("dataset survives a restart on the same storage dir",
                      st == 200 and after.get("rows") == before.get("rows")
                      and after.get("columns") == before.get("columns"), (st, after))
                st, body_csv, _ = get_raw(url + persisted_ep + "/export")
                check("restarted export works",
                      st == 200 and read_csv(body_csv)[0] == before.get("columns"),
                      (st, body_csv[:80]))
            finally:
                stop_server(child)

            child, url = start_server({"STORAGE_DIR": os.path.join(work, "elsewhere")})
            try:
                st, b = call(url + persisted_ep)
                check("a different storage dir does not see it",
                      st == 404 and envelope(b), (st, b))
            finally:
                stop_server(child)

            # --- DATAGATE_CONFIG file -------------------------------------
            conf_storage = os.path.join(work, "from-file")
            conf = os.path.join(work, "datagate.conf")
            with open(conf, "w") as fh:
                fh.write("# datagate settings\n"
                         "\n"
                         "   ; another comment\n"
                         "MAX_SOURCE_SIZE = %d\n"
                         "ORIGIN_ALLOWLIST = Example.COM , cdn.trusted.org\n"
                         "REQUIRE_TLS = YES\n"
                         "STORAGE_DIR = %s\n"
                         "CACHE_ENABLED = off\n" % (exact, conf_storage))

            child, url = start_server({"DATAGATE_CONFIG": conf})
            try:
                host = url.split("//", 1)[1]
                st, b = convert_on(url, limited_src, {"Referer": "https://example.com/"})
                check("config file: allowlist and tls applied",
                      st == 200 and b.get("endpoint", "").startswith(
                          "https://%s/datasets/" % host), (st, b))
                check("config file: storage dir used",
                      os.path.isdir(conf_storage) and os.listdir(conf_storage),
                      conf_storage)
                st, b = convert_on(url, base_fx + "/basic.csv",
                                   {"Referer": "https://example.com/"})
                check("config file: size limit applied", st == 400 and envelope(b),
                      (st, b))
                st, b = convert_on(url, limited_src, {"Referer": "https://evil.net/"})
                check("config file: referer still refused", st == 403 and envelope(b),
                      (st, b))
            finally:
                stop_server(child)

            # environment beats the file
            child, url = start_server({"DATAGATE_CONFIG": conf,
                                       "REQUIRE_TLS": "0",
                                       "ORIGIN_ALLOWLIST": "",
                                       "MAX_SOURCE_SIZE": "",
                                       "STORAGE_DIR": os.path.join(work, "env-wins")})
            try:
                st, b = convert_on(url, base_fx + "/basic.csv")
                check("environment overrides the config file",
                      st == 200 and b.get("endpoint", "").startswith("/datasets/"),
                      (st, b))
            finally:
                stop_server(child)

            # --- startup failures ------------------------------------------
            bad_configs = {
                "no separator": "MAX_SOURCE_SIZE 100\n",
                "non-numeric size": "MAX_SOURCE_SIZE=lots\n",
                "negative size": "MAX_SOURCE_SIZE=-1\n",
                "bad boolean": "REQUIRE_TLS=perhaps\n",
                "bad cache boolean": "CACHE_ENABLED=2\n",
                "empty key": "=value\n",
            }
            for label, text in bad_configs.items():
                bad_path = os.path.join(work, "bad.conf")
                with open(bad_path, "w") as fh:
                    fh.write(text)
                p = subprocess.run(
                    [os.path.join(ROOT, "venv", "bin", "python"),
                     os.path.join(ROOT, "datagate.py"), "start",
                     "--port", str(free_port()), "--address", "127.0.0.1"],
                    env=dict(os.environ, DATAGATE_CONFIG=bad_path),
                    capture_output=True, timeout=30)
                check("invalid config (%s) fails startup" % label, p.returncode != 0,
                      (p.returncode, p.stderr[-200:]))

            p = subprocess.run(
                [os.path.join(ROOT, "venv", "bin", "python"),
                 os.path.join(ROOT, "datagate.py"), "start",
                 "--port", str(free_port()), "--address", "127.0.0.1"],
                env=dict(os.environ,
                         DATAGATE_CONFIG=os.path.join(work, "does-not-exist.conf")),
                capture_output=True, timeout=30)
            check("unreadable config fails startup", p.returncode != 0,
                  (p.returncode, p.stderr[-200:]))

            p = subprocess.run(
                [os.path.join(ROOT, "venv", "bin", "python"),
                 os.path.join(ROOT, "datagate.py"), "start",
                 "--port", str(free_port()), "--address", "127.0.0.1"],
                env=dict(os.environ, MAX_SOURCE_SIZE="huge"),
                capture_output=True, timeout=30)
            check("invalid environment value fails startup", p.returncode != 0,
                  (p.returncode, p.stderr[-200:]))

            # trimmed, case-insensitive booleans are accepted
            child, url = start_server({"REQUIRE_TLS": " True ",
                                       "CACHE_ENABLED": " OFF ",
                                       "STORAGE_DIR": os.path.join(work, "trimmed")})
            try:
                st, b = convert_on(url, limited_src)
                check("trimmed booleans are accepted",
                      st == 200 and b.get("endpoint", "").startswith("https://"), (st, b))
            finally:
                stop_server(child)
        finally:
            shutil.rmtree(work, ignore_errors=True)

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

        req = urllib.request.Request(base + "/upload", method="OPTIONS",
                                     headers={"Origin": "https://x.com",
                                              "Access-Control-Request-Method": "POST"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                h, st = dict(r.headers), r.status
        except urllib.error.HTTPError as e:
            h, st = dict(e.headers), e.code
        check("preflight cors upload", st in (200, 204) and h.get("Access-Control-Allow-Origin") == "*", (st, h))
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    print("\n%d passed, %d failed" % (PASS, FAILED))
    if FAILURES:
        print("failing: " + ", ".join(FAILURES))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
