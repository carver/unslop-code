"""Checks for datagate /convert caching, CACHE_ENABLED and the force flag."""

import os
import socket
import subprocess
import sys
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


def spawn(port, cache_value=None):
    env = dict(os.environ)
    env.pop("CACHE_ENABLED", None)
    if cache_value is not None:
        env["CACHE_ENABLED"] = cache_value
    return subprocess.Popen(
        [sys.executable, "datagate.py", "start", "--port", str(port),
         "--address", "127.0.0.1"],
        cwd="/workspace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env,
    )


def wait_ready(proc, port, timeout=20):
    base = "http://127.0.0.1:%d" % port
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            requests.get(base + "/", timeout=1)
            return True
        except requests.RequestException:
            time.sleep(0.1)
    return False


class Server:
    """A datagate subprocess with a given CACHE_ENABLED setting."""

    def __init__(self, cache_value=None):
        self.port = free_port()
        self.proc = spawn(self.port, cache_value)
        self.base = "http://127.0.0.1:%d" % self.port
        self.ready = wait_ready(self.proc, self.port)

    def convert(self, src, charset=None, force=None):
        url = self.base + "/convert?source=" + quote(src, safe="")
        if charset is not None:
            url += "&charset=" + quote(charset, safe="")
        if force is not None:
            url += "&force" + ("" if force == "" else "=" + quote(force, safe=""))
        return requests.get(url, timeout=20)

    def dataset(self, endpoint):
        return requests.get(self.base + endpoint, timeout=20)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def envelope(r):
    try:
        j = r.json()
    except ValueError:
        return False
    return j.get("ok") is False and isinstance(j.get("error"), str)


