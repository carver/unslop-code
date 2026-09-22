#!/usr/bin/env python3
"""Self-contained checks for merge_files.py.  Run: python tests.py"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

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
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print()
    if FAILED:
        print("%d test(s) failed" % len(FAILED))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
