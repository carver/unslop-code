"""Spec sections: Performance & Memory, plus error handling and cleanup."""

import csv
import io
import os
import random

from conftest import col, header, lines, read_text, run, run_ok, write, write_schema


def make_big_csv(path, n_rows, cols=("id", "payload"), seed=0):
    """Write n_rows of shuffled ids with a fat payload column."""
    rnd = random.Random(seed)
    ids = list(range(n_rows))
    rnd.shuffle(ids)
    payload = "x" * 200
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for i in ids:
            fh.write(f"{i},{payload}\n")
    return str(path), ids


# --- Spec: "Tool must handle inputs exceeding --memory-limit-mb constraint" ---
# Context: Sorting. A dataset far bigger than the stated limit still sorts fully.
def test_sorts_dataset_larger_than_memory_limit(ws):
    a, _ = make_big_csv(ws / "a.csv", 20000, seed=1)
    b, _ = make_big_csv(ws / "b.csv", 20000, seed=2)
    out = ws / "o.csv"
    run_ok("--output", str(out), "--key", "id", "--memory-limit-mb", "1", a, b)
    text = read_text(out)
    ids = [int(v) for v in col(text, "id")]
    assert len(ids) == 40000
    assert ids == sorted(ids)


# --- Spec: "Tool must work under small --memory-limit-mb (e.g., 64MB)" ---
# Context: Performance & Memory; the 64MB example value works.
def test_works_under_64mb_limit(ws):
    a, _ = make_big_csv(ws / "a.csv", 5000, seed=3)
    res = run_ok("--output", "-", "--key", "id", "--memory-limit-mb", "64", a)
    ids = [int(v) for v in col(res.stdout, "id")]
    assert ids == sorted(ids)


# --- Spec: "Tool must handle inputs exceeding --memory-limit-mb" with --desc ---
# Context: Sorting; the external path honours sort direction.
def test_external_sort_respects_desc(ws):
    a, _ = make_big_csv(ws / "a.csv", 8000, seed=4)
    res = run_ok("--output", "-", "--key", "id", "--desc", "--memory-limit-mb", "1", a)
    ids = [int(v) for v in col(res.stdout, "id")]
    assert ids == sorted(ids, reverse=True)


# --- Spec: "Sort must be stable" under the external (spilling) path ---
# Context: Sorting + Performance & Memory.
def test_external_sort_is_stable(ws):
    n = 6000
    with open(ws / "a.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write("k,seq\n")
        for i in range(n):
            fh.write(f"{i % 5},{i}\n")
    res = run_ok("--output", "-", "--key", "k", "--memory-limit-mb", "1",
                 str(ws / "a.csv"))
    rows = list(csv.reader(io.StringIO(res.stdout)))[1:]
    for group in range(5):
        seqs = [int(s) for k, s in rows if k == str(group)]
        assert seqs == sorted(seqs)


# --- Spec: "All intermediate resources must be cleaned up on exit" ---
# Context: Performance & Memory; --temp-dir is empty again after a spilling run.
def test_temp_dir_is_emptied_after_success(ws):
    tmp = ws / "scratch"
    tmp.mkdir()
    a, _ = make_big_csv(ws / "a.csv", 20000, seed=5)
    run_ok("--output", str(ws / "o.csv"), "--key", "id",
           "--memory-limit-mb", "1", "--temp-dir", str(tmp), a)
    assert os.listdir(tmp) == []


# --- Spec: "All intermediate resources must be cleaned up on exit" ---
# Context: Performance & Memory; also true when the run fails.
def test_temp_dir_is_emptied_after_failure(ws):
    tmp = ws / "scratch"
    tmp.mkdir()
    a = write(ws / "a.csv", "id,v\n1,x\n2,bad\n")
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run("--output", str(ws / "o.csv"), "--key", "id", "--schema", s,
              "--on-type-error", "fail", "--temp-dir", str(tmp),
              "--memory-limit-mb", "1", a)
    assert not res.ok
    assert os.listdir(tmp) == []


# --- Spec: "--temp-dir <PATH>" is where intermediates live ---
# Context: Performance & Memory; a read-only/nonexistent temp dir surfaces an error
# rather than silently writing elsewhere.
def test_missing_temp_dir_is_error(ws):
    a, _ = make_big_csv(ws / "a.csv", 20000, seed=6)
    res = run("--output", "-", "--key", "id", "--memory-limit-mb", "1",
              "--temp-dir", str(ws / "does" / "not" / "exist"), a)
    assert not res.ok


# --- Spec: input files are the positional arguments ---
# Context: Usage; a nonexistent input is an error.
def test_nonexistent_input_is_error(ws):
    res = run("--output", "-", "--key", "id", str(ws / "nope.csv"))
    assert not res.ok
    assert res.stderr.strip() != ""


# --- Spec: "<INPUT1.csv> [<INPUT2.csv> ...]" — at least one input ---
# Context: Usage.
def test_no_inputs_is_error(ws):
    res = run("--output", "-", "--key", "id")
    assert not res.ok


# --- Spec: "otherwise write to file path" — an unwritable path is an error ---
# Context: Output.
def test_unwritable_output_path_is_error(ws):
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--output", str(ws / "no" / "such" / "dir" / "o.csv"), "--key", "id", a)
    assert not res.ok


# --- Spec: "all rows from inputs" — nothing is dropped at scale ---
# Context: Output + Performance & Memory.
def test_no_rows_lost_across_spill_boundary(ws):
    a, ids_a = make_big_csv(ws / "a.csv", 15000, seed=7)
    b, ids_b = make_big_csv(ws / "b.csv", 15000, seed=8)
    res = run_ok("--output", "-", "--key", "id", "--memory-limit-mb", "1", a, b)
    got = sorted(int(v) for v in col(res.stdout, "id"))
    assert got == sorted(ids_a + ids_b)


# --- Spec: "Tool must handle inputs exceeding --memory-limit-mb constraint" ---
# Context: Sorting; a string key column also spills correctly.
def test_external_sort_string_key(ws):
    rnd = random.Random(9)
    words = [f"w{rnd.randrange(10**6):06d}" for _ in range(12000)]
    with open(ws / "a.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write("w,pad\n")
        for x in words:
            fh.write(f"{x},{'p' * 100}\n")
    res = run_ok("--output", "-", "--key", "w", "--memory-limit-mb", "1",
                 str(ws / "a.csv"))
    got = col(res.stdout, "w")
    assert got == sorted(words)
