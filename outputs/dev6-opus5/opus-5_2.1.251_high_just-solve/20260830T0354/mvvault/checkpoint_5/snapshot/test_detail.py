"""End-to-end spec tests for the mvault viewer detail pages and static assets."""
import json, os, re, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MV = os.path.join(HERE, "mvault.py")
PY = sys.executable

tmp = tempfile.mkdtemp()
os.chdir(tmp)
fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def write_vault(name, catalog, media=(), previews=()):
    shutil.rmtree(name, ignore_errors=True)
    os.makedirs(name)
    with open(os.path.join(name, "catalog.json"), "w") as fh:
        json.dump(catalog, fh, indent=2)
    for directory, files in (("media", media), ("previews", previews)):
        if not files:
            continue
        os.makedirs(os.path.join(name, directory), exist_ok=True)
        for filename, blob in files:
            with open(os.path.join(name, directory, filename), "wb") as fh:
                fh.write(blob)


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

# v1: UNIX-epoch history keys. "999999999" is numerically older than
# "1718444400" but lexicographically newer, so ordering must use numbers.
OLD, MID, NEW = "999999999", "1718444400", "1718451600"
V1 = {
    "version": 1,
    "source_id": "abc123",
    "entries": [
        {"id": "e1", "published": "2024-05-03T00:00:00", "width": 1920,
         "height": 1080,
         "title": {OLD: "Old title", NEW: "V1 current title"},
         "description": {OLD: "old text", NEW: "V1 current description"},
         "views": {NEW: 30, OLD: 5, MID: 10},
         "likes": {MID: None, OLD: 1},
         "preview": {OLD: "p1"}},
        {"id": "e2", "published": "2024-05-02T10:00:00", "width": 640,
         "height": 480,
         "title": {MID: "Two"}, "description": {MID: "D2"},
         "views": {MID: 1}, "likes": {MID: 0}, "preview": {MID: "p2"}},
    ],
}

TS1, TS2, TS3 = "2024-06-15T09:00:00", "2024-06-15T11:00:00", "2024-07-01T08:30:00"
V2 = {
    "version": 2,
    "source": "https://feeds.example.org/chan",
    "episodes": [
        {"id": "e1", "published": "2024-05-03T00:00:00", "width": 1280,
         "height": 720,
         "title": {TS1: "First", TS2: "V2 current title"},
         "description": {TS1: "V2 current description"},
         "views": {TS1: 10, TS2: 20, TS3: 25},
         "likes": {TS1: None, TS2: 4},
         "preview": {TS1: "p1"}},
    ],
    "streams": [
        {"id": "s1", "published": "2023-01-01T05:06:07", "width": 100,
         "height": 200, "title": {TS1: "S"}, "description": {TS1: "SD"},
         "views": {TS1: 3}, "likes": {TS1: 4}, "preview": {TS1: "sp"}},
    ],
    "clips": [],
}


def v3_entry(eid, **kw):
    base = {"id": eid, "published": "2024-05-03T00:00:00", "width": 1920,
            "height": 1080,
            "title": {TS1: "T-" + eid}, "description": {TS1: "D-" + eid},
            "views": {TS1: 1}, "likes": {TS1: 2}, "preview": {TS1: "p"},
            "removed": {TS1: False}, "annotations": []}
    base.update(kw)
    return base


V3 = {
    "version": 3,
    "source": "https://feeds.example.org/three/",
    "episodes": [
        v3_entry("e1",
                 title={TS1: "Old", TS2: "V3 current title"},
                 description={TS1: "old", TS2: "V3 current description"},
                 views={TS3: 300, TS1: 100, TS2: 200},
                 likes={TS1: None, TS2: 7, TS3: None}),
        v3_entry("gone", removed={TS1: False, TS2: True}),
        v3_entry("single"),
    ],
    "streams": [v3_entry("s1")],
    "clips": [v3_entry("dup")],
}

write_vault("v1", V1)
write_vault("v2", V2)
write_vault("v3", V3,
            media=[("e1.mp4", MP4), ("clip-single-x.webm", b"\x1a\x45\xdf\xa3xx"),
                   ("secret-not-an-entry.mp4", MP4)],
            previews=[("e1.png", PNG), ("single.part", b"partial")])
