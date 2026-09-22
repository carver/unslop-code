"""Behaviour under a small memory limit: external sorting and temp cleanup."""

import random

from conftest import column, rows_of


def _big_input(make_csv, name, ids):
    body = "".join("{},{}\n".format(i, "x" * 200) for i in ids)
    return make_csv(name, "id,pad\n" + body)


# Spec: "Tool must handle inputs exceeding `--memory-limit-mb` constraint"
def test_sorts_correctly_when_spilling_to_disk(make_csv, run, workdir):
    ids = list(range(4000))
    random.Random(7).shuffle(ids)
    _big_input(make_csv, "a.csv", ids[:2000])
    _big_input(make_csv, "b.csv", ids[2000:])
    run("--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "a.csv", "b.csv")
    rows = rows_of((workdir / "out.csv").read_text())
    assert [int(v) for v in column(rows, "id")] == sorted(ids)


# Spec: "Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily large inputs"
# Context: spilled runs merge back in descending order too.
def test_spilled_sort_honours_desc(make_csv, run, workdir):
    ids = list(range(3000))
    random.Random(11).shuffle(ids)
    _big_input(make_csv, "a.csv", ids)
    run("--output", "out.csv", "--key", "id", "--desc", "--memory-limit-mb", "1", "a.csv")
    rows = rows_of((workdir / "out.csv").read_text())
    assert [int(v) for v in column(rows, "id")] == sorted(ids, reverse=True)


# Spec: "Sort must be stable with respect to input appearance for equal keys"
# Context: stability must survive the spill/merge path.
def test_stability_survives_spilling(make_csv, run, workdir):
    body = "".join("{},{},{}\n".format(i % 50, i, "x" * 200) for i in range(4000))
    make_csv("a.csv", "id,seq,pad\n" + body)
    run("--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "a.csv")
    rows = rows_of((workdir / "out.csv").read_text())
    seqs = [int(v) for v in column(rows, "seq")]
    for group_start in range(0, len(seqs), 80):
        group = seqs[group_start:group_start + 80]
        assert group == sorted(group)


# Spec: "[--temp-dir <PATH>]" and "All intermediate resources must be cleaned up on exit"
def test_temp_dir_is_used_and_left_clean(make_csv, run, workdir):
    ids = list(range(3000))
    random.Random(3).shuffle(ids)
    _big_input(make_csv, "a.csv", ids)
    scratch = workdir / "scratch"
    scratch.mkdir()
    run("--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "--temp-dir", str(scratch), "a.csv")
    assert list(scratch.iterdir()) == []


# Spec: "If `--output -`: write to stdout" together with spilling
def test_spilled_sort_can_stream_to_stdout(make_csv, run):
    ids = list(range(2000))
    random.Random(5).shuffle(ids)
    _big_input(make_csv, "a.csv", ids)
    proc = run("--output", "-", "--key", "id", "--memory-limit-mb", "1", "a.csv")
    assert [int(v) for v in column(rows_of(proc.stdout), "id")] == sorted(ids)


# Spec: "`fail`: write error to stderr and exit non-zero" with
# "All intermediate resources must be cleaned up on exit"
# Context: a failed run leaves neither a partial output file nor scratch files.
def test_failed_run_leaves_no_output_or_scratch_files(make_csv, make_schema, run, workdir):
    make_csv("a.csv", "id,v\n1,abc\n")
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run(
        "--output", "out.csv", "--key", "id", "--schema", "s.json",
        "--on-type-error", "fail", "a.csv", expect_ok=False,
    )
    assert proc.returncode != 0
    assert sorted(p.name for p in workdir.iterdir()) == ["a.csv", "s.json"]
