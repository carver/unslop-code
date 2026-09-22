"""End-to-end spec tests for mvault entry-detail annotations."""
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


def write_vault(name, catalog, media=()):
    shutil.rmtree(name, ignore_errors=True)
    os.makedirs(name)
    with open(os.path.join(name, "catalog.json"), "w") as fh:
        json.dump(catalog, fh, indent=2)
    if media:
        os.makedirs(os.path.join(name, "media"), exist_ok=True)
        for filename, blob in media:
            with open(os.path.join(name, "media", filename), "wb") as fh:
                fh.write(blob)


def catalog(name):
    with open(os.path.join(name, "catalog.json")) as fh:
        return json.load(fh)


def backup(name):
    path = os.path.join(name, "catalog.bak")
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        return json.load(fh)


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
TS1, TS2 = "2024-06-15T09:00:00", "2024-06-15T11:00:00"
EPOCH_A, EPOCH_B = "1718444400", "1718451600"


def v1_catalog():
    return {
        "version": 1, "source_id": "abc123",
        "entries": [
            {"id": "e1", "published": "2024-05-03T00:00:00", "width": 1920,
             "height": 1080,
             "title": {EPOCH_A: "V1 one"}, "description": {EPOCH_A: "d1"},
             "views": {EPOCH_A: 5, EPOCH_B: 9}, "likes": {EPOCH_A: None},
             "preview": {EPOCH_A: "p1"}},
            {"id": "e2", "published": "2024-05-01T00:00:00", "width": 640,
             "height": 480,
             "title": {EPOCH_A: "V1 two"}, "description": {EPOCH_A: "d2"},
             "views": {EPOCH_A: 1}, "likes": {EPOCH_A: 0},
             "preview": {EPOCH_A: "p2"}},
        ],
    }


def v2_catalog():
    return {
        "version": 2, "source": "https://feeds.example.org/chan",
        "episodes": [
            {"id": "e1", "published": "2024-05-03T00:00:00", "width": 1280,
             "height": 720, "title": {TS1: "V2 one"},
             "description": {TS1: "d"}, "views": {TS1: 10},
             "likes": {TS1: 4}, "preview": {TS1: "p"}},
        ],
        "streams": [], "clips": [],
    }


def v3_entry(eid, **kw):
    base = {"id": eid, "published": "2024-05-03T00:00:00", "width": 1920,
            "height": 1080, "title": {TS1: "T-" + eid},
            "description": {TS1: "D-" + eid}, "views": {TS1: 1},
            "likes": {TS1: 2}, "preview": {TS1: "p"},
            "removed": {TS1: False}, "annotations": []}
    base.update(kw)
    return base


def v3_catalog():
    return {"version": 3, "source": "https://feeds.example.org/three/",
            "episodes": [v3_entry("e1"), v3_entry("e2")],
            "streams": [v3_entry("s1")], "clips": []}


write_vault("v3", v3_catalog(), media=[("e1.mp4", MP4)])
write_vault("v1", v1_catalog())
write_vault("v2", v2_catalog())

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


def request(method, path, payload=None, raw=None):
    data = raw
    if data is None and payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        resp = opener.open(req, timeout=10)
        return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode("utf-8", "replace")


def get(path):
    return request("GET", path)


def anns(body):
    m = re.search(r'<script type="application/json" id="annotation-data">(.*?)</script>',
                  body, re.S)
    return json.loads(m.group(1).replace("\\u003c", "<")) if m else None


def redirected(headers):
    return headers.get("Location", "")


# ------------------------------------------------------------ v3 create
st, hd, body = request("POST", "/catalog/v3/episodes/e1",
                       {"title": "Intro", "timecode": "1:30", "body": "note"})
check(st in (301, 302, 303, 307, 308), "v3 POST annotation redirects (got %s)" % st)
check(redirected(hd) == "/catalog/v3/episodes/e1?timecode=90",
      "redirect carries integer seconds: %r" % redirected(hd))

stored = catalog("v3")["episodes"][0]["annotations"]
check(len(stored) == 1, "one annotation stored")
a = stored[0]
check(isinstance(a.get("id"), str) and a["id"], "annotation id is a string")
check(a.get("timecode") == 90, "timecode stored as integer whole seconds")
check(a.get("title") == "Intro", "title stored as provided")
check(a.get("body") == "note", "body stored as provided")
check(backup("v3") is not None and backup("v3")["episodes"][0]["annotations"] == [],
      "catalog.bak holds the pre-annotation catalog")

st, hd, body = get("/catalog/v3/episodes/e1?timecode=90")
check(st == 200 and "Intro" in body and "note" in body,
      "GET visibly renders the stored annotation")
data = anns(body)
check(data is not None and [x["title"] for x in data["annotations"]] == ["Intro"],
      "annotation data embedded")
