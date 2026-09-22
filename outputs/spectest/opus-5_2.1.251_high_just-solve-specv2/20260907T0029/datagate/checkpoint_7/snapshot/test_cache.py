"""Checks for the caching / cache-control specification."""
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

HERE = os.path.dirname(os.path.abspath(__file__))

# Mutable fixture state so a re-download is observable in the parsed data.
STATE = {
    "/a.csv": b"name,age\nAlice,30\n",
    "/b.csv": b"x,y\n1,2\n",
    "/broken.csv": b"p,q\n7,8\n",
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
            self.send_header("Content-Type", "text/plain")
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


def spawn(cache_value=None):
    """Start the app; returns (proc, base_url) or (proc, None) if it exited."""
    env = dict(os.environ)
    env.pop("CACHE_ENABLED", None)
    if cache_value is not None:
        env["CACHE_ENABLED"] = cache_value
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "datagate.py"), "start",
         "--port", str(port), "--address", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
    )
    base = "http://127.0.0.1:%d" % port
    for _ in range(100):
        if proc.poll() is not None:
            return proc, None
        try:
            requests.get(base + "/", timeout=1)
            return proc, base
        except Exception:
            time.sleep(0.1)
    return proc, None


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

    def envelope(r, status):
        try:
            body = r.json()
        except Exception:
            return False
        return (r.status_code == status and body.get("ok") is False
                and isinstance(body.get("error"), str) and body["error"])

    # ================= caching enabled (default) =================
    proc, BASE = spawn()
    try:
        assert BASE, "server never started"

        def conv(source, query="", base=None):
            url = (base or BASE) + "/convert?source=" + requests.utils.quote(source, safe="")
            if query:
                url += "&" + query
            return requests.get(url, timeout=20)

        def rows(endpoint, base=None):
            return requests.get((base or BASE) + endpoint, timeout=20).json()["rows"]

        # ---- basic cache behaviour
        HITS.clear()
        r1 = conv(FIX + "/a.csv")
        r2 = conv(FIX + "/a.csv")
        check("convert ok", r1.status_code == 200 and r1.json()["ok"] is True, r1.text)
        check("cache: one download for two requests", HITS.get("/a.csv") == 1, HITS)
        check("cache: same endpoint", r1.json()["endpoint"] == r2.json()["endpoint"], (r1.text, r2.text))
        check("cache: identical body", r1.json() == r2.json(), (r1.text, r2.text))
        check("cache: identical status", r1.status_code == r2.status_code)
        check("cache: no extra fields", set(r2.json()) == set(r1.json()), r2.text)

        ep = r1.json()["endpoint"]
        check("cache: dataset queryable", rows(ep) == [["Alice", 30]], rows(ep))

        # ---- cached data is served even after the source changes
        STATE["/a.csv"] = b"name,age\nZed,99\n"
        r3 = conv(FIX + "/a.csv")
        check("cache: still no re-download", HITS.get("/a.csv") == 1, HITS)
        check("cache: stale data kept", rows(ep) == [["Alice", 30]], rows(ep))
        check("cache: response unchanged", r3.json() == r1.json(), r3.text)

        # ---- force bypass
        r4 = conv(FIX + "/a.csv", "force")
        check("force: re-downloads", HITS.get("/a.csv") == 2, HITS)
        check("force: same envelope", r4.status_code == 200 and r4.json() == r1.json(), r4.text)
        check("force: replaces dataset", rows(ep) == [["Zed", 99]], rows(ep))
        conv(FIX + "/a.csv")
        check("force: refreshes the cache", HITS.get("/a.csv") == 2, HITS)

        # ---- force with a value is a 400
        for bad in ["1", "0", "true", "false", "yes", "no", "on", "off",
                    "force", "%20", "null", "True", "-1", "abc"]:
            r = conv(FIX + "/a.csv", "force=" + bad)
            check("force=%s rejected" % bad, envelope(r, 400), r.text[:160])
        check("force value did not re-download", HITS.get("/a.csv") == 2, HITS)

        # ---- an empty value is the presence flag as parsed from the query
        r = conv(FIX + "/a.csv", "force=")
        check("force= accepted as presence", r.status_code == 200 and r.json() == r1.json(), r.text[:160])
        check("force= forced a download", HITS.get("/a.csv") == 3, HITS)

        # ---- repeated force
        r = conv(FIX + "/a.csv", "force&force")
        check("repeated force rejected", envelope(r, 400), r.text[:160])
        r = conv(FIX + "/a.csv", "force&force=1")
        check("repeated mixed force rejected", envelope(r, 400), r.text[:160])

        # ---- force is validated before the source is fetched
        r = conv(FIX + "/missing.csv", "force=1")
        check("force checked before fetch", envelope(r, 400), r.text[:160])
        r = requests.get(BASE + "/convert?force=1", timeout=20)
        check("force value without source", envelope(r, 400), r.text[:160])
        r = requests.get(BASE + "/convert?force", timeout=20)
        check("force without source still 400", envelope(r, 400), r.text[:160])

        # ---- error handling: existing codes survive re-ingestion
        fresh = conv(FIX + "/missing.csv")
        check("missing source 404", envelope(fresh, 404), fresh.text[:160])
        again = conv(FIX + "/missing.csv", "force")
        check("forced missing source keeps code", envelope(again, 404), again.text[:160])
        check("forced failure keeps envelope", again.json().keys() == fresh.json().keys(), again.text[:160])

        # ---- forced failure keeps the prior dataset queryable
        b_ep = conv(FIX + "/b.csv").json()["endpoint"]
        check("b parsed", rows(b_ep) == [[1, 2]], rows(b_ep))
        STATE["/b.csv"] = b"<!DOCTYPE html>\n<html><body><p>nope</p></body></html>\n"
        r = conv(FIX + "/b.csv", "force")
        check("forced unsupported format 400", envelope(r, 400), r.text[:160])
        check("prior dataset still queryable", rows(b_ep) == [[1, 2]], rows(b_ep))
        STATE["/b.csv"] = None
        del STATE["/b.csv"]
        r = conv(FIX + "/b.csv", "force")
        check("forced unreachable 404", envelope(r, 404), r.text[:160])
        check("prior dataset queryable after 404", rows(b_ep) == [[1, 2]], rows(b_ep))
        STATE["/b.csv"] = b"x,y\n5,6\n"
        r = conv(FIX + "/b.csv", "force")
        check("recovers after failures", r.status_code == 200 and r.json()["endpoint"] == b_ep, r.text)
        check("recovered data replaced", rows(b_ep) == [[5, 6]], rows(b_ep))

        # ---- distinct sources are cached independently
        HITS.clear()
        conv(FIX + "/a.csv")
        conv(FIX + "/broken.csv")
        conv(FIX + "/broken.csv")
        check("independent keys", HITS.get("/broken.csv") == 1 and "/a.csv" not in HITS, HITS)

        # ---- charset still honoured on a cached source
        r = conv(FIX + "/a.csv", "charset=not-a-codec")
        check("bad charset on cached source 400", envelope(r, 400), r.text[:160])
        check("bad charset kept dataset", rows(ep) == [["Zed", 99]], rows(ep))
    finally:
        stop(proc)

    # ================= caching disabled =================
    proc, BASE = spawn("0")
    try:
        assert BASE, "server never started with CACHE_ENABLED=0"

        def conv2(source, query=""):
            url = BASE + "/convert?source=" + requests.utils.quote(source, safe="")
            if query:
                url += "&" + query
            return requests.get(url, timeout=20)

        STATE["/a.csv"] = b"name,age\nAlice,30\n"
        HITS.clear()
        r1 = conv2(FIX + "/a.csv")
        r2 = conv2(FIX + "/a.csv")
        ep = r1.json()["endpoint"]
        check("disabled: re-downloads every time", HITS.get("/a.csv") == 2, HITS)
        check("disabled: same endpoint", r1.json() == r2.json(), (r1.text, r2.text))
        STATE["/a.csv"] = b"name,age\nZed,99\n"
        conv2(FIX + "/a.csv")
        check("disabled: replaces stored data",
              requests.get(BASE + ep, timeout=20).json()["rows"] == [["Zed", 99]])
        check("disabled: third download", HITS.get("/a.csv") == 3, HITS)

        r = conv2(FIX + "/a.csv", "force")
        check("disabled: force still ok", r.status_code == 200 and r.json() == r1.json(), r.text)
        check("disabled: force no extra effect", HITS.get("/a.csv") == 4, HITS)
        r = conv2(FIX + "/a.csv", "force=1")
        check("disabled: force value still 400", envelope(r, 400), r.text[:160])
        check("disabled: rejected request did not fetch", HITS.get("/a.csv") == 4, HITS)
        r = conv2(FIX + "/missing.csv", "force")
        check("disabled: failure code kept", envelope(r, 404), r.text[:160])
    finally:
        stop(proc)

    # ================= CACHE_ENABLED value parsing =================
    STATE["/a.csv"] = b"name,age\nAlice,30\n"

    def cache_is_on(value):
        proc, base = spawn(value)
        try:
            if base is None:
                return None
            HITS.clear()
            url = base + "/convert?source=" + requests.utils.quote(FIX + "/a.csv", safe="")
            requests.get(url, timeout=20)
            requests.get(url, timeout=20)
            return HITS.get("/a.csv") == 1
        finally:
            stop(proc)

    for value in ["1", "true", "yes", "on", "TRUE", "Yes", "ON", "TrUe"]:
        check("CACHE_ENABLED=%s enables" % value, cache_is_on(value) is True)
    for value in ["0", "false", "no", "off", "FALSE", "No", "OFF", "OfF"]:
        check("CACHE_ENABLED=%s disables" % value, cache_is_on(value) is False)
    check("CACHE_ENABLED unset defaults on", cache_is_on(None) is True)

    for value in ["", " ", "2", "-1", "maybe", "y", "n", "t", "f", "truee",
                  " true", "true ", "enable", "enabled", "null", "None",
                  "yes!", "1.0", "01"]:
        proc, base = spawn(value)
        stopped = proc.poll() is not None or (stop(proc) or proc.returncode is not None)
        check("CACHE_ENABLED=%r fails startup" % value,
              base is None and proc.returncode not in (0, None),
              (base, proc.returncode))

    httpd.shutdown()
    print("\n%d checks, %d failures" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        print("failed: " + ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
