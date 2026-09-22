#!/usr/bin/env python3
"""Self-contained checks for merge_files.py.  Run: python tests.py

Covers checkpoint 1 (CSV merging), checkpoint 2 (CSV/TSV/JSONL/Parquet with
schema reconciliation), checkpoint 3 (partitioned / sharded output) and
checkpoint 4 (nested struct/array/map types, type aliases and field paths).
The Parquet fixtures below were produced by pyarrow and are embedded
gzip+base64 so the suite has no third-party dependencies.
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
    "nested_full": (
        "H4sIAOgtlGoC/6VXy28bRRifGW82TmJBUnVXa2RBhNKVEWk2dus0RanE2F7ngVNsg+PGQkIbe+skjR3Ha8fYfwJCPaAqBxRxqjih"
        "Hjhx5syBA+cKceqRM0KI+WZ3vetHUlWsktmZ7/H7fa8dJTlaiEmCtCqtZCVRQjcQUgSMZvAGQfYTcN4Skm5KyjIzmme/YkQJuhol"
        "iJ2djKITpAsLbJldAkARk8ASYnwRaTHLXsD31l1wMeo9eB2cHowSrZFogImVADNxoMAyMItwgDCMoBTKSoRDCaF3J0UqgNReZSHq"
        "O/nhRIQJRMZc3chmlyCFPiwGA12UlpYZmxOVEMV9BRscYp5XK0A40HtOXGNAMVjiDOh9SR0Giis4xoEWPraBBFiryEFSpIiLFFoG"
        "AyvG10lYxIorxLoObV666dYrGPF1dwjJ3113J5PoBOk40xfIKaUsveMyzUWnmapy2mm0Wz23lr4OTzsqxd346ioit98CmlSNjgVr"
        "1ZwASzqWQqrmONjbdjHC/9xIIEW0Kodm3ZCCDP4WUchRFSWIInQssyWJSAoxmdAw6uYtlI1ArQgTBIyaCVZTzZb52GJZkuwy0yUE"
        "ZeaJ2fvy3DjpmJIAzkgJMInrC2BTXOtIAOOobdYBQ8xu2BjCyZHVlggop80Ts2422jYYI7aedFwwiDZw1u5xEKPdbv2fQGQxHAlf"
        "qijCypJA4nwYCiERWZRfYvkPrBbU4Jt99OFlaBPLgi3z7LXxgRhWWQMQApKQTRLlZebl5VxPsXyB1edEfYVHv/wxPDkUFsNrBAkO"
        "JPFDQoM44gWWv8fqDwH1X3L9VTAp3jVCyHDAWxzdbrtXYagsYwvKX2P5W6z+JqiXgv+OGI9dCKsiCWeIF/61BHarOMU3WH6G1T+n"
        "1BdT/tvjKoo9yGCUwx45PmbugMFgcfxnWL7E6t+i+svIjTLOEBxnEK5hYKPKGX7F8u9YfRpUX06/2U0z3iKXf7RN6/b3MNYhUX6O"
        "5R+x+mpG/WnmqptnPNEISxT5Z+0qmkGfRDYH8ndYvZhTX84O30WT64jYMNhllF/MyaIalP+aQ+GIEqKFwqelj+w7Svk5qMHTo2lK"
        "aZ7azyeUdmmyRjOU1miqxmXJJKW7sElRus0F3ttxTd1l5nSf6pRmuVCHxcjd0bQu2xT0Ipy3Bva2a4afQZU8rG4VehWw3Tm+r2nr"
        "Ne1c00CbLvAgah7f9mBn+1fgfHLQKPSM0l6f7oK/pmuPuX8yWeBG+56/51qtZ6xqCfjTXbA3c/fseGkx7+HnPS/QbbZPzDwtQny6"
        "a5/vvi6/ZnVzr83z09MfsvzWnfySV+SnD/Pb/vy4Bf73LdefHg5I/PmleWUeFRI00wc+ruaR7Rw7Zz2je1Ldc4VWJ/vGnSLtQn73"
        "XH/9Ic8v5bPvUoc2PVKvZKwS3+vxY+5z5q913Xj1Qt5tmhOv7sUPqq1kr1wq93klcsxz7Vhz4n+46QzhgL82VGSa5P3Z61S3dprl"
        "R7u0CP6rfW0439pIvrw/8f3SV7Ey5+d8eQgm5cxX2gnWc3rdfKQs+LTOgJ/Px/Y19plGOZ/aB3su+4y3r+ic3fmtjPSXh3JQz7TL"
        "efect/VJzrMNI8/qsTtQUqdXhxPxeKpGKc+Lmub+FSd/L3L7efAAKYtNo3XWMdu3K83mbaPVOu0unpst6+i0sRhPrKyuxMKX7A+B"
        "q36QNoNQjv278B9D6pBsMwwAAA=="
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

    partition_tests(d)
    nested_tests(os.path.join(d, "cp4"))


def tree(root):
    """Every file under *root*, as {relative posix path: contents}."""
    found = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            with open(path, encoding="utf-8", newline="") as fh:
                found[rel] = fh.read()
    return found


def partition_tests(d):
    write(d, "p.csv", "id,ts,country,dt,note\n"
                      "3,2024-01-01T00:00:03Z,US,2024-01-01,c\n"
                      "1,2024-01-01T00:00:01Z,DE,2024-01-02,a\n"
                      "2,2024-01-01T00:00:02Z,US,2024-01-01,b\n"
                      "4,2024-01-01T00:00:04Z,,2024-01-02,d\n"
                      "5,2024-01-01T00:00:05Z,a b/\u00d1,2024-01-03,e\n")
    hdr = "country,dt,id,note,ts\n"

    out = os.path.join(d, "hive")
    rc, _, _ = run(["--output", out, "--key", "ts,id",
                    "--partition-by", "country,dt", "p.csv"], d)
    check("hive layout: encoding, _null, per-partition sort", (rc, tree(out)), (0, {
        "country=US/dt=2024-01-01/part-00000.csv": hdr
            + "US,2024-01-01,2,b,2024-01-01T00:00:02Z\n"
            + "US,2024-01-01,3,c,2024-01-01T00:00:03Z\n",
        "country=DE/dt=2024-01-02/part-00000.csv": hdr
            + "DE,2024-01-02,1,a,2024-01-01T00:00:01Z\n",
        "country=_null/dt=2024-01-02/part-00000.csv": hdr
            + ",2024-01-02,4,d,2024-01-01T00:00:04Z\n",
        "country=a%20b%2F%C3%91/dt=2024-01-03/part-00000.csv": hdr
            + "a b/\u00d1,2024-01-03,5,e,2024-01-01T00:00:05Z\n",
    }))

    out = os.path.join(d, "hive_desc")
    rc, _, _ = run(["--output", out, "--key", "ts,id", "--desc",
                    "--partition-by", "country", "p.csv"], d)
    check("descending inside each partition",
          (rc, tree(out)["country=US/part-00000.csv"]),
          (0, hdr + "US,2024-01-01,3,c,2024-01-01T00:00:03Z\n"
                  + "US,2024-01-01,2,b,2024-01-01T00:00:02Z\n"))

    write(d, "n.csv", "k,v\n" + "".join("%d,%d\n" % (i, i) for i in range(1, 11)))

    out = os.path.join(d, "rows")
    rc, _, _ = run(["--output", out, "--key", "k", "--max-rows-per-file", "3",
                    "n.csv"], d)
    got = tree(out)
    check("max-rows-per-file cuts at 3 data rows",
          (rc, sorted(got), got.get("part-00000.csv"), got.get("part-00003.csv")),
          (0, ["part-0000%d.csv" % i for i in range(4)],
           "k,v\n1,1\n2,2\n3,3\n", "k,v\n10,10\n"))

    out = os.path.join(d, "bytes")
    rc, _, _ = run(["--output", out, "--key", "k", "--max-bytes-per-file", "20",
                    "n.csv"], d)
    got = tree(out)
    sizes = [len(got[k].encode("utf-8")) for k in sorted(got)]
    check("max-bytes-per-file counts header and newlines",
          (rc, sizes, got["part-00000.csv"]),
          (0, [20, 20, 14], "k,v\n1,1\n2,2\n3,3\n4,4\n"))

    out = os.path.join(d, "both")
    rc, _, _ = run(["--output", out, "--key", "k", "--max-rows-per-file", "5",
                    "--max-bytes-per-file", "20", "n.csv"], d)
    check("both limits cut at the earliest boundary",
          (rc, [len(v.encode("utf-8")) for v in
                (lambda g: [g[k] for k in sorted(g)])(tree(out))]),
          (0, [20, 20, 14]))

    write(d, "wide.csv", "k,v\n1,%s\n2,b\n" % ("x" * 50))
    out = os.path.join(d, "wide")
    rc, _, _ = run(["--output", out, "--key", "k", "--max-bytes-per-file", "10",
                    "wide.csv"], d)
    got = tree(out)
    check("a row larger than the limit gets a file of its own",
          (rc, sorted(got), got.get("part-00001.csv")),
          (0, ["part-00000.csv", "part-00001.csv"], "k,v\n2,b\n"))

    out = os.path.join(d, "shard_hive")
    rc, _, _ = run(["--output", out, "--key", "k", "--partition-by", "v",
                    "--max-rows-per-file", "1", "dup1.csv"], d)
    check("sharding applies per partition directory", (rc, tree(out)), (0, {
        "v=a/part-00000.csv": "k,v\n5,a\n",
        "v=b/part-00000.csv": "k,v\n5,b\n",
    }))

    rc, _, err = run(["--output", "-", "--key", "k", "--max-rows-per-file", "2",
                      "n.csv"], d)
    check("--output - rejected when partitioning", (rc, "directory" in err), (2, True))

    out = os.path.join(d, "nokey")
    rc, _, err = run(["--output", out, "--key", "k", "--partition-by", "nope",
                      "n.csv"], d)
    check("partition column absent from schema -> exit 3",
          (rc, os.path.exists(out), "partition column" in err), (3, False, True))

    write(d, "castp.json", json.dumps({"columns": [{"name": "k", "type": "int"},
                                                   {"name": "v", "type": "int"}]}))
    write(d, "badp.csv", "k,v\n1,1\n2,nope\n")
    out = os.path.join(d, "failed")
    rc, _, _ = run(["--output", out, "--key", "k", "--partition-by", "v",
                    "--schema", "castp.json", "--on-type-error", "fail",
                    "badp.csv"], d)
    leftovers = [f for f in os.listdir(d) if f.startswith(".merge_files_")]
    check("failed partitioned run leaves no tree and no temp dirs",
          (rc, os.path.exists(out), leftovers), (4, False, []))

    out = os.path.join(d, "replaced")
    os.makedirs(out, exist_ok=True)
    write(out, "stale.csv", "junk\n")
    rc, _, _ = run(["--output", out, "--key", "k", "--partition-by", "v",
                    "dup1.csv"], d)
    check("an existing output directory is replaced, not merged into",
          (rc, sorted(tree(out))), (0, ["v=a/part-00000.csv", "v=b/part-00000.csv"]))

    write(d, "none.csv", "k,v\n")
    out = os.path.join(d, "empty_shard")
    rc, _, _ = run(["--output", out, "--key", "k", "--max-rows-per-file", "5",
                    "none.csv"], d)
    check("no rows: header-only first shard", (rc, tree(out)),
          (0, {"part-00000.csv": "k,v\n"}))
    out = os.path.join(d, "empty_hive")
    rc, _, _ = run(["--output", out, "--key", "k", "--partition-by", "v",
                    "none.csv"], d)
    check("no rows: no partition directories",
          (rc, os.path.isdir(out), tree(out)), (0, True, {}))

    # large, partitioned, external sort -- and identical whatever the budget
    rows = ["k,v,g"] + ["%d,%d,g%d" % ((i * 7919) % 1000, i, i % 5)
                        for i in range(20000)]
    write(d, "pbig.csv", "\n".join(rows) + "\n")
    seen = []
    for mem in ("1", "256"):
        out = os.path.join(d, "big_%s" % mem)
        rc, _, _ = run(["--output", out, "--key", "k", "--partition-by", "g",
                        "--max-rows-per-file", "1500", "--memory-limit-mb", mem,
                        "pbig.csv"], d)
        seen.append((rc, tree(out)))
    got = seen[0][1]
    names = sorted(got)
    body = [got[n].split("\n")[1:-1] for n in names]
    # rows of one partition, in shard order: sorted on k (column index 1)
    joined = [sum(body[i:i + 3], []) for i in range(0, len(body), 3)]
    ordered = all(rows == sorted(rows, key=lambda r: int(r.split(",")[1]))
                  and all(r.startswith("g%d," % g) for r in rows)
                  for g, rows in enumerate(joined))
    check("partitioned external sort: shards, order, memory independence", (
        seen[0][0],
        seen[0][1] == seen[1][1],
        names == ["g=g%d/part-%05d.csv" % (g, i)
                  for g in range(5) for i in range(3)],
        [len(b) for b in body] == [1500, 1500, 1000] * 5,
        ordered,
        sum(len(b) for b in body),
    ), (0, True, True, True, True, 20000))


NESTED_SCHEMA = {"columns": [
    {"name": "id", "type": "int"},
    {"name": "user", "type": {"struct": {"fields": [
        {"name": "name", "type": "string"},
        {"name": "age", "type": "int"},
        {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}},
    ]}}},
    {"name": "items", "type": {"array": {"element": {"struct": {"fields": [
        {"name": "sku", "type": "string"},
        {"name": "qty", "type": "int"},
    ]}}}}},
    {"name": "attrs", "type": {"map": {"key": "string", "value": "string"}}},
]}

PQ_NESTED = (
    "id,user,items,attrs\n"
    '1,"{""name"":""amy"",""age"":30,""prefs"":{""a"":""2"",""z"":""1""}}",'
    '"[{""sku"":""s1"",""qty"":3},{""sku"":""s2"",""qty"":null}]",'
    '"{""country"":""us""}"\n'
    '2,"{""name"":""bob"",""age"":null,""prefs"":null}",[],'
    '"{""country"":""de""}"\n'
    "3,,,\n"
)


def nested_tests(d):
    """Checkpoint 4: nested types, aliases and field paths."""
    os.makedirs(d, exist_ok=True)
    write(d, "schema.json", json.dumps(NESTED_SCHEMA))

    # ---- JSON Lines -----------------------------------------------------
    write(d, "events.jsonl",
          '{"id": 2, "user": {"name": "bob", "age": "41", '
          '"prefs": {"z": 1, "a": "x"}}, "items": [{"sku": "s1", "qty": "3"}, '
          '{"sku": "s2"}], "attrs": {"country": "us"}}\n'
          '{"id": 1, "user": {"name": "amy", "age": 30}, "items": [], '
          '"attrs": {"country": "de"}}\n'
          '{"id": 3, "user": null, "items": null, "attrs": {}}\n')
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "schema.json",
                      "events.jsonl"], d)
    check("nested jsonl -> canonical JSON cells", (rc, out), (0,
          "id,user,items,attrs\n"
          '1,"{""name"":""amy"",""age"":30,""prefs"":null}",[],'
          '"{""country"":""de""}"\n'
          '2,"{""name"":""bob"",""age"":41,""prefs"":{""a"":""x"",""z"":""1""}}",'
          '"[{""sku"":""s1"",""qty"":3},{""sku"":""s2"",""qty"":null}]",'
          '"{""country"":""us""}"\n'
          "3,,,{}\n"))

    # struct field order follows the schema, not the input
    write(d, "reorder.json", json.dumps({"columns": [
        {"name": "id", "type": "int"},
        {"name": "user", "type": {"struct": {"fields": [
            {"name": "age", "type": "int"}, {"name": "name", "type": "string"}]}}},
    ]}))
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "reorder.json",
                      "events.jsonl"], d)
    check("struct fields keep the declared order", (rc, out.split("\n")[1]),
          (0, '1,"{""age"":30,""name"":""amy""}"'))

    # ---- field paths ----------------------------------------------------
    rc, out, _ = run(["--output", "-", "--key", "user.name", "--schema",
                      "schema.json", "events.jsonl"], d)
    check("key on a nested leaf sorts by it",
          (rc, [r.split(",")[0] for r in out.strip().split("\n")[1:]]),
          (0, ["3", "1", "2"]))

    rc, out, _ = run(["--output", "-", "--key", "items.0.qty,id", "--schema",
                      "schema.json", "events.jsonl"], d)
    check("array index path; out of range / null is a null fragment",
          (rc, [r.split(",")[0] for r in out.strip().split("\n")[1:]]),
          (0, ["1", "3", "2"]))

    rc, out, _ = run(["--output", "-", "--key", 'attrs["country"],id',
                      "--schema", "schema.json", "events.jsonl"], d)
    check("bracketed map lookup as a key",
          (rc, [r.split(",")[0] for r in out.strip().split("\n")[1:]]),
          (0, ["3", "1", "2"]))

    out_dir = os.path.join(d, "parts")
    rc, _, _ = run(["--output", out_dir, "--key", "id", "--partition-by",
                    'attrs[country]', "--schema", "schema.json",
                    "events.jsonl"], d)
    check("partition by a map value", (rc, sorted(tree(out_dir))),
          (0, ["attrs%5Bcountry%5D=_null/part-00000.csv",
               "attrs%5Bcountry%5D=de/part-00000.csv",
               "attrs%5Bcountry%5D=us/part-00000.csv"]))

    rc, _, err = run(["--output", "-", "--key", "user", "--schema",
                      "schema.json", "events.jsonl"], d)
    check("non-primitive key -> exit 3",
          (rc, 'ERR 3 key column "user" does not resolve to a primitive' in err),
          (3, True))
    rc, _, err = run(["--output", os.path.join(d, "never"), "--key", "id",
                      "--partition-by", "items", "--schema", "schema.json",
                      "events.jsonl"], d)
    check("non-primitive partition -> exit 3",
          (rc, 'ERR 3 partition column "items" does not resolve to a primitive'
           in err), (3, True))
    rc, _, _ = run(["--output", "-", "--key", "user.nope", "--schema",
                    "schema.json", "events.jsonl"], d)
    check("unknown nested path -> exit 3", rc, 3)
    rc, _, _ = run(["--output", "-", "--key", "items.-1.qty", "--schema",
                    "schema.json", "events.jsonl"], d)
    check("negative array index -> exit 3", rc, 3)

    # ---- no schema ------------------------------------------------------
    rc, _, err = run(["--output", "-", "--key", "id", "events.jsonl"], d)
    check("nested jsonl without --schema -> exit 6",
          (rc, "ERR 6 nested structure requires provided --schema" in err),
          (6, True))

    # ---- Parquet --------------------------------------------------------
    parquet_fixture(d, "nested_full", "nested.parquet")
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "schema.json",
                      "nested.parquet"], d)
    check("nested parquet: struct/list/map assembly", (rc, out), (0, PQ_NESTED))
    rc, _, err = run(["--output", "-", "--key", "id", "nested.parquet"], d)
    check("nested parquet without --schema -> exit 6", (rc, "nested" in err),
          (6, True))
    rc, out, _ = run(["--output", "-", "--key", "user.name,id", "--schema",
                      "schema.json", "--memory-limit-mb", "1",
                      "nested.parquet"], d)
    check("parquet nested leaf key",
          (rc, [r.split(",")[0] for r in out.strip().split("\n")[1:]]),
          (0, ["3", "1", "2"]))

    # ---- CSV/TSV cells --------------------------------------------------
    write(d, "cells.tsv", "id\tpayload\ttags\n"
                          '1\t{"b": 2, "a": [1, "x", null]}\t["p","q"]\n'
                          "2\t\t[]\n"
                          "3\tnot json\t[\"r\"]\n")
    write(d, "js.json", json.dumps({"columns": [
        {"name": "id", "type": "int"},
        {"name": "payload", "type": "json"},
        {"name": "tags", "type": "array<string>"}]}))
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "js.json",
                      "cells.tsv"], d)
    check("json type from a TSV cell; invalid JSON coerced to null", (rc, out),
          (0, "id,payload,tags\n"
              '1,"{""a"":[1,""x"",null],""b"":2}","[""p"",""q""]"\n'
              "2,,[]\n"
              '3,,"[""r""]"\n'))
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "js.json",
                      "--on-type-error", "keep-string", "cells.tsv"], d)
    check("keep-string keeps the unparsed cell", (rc, out.split("\n")[3]),
          (0, '3,"""not json""","[""r""]"'))
    rc, _, err = run(["--output", "-", "--key", "id", "--schema", "js.json",
                      "--on-type-error", "fail", "cells.tsv"], d)
    check("--on-type-error=fail on a nested cell -> exit 4",
          (rc, 'ERR 4 cannot cast "not json" to json in field "payload" '
               "(file=cells.tsv line=4)" in err), (4, True))

    # cast failure deep inside a nested value names the full path
    write(d, "bad.jsonl", '{"id": 1, "items": [{"sku": "x", "qty": "nope"}]}\n')
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "schema.json",
                      "bad.jsonl"], d)
    check("nested cast failure -> JSON null inside the structure",
          (rc, out.split("\n")[1]),
          (0, '1,,"[{""sku"":""x"",""qty"":null}]",'))
    rc, _, err = run(["--output", "-", "--key", "id", "--schema", "schema.json",
                      "--on-type-error", "keep-string", "bad.jsonl"], d)
    rc2, _, err2 = run(["--output", "-", "--key", "id", "--schema",
                        "schema.json", "--on-type-error", "fail",
                        "bad.jsonl"], d)
    check("deep cast failure reports the field path",
          (rc2, 'in field "items.0.qty"' in err2), (4, True))

    # a flat declaration facing a nested input is a cast error, not exit 6
    write(d, "flat.json", json.dumps({"columns": [
        {"name": "id", "type": "int"}, {"name": "user", "type": "string"}]}))
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "flat.json",
                      "events.jsonl"], d)
    rc2, out2, _ = run(["--output", "-", "--key", "id", "--schema", "flat.json",
                        "--on-type-error", "keep-string", "events.jsonl"], d)
    rc3, _, _ = run(["--output", "-", "--key", "id", "--schema", "flat.json",
                     "--on-type-error", "fail", "events.jsonl"], d)
    check("flat declaration + nested input follows --on-type-error",
          (rc, out.split("\n")[1], rc2,
           out2.split("\n")[1], rc3),
          (0, "1,", 0, '1,"{""age"":30,""name"":""amy""}"', 4))

    # ---- type aliases ---------------------------------------------------
    write(d, "aliases.json", json.dumps({"aliases": {
        "smallint": "int", "decimal": "float", "uuid": "string",
        "myts": "timestamp", "tinylist": "LIST<SmallInt>"}}))
    write(d, "al.json", json.dumps({"columns": [
        {"name": "id", "type": "SMALLINT"}, {"name": "amt", "type": "Decimal"},
        {"name": "u", "type": "UUID"}, {"name": "t", "type": "myts"},
        {"name": "l", "type": "tinylist"}]}))
    write(d, "al.jsonl", '{"id": "7", "amt": "1.50", "u": "abc", '
                         '"t": "2024-01-02 03:04:05+01:00", "l": [1, "2", 3.0]}\n')
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "al.json",
                      "--type-alias-file", "aliases.json", "al.jsonl"], d)
    check("case-insensitive, transitive aliases", (rc, out),
          (0, "id,amt,u,t,l\n7,1.5,abc,2024-01-02T02:04:05Z,\"[1,2,3]\"\n"))

    write(d, "cyc.json", json.dumps({"aliases": {"a": "b", "b": "c", "c": "a"}}))
    rc, _, err = run(["--output", "-", "--key", "id", "--schema", "al.json",
                      "--type-alias-file", "cyc.json", "al.jsonl"], d)
    check("alias cycle -> exit 2", (rc, "ERR 2 type alias cycle" in err),
          (2, True))
    write(d, "cyc2.json", json.dumps({"aliases": {"string": "text"}}))
    rc, _, _ = run(["--output", "-", "--key", "id", "--schema", "al.json",
                    "--type-alias-file", "cyc2.json", "al.jsonl"], d)
    check("cycle through a built-in alias -> exit 2", rc, 2)
    write(d, "unknown.json", json.dumps({"columns": [
        {"name": "id", "type": "widget"}]}))
    rc, _, err = run(["--output", "-", "--key", "id", "--schema",
                      "unknown.json", "al.jsonl"], d)
    check("unknown type -> exit 3", (rc, "unknown type" in err), (3, True))
    write(d, "dup.json", json.dumps({"columns": [{"name": "s", "type": {
        "struct": {"fields": [{"name": "a", "type": "int"},
                              {"name": "a", "type": "int"}]}}}]}))
    rc, _, err = run(["--output", "-", "--key", "s.a", "--schema", "dup.json",
                      "al.jsonl"], d)
    check("duplicate struct field -> exit 3", (rc, "duplicate field" in err),
          (3, True))

    # ---- canonical encoding details -------------------------------------
    write(d, "uni.jsonl",
          '{"id":1,"user":{"name":"caf\\u00e9 \\u2603","age":5,'
          '"prefs":{"\\u00fc":"a\\"b\\\\c\\u0001d","a":"1"}}}\n')
    rc, out, _ = run(["--output", "-", "--key", "id", "--schema", "schema.json",
                      "uni.jsonl"], d)
    check("UTF-8 output, RFC 8259 escaping, sorted map keys",
          (rc, out.split("\n")[1]),
          (0, '1,"{""name"":""caf\u00e9 \u2603"",""age"":5,""prefs"":'
              '{""a"":""1"",""\u00fc"":""a\\""b\\\\c\\u0001d""}}",,'))

    # nested values survive the external sort unchanged
    variants = []
    for mem in ("1", "128"):
        rc, out, _ = run(["--output", "-", "--key", "user.name,id",
                          "--memory-limit-mb", mem, "--schema", "schema.json",
                          "events.jsonl", "nested.parquet"], d)
        variants.append((rc, out))
    check("nested rows are memory-limit independent",
          (len(set(variants)), variants[0][0]), (1, 0))


if __name__ == "__main__":
    sys.exit(main())
