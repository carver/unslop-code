"""Checks for the configuration, size limit and access control specification."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

HERE = os.path.dirname(os.path.abspath(__file__))

BODIES = {
    "/small.csv": b"a,b\n1,2\n",                       # 8 bytes
    "/exact.csv": b"name,age\nAlice,30\n",             # 18 bytes
    "/big.csv": b"name,age\nAlice,30\nBob,41\nCid,52\n",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        body = BODIES.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
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


SETTINGS = ("MAX_SOURCE_SIZE", "ORIGIN_ALLOWLIST", "REQUIRE_TLS",
            "STORAGE_DIR", "CACHE_ENABLED", "DATAGATE_CONFIG")


def spawn(env_extra=None, config_text=None, config_path=None, tmp=None):
    """Start the app with the given environment / config file."""
    env = dict(os.environ)
    for name in SETTINGS:
        env.pop(name, None)
    if config_text is not None:
        path = config_path or os.path.join(tmp, "datagate-%d.conf" % free_port())
        with open(path, "w") as handle:
            handle.write(config_text)
        env["DATAGATE_CONFIG"] = path
    elif config_path is not None:
        env["DATAGATE_CONFIG"] = config_path
    env.update(env_extra or {})
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


def envelope(r, status):
    try:
        body = r.json()
    except Exception:
        return False
    return (r.status_code == status and body.get("ok") is False
            and isinstance(body.get("error"), str) and bool(body["error"]))


def fails_startup(**kw):
    proc, base = spawn(**kw)
    if base is not None:
        stop(proc)
        return False
    stop(proc)
    return proc.returncode not in (0, None)


def main():
    fixture_port = free_port()
    httpd = HTTPServer(("127.0.0.1", fixture_port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    FIX = "http://127.0.0.1:%d" % fixture_port
    tmp = tempfile.mkdtemp(prefix="datagate-test-")

    def conv(base, path, headers=None):
        url = base + "/convert?source=" + requests.utils.quote(FIX + path, safe="")
        return requests.get(url, timeout=20, headers=headers)

    def upload(base, data, headers=None):
        return requests.post(base + "/upload", files={"file": ("x.csv", data)},
                             timeout=20, headers=headers)

    # ================= defaults =================
    proc, BASE = spawn()
    try:
        check("default: server starts", BASE is not None)
        r = conv(BASE, "/big.csv")
        check("default: no size limit", r.status_code == 200, r.text[:200])
        check("default: relative endpoint", r.json()["endpoint"].startswith("/datasets/"), r.text)
        check("default: no allowlist", requests.get(BASE + "/", timeout=10).status_code == 200)
        u = upload(BASE, b"x,y\n1,2\n")
        check("default: upload ok", u.status_code == 200 and u.json()["ok"] is True, u.text[:200])
    finally:
        stop(proc)

    # ================= MAX_SOURCE_SIZE =================
    exact = len(BODIES["/exact.csv"])
    proc, BASE = spawn({"MAX_SOURCE_SIZE": str(exact)})
    try:
        r = conv(BASE, "/exact.csv")
        check("size: exactly the limit accepted", r.status_code == 200 and r.json()["ok"] is True, r.text[:200])
        r = conv(BASE, "/small.csv")
        check("size: under the limit accepted", r.status_code == 200, r.text[:200])
        r = conv(BASE, "/big.csv")
        check("size: over the limit 400", envelope(r, 400), r.text[:200])
        r2 = conv(BASE, "/big.csv")
        check("size: repeat over the limit 400", envelope(r2, 400), r2.text[:200])
        payload = b"a," + b"b" * (exact - 3) + b"\n"
        check("upload fixture is at the limit", len(payload) == exact)
        u = upload(BASE, b"a,b\n1,2\n")
        check("size: small upload ok", u.status_code == 200, u.text[:200])
        u = upload(BASE, b"n,v\n" + b"x" * exact)
        check("size: oversize upload 400", envelope(u, 400), u.text[:200])
        u = upload(BASE, b"ab,cd\n1,2\n"[:exact].ljust(exact, b"z"))
        check("size: upload of exactly the limit not rejected for size",
              u.status_code != 400 or "too large" not in u.json().get("error", "").lower(),
              u.text[:200])
    finally:
        stop(proc)

    proc, BASE = spawn({"MAX_SOURCE_SIZE": "0"})
    try:
        r = conv(BASE, "/small.csv")
        check("size: zero limit rejects content", envelope(r, 400), r.text[:200])
    finally:
        stop(proc)

    for bad in ["", " ", "abc", "-1", "1.5", "10MB", "1_000", "0x10", "1e3"]:
        if bad.strip() == "":
            continue
        check("MAX_SOURCE_SIZE=%r fails startup" % bad,
              fails_startup(env_extra={"MAX_SOURCE_SIZE": bad}))

    # ================= ORIGIN_ALLOWLIST =================
    proc, BASE = spawn({"ORIGIN_ALLOWLIST": "example.com,test.org"})
    try:
        r = requests.get(BASE + "/", timeout=10)
        check("allowlist: missing Referer 403", envelope(r, 403), r.text[:200])
        for ref, ok in [
            ("https://example.com/page", True),
            ("http://example.com/", True),
            ("https://app.example.com/x", True),
            ("https://a.b.example.com/x", True),
            ("https://EXAMPLE.COM/x", True),
            ("https://App.Example.Com/x", True),
            ("https://example.com:8443/x", True),
            ("https://test.org/x", True),
            ("https://notexample.com/x", False),
            ("https://example.com.evil.net/x", False),
            ("https://evil.net/example.com", False),
            ("https://xexample.com/x", False),
            ("https://example.org/x", False),
            ("https://test.org.uk/x", False),
            ("", False),
            ("not a url", False),
        ]:
            r = requests.get(BASE + "/", timeout=10, headers={"Referer": ref})
            if ok:
                check("allowlist accepts %r" % ref, r.status_code == 200, r.text[:200])
            else:
                check("allowlist rejects %r" % ref, envelope(r, 403), r.text[:200])

        r = conv(BASE, "/small.csv", headers={"Referer": "https://evil.net/"})
        check("allowlist: /convert blocked", envelope(r, 403), r.text[:200])
        r = conv(BASE, "/small.csv", headers={"Referer": "https://example.com/"})
        check("allowlist: /convert allowed", r.status_code == 200, r.text[:200])
        ep = r.json()["endpoint"]
        r = requests.get(BASE + ep, timeout=10)
        check("allowlist: dataset blocked without referer", envelope(r, 403), r.text[:200])
        r = requests.get(BASE + ep, timeout=10, headers={"Referer": "https://example.com/"})
        check("allowlist: dataset allowed", r.status_code == 200, r.text[:200])
        r = requests.get(BASE + "/nope", timeout=10, headers={"Referer": "https://evil.net/"})
        check("allowlist: checked before routing", envelope(r, 403), r.text[:200])
        u = upload(BASE, b"a,b\n1,2\n", headers={"Referer": "https://evil.net/"})
        check("allowlist: /upload blocked", envelope(u, 403), u.text[:200])
        u = upload(BASE, b"a,b\n1,2\n", headers={"Referer": "https://sub.test.org/"})
        check("allowlist: /upload allowed", u.status_code == 200, u.text[:200])
    finally:
        stop(proc)

    # spacing and leading dots in the list
    proc, BASE = spawn({"ORIGIN_ALLOWLIST": " .example.com , test.org "})
    try:
        r = requests.get(BASE + "/", timeout=10, headers={"Referer": "https://x.example.com/"})
        check("allowlist: entries trimmed", r.status_code == 200, r.text[:200])
        r = requests.get(BASE + "/", timeout=10, headers={"Referer": "https://other.net/"})
        check("allowlist: still rejects others", envelope(r, 403), r.text[:200])
    finally:
        stop(proc)

    # ================= REQUIRE_TLS =================
    for value, absolute in [("0", False), ("false", False), ("no", False), ("off", False),
                            ("1", True), ("true", True), ("YES", True), ("On", True),
                            (" true ", True)]:
        proc, BASE = spawn({"REQUIRE_TLS": value})
        try:
            check("REQUIRE_TLS=%r starts" % value, BASE is not None)
            if BASE is None:
                continue
            host = BASE.split("//", 1)[1]
            r = conv(BASE, "/small.csv")
            ep = r.json()["endpoint"]
            u = upload(BASE, b"p,q\n3,4\n").json()["endpoint"]
            if absolute:
                check("REQUIRE_TLS=%r absolute convert" % value,
                      ep.startswith("https://" + host + "/datasets/"), ep)
                check("REQUIRE_TLS=%r absolute upload" % value,
                      u.startswith("https://" + host + "/datasets/"), u)
                path = "/datasets/" + ep.rsplit("/", 1)[1]
                q = requests.get(BASE + path, timeout=10)
                check("REQUIRE_TLS=%r dataset queryable" % value, q.status_code == 200, q.text[:200])
            else:
                check("REQUIRE_TLS=%r relative convert" % value, ep.startswith("/datasets/"), ep)
                check("REQUIRE_TLS=%r relative upload" % value, u.startswith("/datasets/"), u)
        finally:
            stop(proc)

    for bad in ["", " ", "2", "maybe", "y", "truee", "enable", "None"]:
        check("REQUIRE_TLS=%r fails startup" % bad,
              fails_startup(env_extra={"REQUIRE_TLS": bad}))

    # ================= STORAGE_DIR =================
    store = os.path.join(tmp, "store", "nested")
    proc, BASE = spawn({"STORAGE_DIR": store})
    try:
        check("storage: directory created", os.path.isdir(store), store)
        ep = conv(BASE, "/big.csv").json()["endpoint"]
        rows = requests.get(BASE + ep, timeout=10).json()["rows"]
        up_ep = upload(BASE, b"p,q\n7,8\n").json()["endpoint"]
    finally:
        stop(proc)

    proc, BASE = spawn({"STORAGE_DIR": store})
    try:
        r = requests.get(BASE + ep, timeout=10)
        check("storage: converted dataset survives restart",
              r.status_code == 200 and r.json()["rows"] == rows, r.text[:200])
        r = requests.get(BASE + up_ep, timeout=10)
        check("storage: uploaded dataset survives restart",
              r.status_code == 200 and r.json()["rows"] == [[7, 8]], r.text[:200])
    finally:
        stop(proc)

    other = os.path.join(tmp, "other-store")
    proc, BASE = spawn({"STORAGE_DIR": other})
    try:
        r = requests.get(BASE + ep, timeout=10)
        check("storage: separate directory is empty", envelope(r, 404), r.text[:200])
    finally:
        stop(proc)

    # ================= config file =================
    conf = os.path.join(tmp, "a.conf")
    text = (
        "# datagate configuration\n"
        "\n"
        "MAX_SOURCE_SIZE = %d\n"
        "ORIGIN_ALLOWLIST = example.com, test.org\n"
        "REQUIRE_TLS = true\n"
        "STORAGE_DIR = %s\n"
        "CACHE_ENABLED = off\n"
        "\n"
        "# trailing comment\n"
    ) % (exact, os.path.join(tmp, "file-store"))
    proc, BASE = spawn(config_text=text, config_path=conf)
    try:
        check("file: server starts", BASE is not None)
        hdr = {"Referer": "https://example.com/"}
        r = conv(BASE, "/big.csv", headers=hdr)
        check("file: MAX_SOURCE_SIZE applied", envelope(r, 400), r.text[:200])
        r = conv(BASE, "/exact.csv", headers=hdr)
        check("file: at limit accepted", r.status_code == 200, r.text[:200])
        check("file: REQUIRE_TLS applied", r.json()["endpoint"].startswith("https://"), r.text)
        r = requests.get(BASE + "/", timeout=10)
        check("file: allowlist applied", envelope(r, 403), r.text[:200])
        check("file: STORAGE_DIR applied", os.path.isdir(os.path.join(tmp, "file-store")))
    finally:
        stop(proc)

    # env overrides the file
    proc, BASE = spawn({"REQUIRE_TLS": "false", "ORIGIN_ALLOWLIST": "override.test",
                        "MAX_SOURCE_SIZE": "1000000"},
                       config_text=text, config_path=os.path.join(tmp, "b.conf"))
    try:
        r = conv(BASE, "/big.csv", headers={"Referer": "https://override.test/"})
        check("env overrides file size", r.status_code == 200, r.text[:200])
        check("env overrides file tls", r.json()["endpoint"].startswith("/datasets/"), r.text)
        r = requests.get(BASE + "/", timeout=10, headers={"Referer": "https://example.com/"})
        check("env overrides file allowlist", envelope(r, 403), r.text[:200])
    finally:
        stop(proc)

    # invalid config files and read failures
    check("missing config file fails startup",
          fails_startup(config_path=os.path.join(tmp, "does-not-exist.conf")))
    check("config dir instead of file fails startup", fails_startup(config_path=tmp))
    for bad_text in ["REQUIRE_TLS=maybe\n", "MAX_SOURCE_SIZE=lots\n", "CACHE_ENABLED=2\n",
                     "this is not a setting\n", "=value\n", "MAX_SOURCE_SIZE=-5\n"]:
        check("invalid config %r fails startup" % bad_text.strip(),
              fails_startup(config_text=bad_text, tmp=tmp))
    for good_text in ["\n\n# only comments\n", "; semicolon comment\nREQUIRE_TLS=1\n",
                      "UNKNOWN_KEY=whatever\n", "CACHE_ENABLED = TRUE \n"]:
        proc, base = spawn(config_text=good_text, tmp=tmp)
        check("valid config %r starts" % good_text.strip()[:30], base is not None)
        stop(proc)

    # ---- misc edge cases
    check("empty DATAGATE_CONFIG ignored", not fails_startup(env_extra={"DATAGATE_CONFIG": ""}))
    file_path = os.path.join(tmp, "not-a-dir")
    open(file_path, "w").close()
    check("STORAGE_DIR pointing at a file fails startup",
          fails_startup(env_extra={"STORAGE_DIR": file_path}))
    check("CRLF config parses",
          not fails_startup(config_text="REQUIRE_TLS=1\r\nMAX_SOURCE_SIZE=10\r\n", tmp=tmp))
    check("padded env size accepted", not fails_startup(env_extra={"MAX_SOURCE_SIZE": " 64 "}))

    # export and filters still work on a dataset restored from disk
    store2 = os.path.join(tmp, "roundtrip")
    proc, BASE = spawn({"STORAGE_DIR": store2})
    try:
        ep2 = conv(BASE, "/big.csv").json()["endpoint"]
        before = requests.get(BASE + ep2 + "/export", timeout=10).text
    finally:
        stop(proc)
    proc, BASE = spawn({"STORAGE_DIR": store2})
    try:
        after = requests.get(BASE + ep2 + "/export", timeout=10)
        check("storage: export identical after restart",
              after.status_code == 200 and after.text == before, (before, after.text[:200]))
        q = requests.get(BASE + ep2, params={"name__exact": "Bob"}, timeout=10)
        check("storage: filters work after restart",
              q.status_code == 200 and q.json()["rows"] == [["Bob", 41]], q.text[:200])
        q = requests.get(BASE + ep2, params={"_sort_desc": "age"}, timeout=10)
        check("storage: sorting works after restart",
              q.status_code == 200 and q.json()["rows"][0] == ["Cid", 52], q.text[:200])
    finally:
        stop(proc)

    shutil.rmtree(tmp, ignore_errors=True)
    httpd.shutdown()
    print("\n%d checks, %d failures" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        print("failed: " + ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
