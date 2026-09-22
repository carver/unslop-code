"""Helpers for the `serve` / viewer spec tests.

Everything drives the real CLI as a black box: a `python mvault.py serve ...`
subprocess is started in an isolated cwd and spoken to over HTTP.
"""
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit, urljoin

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MVAULT = os.path.join(REPO_ROOT, "mvault.py")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840
REDIRECTS = (301, 302, 303, 307, 308)


# --------------------------------------------------------------------------
# ports / process control
# --------------------------------------------------------------------------
def free_port():
    sock = socket.socket()
    try:
        sock.bind((DEFAULT_HOST, 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def port_is_free(port, host=DEFAULT_HOST):
    sock = socket.socket()
    try:
        sock.connect((host, port))
    except OSError:
        return True
    else:
        return False
    finally:
        sock.close()


def wait_for_port(port, host=DEFAULT_HOST, timeout=15.0, proc=None):
    """Block until the server accepts a connection (or it dies / times out)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        sock = socket.socket()
        sock.settimeout(0.5)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            time.sleep(0.05)
        finally:
            sock.close()
    return False


# --------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------
class Response:
    def __init__(self, status, headers, body, path):
        self.status = status
        self.headers = headers
        self.body = body
        self.path = path

    @property
    def location(self):
        for key, value in self.headers:
            if key.lower() == "location":
                return value
        return None

    @property
    def is_redirect(self):
        return self.status in REDIRECTS

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Response(%r %r -> %r, %d bytes)" % (
            self.path, self.status, self.location, len(self.body))


class Client:
    """Minimal HTTP client that never follows redirects unless asked to."""

    def __init__(self, host, port):
        self.host = host
        self.port = port

    @property
    def origin(self):
        return "http://%s:%d" % (self.host, self.port)

    def request(self, method, path, body=None, headers=None, follow=False,
                _depth=0):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=15)
        send_headers = dict(headers or {})
        payload = None
        if body is not None:
            payload = body if isinstance(body, bytes) else body.encode("utf-8")
            send_headers.setdefault("Content-Type",
                                    "application/x-www-form-urlencoded")
        try:
            conn.request(method, path, body=payload, headers=send_headers)
            raw = conn.getresponse()
            data = raw.read()
            response = Response(raw.status, raw.getheaders(),
                                data.decode("utf-8", "replace"), path)
        finally:
            conn.close()
        if follow and response.is_redirect and _depth < 5:
            target = response.location or "/"
            split = urlsplit(urljoin("http://%s:%d%s" % (self.host, self.port,
                                                         path), target))
            next_path = split.path or "/"
            if split.query:
                next_path += "?" + split.query
            return self.request("GET", next_path, follow=True,
                                _depth=_depth + 1)
        return response

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, fields=None, raw=None, **kwargs):
        body = raw if raw is not None else urlencode(fields or {})
        return self.request("POST", path, body=body, **kwargs)


class Server:
    """A running `mvault.py serve` subprocess."""

    def __init__(self, proc, host, port, log_path, browser_log=None):
        self.proc = proc
        self.host = host
        self.port = port
        self.log_path = log_path
        self.browser_log = browser_log
        self.client = Client(host, port)

    # -- convenience proxies ------------------------------------------------
    def request(self, method, path, **kwargs):
        return self.client.request(method, path, **kwargs)

    def get(self, path, **kwargs):
        return self.client.get(path, **kwargs)

    def post(self, path, **kwargs):
        return self.client.post(path, **kwargs)

    @property
    def origin(self):
        return self.client.origin

    def output(self):
        try:
            with open(self.log_path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    def browser_urls(self):
        """URLs the CLI asked the browser to open, in order."""
        if not self.browser_log or not os.path.exists(self.browser_log):
            return []
        with open(self.browser_log, "r", encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]

    def wait_browser_urls(self, count=1, timeout=10.0):
        """Wait for the fake browser to have been handed `count` URLs."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            urls = self.browser_urls()
            if len(urls) >= count:
                return urls
            time.sleep(0.05)
        return self.browser_urls()

    def stop(self):
        """Terminate exactly this server by PID (never a pkill)."""
        if self.proc.poll() is None:
            try:
                self.proc.send_signal(signal.SIGINT)
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
                except Exception:
                    pass


def make_browser_stub(directory):
    """A fake browser: records each URL it is handed, one per line."""
    log = os.path.join(str(directory), "browser.log")
    script = os.path.join(str(directory), "fake-browser.sh")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write('#!/bin/sh\nprintf "%%s\\n" "$1" >> %s\n' % json.dumps(log))
    os.chmod(script, 0o755)
    return script, log


def start_server(cwd, name=None, host=None, port=None, extra=(),
                 browser=True, wait=True):
    """Launch `mvault.py serve` in `cwd`; output goes to a log file, not a pipe."""
    cwd = str(cwd)
    argv = [sys.executable, MVAULT, "serve"]
    if name is not None:
        argv.append(name)
    if host is not None:
        argv.append("--host=%s" % host)
    if port is not None:
        argv.append("--port=%s" % port)
    argv.extend(str(item) for item in extra)

    env = dict(os.environ)
    env["DISPLAY"] = ""
    browser_log = None
    if browser:
        script, browser_log = make_browser_stub(cwd)
        env["BROWSER"] = script
    else:
        env["BROWSER"] = "/bin/true"

    log_path = os.path.join(cwd, "serve.log")
    log = open(log_path, "wb")
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    finally:
        log.close()

    server = Server(proc, host or DEFAULT_HOST, port or DEFAULT_PORT, log_path,
                    browser_log)
    if wait:
        ready = wait_for_port(server.port, host=server.host, proc=proc)
        if not ready:
            server.stop()
            raise AssertionError("serve did not start: %r\n%s"
                                 % (argv, server.output()))
    return server


# --------------------------------------------------------------------------
# HTML inspection
# --------------------------------------------------------------------------
class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []          # (tag, {attrs}) in document order
        self._stack = []
        self.texts = {}         # index in self.tags -> collected text

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        index = len(self.tags) - 1
        self.texts[index] = ""
        self._stack.append(index)

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        self.texts[len(self.tags) - 1] = ""

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        for index in self._stack:
            self.texts[index] += data


def parse(html):
    collector = _Collector()
    collector.feed(html)
    return collector


def tags(html, name):
    """All `<name>` tags as attribute dicts, in document order."""
    return [attrs for tag, attrs in parse(html).tags if tag == name]


def links(html):
    """`[(href, text), ...]` for every anchor, in document order."""
    collector = parse(html)
    found = []
    for index, (tag, attrs) in enumerate(collector.tags):
        if tag == "a" and "href" in attrs:
            found.append((attrs["href"], collector.texts.get(index, "").strip()))
    return found


def hrefs(html):
    return [href for href, _ in links(html)]


def catalog_links(html, name=None):
    """Anchors pointing into `/catalog/`, optionally for one vault only."""
    prefix = "/catalog/" if name is None else "/catalog/%s" % name
    return [(href, text) for href, text in links(html) if href.startswith(prefix)]


LI_RE = re.compile(r"<li\b.*?</li>", re.DOTALL | re.IGNORECASE)
TR_RE = re.compile(r"<tr\b.*?</tr>", re.DOTALL | re.IGNORECASE)


def rows(html):
    """Raw markup of every row-ish element that links to an entry page."""
    found = [chunk for chunk in LI_RE.findall(html) if "/catalog/" in chunk]
    if not found:
        found = [chunk for chunk in TR_RE.findall(html) if "/catalog/" in chunk]
    return found


def row_for(html, entry_id):
    """The row markup for one entry id (matched on its entry-page link)."""
    needle = "/%s" % entry_id
    for chunk in rows(html):
        for href in hrefs(chunk):
            if href.rstrip("/").endswith(needle) and "/catalog/" in href:
                return chunk
    return None


def listed_ids(html, name, category):
    """Entry ids in listing order, read from the entry-page links."""
    prefix = "/catalog/%s/%s/" % (name, category)
    ordered = []
    for href in hrefs(html):
        if href.startswith(prefix):
            entry_id = href[len(prefix):].split("?")[0].split("#")[0]
            if entry_id and entry_id not in ordered:
                ordered.append(entry_id)
    return ordered


def normalize(markup, entry_id, title):
    """Strip a row down to what is *not* the entry's own identity.

    Used to prove two rows are visually distinguishable for reasons other than
    carrying a different id or title.
    """
    text = markup.replace(entry_id, "").replace(title, "")
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------
# embedded chart data
# --------------------------------------------------------------------------
JSON_SCRIPT_RE = re.compile(
    r"<script\b[^>]*\btype\s*=\s*[\"']application/(?:ld\+)?json[\"'][^>]*>"
    r"(.*?)</script>",
    re.DOTALL | re.IGNORECASE)

# Key names the spec leaves unspecified, so the tests stay shape-agnostic.
TS_KEYS = ("timestamp", "time", "t", "x", "key", "date", "at", "stamp")
VALUE_KEYS = ("value", "v", "y", "count", "n")


def json_blobs(html):
    """Every embedded machine-readable JSON payload on the page, parsed."""
    found = []
    for raw in JSON_SCRIPT_RE.findall(html):
        text = raw.strip()
        if not text:
            continue
        try:
            found.append(json.loads(text))
        except ValueError:
            continue
    return found


def _point(item):
    """One chart point as `(timestamp, value)`, whatever shape it is in."""
    if isinstance(item, dict):
        stamp = None
        for key in TS_KEYS:
            if key in item:
                stamp = item[key]
                break
        value = None
        for key in VALUE_KEYS:
            if key in item:
                value = item[key]
                break
        if stamp is None and len(item) == 1:      # {"<timestamp>": value}
            only = list(item)[0]
            return (only, item[only])
        return (stamp, value)
    if isinstance(item, (list, tuple)) and len(item) == 2:
        return (item[0], item[1])
    return (None, item)


def _find_series(blob, field):
    """The first list stored under key `field`, at any depth."""
    if isinstance(blob, dict):
        value = blob.get(field)
        if isinstance(value, list):
            return value
        for item in blob.values():
            found = _find_series(item, field)
            if found is not None:
                return found
    elif isinstance(blob, list):
        for item in blob:
            found = _find_series(item, field)
            if found is not None:
                return found
    return None


def chart_points(html, field):
    """`[(timestamp, value), ...]` for one charted field, or None if absent."""
    for blob in json_blobs(html):
        series = _find_series(blob, field)
        if series is not None:
            return [_point(item) for item in series]
    return None


def chart_timestamps(html, field):
    points = chart_points(html, field)
    return None if points is None else [stamp for stamp, _ in points]


def chart_values(html, field):
    points = chart_points(html, field)
    return None if points is None else [value for _, value in points]


ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []

    def handle_data(self, data):
        self.chunks.append(data)


def text_of(html):
    """All visible text of a document, whitespace-collapsed."""
    stripper = _Text()
    stripper.feed(re.sub(r"(?is)<script\b.*?</script>", " ", html))
    return re.sub(r"\s+", " ", "".join(stripper.chunks)).strip()


def srcs(html, tag):
    """`src` attributes of every `<tag>` on the page, in document order."""
    return [attrs["src"] for attrs in tags(html, tag) if "src" in attrs]


def vault_refs(html):
    """Every `/vault/...` URL the page references, via `src` or `href`."""
    found = []
    collector = parse(html)
    for _, attrs in collector.tags:
        for key in ("src", "href", "data-src", "poster"):
            value = attrs.get(key)
            if value and value.startswith("/vault/"):
                found.append(value)
    return found
