#!/usr/bin/env python3
"""Self-contained checks for merge_files.py.  Run: python tests.py

Covers checkpoint 1 (CSV merging) and checkpoint 2 (CSV/TSV/JSONL/Parquet with
schema reconciliation).  The Parquet fixtures below were produced by pyarrow and
are embedded gzip+base64 so the suite has no third-party dependencies.
"""
import base64
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile

PARQUET_FIXTURES = {
    "basic": (
        "H4sIAIsklGoC/5VWzW8bRRSfWa/XW8dUbtRZzQoj5RAvoXHjpm2qglKl448kVWyIDU3aqJf1epWkjePUdm1Uif8gB45FQhw4"
        "IE4VB4TgguCOEH9BVSGEOHDhgnJB4b3ZXdvYi9WMkpk37+P3fu/tvCiborrIVHaFLZSYxsg0IVyNkHN0mRJvxfyTEXaR8QzT"
        "WRIctRTXAwvXA19DmQvRXrgAW3xWgT0ypURmicx3vZ/vQRQs9sG+40ZAqDVrKhx1u+uOpryhzKmo51HpHY6b6eMSEqXqyUo0"
        "Nkfitz0qydvjZQSWQDpZwTLGtcPpXpPpCDvPphGKeFCUcoo9kKd0j3GPXXS0ZJKc31pIaYS8nr++8leU/PDGP999ckkL6XJg"
        "ASK+L9Ib147TUxlnqSBlIvNjmZCtNUJ+uhTyMVW0chVtAD90C2vyDJstYdUAm5TvRFrhVw17JypquYp+Bpkbug1B61SJ/DbG"
        "GAwfnZ6eQpfeTI7DoparaEfGg1sIY/PTJcK1trPnNmyWBEVa4cp+nbAECOqh3XDTpJRC8nFQRNtOs+VCISBrttPZ77p+SKed"
        "vlg6nk5lvIlQQEfr6UTpILhF2w374ADfhc4UHqm7TjoOVU1nHuCOHdDNlHlskRSQWiJa0kQeTDF04wU1XlKraulnmywzA8iQ"
        "HPuehGP5Lc20FGgZwSQJP4msUab5khpfUetbxfqDhszTGJrBzWG8uI/ntSjg/YJaLyPWs8jZhmkyc2KmNWIG/ZeZPjDuWX+r"
        "y2NjZoK3BPovQr/BnXZA9HdqfaZZP0fPNlaTiSp+Gup9xi+o8Zxaf8asr2OTp+rVUL0HJZGfU+Mban1+zvpVnzxUochE95HP"
        "+8j4OIcY/xK3nsUnT9X/MzY+njJ0Sze+n4KPwROiWn1v+x1v3PiJmsX1tsgJISrCWxtC9ERuV6wKsSvyu1KXA4cyCnkh7kjF"
        "4BToB1ITETZEUYhNhCpI+yFu69LpZt+//HA+m8Vrcb0olT3ci6K/MFXu0c52GfOVkVqQNy9Zoli4me1msxJyTwbdH/CRaxU3"
        "5+riXm0N8Qs931+I9+XextIxJO8F3R2Jl+KOTFfLenyF2NoEEeEqzUo/Sb91fivWq0+B6RMfPy/Wn/rxxTWv3t2RepF6bu/+"
        "tepRvQE0Nh6C//yjgJ/4UDo54fW923UgBiDvII4HjTwKd4P4XDU0XuavNVY7O5XgXvHsOQnu4fW8714cFBn0exQvj5u9XZFN"
        "KMh4x1MO6Prr1i3CZ47s1uMnbueyc3R02W61mr2Zrttq7zcPZ64uLVxZWDSP4a9+6A+5AQ97E/45+hd1jxSOIQkAAA=="
    ),
    "v2": (
        "H4sIAIsklGoC/5VWzW8bRRSfWe9uto6p3IhZ7Qoj5VAvoXHjpjSooFTp+CNJFRtioyZqlEPX61WSNo6D7dqoEv9Bjr0gceCI"
        "KoQ4VAhucO+BP6BCPVScOJRbLii8N7tjO/4SGdmzb97H7/3e23mWN3l5kansBlsoMJ2RGUIsNUIu0WVKgjUVPsEaY7FdZjAF"
        "vnGIITMJy5Bmy5ABpjI3QnvlCmyRaSVylYh0t7rpdjWwuIcHnh8BoVKvqPCoum1/ZMaPlTkVjZYmQgZhU11YQjSqnq5oU3Mk"
        "ejfgEL87pghpltLpChYxrA2yvSOy6RAel0h6iESpRbEB4im54a4NFk3i81sLCZ2Q97K3Vv7RyG/v//vrN9f0cW2WZuASBiDD"
        "YW0/Q5VZLCEzxlK/FwnZWiPk5bVxL1NFF0tFB0DvO53v8iy7WoAoRI2LayIqhK967pqQfmQ0WSo6m2Su7ySQDapE3gzxBcPX"
        "Z2dn0KIP4mP4oslS0Qn59k7n+NrfLhFLb3r7fs1lcVAkFUs5qBIWA0E9cmt+khQSSD0KCq3p1Rs+YQRk3fVaB20/DGk1k+8W"
        "TmYSqWAcFNDRajJWOJQnrVlzDw8Ju4w0rUjV95JRYDqT2sUdSzfshH3ikASQWiJ63EYeTDEN8zU1/6RO2TEuNlF2CjvBFKAL"
        "TVHI8oe67SjQMYJJYmESUaNI85yaP1LnZ8X5i44YpCE007L78aIhXtAiyfsVdV5FnGeRi43RZObEZrot2y8SPTQfOm/V5aEB"
        "s8EZLscgQLe/rabk+YY63+nOH9rFhmkyTyVMQ4O3+D01f6DO31POi6nJw/T/UIP7JJB/ouYL4H/JeW1MHqaRyMQIkS+HyHg3"
        "+xi/jDrPopPHaTxj8/m0aTiG+cs0vAwrxsvlz7c/DabNOlXTuD7hGc55iQdrg/MOz+zxVc73eHZP6DLgUEQhy/k9oeg9OfqB"
        "VEeEDZ7nfBOhcsJ+hNu6cLrd9S8+mk+n8ZhfzwtlB/c87y5MlXm8s13EfEWkJvNmBUsUc7fT7XRaQO6LoAc9PmKt4ubdXNyv"
        "rCF+rhP6c/6F2JtYOoZkg6D7A/FC3BHpKumAL+dbmyAiXKle6ibpti5sxXr5KTB9EuJn+frTMD6/FtS7N1AvUs/sP/iofFyt"
        "AY2NR+A//1jy418JJ290fZ+1PYgByHuIE0Ajj9x9GZ8pj4wX+Su11dZOSZ5LgT0jwAO8TvDe870iZb8H8bK4udsl0YSciPcC"
        "ZY9uuO7cIdbssdv48onfuu4dH193G416Z7btN5oH9aPZm0sLNxYW7RP40R/5IUtwsTfhj9F/zu+T8R0JAAA="
    ),
    "nested": (
        "H4sIAIsklGoC/5VTzW7TQBDe3axMkCKRVlprLVnIQq1VpLQkSEYBhcO4zU/VVMSRUAXi4rqWSZumIQnkCXgDTohH4FE4cuTA"
        "I/AIzHjjNBK9MIfZnflmv/l2vB7AsKGk8tROHxe2zVi1xZkxsVoVU9vKriFeVZayXF0uEF0uam22d0d2awvdfY8AyXlJIMVD"
        "9aiPLNTpQZPqYnLn5BJshEJqCJtGz9geTzSPc5pqi2hKgrxVEqUdpqTzLmDamifv0+tYSUzsCi1GFywQWi7ibK6EsvotPBBI"
        "Lcej+UIJpipYdC8dp9fpZLHL+i6pl47r1HzmImXArKpDLErY0v7B7Z/c7/nl/7u1Q9Ni1I3hXQRrPbYcn0kEqUnFNGnmGnNd"
        "hR7sadlfuP2N+1+F/4tvjuAfThs5pXA6NBAS8xsF+2X7j2COqyswHL46e2Fmo7+LJ2TPM0CLwNgJwBLCDDoAGRzmEIQhwClt"
        "DgGO88TtCmYbLtfxySWSNnHTPu3AGmpD0SWM1vFFtzNJcvjoDUlpDNBRHL3Oi3qwKW3F3x3X357Vi7i9wiPiRX1dgASObkFj"
        "0fGdfJDlfFfmEks63zNJQ79R+ZJpbxrPPnxMF/vJdLofz2Y3S+9TOpuPbibe0+CgftBwavhu6Ol8xu8/wJ/oL9Gq5UNJAwAA"
    ),
    "required": (
        "H4sIAIsklGoC/5VSzU7CQBCeFtL0wAFMlrRJQzhIw6EgmECMwcMUQYioQEw8EySIf2CrgoTH8Lk8ePQZfAhnukUa4sWv7c5k"
        "duabr7PbxX5ZxEVJlDpCE7ADoICEGtpYaAUIXegOZSXp0yxDX+8Y+romDfk/oqkU08V2gRplRCbaaMHLGy/Lbf4q5JWloSwi"
        "1WatAobmD29GDwMRp0AODHVyDSJBjuLnoGOxCM20TMcGiwoqoCVNzhEUTn8q9NqXtv4/8aZDwkGoPIKk4LkweSIkV/yAe5Ve"
        "2e+q/aVEhW9X1kgbPdzsQ01rtk4GTMtIYL9/cXUo/8z4VvYY1TESeihxijhHd4xNxDHWgy10XcQzduqI7SCwsShd6QXr+S2R"
        "HrDXbATBgKSBv2DXXYb5jbB1D90e8xOGeLzZDNEOkloYlYosEfHk/k6KmHN9SwalnEjmERjZ2cB7ehk9F4azWWHgedN59nXk"
        "+ZPpY3a/UiwVy6ZD58pHG6Phd+nG/gAuP0XjtgIAAA=="
    ),
}