def main():
    origin_port = free_port()
    origin = ThreadingHTTPServer(("127.0.0.1", origin_port), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    origin_base = "http://127.0.0.1:%d" % origin_port

    V1 = b"name,age\nAlice,30\nBob,25\n"
    V2 = b"name,age\nCarol,41\n"
    FIXTURES["/a.csv"] = (200, "text/csv", V1)
    FIXTURES["/b.csv"] = (200, "text/csv", b"x,y\n1,2\n")
    FIXTURES["/flip.csv"] = (200, "text/csv", V1)
    FIXTURES["/off.csv"] = (200, "text/csv", V1)
    FIXTURES["/err.csv"] = (200, "text/csv", V1)
    FIXTURES["/gone.csv"] = (200, "text/csv", V1)
    FIXTURES["/prose.csv"] = (200, "text/csv", V1)
    FIXTURES["/cs.csv"] = (200, "text/csv", V1)
    FIXTURES["/lock.csv"] = (200, "text/csv", V1)

    servers = []
    try:
        # ---------------------------------------------------------------
        print("\n[startup: CACHE_ENABLED accepted values]")
        for value in ["1", "true", "yes", "on", "TRUE", "Yes", "On", "TrUe",
                      "0", "false", "no", "off", "FALSE", "No", "OFF"]:
            s = Server(value)
            servers.append(s)
            check("CACHE_ENABLED=%r starts" % value, s.ready,
                  s.proc.stdout.read() if s.proc.poll() is not None else "")
            s.stop()
            servers.remove(s)

        print("\n[startup: CACHE_ENABLED invalid values fail startup]")
        for value in ["", " ", "maybe", "2", "-1", "y", "n", "t", "f", "enable",
                      "enabled", "disabled", "true ", " true", "yes!", "null",
                      "none", "True1", "on/off"]:
            port = free_port()
            proc = spawn(port, value)
            try:
                rc = proc.wait(timeout=20)
                exited = rc != 0
            except subprocess.TimeoutExpired:
                proc.kill()
                exited = False
            check("CACHE_ENABLED=%r fails startup" % value, exited)

        # ---------------------------------------------------------------
        print("\n[cache on by default]")
        srv = Server()
        servers.append(srv)
        check("server started", srv.ready)

        HITS.clear()
        r1 = srv.convert(origin_base + "/a.csv")
        check("first convert 200", r1.status_code == 200, r1.text)
        check("one download", HITS.get("/a.csv") == 1, HITS)
        r2 = srv.convert(origin_base + "/a.csv")
        check("second convert 200", r2.status_code == 200, r2.text)
        check("no re-download", HITS.get("/a.csv") == 1, HITS)
        check("same dataset id", r2.json() == r1.json(), (r1.text, r2.text))
        check("cache response identical body", r2.text == r1.text,
              (r1.text, r2.text))
        check("cache response identical content-type",
              r2.headers.get("Content-Type") == r1.headers.get("Content-Type"))
        check("only ok+endpoint keys", set(r2.json()) == {"ok", "endpoint"},
              r2.json())
        for _ in range(3):
            srv.convert(origin_base + "/a.csv")
        check("still one download after repeats", HITS.get("/a.csv") == 1, HITS)

        r3 = srv.convert(origin_base + "/b.csv")
        check("different source downloads", HITS.get("/b.csv") == 1, HITS)
        check("different source different id",
              r3.json()["endpoint"] != r1.json()["endpoint"])

        print("\n[cache serves the stored parse]")
        endpoint = r1.json()["endpoint"]
        FIXTURES["/a.csv"] = (200, "text/csv", V2)
        rc = srv.convert(origin_base + "/a.csv")
        check("cached convert still 200", rc.status_code == 200, rc.text)
        check("origin untouched after change", HITS.get("/a.csv") == 1, HITS)
        dj = srv.dataset(endpoint).json()
        check("cached rows unchanged",
              dj["rows"] == [["Alice", 30], ["Bob", 25]], dj["rows"])

        # ---------------------------------------------------------------
        print("\n[force: presence flag re-ingests]")
        rf = srv.convert(origin_base + "/a.csv", force="")
        check("force 200", rf.status_code == 200, rf.text)
        check("force re-downloaded", HITS.get("/a.csv") == 2, HITS)
        check("force keeps same id", rf.json()["endpoint"] == endpoint, rf.text)
        check("force response identical to fresh", rf.text == r1.text,
              (r1.text, rf.text))
        dj = srv.dataset(endpoint).json()
        check("force replaced dataset", dj["rows"] == [["Carol", 41]],
              dj["rows"])
        rn = srv.convert(origin_base + "/a.csv")
        check("re-ingested result is now cached", HITS.get("/a.csv") == 2, HITS)
        check("cached id unchanged", rn.json()["endpoint"] == endpoint)

        print("\n[force: any value is 400]")
        before = HITS.get("/a.csv")
        for value in ["1", "0", "true", "false", "yes", "no", "on", "off",
                      "force", "TRUE", "-1", "null", "x"]:
            r = srv.convert(origin_base + "/a.csv", force=value)
            check("force=%r -> 400" % value, r.status_code == 400, r.text)
            check("force=%r error envelope" % value, envelope(r), r.text)
        check("rejected force never downloads", HITS.get("/a.csv") == before,
              HITS)
        dj = srv.dataset(endpoint).json()
        check("dataset intact after rejected force",
              dj["rows"] == [["Carol", 41]], dj["rows"])

        r = requests.get(
            srv.base + "/convert?source=" + quote(origin_base + "/a.csv", safe="")
            + "&force&force", timeout=20)
        check("repeated force -> 400", r.status_code == 400, r.text)
        check("repeated force envelope", envelope(r), r.text)
        r = requests.get(
            srv.base + "/convert?source=" + quote(origin_base + "/a.csv", safe="")
            + "&force=", timeout=20)
        check("empty force= accepted", r.status_code == 200, r.text)

        print("\n[force on an uncached source]")
        HITS.pop("/flip.csv", None)
        r = srv.convert(origin_base + "/flip.csv", force="")
        check("force on cold cache 200", r.status_code == 200, r.text)
        check("force on cold cache downloads", HITS.get("/flip.csv") == 1, HITS)

        print("\n[validation still applies to cached sources]")
        r = srv.convert(origin_base + "/cs.csv")
        check("charset source cached", r.status_code == 200, r.text)
        r = srv.convert(origin_base + "/cs.csv", charset="no-such-charset")
        check("bad charset on cached source -> 400", r.status_code == 400,
              r.text)
        check("bad charset envelope", envelope(r), r.text)
        r = requests.get(srv.base + "/convert?force", timeout=20)
        check("missing source with force -> 400", r.status_code == 400, r.text)

        # ---------------------------------------------------------------
        print("\n[errors: re-ingestion failure keeps codes and envelope]")
        r = srv.convert(origin_base + "/err.csv")
        err_endpoint = r.json()["endpoint"]
        check("seed dataset ok", r.status_code == 200, r.text)
        FIXTURES["/err.csv"] = (500, "text/plain", b"boom")
        r = srv.convert(origin_base + "/err.csv", force="")
        check("forced failure -> 404", r.status_code == 404, r.text)
        check("forced failure envelope", envelope(r), r.text)
        d = srv.dataset(err_endpoint)
        check("prior dataset still queryable", d.status_code == 200, d.text)
        check("prior rows intact",
              d.json()["rows"] == [["Alice", 30], ["Bob", 25]],
              d.json()["rows"])

        r = srv.convert(origin_base + "/gone.csv")
        gone_endpoint = r.json()["endpoint"]
        del FIXTURES["/gone.csv"]
        r = srv.convert(origin_base + "/gone.csv", force="")
        check("forced missing source -> 404", r.status_code == 404, r.text)
        d = srv.dataset(gone_endpoint)
        check("dataset survives missing source", d.status_code == 200, d.text)
        check("rows survive missing source",
              d.json()["rows"] == [["Alice", 30], ["Bob", 25]])

        r = srv.convert(origin_base + "/prose.csv")
        prose_endpoint = r.json()["endpoint"]
        FIXTURES["/prose.csv"] = (
            200, "text/html",
            b"<!DOCTYPE html><html><body><p>hello there</p></body></html>")
        r = srv.convert(origin_base + "/prose.csv", force="")
        check("forced non-tabular -> 400", r.status_code == 400, r.text)
        check("forced non-tabular envelope", envelope(r), r.text)
        d = srv.dataset(prose_endpoint)
        check("dataset survives bad content", d.status_code == 200, d.text)
        check("rows survive bad content",
              d.json()["rows"] == [["Alice", 30], ["Bob", 25]])
        # The failed force never invalidated the entry, so a plain request
        # keeps serving the good parse instead of re-fetching a broken source.
        before = HITS.get("/prose.csv")
        r = srv.convert(origin_base + "/prose.csv")
        check("unforced convert still served from cache",
              r.status_code == 200 and r.json()["endpoint"] == prose_endpoint,
              r.text)
        check("unforced convert after failure does not re-download",
              HITS.get("/prose.csv") == before, HITS)

        print("\n[concurrent requests for one source download once]")
        HITS.pop("/lock.csv", None)
        results = []

        def hit():
            try:
                results.append(srv.convert(origin_base + "/lock.csv").status_code)
            except requests.RequestException as exc:
                results.append(repr(exc))

        threads = [threading.Thread(target=hit) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check("all concurrent converts 200", results == [200] * 6, results)
        check("single download under concurrency",
              HITS.get("/lock.csv") == 1, HITS)

        srv.stop()
        servers.remove(srv)

        # ---------------------------------------------------------------
        print("\n[CACHE_ENABLED=false: always re-ingest]")
        off = Server("false")
        servers.append(off)
        check("server started", off.ready)

        HITS.pop("/off.csv", None)
        FIXTURES["/off.csv"] = (200, "text/csv", V1)
        r1 = off.convert(origin_base + "/off.csv")
        check("first convert 200", r1.status_code == 200, r1.text)
        off_endpoint = r1.json()["endpoint"]
        r2 = off.convert(origin_base + "/off.csv")
        check("second convert 200", r2.status_code == 200, r2.text)
        check("re-downloaded every time", HITS.get("/off.csv") == 2, HITS)
        check("same id", r2.json()["endpoint"] == off_endpoint)
        check("identical response", r2.text == r1.text)

        FIXTURES["/off.csv"] = (200, "text/csv", V2)
        r3 = off.convert(origin_base + "/off.csv")
        check("third convert 200", r3.status_code == 200, r3.text)
        check("three downloads", HITS.get("/off.csv") == 3, HITS)
        dj = off.dataset(off_endpoint).json()
        check("stored data replaced", dj["rows"] == [["Carol", 41]], dj["rows"])

        print("\n[CACHE_ENABLED=false: force has no additional effect]")
        rf = off.convert(origin_base + "/off.csv", force="")
        check("force 200", rf.status_code == 200, rf.text)
        check("force downloads once more", HITS.get("/off.csv") == 4, HITS)
        check("force same id", rf.json()["endpoint"] == off_endpoint)
        check("force identical response", rf.text == r3.text)
        r = off.convert(origin_base + "/off.csv", force="1")
        check("force=1 still 400 when disabled", r.status_code == 400, r.text)
        check("force=1 envelope", envelope(r), r.text)
        check("rejected force did not download", HITS.get("/off.csv") == 4,
              HITS)

        FIXTURES["/off.csv"] = (500, "text/plain", b"boom")
        r = off.convert(origin_base + "/off.csv", force="")
        check("failure when disabled -> 404", r.status_code == 404, r.text)
        d = off.dataset(off_endpoint)
        check("prior dataset queryable when disabled", d.status_code == 200)
        check("prior rows intact when disabled",
              d.json()["rows"] == [["Carol", 41]], d.json()["rows"])

        off.stop()
        servers.remove(off)

        # ---------------------------------------------------------------
        print("\n[CACHE_ENABLED truthy spellings all cache]")
        for value in ["1", "true", "YES", "on"]:
            s = Server(value)
            servers.append(s)
            path = "/t_%s.csv" % value.lower()
            FIXTURES[path] = (200, "text/csv", V1)
            HITS.pop(path, None)
            s.convert(origin_base + path)
            s.convert(origin_base + path)
            check("CACHE_ENABLED=%r caches" % value, HITS.get(path) == 1, HITS)
            s.stop()
            servers.remove(s)

        print("\n[CACHE_ENABLED falsy spellings all bypass]")
        for value in ["0", "false", "NO", "off"]:
            s = Server(value)
            servers.append(s)
            path = "/f_%s.csv" % value.lower()
            FIXTURES[path] = (200, "text/csv", V1)
            HITS.pop(path, None)
            s.convert(origin_base + path)
            s.convert(origin_base + path)
            check("CACHE_ENABLED=%r bypasses" % value, HITS.get(path) == 2,
                  HITS)
            s.stop()
            servers.remove(s)

    finally:
        for s in servers:
            s.stop()
        origin.shutdown()

    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
