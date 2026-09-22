"""Checks for the optional dataset enrichment specification."""
import io
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
import openpyxl
import xlwt

HERE = os.path.dirname(os.path.abspath(__file__))


def xlsx_bytes(rows):
    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def xls_bytes(rows):
    book = xlwt.Workbook()
    sheet = book.add_sheet("s")
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            sheet.write(r, c, val)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


STATE = {
    "/a.csv": b"name,age\nAlice,30\n",
    "/mix.csv": b"name,age,score,ratio,blank,mixnum\n"
                b"Alice,30,1.5,2,,1\n"
                b"Bob,25,2.5,3,,2.5\n"
                b"Alice,,3.5,4,,3\n",
    "/x.xlsx": xlsx_bytes([["a", "b"], [1, 2], [3, 4]]),
    "/x.xls": xls_bytes([["a", "b"], [1, 2], [3, 4]]),
    "/bad.csv": b"<!DOCTYPE html>\n<html><body>nope</body></html>\n",
}
HITS = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        HITS[path] = HITS.get(path, 0) + 1
        body = STATE.get(path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
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


def spawn(env_extra=None):
    env = dict(os.environ)
    env.pop("CACHE_ENABLED", None)
    env["STORAGE_DIR"] = os.path.join(HERE, ".enrich-store-%d" % free_port())
    if env_extra:
        env.update(env_extra)
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "datagate.py"), "start",
         "--port", str(port), "--address", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
    )
    base = "http://127.0.0.1:%d" % port
    for _ in range(100):
        if proc.poll() is not None:
            return proc, None, env
        try:
            requests.get(base + "/", timeout=1)
            return proc, base, env
        except Exception:
            time.sleep(0.1)
    return proc, None, env


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def main():
    fixture_port = free_port()
    httpd = HTTPServer(("127.0.0.1", fixture_port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    FIX = "http://127.0.0.1:%d" % fixture_port

    proc, BASE, env = spawn()
    try:
        assert BASE, "server never started"

        def conv(path, query=""):
            url = BASE + "/convert?source=" + requests.utils.quote(FIX + path, safe="")
            if query:
                url += "&" + query
            return requests.get(url, timeout=20)

        def q(endpoint, query=""):
            return requests.get(BASE + endpoint + ("?" + query if query else ""),
                                timeout=20).json()

        # ---------------- trigger ----------------
        r = conv("/mix.csv", "enrich=yes")
        check("enrich success envelope",
              r.status_code == 200 and set(r.json()) == {"ok", "endpoint"}
              and r.json()["ok"] is True, r.text)
        ep = r.json()["endpoint"]
        d = q(ep)
        check("dataset_summary present", isinstance(d.get("dataset_summary"), dict), d)
        check("column_details present", isinstance(d.get("column_details"), dict), d)
        s = d["dataset_summary"]
        check("summary filetype csv", s.get("filetype") == "csv", s)
        check("summary row_count", s.get("row_count") == 3, s)
        check("summary column_count", s.get("column_count") == 6, s)
        cd = d["column_details"]
        check("details keyed by column",
              set(cd) == {"name", "age", "score", "ratio", "blank", "mixnum"}, cd)
        for name, info in cd.items():
            check("details %s keys" % name,
                  {"type", "distinct_count", "missing_count"} <= set(info), info)
            check("details %s type label" % name,
                  info["type"] in ("text", "number", "integer", "float"), info)
        check("name text", cd["name"]["type"] == "text", cd["name"])
        check("name distinct", cd["name"]["distinct_count"] == 2, cd["name"])
        check("name missing", cd["name"]["missing_count"] == 0, cd["name"])
        check("age integer", cd["age"]["type"] == "integer", cd["age"])
        check("age missing 1", cd["age"]["missing_count"] == 1, cd["age"])
        check("age distinct 2", cd["age"]["distinct_count"] == 2, cd["age"])
        check("score float", cd["score"]["type"] == "float", cd["score"])
        check("ratio integer", cd["ratio"]["type"] == "integer", cd["ratio"])
        check("mixnum number", cd["mixnum"]["type"] == "number", cd["mixnum"])
        check("blank all missing",
              cd["blank"]["missing_count"] == 3 and cd["blank"]["distinct_count"] == 0
              and cd["blank"]["type"] == "text", cd["blank"])
        check("rows unchanged", d["rows"][0] == ["Alice", 30, 1.5, 2, "", 1], d["rows"])
        check("columns unchanged",
              d["columns"] == ["name", "age", "score", "ratio", "blank", "mixnum"], d)
        check("total unchanged", d["total"] == 3, d)
        check("query_ms unchanged", isinstance(d["query_ms"], (int, float)), d)
        check("ok unchanged", d["ok"] is True, d)

        # controls still work alongside metadata
        d2 = q(ep, "_size=1&_shape=objects")
        check("controls still work", len(d2["rows"]) == 1 and d2["total"] == 3, d2)
        check("metadata with controls",
              d2["dataset_summary"] == s and d2["column_details"] == cd, d2)
        d3 = q(ep, "_total=hide")
        check("_total=hide still hides", "total" not in d3 and "dataset_summary" in d3, d3)
        d4 = q(ep, "name__exact=Alice")
        check("filters unchanged", d4["total"] == 2, d4)
        check("summary counts whole dataset", d4["dataset_summary"]["row_count"] == 3, d4)

        # export unaffected
        exp = requests.get(BASE + ep + "/export", timeout=20)
        check("export still csv", exp.status_code == 200
              and exp.text.startswith("name,age,score"), exp.text[:80])

        # ---------------- non-triggers ----------------
        for bad in ["enrich=YES", "enrich=Yes", "enrich=yES", "enrich=1", "enrich=true",
                    "enrich=on", "enrich", "enrich=", "enrich=%20yes", "enrich=yes%20",
                    "enrich=no", "enrich=y", "enrich=yess", "enrich=yes&enrich=yes",
                    "enrich=yes&enrich=no", "enrich=no&enrich=yes", "enrich=0"]:
            r = conv("/a.csv", bad + "&force")
            ok = r.status_code == 200 and set(r.json()) == {"ok", "endpoint"}
            body = q(r.json()["endpoint"]) if ok else {}
            check("%s no enrichment" % bad,
                  ok and "dataset_summary" not in body and "column_details" not in body,
                  (r.text[:120], list(body)))
        r = conv("/a.csv", "force")
        check("plain convert no metadata",
              "dataset_summary" not in q(r.json()["endpoint"])
              and "column_details" not in q(r.json()["endpoint"]), q(r.json()["endpoint"]))

        # ---------------- spreadsheets ----------------
        for path, label in (("/x.xlsx", "xlsx"), ("/x.xls", "xls")):
            r = conv(path, "enrich=yes")
            check("%s convert ok" % label, r.status_code == 200, r.text[:120])
            b = q(r.json()["endpoint"])
            check("%s summary excel" % label,
                  b.get("dataset_summary", {}).get("filetype") == "excel", b)
            check("%s no column_details" % label, "column_details" not in b, list(b))
            check("%s rows unchanged" % label, b["rows"] == [[1, 2], [3, 4]], b)
            r2 = conv(path)
            b2 = q(r2.json()["endpoint"])
            check("%s cached enriched keeps metadata" % label,
                  "dataset_summary" in b2, list(b2))

        # ---------------- cache interaction ----------------
        HITS.clear()
        STATE["/c.csv"] = b"k,v\nx,1\n"
        r = conv("/c.csv")
        cep = r.json()["endpoint"]
        check("c not enriched", "dataset_summary" not in q(cep), q(cep))
        check("c one download", HITS.get("/c.csv") == 1, HITS)
        r = conv("/c.csv", "enrich=yes")
        check("enrich upgrades cached dataset", "dataset_summary" in q(cep), q(cep))
        check("upgrade used cached bytes", HITS.get("/c.csv") == 1, HITS)
        r = conv("/c.csv", "enrich=yes")
        check("enriched cache reused", HITS.get("/c.csv") == 1, HITS)
        check("still enriched", "dataset_summary" in q(cep), q(cep))
        r = conv("/c.csv")
        check("plain request keeps enrichment", "dataset_summary" in q(cep), q(cep))
        check("plain request no download", HITS.get("/c.csv") == 1, HITS)

        # re-ingestion recomputes from current bytes
        STATE["/c.csv"] = b"k,v,w\nx,1,2\ny,3,4\n"
        r = conv("/c.csv", "enrich=yes&force")
        check("forced enrich re-downloads", HITS.get("/c.csv") == 2, HITS)
        b = q(cep)
        check("recomputed summary",
              b["dataset_summary"]["row_count"] == 2
              and b["dataset_summary"]["column_count"] == 3, b)
        check("recomputed details", set(b["column_details"]) == {"k", "v", "w"}, b)
        # forced plain re-ingestion drops enrichment
        r = conv("/c.csv", "force")
        b = q(cep)
        check("forced plain drops enrichment",
              "dataset_summary" not in b and "column_details" not in b, list(b))

        # charset change re-ingests with the requested enrichment
        r = conv("/c.csv", "charset=utf-8&enrich=yes")
        check("charset+enrich re-ingests", "dataset_summary" in q(cep), q(cep))

        # ---------------- errors ----------------
        r = conv("/mix.csv", "enrich=yes")
        mep = r.json()["endpoint"]
        check("mix still enriched", "dataset_summary" in q(mep), q(mep))
        r = conv("/missing.csv", "enrich=yes")
        check("enrich unreachable 404",
              r.status_code == 404 and r.json()["ok"] is False
              and isinstance(r.json().get("error"), str), r.text[:160])
        r = conv("/bad.csv", "enrich=yes")
        check("enrich non-tabular 400",
              r.status_code == 400 and r.json()["ok"] is False, r.text[:160])
        r = conv("/mix.csv", "enrich=yes&charset=not-a-codec&force")
        check("enrich bad charset 400", r.status_code == 400
              and r.json()["ok"] is False, r.text[:160])
        check("failure did not downgrade storage", "dataset_summary" in q(mep), q(mep))

        # ---------------- enrich only on /convert ----------------
        b = q(cep, "enrich=yes")
        check("enrich ignored on query", isinstance(b.get("rows"), list), b)
        files = {"file": ("u.csv", b"p,q\n1,2\n", "text/csv")}
        r = requests.post(BASE + "/upload?enrich=yes", files=files, timeout=20)
        ub = q(r.json()["endpoint"])
        check("upload never enriched",
              "dataset_summary" not in ub and "column_details" not in ub, list(ub))
    finally:
        stop(proc)

    # ---------------- persistence across restart ----------------
    store = os.path.join(HERE, ".enrich-persist")
    proc, BASE, _ = spawn({"STORAGE_DIR": store})
    try:
        url = BASE + "/convert?source=" + requests.utils.quote(FIX + "/mix.csv", safe="")
        ep = requests.get(url + "&enrich=yes", timeout=20).json()["endpoint"]
        plain = requests.get(
            BASE + "/convert?source="
            + requests.utils.quote(FIX + "/a.csv", safe=""), timeout=20
        ).json()["endpoint"]
    finally:
        stop(proc)
    proc, BASE, _ = spawn({"STORAGE_DIR": store})
    try:
        b = requests.get(BASE + ep, timeout=20).json()
        check("metadata survives restart",
              "dataset_summary" in b and "column_details" in b, list(b))
        b2 = requests.get(BASE + plain, timeout=20).json()
        check("non-enriched stays bare after restart",
              "dataset_summary" not in b2 and "column_details" not in b2, list(b2))
    finally:
        stop(proc)
        import shutil
        shutil.rmtree(store, ignore_errors=True)

    # ---------------- cache disabled ----------------
    proc, BASE, _ = spawn({"CACHE_ENABLED": "0"})
    try:
        HITS.clear()
        url = BASE + "/convert?source=" + requests.utils.quote(FIX + "/mix.csv", safe="")
        ep = requests.get(url + "&enrich=yes", timeout=20).json()["endpoint"]
        b = requests.get(BASE + ep, timeout=20).json()
        check("cache off: enrich works", "dataset_summary" in b, list(b))
        requests.get(url, timeout=20)
        b = requests.get(BASE + ep, timeout=20).json()
        check("cache off: plain re-ingest drops metadata",
              "dataset_summary" not in b, list(b))
    finally:
        stop(proc)

    httpd.shutdown()
    print("\n%d checks, %d failures" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        print("failed: " + ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
