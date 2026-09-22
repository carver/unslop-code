"""Checks for entry annotations served by the mvault viewer."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
MVAULT = os.path.join(ROOT, "mvault.py")

FAILED = []


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label
          + (" :: " + detail if detail and not condition else ""))
    if not condition:
        FAILED.append(label)


def catalog(name):
    with open(os.path.join(name, "catalog.json")) as fh:
        return json.load(fh)


def backup(name):
    with open(os.path.join(name, "catalog.bak")) as fh:
        return json.load(fh)


def write_catalog(name, doc):
    os.makedirs(name, exist_ok=True)
    with open(os.path.join(name, "catalog.json"), "w") as fh:
        json.dump(doc, fh, indent=2)


def v3_entry(eid, stamp="2024-01-01T00:00:00"):
    return {"id": eid, "published": "2024-01-01T00:00:00", "width": 4,
            "height": 2, "title": {stamp: "T " + eid}, "description": {stamp: "d"},
            "views": {stamp: 3}, "likes": {stamp: 1}, "preview": {stamp: "p"},
            "removed": {stamp: False}, "annotations": []}


def v1_entry(eid):
    return {"id": eid, "published": "2024-01-01T00:00:00", "width": 4,
            "height": 2, "title": {"1700000000": "T " + eid},
            "description": {"1700000000": "d"}, "views": {"1700000000": 3},
            "likes": {"1700000000": 1}, "preview": {"1700000000": "p"}}


def v2_entry(eid):
    return {"id": eid, "published": "2024-01-01T00:00:00", "width": 4,
            "height": 2, "title": {"2024-01-01T00:00:00": "T " + eid},
            "description": {"2024-01-01T00:00:00": "d"},
            "views": {"2024-01-01T00:00:00": 3},
            "likes": {"2024-01-01T00:00:00": 1},
            "preview": {"2024-01-01T00:00:00": "p"}}


def main():
    workdir = tempfile.mkdtemp()
    os.chdir(workdir)

    proc = subprocess.Popen([sys.executable, MVAULT, "serve", "--no-browser",
                             "--port=0"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=workdir)
    line = proc.stdout.readline()
    base = line.split(" at ")[1].strip().rstrip("/")
    session = requests.Session()

    def url(*parts):
        return base + "/catalog/" + "/".join(parts)

    def send(method, target, payload, raw=None, redirects=False):
        data = raw if raw is not None else json.dumps(payload)
        return session.request(method, target, data=data,
                               headers={"Content-Type": "application/json"},
                               allow_redirects=redirects)

    # ---- version 3 create -------------------------------------------------- #
    write_catalog("v3v", {"version": 3, "source": "https://e.example/f.json",
                          "episodes": [v3_entry("e1"), v3_entry("e2")],
                          "streams": [v3_entry("s1")], "clips": []})
    before = open("v3v/catalog.json", "rb").read()
    target = url("v3v", "episodes", "e1")

    res = send("POST", target, {"title": "Intro", "timecode": "1:30"})
    check("create redirects", res.status_code in (302, 303), str(res.status_code))
    check("create redirect names entry and timecode",
          res.headers.get("Location", "").endswith(
              "/catalog/v3v/episodes/e1?timecode=90"),
          res.headers.get("Location", ""))
    cat = catalog("v3v")
    notes = cat["episodes"][0]["annotations"]
    check("annotation stored in entry", len(notes) == 1, json.dumps(notes))
    note = notes[0]
    check("annotation fields",
          isinstance(note["id"], str) and note["timecode"] == 90
          and note["title"] == "Intro" and note["body"] is None,
          json.dumps(note))
    check("other entries untouched",
          cat["episodes"][1]["annotations"] == []
          and cat["streams"][0]["annotations"] == [])
    check("backup holds pre-annotation catalog",
          open("v3v/catalog.bak", "rb").read() == before)
    check("catalog stays version 3", cat["version"] == 3)

    page = session.get(target).text
    check("detail page renders annotation", "Intro" in page, page[:200])
    check("detail page renders timecode", "1:30" in page and "90" in page)

    res = send("POST", target, {"title": "Second", "timecode": "45",
                                "body": "a note"})
    check("second create redirects with its own timecode",
          res.headers.get("Location", "").endswith("?timecode=45"),
          res.headers.get("Location", ""))
    notes = catalog("v3v")["episodes"][0]["annotations"]
    check("annotations keep creation order",
          [n["title"] for n in notes] == ["Intro", "Second"], json.dumps(notes))
    check("unique ids", notes[0]["id"] != notes[1]["id"])
    check("optional body stored", notes[1]["body"] == "a note")
    page = session.get(target).text
    check("both annotations rendered in order",
          page.index("Intro") < page.index("Second") and "a note" in page)

    # ---- timecode grammar --------------------------------------------------- #
    for text, seconds in (("90", 90), ("1:30", 90), ("1:01:30", 3690),
                          ("90:00", 5400), ("00:00:07", 7), ("0", 0),
                          ("007", 7)):
        res = send("POST", url("v3v", "episodes", "e2"),
                   {"title": "t", "timecode": text})
        check("timecode %r parses to %d" % (text, seconds),
              res.headers.get("Location", "").endswith("?timecode=%d" % seconds),
              res.headers.get("Location", ""))
    stored = [n["timecode"] for n in catalog("v3v")["episodes"][1]["annotations"]]
    check("timecodes stored as whole seconds",
          stored == [90, 90, 3690, 5400, 7, 0, 7], str(stored))

    for bad in ("", "abc", "1:2:3:4", "-5", "1.5", ":30", "90:", "1:aa",
                "1: 30", "e", "٣"):
        res = send("POST", url("v3v", "episodes", "e2"),
                   {"title": "t", "timecode": bad})
        check("invalid timecode %r rejected" % bad, res.status_code == 400,
              str(res.status_code))
        check("invalid timecode %r explains format" % bad,
              "timecode" in res.text and "format" in res.text.lower(),
              res.text[:200])

    # ---- update ------------------------------------------------------------- #
    ident = catalog("v3v")["episodes"][0]["annotations"][1]["id"]
    before = open("v3v/catalog.json", "rb").read()
    res = send("PATCH", target, {"id": ident, "title": "Renamed"})
    check("update redirects", res.status_code in (302, 303), str(res.status_code))
    check("update redirect to entry page",
          res.headers.get("Location", "").endswith("/catalog/v3v/episodes/e1"),
          res.headers.get("Location", ""))
    note = catalog("v3v")["episodes"][0]["annotations"][1]
    check("update replaces title", note["title"] == "Renamed", json.dumps(note))
    check("omitted field unchanged", note["body"] == "a note", json.dumps(note))
    check("timecode unchanged by update", note["timecode"] == 45)
    check("update backs up first",
          open("v3v/catalog.bak", "rb").read() == before)

    send("PATCH", target, {"id": ident, "body": "new body"})
    note = catalog("v3v")["episodes"][0]["annotations"][1]
    check("body-only update", note["body"] == "new body"
          and note["title"] == "Renamed", json.dumps(note))
    send("PATCH", target, {"id": ident, "body": None})
    check("body may be cleared to null",
          catalog("v3v")["episodes"][0]["annotations"][1]["body"] is None)
    page = session.get(target).text
    check("update visible on later GET",
          "Renamed" in page and "a note" not in page)

    # ---- delete ------------------------------------------------------------- #
    before = open("v3v/catalog.json", "rb").read()
    res = send("DELETE", target, {"id": ident})
    check("delete redirects", res.status_code in (302, 303), str(res.status_code))
    notes = catalog("v3v")["episodes"][0]["annotations"]
    check("delete removes only that annotation",
          [n["title"] for n in notes] == ["Intro"], json.dumps(notes))
    check("delete backs up first", open("v3v/catalog.bak", "rb").read() == before)
    page = session.get(target).text
    check("delete visible on later GET", "Renamed" not in page and "Intro" in page)

    # ---- errors ------------------------------------------------------------- #
    res = send("POST", target, {"timecode": "10"})
    check("create without title is 400", res.status_code == 400, str(res.status_code))
    check("create without title names field", "title" in res.text, res.text[:200])
    res = send("POST", target, {"title": "x"})
    check("create without timecode is 400", res.status_code == 400,
          str(res.status_code))
    check("create without timecode names field", "timecode" in res.text,
          res.text[:200])
    res = send("PATCH", target, {"title": "x"})
    check("update without id is 400", res.status_code == 400, str(res.status_code))
    check("update without id names field", "id" in res.text, res.text[:200])
    res = send("DELETE", target, {})
    check("delete without id is 400", res.status_code == 400, str(res.status_code))
    check("delete without id names field", "id" in res.text, res.text[:200])
    res = send("PATCH", target, {"id": "nope", "title": "x"})
    check("update of unknown annotation is 404", res.status_code == 404,
          str(res.status_code))
    res = send("DELETE", target, {"id": "nope"})
    check("delete of unknown annotation is 404", res.status_code == 404,
          str(res.status_code))
    for raw in ("{not json", "", "[]", "\"text\"", "title=x&timecode=1"):
        res = send("POST", target, None, raw=raw)
        check("malformed body %r is 400" % raw, res.status_code == 400,
              str(res.status_code))
    res = send("POST", url("v3v", "episodes", "missing"),
               {"title": "x", "timecode": "1"})
    check("annotation on unknown entry is 404", res.status_code == 404,
          str(res.status_code))
    res = send("POST", url("v3v", "entries", "e1"), {"title": "x", "timecode": "1"})
    check("v1 category on a v3 vault is 404", res.status_code == 404,
          str(res.status_code))
    for res in (send("POST", target, {"title": "x", "timecode": "1"}),
                send("POST", target, {"timecode": "nope"}),
                send("PATCH", target, {"id": "nope", "title": "x"})):
        check("no traceback in response", "Traceback" not in res.text
              and "File \"" not in res.text, res.text[:200])
    unchanged = catalog("v3v")["episodes"][0]["annotations"]
    check("failed requests changed nothing but the accepted one",
          [n["title"] for n in unchanged] == ["Intro", "x"], json.dumps(unchanged))

    # ---- version 1 auto-migration ------------------------------------------- #
    v1 = {"version": 1, "source_id": "chan42",
          "entries": [v1_entry("o1"), v1_entry("o2")], "notes": "local"}
    write_catalog("one", v1)
    before = open("one/catalog.json", "rb").read()
    res = send("POST", url("one", "entries", "o1"),
               {"title": "Legacy", "timecode": "2:00"})
    check("v1 annotation redirects", res.status_code in (302, 303),
          str(res.status_code))
    check("v1 redirect uses episodes",
          res.headers.get("Location", "").endswith(
              "/catalog/one/episodes/o1?timecode=120"),
          res.headers.get("Location", ""))
    cat = catalog("one")
    check("vault migrated to v3", cat["version"] == 3, json.dumps(cat)[:200])
    check("v1 entries moved to episodes",
          [e["id"] for e in cat["episodes"]] == ["o1", "o2"]
          and cat["streams"] == [] and cat["clips"] == []
          and "entries" not in cat and "source_id" not in cat)
    check("v1 source_id expanded",
          cat["source"] == "https://media.example.com/channel/chan42",
          cat["source"])
    check("v1 epoch keys converted",
          list(cat["episodes"][0]["title"]) == ["2023-11-14T22:13:20"],
          json.dumps(cat["episodes"][0]["title"]))
    stamps = {k for e in cat["episodes"] for k in e["removed"]}
    check("one migration timestamp for every removed field", len(stamps) == 1,
          str(stamps))
    check("annotation applied after migration",
          [(n["title"], n["timecode"]) for n in cat["episodes"][0]["annotations"]]
          == [("Legacy", 120)], json.dumps(cat["episodes"][0]["annotations"]))
    check("untouched entry gains empty annotations",
          cat["episodes"][1]["annotations"] == [])
    check("local-only keys preserved", cat.get("notes") == "local")
    check("backup holds the original v1 catalog",
          open("one/catalog.bak", "rb").read() == before)

    page = session.get(base + "/catalog/one/episodes/o1").text
    check("migrated entry page shows annotation", "Legacy" in page)
    res = session.get(base + "/catalog/one/entries/o1", allow_redirects=False)
    check("retired v1 route retired", res.status_code in (301, 302, 303, 404),
          str(res.status_code))
    res = session.get(base + "/catalog/one/entries/o1")
    check("retired v1 route resolves cleanly", res.status_code in (200, 404),
          str(res.status_code))

    ident = catalog("one")["episodes"][0]["annotations"][0]["id"]
    res = send("PATCH", url("one", "episodes", "o1"),
               {"id": ident, "body": "after migration"})
    check("update after auto-migration works", res.status_code in (302, 303),
          str(res.status_code))
    check("update after auto-migration stored",
          catalog("one")["episodes"][0]["annotations"][0]["body"]
          == "after migration")
    res = send("PATCH", url("one", "entries", "o1"), {"id": ident, "title": "x"})
    check("v1 route no longer annotates a migrated vault",
          res.status_code == 404, str(res.status_code))

    # pristine v1 patch/delete: nothing to address yet
    write_catalog("one2", {"version": 1, "source_id": "c", "entries": [v1_entry("q")]})
    before = open("one2/catalog.json", "rb").read()
    res = send("PATCH", url("one2", "entries", "q"), {"id": "a1", "title": "x"})
    check("patch on pristine v1 is 404", res.status_code == 404, str(res.status_code))
    check("failed patch leaves v1 catalog untouched",
          open("one2/catalog.json", "rb").read() == before
          and not os.path.exists("one2/catalog.bak"))

    # ---- version 2 auto-migration ------------------------------------------- #
    v2 = {"version": 2, "source": "https://e.example/f.json",
          "episodes": [v2_entry("t1")], "streams": [v2_entry("t2")], "clips": []}
    write_catalog("two", v2)
    before = open("two/catalog.json", "rb").read()
    res = send("POST", url("two", "streams", "t2"),
               {"title": "Note", "timecode": "10", "body": "b"})
    check("v2 annotation redirects to same category",
          res.headers.get("Location", "").endswith(
              "/catalog/two/streams/t2?timecode=10"),
          res.headers.get("Location", ""))
    cat = catalog("two")
    check("v2 vault migrated", cat["version"] == 3)
    check("v2 keeps ISO history keys",
          list(cat["streams"][0]["title"]) == ["2024-01-01T00:00:00"])
    check("v2 entries gain removed=false",
          cat["episodes"][0]["removed"] == cat["streams"][0]["removed"]
          and list(cat["streams"][0]["removed"].values()) == [False],
          json.dumps(cat["streams"][0]["removed"]))
    check("v2 annotation applied",
          cat["streams"][0]["annotations"][0]["title"] == "Note")
    check("v2 backup is the original catalog",
          open("two/catalog.bak", "rb").read() == before)

    # ---- migration failure --------------------------------------------------- #
    broken = {"version": 1, "source_id": "c",
              "entries": [v1_entry("g1"),
                          {"id": "g2", "published": "2024-01-01T00:00:00",
                           "width": 1, "height": 2, "title": {"nope": "x"},
                           "description": {"1700000000": "d"},
                           "views": {"1700000000": 1},
                           "likes": {"1700000000": 0},
                           "preview": {"1700000000": "p"}}]}
    write_catalog("bad", broken)
    before = open("bad/catalog.json", "rb").read()
    res = send("POST", url("bad", "entries", "g1"),
               {"title": "x", "timecode": "1"})
    check("migration failure is 500", res.status_code == 500, str(res.status_code))
    check("migration failure explains itself", res.text.strip() != ""
          and "Traceback" not in res.text, res.text[:200])
    check("migration failure leaves catalog unchanged",
          open("bad/catalog.json", "rb").read() == before
          and not os.path.exists("bad/catalog.bak"))

    # ---- seeking ------------------------------------------------------------- #
    os.makedirs("v3v/media", exist_ok=True)
    with open("v3v/media/e1.mp4", "w") as fh:
        fh.write("x")
    page = session.get(url("v3v", "episodes", "e1") + "?timecode=90").text
    check("detail page seeks to the query timecode",
          "#t=90" in page and "currentTime" in page, page[-1500:])
    page = session.get(url("v3v", "episodes", "e1") + "?timecode=bogus").text
    check("unparsable seek query still renders the page",
          "Annotations" in page and "#t=" not in page)

    # ---- unrelated routes unaffected ----------------------------------------- #
    res = session.post(base + "/", data={"catalog": "v3v"}, allow_redirects=False)
    check("landing form still works",
          res.status_code == 303 and res.headers.get("Location") == "/catalog/v3v",
          str(res.status_code) + res.headers.get("Location", ""))
    res = session.post(base + "/nowhere", data="{}", allow_redirects=False)
    check("annotation method on an unknown path is 404", res.status_code == 404,
          str(res.status_code))
    res = send("POST", base + "/catalog/nosuch/episodes/e1",
               {"title": "x", "timecode": "1"})
    check("annotation on unknown vault is 404", res.status_code == 404,
          str(res.status_code))

    # ---- concurrent writes stay consistent ------------------------------------ #
    import threading
    write_catalog("many", {"version": 3, "source": "https://e.example/f.json",
                           "episodes": [v3_entry("m1")], "streams": [],
                           "clips": []})
    errors = []

    def spam(index):
        try:
            res = send("POST", url("many", "episodes", "m1"),
                       {"title": "n%d" % index, "timecode": str(index)})
            if res.status_code not in (302, 303):
                errors.append(res.status_code)
        except Exception as exc:  # pragma: no cover - diagnostic only
            errors.append(str(exc))

    threads = [threading.Thread(target=spam, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    notes = catalog("many")["episodes"][0]["annotations"]
    check("every concurrent create landed", not errors and len(notes) == 8,
          str(errors) + json.dumps(notes))
    check("concurrent ids stay unique",
          len({n["id"] for n in notes}) == 8, json.dumps(notes))

    proc.terminate()
    proc.wait(timeout=10)
    os.chdir(ROOT)
    shutil.rmtree(workdir, ignore_errors=True)

    print("\n%s" % ("ALL CHECKS PASSED" if not FAILED
                    else "FAILURES: %s" % ", ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