def parquet_fixture(d, key, name):
    path = os.path.join(d, name)
    with open(path, "wb") as fh:
        fh.write(gzip.decompress(base64.b64decode(PARQUET_FIXTURES[key])))
    return path


def gzip_file(path, dest=None):
    dest = dest or (path + ".gz")
    with open(path, "rb") as src, gzip.open(dest, "wb") as out:
        shutil.copyfileobj(src, out)
    return dest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "merge_files.py")
FAILED = []


def run(args, cwd):
    p = subprocess.run([sys.executable, SCRIPT] + args, cwd=cwd,
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def check(name, got, want):
    if got != want:
        FAILED.append(name)
        print("FAIL %s\n  got:  %r\n  want: %r" % (name, got, want))
    else:
        print("ok   %s" % name)


def write(d, name, text):
    path = os.path.join(d, name)
    with open(path, "w", newline="") as fh:
        fh.write(text)
    return path


def main():
    d = tempfile.mkdtemp(prefix="mf_tests_")
    try:
        write(d, "a.csv", 'id,ts,amount,note\n'
                          '3,2024-07-01T12:00:00Z,10.5,hello\n'
                          '1,2024-07-01T08:00:00+02:00,3.25,"a, b"\n'
                          '2,,7,"say ""hi"""\n')
        write(d, "b.csv", 'id,note,extra,is_active\n'
                          '5,world,zzz,true\n'
                          '4,,yyy,0\n')
        write(d, "schema.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "ts", "type": "timestamp"},
            {"name": "amount", "type": "float"},
            {"name": "note", "type": "string"},
            {"name": "is_active", "type": "bool"}]}))

        rc, out, _ = run(["--output", "-", "--key", "id", "a.csv", "b.csv"], d)
        check("infer/lexicographic order + sort by id", (rc, out), (0,
            "amount,extra,id,is_active,note,ts\n"
            '3.25,,1,,"a, b",2024-07-01T06:00:00Z\n'
            '7.0,,2,,"say ""hi""",\n'
            "10.5,,3,,hello,2024-07-01T12:00:00Z\n"
            ",yyy,4,false,,\n"
            ",zzz,5,true,world,\n"))

        rc, out, _ = run(["--output", "-", "--key", "ts,id", "--desc",
                          "--schema", "schema.json", "--on-type-error", "coerce-null",
                          "--memory-limit-mb", "128", "a.csv", "b.csv"], d)
        check("schema order, composite desc, nulls last", (rc, out), (0,
            "id,ts,amount,note,is_active\n"
            "3,2024-07-01T12:00:00Z,10.5,hello,\n"
            '1,2024-07-01T06:00:00Z,3.25,"a, b",\n'
            "5,,,world,true\n"
            "4,,,,false\n"
            '2,,7.0,"say ""hi""",\n'))

        rc, out, _ = run(["--output", "-", "--key", "ts,id", "--schema", "schema.json",
                          "--csv-null-literal", "NULL", "a.csv", "b.csv"], d)
        check("null literal + nulls first ascending", (rc, out), (0,
            "id,ts,amount,note,is_active\n"
            '2,NULL,7.0,"say ""hi""",NULL\n'
            "4,NULL,NULL,NULL,false\n"
            "5,NULL,NULL,world,true\n"
            '1,2024-07-01T06:00:00Z,3.25,"a, b",NULL\n'
            "3,2024-07-01T12:00:00Z,10.5,hello,NULL\n"))

        write(d, "s1.csv", "id,x\n1,1\n2,2\n")
        write(d, "s2.csv", "id,x\n3,1.5\n")
        rc, out, _ = run(["--output", "-", "--key", "id", "--infer", "strict",
                          "s1.csv", "s2.csv"], d)
        check("strict: conflicting types -> string", (rc, out),
              (0, "id,x\n1,1\n2,2\n3,1.5\n"))
        rc, out, _ = run(["--output", "-", "--key", "id", "--infer", "loose",
                          "s1.csv", "s2.csv"], d)
        check("loose: widen to float", (rc, out),
              (0, "id,x\n1,1.0\n2,2.0\n3,1.5\n"))

        write(d, "dt.csv", "d,ts\n2024-07-02,2024-07-01 12:00:00\n"
                           "2024-01-05,2024-03-04T05:06:07.5\n")
        rc, out, _ = run(["--output", "-", "--key", "d", "dt.csv"], d)
        check("date stays date; naive ts -> UTC Z", (rc, out), (0,
            "d,ts\n2024-01-05,2024-03-04T05:06:07.500000Z\n"
            "2024-07-02,2024-07-01T12:00:00Z\n"))

        write(d, "bad.csv", "id,amount\n1,abc\n")
        rc, out, err = run(["--output", "-", "--key", "id", "--schema", "schema.json",
                            "--on-type-error", "fail", "bad.csv"], d)
        check("on-type-error=fail exits non-zero", (rc != 0, "amount" in err), (True, True))
        rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "schema.json",
                          "--on-type-error", "keep-string", "bad.csv"], d)
        check("on-type-error=keep-string", (rc, out), (0, "id,ts,amount,note,is_active\n1,,abc,,\n"))

        rc, out, err = run(["--output", "-", "--key", "nope", "a.csv"], d)
        check("missing key column is an error", rc != 0, True)

        # stability + external sort equivalence
        write(d, "st1.csv", "k,v\n1,a\n1,b\n2,c\n")
        write(d, "st2.csv", "k,v\n1,d\n2,e\n1,f\n")
        rc, asc, _ = run(["--output", "-", "--key", "k", "st1.csv", "st2.csv"], d)
        check("stable ascending", (rc, asc),
              (0, "k,v\n1,a\n1,b\n1,d\n1,f\n2,c\n2,e\n"))
        rc, desc, _ = run(["--output", "-", "--key", "k", "--desc", "st1.csv", "st2.csv"], d)
        check("stable descending", (rc, desc),
              (0, "k,v\n2,c\n2,e\n1,a\n1,b\n1,d\n1,f\n"))

        rows = ["k,v"] + ["%d,%d" % ((i * 7919) % 1000, i) for i in range(20000)]
        write(d, "big.csv", "\n".join(rows) + "\n")
        rc, mem, _ = run(["--output", "-", "--key", "k", "--memory-limit-mb", "512", "big.csv"], d)
        rc2, ext, _ = run(["--output", "-", "--key", "k", "--memory-limit-mb", "1", "big.csv"], d)
        check("external sort == in-memory sort", (rc, rc2, ext == mem), (0, 0, True))

        tmpd = os.path.join(d, "spill")
        rc, _, _ = run(["--output", os.path.join(d, "o.csv"), "--key", "k",
                        "--memory-limit-mb", "1", "--temp-dir", tmpd, "big.csv"], d)
        check("temp files cleaned up", (rc, os.listdir(tmpd)), (0, []))

        checkpoint2(os.path.join(d, "cp2"))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print()
    if FAILED:
        print("%d test(s) failed" % len(FAILED))
        return 1
    print("all tests passed")
    return 0




