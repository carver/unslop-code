"""Checks for datagate optional dataset enrichment (`/convert?enrich=yes`)."""

import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

import requests

FIXTURES = {}
HITS = {}


class Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        HITS[path] = HITS.get(path, 0) + 1
        if path not in FIXTURES:
            self.send_response(404)
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"not found")
            return
        ctype, body = FIXTURES[path]
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


PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (name, extra))


def xlsx_bytes(rows):
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def main():
    global PASS, FAIL

    FIXTURES["/types.csv"] = ("text/csv", b"""name,qty,ratio,mixed
alice,1,1.5,1
bob,2,2.5,2.5
alice,3,3.5,text
""")
    FIXTURES["/gaps.csv"] = ("text/csv", b"""a,b
1,x
,y
3,
""")
    FIXTURES["/small.csv"] = ("text/csv", b"name,age\nAda,36\nBob,41\n")
    FIXTURES["/book.xlsx"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        xlsx_bytes([["name", "age"], ["Ada", 36], ["Bob", 41], ["Cy", 20]]),
    )

    origin_port = free_port()
    origin = ThreadingHTTPServer(("127.0.0.1", origin_port), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    ORIGIN = "http://127.0.0.1:%d" % origin_port

    store_dir = tempfile.mkdtemp(prefix="datagate-enrich-")
    port = free_port()
    env = dict(os.environ)
    env.pop("CACHE_ENABLED", None)
    env["STORAGE_DIR"] = store_dir
    proc = subprocess.Popen(
        [sys.executable, "datagate.py", "start", "--port", str(port),
         "--address", "127.0.0.1"],
        cwd="/workspace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env,
    )
    BASE = "http://127.0.0.1:%d" % port

    def ready(timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            try:
                requests.get(BASE + "/", timeout=1)
                return True
            except Exception:
                time.sleep(0.1)
        return False

    def convert(name, extra=""):
        url = "%s/convert?source=%s%s" % (
            BASE, quote(ORIGIN + name, safe=""), extra
        )
        return requests.get(url, timeout=20)

    def query(endpoint, extra=""):
        if endpoint.startswith("http"):
            url = endpoint
        else:
            url = BASE + endpoint
        return requests.get(url + extra, timeout=20).json()

    try:
        if not ready():
            print("server did not start:\n%s" % proc.stdout.read())
            return 1

        # ---------------------------------------------------------------
        print("\n[trigger: exactly `enrich=yes` enables enrichment]")
        r = convert("/types.csv", "&enrich=yes")
        body = r.json()
        check("enrich=yes -> 200", r.status_code == 200, r.text)
        check("success body is ok+endpoint only",
              body == {"ok": True,
                       "endpoint": "/datasets/%s" % body.get("endpoint", "//").split("/")[-1]}
              and set(body) == {"ok", "endpoint"}, body)
        check("endpoint path shape",
              body["endpoint"].startswith("/datasets/"), body)
        types_ep = body["endpoint"]
        data = query(types_ep)
        check("enriched query has dataset_summary", "dataset_summary" in data, data)
        check("enriched query has column_details", "column_details" in data, data)

        off_cases = [
            ("absent", ""),
            ("bare ?enrich", "&enrich"),
            ("empty value", "&enrich="),
            ("uppercase YES", "&enrich=YES"),
            ("capitalised Yes", "&enrich=Yes"),
            ("trailing space", "&enrich=yes%20"),
            ("leading space", "&enrich=%20yes"),
            ("value 1", "&enrich=1"),
            ("value true", "&enrich=true"),
            ("value on", "&enrich=on"),
            ("value no", "&enrich=no"),
            ("value yess", "&enrich=yess"),
            ("value y", "&enrich=y"),
            ("repeated yes,yes", "&enrich=yes&enrich=yes"),
            ("repeated yes,no", "&enrich=yes&enrich=no"),
            ("repeated no,yes", "&enrich=no&enrich=yes"),
            ("repeated yes,empty", "&enrich=yes&enrich="),
        ]
        for label, extra in off_cases:
            r = convert("/small.csv", extra + "&force")
            got = r.json()
            check("%s -> 200 ok" % label,
                  r.status_code == 200 and got.get("ok") is True, r.text)
            data = query(got["endpoint"])
            check("%s -> no enrichment" % label,
                  "dataset_summary" not in data and "column_details" not in data,
                  data)

        r = convert("/small.csv", "&enrich=yes&force")
        small_ep = r.json()["endpoint"]
        data = query(small_ep)
        check("exact enrich=yes after off cases enriches",
              "dataset_summary" in data and "column_details" in data, data)

        # ---------------------------------------------------------------
        print("\n[enriched CSV output]")
        data = query(types_ep)
        summary = data["dataset_summary"]
        details = data["column_details"]
        check("summary filetype csv", summary.get("filetype") == "csv", summary)
        check("summary row_count", summary.get("row_count") == 3, summary)
        check("summary column_count", summary.get("column_count") == 4, summary)
        check("details keyed by column name",
              sorted(details) == ["mixed", "name", "qty", "ratio"], details)
        check("text column type", details["name"]["type"] == "text", details["name"])
        check("text distinct", details["name"]["distinct_count"] == 2, details["name"])
        check("text missing", details["name"]["missing_count"] == 0, details["name"])
        check("integer column type", details["qty"]["type"] == "integer", details["qty"])
        check("integer distinct", details["qty"]["distinct_count"] == 3, details["qty"])
        check("float column type", details["ratio"]["type"] == "float", details["ratio"])
        check("float distinct", details["ratio"]["distinct_count"] == 3, details["ratio"])
        check("mixed types -> text", details["mixed"]["type"] == "text", details["mixed"])
        check("every detail has the required keys",
              all({"type", "distinct_count", "missing_count"} <= set(d)
                  for d in details.values()), details)
        check("type labels are from the documented set",
              all(d["type"] in ("text", "number", "integer", "float")
                  for d in details.values()), details)

        r = convert("/gaps.csv", "&enrich=yes")
        gaps_ep = r.json()["endpoint"]
        details = query(gaps_ep)["column_details"]
        check("gaps: numeric column with a gap stays integer",
              details["a"]["type"] == "integer", details["a"])
        check("gaps: missing counted", details["a"]["missing_count"] == 1, details["a"])
        check("gaps: distinct excludes missing",
              details["a"]["distinct_count"] == 2, details["a"])
        check("gaps: text column missing", details["b"]["missing_count"] == 1,
              details["b"])
        check("gaps: text column distinct", details["b"]["distinct_count"] == 2,
              details["b"])

        FIXTURES["/nums.csv"] = ("text/csv", b"n\n1\n2.5\n3\n")
        r = convert("/nums.csv", "&enrich=yes")
        details = query(r.json()["endpoint"])["column_details"]
        check("int+float column -> number", details["n"]["type"] == "number",
              details["n"])
        check("int+float distinct", details["n"]["distinct_count"] == 3, details["n"])

        # ---------------------------------------------------------------
        print("\n[enriched spreadsheet output]")
        r = convert("/book.xlsx", "&enrich=yes")
        check("xlsx convert ok", r.json().get("ok") is True, r.text)
        data = query(r.json()["endpoint"])
        check("xlsx has dataset_summary", "dataset_summary" in data, data)
        check("xlsx filetype excel",
              data["dataset_summary"].get("filetype") == "excel",
              data.get("dataset_summary"))
        check("xlsx has no column_details", "column_details" not in data,
              list(data))

        r = convert("/book.xlsx", "&force")
        data = query(r.json()["endpoint"])
        check("non-enriched xlsx omits both",
              "dataset_summary" not in data and "column_details" not in data, data)

        # ---------------------------------------------------------------
        print("\n[unchanged fields]")
        r = convert("/small.csv", "&force")
        plain = query(small_ep)
        r = convert("/small.csv", "&enrich=yes&force")
        rich = query(small_ep)
        for field in ("ok", "columns", "rows", "total"):
            check("%s unchanged by enrichment" % field,
                  plain.get(field) == rich.get(field),
                  (plain.get(field), rich.get(field)))
        check("query_ms still present and numeric",
              isinstance(rich.get("query_ms"), (int, float)), rich.get("query_ms"))
        check("no null metadata on plain response",
              plain.get("dataset_summary", "absent") == "absent"
              and plain.get("column_details", "absent") == "absent", plain)

        rich_page = query(small_ep, "?_size=1&_shape=objects&name__exact=Ada")
        check("metadata describes the whole dataset, not the page",
              rich_page["dataset_summary"]["row_count"] == 2
              and rich_page["total"] == 1, rich_page)
        check("metadata survives filters",
              "column_details" in rich_page, list(rich_page))

        # ---------------------------------------------------------------
        print("\n[cache and enrichment]")
        FIXTURES["/cache.csv"] = ("text/csv", b"a,b\n1,x\n2,y\n")
        before = HITS.get("/cache.csv", 0)
        convert("/cache.csv")
        check("first convert fetches", HITS["/cache.csv"] == before + 1)
        convert("/cache.csv")
        check("plain repeat served from cache", HITS["/cache.csv"] == before + 1)
        ep = convert("/cache.csv").json()["endpoint"]
        check("cached dataset is not enriched",
              "dataset_summary" not in query(ep), query(ep))

        convert("/cache.csv", "&enrich=yes")
        check("enrich=yes on cached non-enriched re-ingests",
              HITS["/cache.csv"] == before + 2, HITS["/cache.csv"])
        check("stored state upgraded to enriched",
              "dataset_summary" in query(ep), query(ep))

        convert("/cache.csv", "&enrich=yes")
        check("enrich=yes on cached enriched uses cache",
              HITS["/cache.csv"] == before + 2, HITS["/cache.csv"])
        check("still enriched", "dataset_summary" in query(ep), query(ep))

        convert("/cache.csv")
        check("plain request on enriched dataset uses cache",
              HITS["/cache.csv"] == before + 2, HITS["/cache.csv"])
        check("plain request does not change stored enrichment",
              "dataset_summary" in query(ep), query(ep))

        # charset is still part of the cache identity
        convert("/cache.csv", "&charset=utf-8&enrich=yes")
        check("a different charset re-ingests",
              HITS["/cache.csv"] == before + 3, HITS["/cache.csv"])

        # re-ingestion recomputes from the current bytes
        FIXTURES["/cache.csv"] = ("text/csv", b"a,b,c\n1,x,9\n2,y,8\n3,z,7\n")
        convert("/cache.csv", "&enrich=yes&force")
        data = query(ep)
        check("re-ingestion recomputes row_count",
              data["dataset_summary"]["row_count"] == 3, data["dataset_summary"])
        check("re-ingestion recomputes column_count",
              data["dataset_summary"]["column_count"] == 3, data["dataset_summary"])
        check("re-ingestion recomputes column_details",
              sorted(data["column_details"]) == ["a", "b", "c"],
              data["column_details"])

        # forced plain re-ingestion is a re-ingestion, so it re-stores plainly
        convert("/cache.csv", "&force")
        check("forced plain re-ingestion downgrades stored state",
              "dataset_summary" not in query(ep), query(ep))

        # ---------------------------------------------------------------
        print("\n[enrich applies only on /convert]")
        convert("/small.csv", "&enrich=yes&force")
        data = query(small_ep, "?enrich=yes")
        check("enrich on /datasets is ignored, not an error",
              data.get("ok") is True, data)
        check("enriched dataset still reports metadata",
              "dataset_summary" in data, data)
        plain_ep = convert("/gaps.csv", "&force").json()["endpoint"]
        data = query(plain_ep, "?enrich=yes")
        check("enrich on /datasets does not enrich a plain dataset",
              "dataset_summary" not in data and "column_details" not in data, data)
        r = requests.get(BASE + plain_ep + "/export?enrich=yes", timeout=20)
        check("enrich on /export is ignored",
              r.status_code == 200 and r.headers["Content-Type"].startswith("text/csv"),
              r.status_code)

        r = requests.post(
            BASE + "/upload?enrich=yes",
            files={"file": ("d.csv", b"a,b\n1,2\n", "text/csv")},
            timeout=20,
        )
        check("upload with enrich=yes -> 200", r.status_code == 200, r.text)
        data = query(r.json()["endpoint"])
        check("upload is never enriched",
              "dataset_summary" not in data and "column_details" not in data, data)

        # ---------------------------------------------------------------
        print("\n[error handling]")
        r = convert("/missing.csv", "&enrich=yes")
        body = r.json()
        check("enriched convert of a 404 source -> JSON error",
              r.status_code >= 400 and body.get("ok") is False
              and isinstance(body.get("error"), str), (r.status_code, r.text))

        FIXTURES["/broken.csv"] = ("text/csv", b"a,b\n1,2\n")
        ok_ep = convert("/broken.csv", "&enrich=yes").json()["endpoint"]
        check("enriched before breaking", "dataset_summary" in query(ok_ep))
        FIXTURES["/broken.csv"] = ("text/csv", b"\x00\x01\x02\x03 not tabular \x00")
        r = convert("/broken.csv", "&enrich=yes&force")
        check("failed re-ingestion -> JSON error",
              r.status_code >= 400 and r.json().get("ok") is False, r.text)
        data = query(ok_ep)
        check("failed enrichment does not downgrade stored state",
              "dataset_summary" in data and "column_details" in data, data)
        check("failed re-ingestion keeps the previous rows",
              data["rows"] == [[1, 2]], data["rows"])

        r = requests.get(BASE + "/convert?enrich=yes", timeout=20)
        check("missing source with enrich -> 400 JSON error",
              r.status_code == 400 and r.json().get("ok") is False, r.text)

        # ---------------------------------------------------------------
        print("\n[persistence]")
        keep_ep = convert("/types.csv", "&enrich=yes&force").json()["endpoint"]
        proc.terminate()
        proc.wait(timeout=20)
        proc = subprocess.Popen(
            [sys.executable, "datagate.py", "start", "--port", str(port),
             "--address", "127.0.0.1"],
            cwd="/workspace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env,
        )
        if not ready():
            print("restart failed:\n%s" % proc.stdout.read())
            return 1
        data = query(keep_ep)
        check("enrichment survives a restart",
              data.get("dataset_summary", {}).get("filetype") == "csv"
              and "column_details" in data, data)
        check("restored details intact",
              data["column_details"]["qty"]["type"] == "integer",
              data.get("column_details"))
        before = HITS.get("/types.csv", 0)
        convert("/types.csv", "&enrich=yes")
        check("restored enriched dataset serves the cache",
              HITS.get("/types.csv", 0) == before, HITS.get("/types.csv"))
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        origin.shutdown()
        shutil.rmtree(store_dir, ignore_errors=True)

    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