with open("topsecret.txt", "w") as fh:
    fh.write("do not serve me")

# ------------------------------------------------------------------- server
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()
env = dict(os.environ, MVAULT_STATE_DIR=os.path.join(tmp, "state"),
           BROWSER="/bin/true")
proc = subprocess.Popen([PY, MV, "serve", "--port", str(PORT)], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
BASE = "http://127.0.0.1:%d" % PORT
for _ in range(100):
    try:
        urllib.request.urlopen(BASE + "/", timeout=1).read()
        break
    except Exception:
        time.sleep(0.1)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


opener = urllib.request.build_opener(NoRedirect)


def get(path):
    """Return (status, headers, body_bytes) without following redirects."""
    try:
        resp = opener.open(BASE + path, timeout=10)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def text(path):
    status, headers, body = get(path)
    return status, headers, body.decode("utf-8", "replace")


def chart(body):
    m = re.search(r'<script type="application/json" id="chart-data">(.*?)</script>',
                  body, re.S)
    return json.loads(m.group(1)) if m else None


def pairs(data, field):
    return [(p["timestamp"], p["value"]) for p in data[field]]


# --------------------------------------------------------------- v3 details
st, hd, body = text("/catalog/v3/episodes/e1")
check(st == 200, "v3 detail 200")
check("V3 current title" in body and "Old" not in body.replace("Old title", ""),
      "v3 current title from latest history key")
check("V3 current description" in body, "v3 current description")
check("2024-05-03T00:00:00" in body, "v3 published date displayed")
check("1920" in body and "1080" in body, "v3 dimensions displayed")
check("https://feeds.example.org/three/entry/e1" in body, "v3 source link")
check('href="/catalog/v3/episodes"' in body, "v3 back link to category listing")
check("/vault/v3/media/e1.mp4" in body, "v3 media static endpoint referenced")

data = chart(body)
check(data is not None, "v3 chart data embedded as machine-readable JSON")
check(pairs(data, "views") == [(TS1, 100), (TS2, 200), (TS3, 300)],
      "v3 views points chronological oldest first")
check(pairs(data, "likes") == [(TS1, None), (TS2, 7), (TS3, None)],
      "v3 likes nulls preserved, unfiltered")

st, hd, body = text("/catalog/v3/episodes/gone")
check(st == 200 and "T-gone" in body, "v3 removed entry still reachable")

st, hd, body = text("/catalog/v3/episodes/single")
data = chart(body)
check(st == 200, "v3 single-point entry 200")
check("T-single" in body and "D-single" in body and "2024-05-03T00:00:00" in body
      and "1920" in body and "/entry/single" in body,
      "single-point entry still renders metadata and source link")
check(data is not None and pairs(data, "views") == [(TS1, 1)],
      "single-point history exposed without filtering")
check("/vault/v3/media/clip-single-x.webm" in body,
      "media discovered by filename containing the entry id")

st, hd, body = text("/catalog/v3/streams/s1")
check(st == 200 and "T-s1" in body, "v3 stream detail")
check("No media file" in body or "media-missing" in body,
      "missing media noted, metadata kept")
check(chart(body) is not None, "chart data present without downloaded media")

# ------------------------------------------------------- v1 (epoch) details
st, hd, body = text("/catalog/v1/entries/e1")
check(st == 200, "v1 detail in 'entries' category 200")
check("V1 current title" in body, "v1 current title by numeric key comparison")
check("V1 current description" in body, "v1 current description")
check("https://media.example.com/channel/abc123/entry/e1" in body,
      "v1 source link derived from source_id")
data = chart(body)
check(pairs(data, "views") == [("2001-09-09T01:46:39", 5),
                               ("2024-06-15T09:40:00", 10),
                               ("2024-06-15T11:40:00", 30)],
      "v1 epoch keys -> ISO 8601, ordered numerically (%r)"
      % (pairs(data, "views") if data else None))
check(pairs(data, "likes") == [("2001-09-09T01:46:39", 1),
                               ("2024-06-15T09:40:00", None)],
      "v1 likes null preserved after normalization")

# ------------------------------------------------------------- v2 details
st, hd, body = text("/catalog/v2/episodes/e1")
check(st == 200, "v2 detail 200")
check("V2 current title" in body and "V2 current description" in body,
      "v2 current values by lexicographic key comparison")
check("https://feeds.example.org/chan/entry/e1" in body, "v2 source link")
data = chart(body)
check(pairs(data, "views") == [(TS1, 10), (TS2, 20), (TS3, 25)],
      "v2 ISO keys pass through in order")
check(pairs(data, "likes") == [(TS1, None), (TS2, 4)], "v2 likes null kept")

# --------------------------------------------------------------- lookup rules
st, hd, body = text("/catalog/v3/episodes/dup")
check(st == 404 or (st in (301, 302, 303, 307)
                    and "/catalog/v3/episodes" in hd.get("Location", "")),
      "entry from another category does not satisfy lookup (got %d)" % st)
check(st != 200, "cross-category id not served")
st, hd, body = text("/catalog/v3/clips/dup")
check(st == 200 and "T-dup" in body, "entry found in its own category")
st, hd, body = text("/catalog/v3/episodes/nope")
check(st == 404 or st in (301, 302, 303, 307), "missing entry -> 404/redirect")
check("Traceback" not in body and "File \"" not in body,
      "error page exposes no stack trace")
st, hd, body = text("/catalog/v1/episodes/e1")
check(st in (301, 302, 303, 307) and "/catalog/v1/entries" in hd.get("Location", ""),
      "invalid category on v1 detail route redirects like the listing route")
st, hd, body = text("/catalog/nosuch/episodes/e1")
check(st in (301, 302, 303, 307) and hd.get("Location") == "/",
      "missing vault on detail route redirects to landing")
st, hd, body = text("/")
check("not found" in body.lower() and "nosuch" in body,
      "landing shows vault-not-found indication")

# ---------------------------------------------------------------- static files
st, hd, body = get("/vault/v3/media/e1.mp4")
check(st == 200 and body == MP4, "media file served byte-for-byte")
check(hd.get("Content-Type", "").startswith(("video/", "audio/")),
      "media MIME type (%s)" % hd.get("Content-Type"))
st, hd, body = get("/vault/v3/preview/e1")
check(st == 200 and body == PNG, "preview served by id -> filename match")
check(hd.get("Content-Type", "").startswith("image/"),
      "preview image MIME type (%s)" % hd.get("Content-Type"))
st, hd, body = get("/vault/v3/media/missing.mp4")
check(st == 404, "missing media -> 404")
st, hd, body = get("/vault/v3/preview/nosuchid")
check(st == 404, "missing preview -> 404")
st, hd, body = get("/vault/v3/preview/single")
check(st == 404, "partial preview file is not served")
st, hd, body = get("/vault/nosuch/media/e1.mp4")
check(st in (301, 302, 303, 307) and hd.get("Location") == "/",
      "missing vault on static route redirects to landing")

for attack in ("/vault/v3/media/../../topsecret.txt",
               "/vault/v3/media/..%2f..%2ftopsecret.txt",
               "/vault/v3/media/%2e%2e/catalog.json",
               "/vault/v3/preview/../../topsecret.txt",
               "/vault/v3/media/../catalog.json",
               "/vault/../topsecret.txt/media/x"):
    st, hd, body = get(attack)
    check(st in (403, 404) and b"do not serve" not in body,
          "traversal blocked: %s (got %d)" % (attack, st))

st, hd, body = get("/vault/v3/media/e1.mp4/extra")
check(st in (403, 404), "nested media path under a file -> 4xx")

# ------------------------------------------------------------------- teardown
proc.terminate()
try:
    proc.wait(timeout=10)
except subprocess.TimeoutExpired:
    proc.kill()

print()
print("FAILURES: %d" % len(fails))
for f in fails:
    print("  -", f)
os.chdir(HERE)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