def checkpoint2(d):
    """CSV/TSV/JSONL/Parquet inputs with schema reconciliation."""
    os.makedirs(d, exist_ok=True)
    basic = parquet_fixture(d, "basic", "metrics.parquet")

    PQ_ONLY = ("active,d,dec,id,name,score,small,ts\n"
               ",,,,,3.25,3,2023-01-02T03:04:05.600000Z\n"
               "false,2020-01-01,-2.5,1,bob,,2,\n"
               "true,2024-07-01,1.25,3,alice,1.5,1,2024-07-01T12:00:00Z\n"
               "true,1999-12-31,100.0,7,dave,4.0,4,2024-12-31T23:59:59Z\n")

    rc, out, err = run(["--output", "-", "--key", "id", "metrics.parquet"], d)
    check("parquet: declared types, nulls, row order", (rc, out), (0, PQ_ONLY))

    parquet_fixture(d, "v2", "v2.parquet")
    rc, out2, _ = run(["--output", "-", "--key", "id", "v2.parquet"], d)
    check("parquet: data page v2 == v1", (rc, out2), (0, PQ_ONLY))

    gzip_file(os.path.join(d, "metrics.parquet"))
    rc, out3, _ = run(["--output", "-", "--key", "id", "metrics.parquet.gz"], d)
    check("parquet: gzip wrapped", (rc, out3), (0, PQ_ONLY))

    rc, out4, _ = run(["--output", "-", "--key", "id", "--input-format", "parquet",
                       "--parquet-row-group-bytes", "64", "metrics.parquet"], d)
    check("parquet: forced format + tiny row-group hint", (rc, out4), (0, PQ_ONLY))

    parquet_fixture(d, "required", "required.parquet")
    rc, out, _ = run(["--output", "-", "--key", "id", "required.parquet"], d)
    check("parquet: required (non-null) columns", (rc, out),
          (0, "id,s\n1,x\n2,y\n3,z\n"))

    parquet_fixture(d, "nested", "nested.parquet")
    rc, _, err = run(["--output", "-", "--key", "id", "nested.parquet"], d)
    check("parquet: nested column -> exit 6", (rc, "nested" in err), (6, True))

    # ---- JSON Lines -----------------------------------------------------
    write(d, "e.jsonl", '{"id": 2, "name": "bob", "score": 4}\n'
                        '   \n'
                        '{"id": 1, "name": null, "score": 2.5}\n'
                        '{"id": 3, "score": null, "extra": true}\n')
    rc, out, _ = run(["--output", "-", "--key", "id", "e.jsonl"], d)
    check("jsonl: typed inference, nulls, blank lines", (rc, out), (0,
          "extra,id,name,score\n"
          ",1,,2.5\n"
          ",2,bob,4.0\n"
          "true,3,,\n"))

    write(d, "n.jsonl", '{"n": 3.0, "big": 1e30, "s": "x"}\n')
    rc, out, _ = run(["--output", "-", "--key", "s", "n.jsonl"], d)
    check("jsonl: integral number -> int, huge -> float", (rc, out),
          (0, "big,n,s\n1e+30,3,x\n"))

    write(d, "bad1.jsonl", '{"a": 1, "b": {"c": 2}}\n')
    rc, _, err = run(["--output", "-", "--key", "a", "bad1.jsonl"], d)
    check("jsonl: nested value -> exit 6", (rc, "nested" in err), (6, True))
    write(d, "bad2.jsonl", '{"a": 1}\n[1, 2]\n')
    rc, _, _ = run(["--output", "-", "--key", "a", "bad2.jsonl"], d)
    check("jsonl: top-level array -> exit 6", rc, 6)
    write(d, "bad3.jsonl", '{"a": 1}\n{oops\n')
    rc, _, _ = run(["--output", "-", "--key", "a", "bad3.jsonl"], d)
    check("jsonl: invalid JSON -> exit 5", rc, 5)

    # ---- TSV ------------------------------------------------------------
    write(d, "t.tsv", 'id\tcreated_at\tnote\textra\n'
                      '1\t2024-01-01T00:00:00Z\thi, "there"\tzz\n'
                      '2\t2024-05-05T05:05:05Z\t\tyy\n')
    rc, out, _ = run(["--output", "-", "--key", "id", "t.tsv"], d)
    check("tsv: tab delimited, quotes are literal", (rc, out), (0,
          "created_at,extra,id,note\n"
          '2024-01-01T00:00:00Z,zz,1,"hi, ""there"""\n'
          "2024-05-05T05:05:05Z,yy,2,\n"))

    write(d, "tab.tsv", "a\tb\n1\t2\t3\n")
    rc, _, err = run(["--output", "-", "--key", "a", "tab.tsv"], d)
    check("tsv: literal tab in field -> exit 5", (rc, "tab" in err), (5, True))
    write(d, "empty.tsv", "")
    rc, _, _ = run(["--output", "-", "--key", "a", "empty.tsv"], d)
    check("tsv: missing header row -> exit 5", rc, 5)

    # ---- format & compression detection ---------------------------------
    write(d, "u.csv", "id,ts,name\n3,2024-07-01T12:00:00Z,carol\n"
                      "1,2024-07-01T08:00:00+02:00,alice\n")
    gzip_file(os.path.join(d, "u.csv"))
    gzip_file(os.path.join(d, "e.jsonl"))
    shutil.copy(os.path.join(d, "e.jsonl"), os.path.join(d, "e2.ndjson"))

    rc, out, _ = run(["--output", "-", "--key", "id", "u.csv.gz"], d)
    check("auto: .csv.gz", (rc, out), (0,
          "id,name,ts\n1,alice,2024-07-01T06:00:00Z\n3,carol,2024-07-01T12:00:00Z\n"))
    rc, a, _ = run(["--output", "-", "--key", "id", "e.jsonl.gz"], d)
    rc2, b, _ = run(["--output", "-", "--key", "id", "e2.ndjson"], d)
    check("auto: .jsonl.gz and .ndjson agree", (rc, rc2, a == b, a.count("\n")),
          (0, 0, True, 4))

    shutil.copy(os.path.join(d, "u.csv"), os.path.join(d, "mystery.dat"))
    rc, _, err = run(["--output", "-", "--key", "id", "mystery.dat"], d)
    check("undetectable format -> exit 2", (rc, "--input-format" in err), (2, True))
    rc, out, _ = run(["--output", "-", "--key", "id", "--input-format", "csv",
                      "mystery.dat"], d)
    check("--input-format overrides detection", (rc, out.splitlines()[0]),
          (0, "id,name,ts"))
    shutil.copy(os.path.join(d, "metrics.parquet"), os.path.join(d, "magic.dat"))
    rc, out, _ = run(["--output", "-", "--key", "id", "magic.dat"], d)
    check("parquet magic bytes win over unknown extension", (rc, out), (0, PQ_ONLY))

    rc, _, err = run(["--output", "-", "--key", "id", "--compression", "none",
                      "u.csv.gz"], d)
    check("--compression=none on gzip input -> exit 5", (rc, "gzip" in err), (5, True))
    rc, _, err = run(["--output", "-", "--key", "id", "--compression", "gzip",
                      "u.csv"], d)
    check("--compression=gzip on plain input -> exit 5", (rc, "gzip" in err), (5, True))
    shutil.copy(os.path.join(d, "u.csv"), os.path.join(d, "fake.csv.gz"))
    rc, _, _ = run(["--output", "-", "--key", "id", "fake.csv.gz"], d)
    check(".gz extension on plain file -> exit 5", rc, 5)
    rc, out, _ = run(["--output", "-", "--key", "id", "--compression", "gzip",
                      "--input-format", "csv", "u.csv.gz"], d)
    check("forced gzip + forced csv", (rc, out.splitlines()[0]), (0, "id,name,ts"))

    # ---- schema reconciliation ------------------------------------------
    write(d, "c1.csv", "id,x\n1,10\n")
    write(d, "c2.csv", "id,x\n2,20\n")
    write(d, "j1.jsonl", '{"id": 3, "x": 1.5}\n')
    strat = {}
    for name in ("authoritative", "consensus", "union"):
        rc, out, _ = run(["--output", "-", "--key", "id", "--schema-strategy", name,
                          "c1.csv", "c2.csv", "j1.jsonl"], d)
        strat[name] = (rc, out)
    check("strategy authoritative: typed source wins", strat["authoritative"],
          (0, "id,x\n1,10.0\n2,20.0\n3,1.5\n"))
    check("strategy consensus: majority int", strat["consensus"],
          (0, "id,x\n1,10\n2,20\n3,\n"))
    check("strategy union: widen to float", strat["union"],
          (0, "id,x\n1,10.0\n2,20.0\n3,1.5\n"))

    rc, out, _ = run(["--output", "-", "--key", "id", "--schema-strategy", "consensus",
                      "c1.csv", "c2.csv", "j1.jsonl", "--on-type-error", "keep-string"], d)
    check("consensus + keep-string keeps the minority value", (rc, out),
          (0, "id,x\n1,10\n2,20\n3,1.5\n"))

    # parquet declares a string column; csv would infer int
    write(d, "s1.csv", "id,name\n9,123\n")
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema-strategy",
                      "authoritative", "s1.csv", "metrics.parquet"], d)
    check("authoritative: parquet outranks csv", (rc, out.splitlines()[0:2]),
          (0, ["active,d,dec,id,name,score,small,ts",
               ",,,,,3.25,3,2023-01-02T03:04:05.600000Z"]))

    # ---- provided schema across formats ---------------------------------
    write(d, "s.json", json.dumps({"columns": [
        {"name": "id", "type": "int"},
        {"name": "ts", "type": "timestamp"},
        {"name": "name", "type": "string"},
        {"name": "missing", "type": "float"}]}))
    rc, out, _ = run(["--output", "-", "--key", "ts,id", "--schema", "s.json",
                      "u.csv", "e.jsonl", "metrics.parquet"], d)
    check("provided schema: order, extras dropped, missing filled", (rc, out), (0,
          "id,ts,name,missing\n"
          "1,,,\n"            # e.jsonl, ts absent
          "1,,bob,\n"         # parquet, ts null
          "2,,bob,\n"
          "3,,,\n"
          ",2023-01-02T03:04:05.600000Z,,\n"
          "1,2024-07-01T06:00:00Z,alice,\n"
          "3,2024-07-01T12:00:00Z,carol,\n"   # u.csv before parquet on a tie
          "3,2024-07-01T12:00:00Z,alice,\n"
          "7,2024-12-31T23:59:59Z,dave,\n"))

    # ---- misc behaviour --------------------------------------------------
    rc, out, _ = run(["--output", "-", "--key", "id", "--csv-null-literal", "NULL",
                      "j1.jsonl", "u.csv"], d)
    check("null literal across formats", (rc, out), (0,
          "id,name,ts,x\n"
          "1,alice,2024-07-01T06:00:00Z,NULL\n"
          "3,NULL,NULL,1.5\n"      # j1.jsonl is listed first
          "3,carol,2024-07-01T12:00:00Z,NULL\n"))

    write(d, "dup1.csv", "k,v\n5,a\n5,b\n")
    write(d, "dup2.jsonl", '{"k": 5, "v": "c"}\n{"k": 5, "v": "a"}\n')
    write(d, "dup3.tsv", "k\tv\n5\td\n")
    rc, out, _ = run(["--output", "-", "--key", "k",
                      "dup1.csv", "dup2.jsonl", "dup3.tsv"], d)
    check("no dedup; stable across mixed sources", (rc, out),
          (0, "k,v\n5,a\n5,b\n5,c\n5,a\n5,d\n"))
    rc, out, _ = run(["--output", "-", "--key", "k", "--desc",
                      "dup1.csv", "dup2.jsonl", "dup3.tsv"], d)
    check("stable descending across mixed sources", (rc, out),
          (0, "k,v\n5,a\n5,b\n5,c\n5,a\n5,d\n"))

    rc, out, err = run(["--output", "-", "--key", "nope", "metrics.parquet"], d)
    check("key column absent from resolved schema -> exit 3", rc, 3)

    write(d, "cast.json", json.dumps({"columns": [{"name": "id", "type": "int"},
                                                  {"name": "name", "type": "int"}]}))
    target = os.path.join(d, "never.csv")
    rc, _, err = run(["--output", target, "--key", "id", "--schema", "cast.json",
                      "--on-type-error", "fail", "metrics.parquet"], d)
    check("on-type-error=fail -> exit 4, no partial output",
          (rc, os.path.exists(target)), (4, False))

    outp = os.path.join(d, "written.csv")
    rc, _, _ = run(["--output", outp, "--key", "id", "--memory-limit-mb", "1",
                    "u.csv", "e.jsonl", "metrics.parquet"], d)
    with open(outp) as fh:
        written = fh.read()
    leftovers = [f for f in os.listdir(d) if f.startswith(".merge_files_")]
    check("writes output file, no temp leftovers", (rc, leftovers), (0, []))

    # determinism across memory limits and parquet batch sizes
    variants = []
    for mem, rgb in (("1", "64"), ("64", "1048576"), ("256", "134217728")):
        rc, out, _ = run(["--output", "-", "--key", "id", "--memory-limit-mb", mem,
                          "--parquet-row-group-bytes", rgb,
                          "u.csv", "e.jsonl", "metrics.parquet"], d)
        variants.append((rc, out))
    check("identical output regardless of memory limit / batch size",
          (len(set(variants)), variants[0][0], variants[0][1] == written),
          (1, 0, True))


if __name__ == "__main__":
    sys.exit(main())
