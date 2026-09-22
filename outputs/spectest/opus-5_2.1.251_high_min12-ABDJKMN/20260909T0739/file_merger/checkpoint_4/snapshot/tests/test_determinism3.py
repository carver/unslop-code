"""The `Determinism Checklist` of the partitioned-output spec."""
import re
import os
from pathlib import Path

from conftest import data_rows, read_text, run, tree, write


def build(tmp_path, name="out", *args):
    a = write(tmp_path, "a.csv",
              "id,c,v\n3,us,x\n1,de,y\n2,us, z \n4,new york,w\n")
    out = Path(tmp_path) / name
    r = run("--output", str(out), "--key", "id", "--partition-by", "c", *args,
            str(a), cwd=tmp_path)
    return r, out


# --- Spec: "Directory layout and file names follow exact rules (Hive-style
#     segments, `_null` for missing, percent-encoding)" ---------------------
def test_layout_is_exact(tmp_path):
    r, out = build(tmp_path)
    assert r.ok, r
    assert tree(out) == [
        "c=de/part-00000.csv",
        "c=new%20york/part-00000.csv",
        "c=us/part-00000.csv",
    ]


# --- Spec: "Directory layout and file names follow exact rules": two runs of
#     the same inputs produce byte-identical trees -------------------------
def test_repeated_runs_are_identical(tmp_path):
    r1, out1 = build(tmp_path, "out1")
    r2, out2 = build(tmp_path, "out2")
    assert r1.ok and r2.ok
    assert tree(out1) == tree(out2)
    for rel in tree(out1):
        assert read_text(out1 / rel) == read_text(out2 / rel)


# --- Spec: "Size/row-based cutting produces deterministically named
#     `part-xxxxx.csv` files with headers" ---------------------------------
def test_cut_files_named_and_headed(tmp_path):
    a = write(tmp_path, "a.csv", "id\n" + "".join(f"{i}\n" for i in range(7)))
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--max-rows-per-file", "3", str(a))
    assert r.ok, r
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    for rel in tree(out):
        assert read_text(out / rel).startswith("id\n")


# --- Spec: "Atomic directory creation/move semantics; temp artifacts cleaned
#     on failure" ----------------------------------------------------------
def test_temp_artifacts_cleaned_on_failure(tmp_path):
    schema = write(tmp_path, "s.json",
                   '{"columns":[{"name":"id","type":"int"},'
                   '{"name":"c","type":"int"}]}')
    a = write(tmp_path, "a.csv", "id,c\n1,us\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--partition-by", "c",
            "--schema", str(schema), "--on-type-error", "fail", str(a))
    assert r.returncode == 4, r
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.csv", "s.json"]


# --- Spec: "Exact exit codes and stderr message shapes as specified" ------
def test_error_message_shape(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = run("--output", "-", "--key", "id", "--partition-by", "id", str(a))
    assert r.returncode == 2, r
    assert re.match(r"^ERR \d ", r.stderr), r.stderr
    assert r.stderr.endswith("\n")
    assert len(r.stderr.strip().splitlines()) == 1


# --- Spec: "Exact exit codes": success is 0 and quiet on stderr -----------
def test_success_is_quiet(tmp_path):
    r, out = build(tmp_path)
    assert r.returncode == 0
    assert r.stderr == ""
