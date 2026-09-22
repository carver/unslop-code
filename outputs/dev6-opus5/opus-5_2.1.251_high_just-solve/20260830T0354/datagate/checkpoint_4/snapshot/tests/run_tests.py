"""End-to-end tests for datagate."""
import csv, functools, http.server, io, json, os, socket, subprocess, sys, threading, time
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