check('data-timecode="90"' in body, "detail page carries the seek timecode")

# body default null
st, hd, body = request("POST", "/catalog/v3/episodes/e1",
                       {"title": "Second", "timecode": "90"})
check(st in (302, 303) and redirected(hd).endswith("?timecode=90"),
      "SS timecode -> 90 seconds")
stored = catalog("v3")["episodes"][0]["annotations"]
check(len(stored) == 2 and stored[1]["body"] is None, "omitted body defaults to null")
check([x["title"] for x in stored] == ["Intro", "Second"], "creation order preserved")
check(stored[0]["id"] != stored[1]["id"], "annotation ids unique within entry")

st, hd, body = request("POST", "/catalog/v3/episodes/e1",
                       {"title": "Third", "timecode": "1:01:30"})
check(redirected(hd).endswith("?timecode=3690"), "HH:MM:SS -> 3690")
st, hd, body = request("POST", "/catalog/v3/episodes/e1",
                       {"title": "Fourth", "timecode": "90:00"})
check(redirected(hd).endswith("?timecode=5400"), "MM:SS clock bounds not enforced")
st, hd, body = request("POST", "/catalog/v3/episodes/e1",
                       {"title": "Fifth", "timecode": "0090"})
check(redirected(hd).endswith("?timecode=90"), "leading zeros allowed")

ids = [x["id"] for x in catalog("v3")["episodes"][0]["annotations"]]
check(len(set(ids)) == 5, "all five ids unique")

# ------------------------------------------------------------ v3 update
target = ids[0]
st, hd, body = request("PATCH", "/catalog/v3/episodes/e1",
                       {"id": target, "title": "Intro edited"})
check(st in (302, 303), "PATCH redirects (got %s)" % st)
check(redirected(hd) == "/catalog/v3/episodes/e1", "PATCH redirect to detail page")
a = catalog("v3")["episodes"][0]["annotations"][0]
check(a["title"] == "Intro edited", "title replaced")
check(a["body"] == "note", "omitted body left unchanged")
check(a["timecode"] == 90, "timecode untouched by update")

st, hd, body = request("PATCH", "/catalog/v3/episodes/e1",
                       {"id": target, "body": "new body"})
a = catalog("v3")["episodes"][0]["annotations"][0]
check(a["title"] == "Intro edited" and a["body"] == "new body",
      "body replaced, omitted title unchanged")
check(backup("v3")["episodes"][0]["annotations"][0]["body"] == "note",
      "catalog.bak precedes the update")

st, hd, body = get("/catalog/v3/episodes/e1")
check("Intro edited" in body and "new body" in body, "update visible on GET")

# ------------------------------------------------------------ v3 delete
st, hd, body = request("DELETE", "/catalog/v3/episodes/e1", {"id": target})
check(st in (302, 303) and redirected(hd) == "/catalog/v3/episodes/e1",
      "DELETE redirects to detail page")
left = catalog("v3")["episodes"][0]["annotations"]
check([x["id"] for x in left] == ids[1:], "annotation removed, order preserved")
st, hd, body = get("/catalog/v3/episodes/e1")
check("Intro edited" not in body, "deleted annotation no longer rendered")

# ------------------------------------------------------------ errors
st, hd, body = request("POST", "/catalog/v3/episodes/e2", {"timecode": "10"})
check(st == 400 and "title" in body, "missing title -> 400 naming the field")
st, hd, body = request("POST", "/catalog/v3/episodes/e2", {"title": "x"})
check(st == 400 and "timecode" in body, "missing timecode -> 400 naming the field")
for bad in ["abc", "", "1:2:3:4", "-5", "1.5", "1:", ":30", "1:xx", "  "]:
    st, hd, body = request("POST", "/catalog/v3/episodes/e2",
                           {"title": "x", "timecode": bad})
    check(st == 400, "invalid timecode %r -> 400 (got %s)" % (bad, st))
st, hd, body = request("PATCH", "/catalog/v3/episodes/e2", {"title": "x"})
check(st == 400 and "id" in body, "missing id on update -> 400 naming the field")
st, hd, body = request("DELETE", "/catalog/v3/episodes/e2", {})
check(st == 400 and "id" in body, "missing id on delete -> 400 naming the field")
st, hd, body = request("PATCH", "/catalog/v3/episodes/e2",
                       {"id": "nope", "title": "x"})
check(st == 404, "unknown annotation id on update -> 404 (got %s)" % st)
st, hd, body = request("DELETE", "/catalog/v3/episodes/e2", {"id": "nope"})
check(st == 404, "unknown annotation id on delete -> 404 (got %s)" % st)
st, hd, body = request("POST", "/catalog/v3/episodes/e2", raw=b"{not json")
check(st == 400, "malformed JSON -> 400 (got %s)" % st)
check(catalog("v3")["episodes"][1]["annotations"] == [],
      "failed requests wrote nothing")
for st_, _hd, bd in [request("POST", "/catalog/v3/episodes/e2", raw=b"{no"),
                     request("PATCH", "/catalog/v3/episodes/e2", {"id": "x"})]:
    check("Traceback" not in bd and "File \"" not in bd,
          "error response carries no traceback")
st, hd, body = request("POST", "/catalog/v3/episodes/missing",
                       {"title": "x", "timecode": "1"})
check(st == 404, "unknown entry -> 404")

# ---------------------------------------------------- v1 auto-migration
before = catalog("v1")
st, hd, body = request("POST", "/catalog/v1/entries/e1",
                       {"title": "V1 note", "timecode": "2:00"})
check(st in (302, 303), "v1 annotation via pre-migration category (got %s)" % st)
check(redirected(hd) == "/catalog/v1/episodes/e1?timecode=120",
      "redirect uses post-migration category: %r" % redirected(hd))
cat = catalog("v1")
check(cat["version"] == 3, "v1 vault auto-migrated to version 3")
check(cat["source"] == "https://media.example.com/channel/abc123",
      "v1 source_id converted the same way migrate does")
check("entries" not in cat and len(cat["episodes"]) == 2,
      "v1 entries moved to episodes")
check(list(cat["episodes"][0]["title"].keys())[0] == "2024-06-15T11:00:00" or
      "2024-06-15" in list(cat["episodes"][0]["title"].keys())[0],
      "v1 epoch history keys converted to ISO 8601")
stamps = set()
for cat_entry in cat["episodes"]:
    stamps.update(cat_entry["removed"].keys())
check(len(stamps) == 1, "one shared timestamp for migration-added removed fields")
check(cat["episodes"][0]["annotations"][0]["timecode"] == 120,
      "annotation applied after migration")
check(cat["episodes"][1]["annotations"] == [],
      "other entries gain an empty annotations list")
check(backup("v1") == before,
      "catalog.bak holds the original pre-migration catalog")

st, hd, body = get("/catalog/v1/episodes/e1")
check(st == 200 and "V1 note" in body, "migrated entry renders its annotation")
st, hd, body = get("/catalog/v1/entries/e1")
check(st == 404 or st in (301, 302, 303),
      "retired v1 entries route 404s or redirects (got %s)" % st)

aid = cat["episodes"][0]["annotations"][0]["id"]
st, hd, body = request("PATCH", "/catalog/v1/episodes/e1",
                       {"id": aid, "title": "V1 edited"})
check(st in (302, 303), "PATCH on the migrated vault")
check(catalog("v1")["episodes"][0]["annotations"][0]["title"] == "V1 edited",
      "PATCH applied after migration")
st, hd, body = request("DELETE", "/catalog/v1/episodes/e1", {"id": aid})
check(st in (302, 303) and catalog("v1")["episodes"][0]["annotations"] == [],
      "DELETE on the migrated vault")

# ---------------------------------------------------- v2 auto-migration
before = catalog("v2")
st, hd, body = request("POST", "/catalog/v2/episodes/e1",
                       {"title": "V2 note", "timecode": "45"})
check(st in (302, 303) and redirected(hd) == "/catalog/v2/episodes/e1?timecode=45",
      "v2 annotation redirect")
cat = catalog("v2")
check(cat["version"] == 3, "v2 vault auto-migrated to version 3")
check(cat["episodes"][0]["annotations"][0]["title"] == "V2 note",
      "annotation applied to migrated v2 entry")
check(backup("v2") == before, "catalog.bak holds the pre-migration v2 catalog")
check(cat["episodes"][0]["removed"] == {list(cat["episodes"][0]["removed"])[0]: False},
      "v2 migration adds removed history")

# ---------------------------------------------------- migration failure
broken = v1_catalog()
broken["entries"][0]["views"] = {"not-an-epoch": 5}
write_vault("bad", broken)
before = catalog("bad")
st, hd, body = request("POST", "/catalog/bad/entries/e1",
                       {"title": "x", "timecode": "1"})
check(st == 500, "migration failure -> 500 (got %s)" % st)
check("Traceback" not in body and "File \"" not in body,
      "500 response is a well-formed page with no traceback")
check(catalog("bad") == before, "original catalog unchanged after failed migration")
check(backup("bad") is None, "no backup written when migration fails")

# ---------------------------------------------------- timecode seek
st, hd, body = get("/catalog/v3/episodes/e1?timecode=42")
check(st == 200 and 'data-timecode="42"' in body, "GET honours ?timecode=")
check("#t=42" in body or "currentTime" in body, "player seeks to the timecode")

proc.terminate()
proc.wait(timeout=10)
print("")
print("FAILURES: %d" % len(fails))
for f in fails:
    print("  - " + f)
sys.exit(1 if fails else 0)
