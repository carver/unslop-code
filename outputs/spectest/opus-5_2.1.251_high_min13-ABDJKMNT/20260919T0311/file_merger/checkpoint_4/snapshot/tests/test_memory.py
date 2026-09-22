"""Spec section: Performance & Memory."""
import os

from conftest import column, table


def _big_csv(path, rows):
    """Write `rows` rows whose keys are shuffled deterministically."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("id,payload\n")
        for i in range(rows):
            key = (i * 7919) % rows
            fh.write(f"{key},{'x' * 200}\n")


# Phrase: "Tool must handle inputs exceeding --memory-limit-mb constraint"
# Context: a multi-megabyte input under a 1MB budget still sorts correctly.
def test_spills_to_disk_and_sorts_correctly(run, tmp_path):
    rows = 20000
    _big_csv(tmp_path / "big.csv", rows)
    res = run("--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "big.csv")
    assert res.returncode == 0, res.stderr
    with open(tmp_path / "out.csv", encoding="utf-8") as fh:
        assert fh.readline() == "id,payload\n"
        keys = [int(line.split(",", 1)[0]) for line in fh]
    assert len(keys) == rows
    assert keys == sorted(keys)


# Phrase: "All intermediate resources must be cleaned up on exit"
# Context: --temp-dir holds spill files during the run and is empty afterwards.
def test_temp_dir_is_emptied_on_success(run, tmp_path):
    spill = tmp_path / "spill"
    spill.mkdir()
    _big_csv(tmp_path / "big.csv", 5000)
    res = run(
        "--output", "out.csv", "--key", "id",
        "--memory-limit-mb", "1", "--temp-dir", str(spill), "big.csv",
    )
    assert res.returncode == 0, res.stderr
    assert os.listdir(spill) == []


# Phrase: "All intermediate resources must be cleaned up on exit"
# Context: a run that fails after spill files already exist cleans them up too.
def test_temp_dir_is_emptied_on_failure(run, tmp_path, schema_file):
    spill = tmp_path / "spill"
    spill.mkdir()
    with open(tmp_path / "late.csv", "w", encoding="utf-8") as fh:
        fh.write("id,payload\n")
        for i in range(20000):
            fh.write(f"{i},{i}\n")
        fh.write("99999,not-an-int\n")
    schema = schema_file([("id", "int"), ("payload", "int")])
    res = run(
        "--output", "out.csv", "--key", "id", "--schema", schema,
        "--on-type-error", "fail", "--memory-limit-mb", "1",
        "--temp-dir", str(spill), "late.csv",
    )
    assert res.returncode != 0
    assert os.listdir(spill) == []


# Phrase: "[--temp-dir <PATH>]"
# Context: spill files go to the requested directory, not the system default.
def test_temp_dir_must_be_usable(run, tmp_path, csv_file):
    csv_file("a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--temp-dir", "no/such/dir", "a.csv")
    assert res.returncode != 0


# Phrase: "Tool must work under small --memory-limit-mb (e.g., 64MB)"
# Context: stability survives the spill-and-merge path.
def test_stability_survives_spilling(run, tmp_path):
    with open(tmp_path / "a.csv", "w", encoding="utf-8") as fh:
        fh.write("k,seq\n")
        for i in range(6000):
            fh.write(f"{i % 3},{i}\n")
    res = run("--output", "-", "--key", "k", "--memory-limit-mb", "1", "a.csv")
    assert res.returncode == 0, res.stderr
    seqs = [int(v) for v in column(res.stdout, "seq")]
    assert seqs[:3] == [0, 3, 6]
    assert seqs == sorted(seqs, key=lambda s: (s % 3, s))


# Phrase: "Tool must handle inputs exceeding --memory-limit-mb constraint"
# Context: many files merge under a tight budget.
def test_many_files_merge_under_budget(run, tmp_path):
    for f in range(5):
        with open(tmp_path / f"p{f}.csv", "w", encoding="utf-8") as fh:
            fh.write("id\n")
            for i in range(2000):
                fh.write(f"{i * 5 + f}\n")
    res = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "1",
        *[f"p{f}.csv" for f in range(5)],
    )
    assert res.returncode == 0, res.stderr
    ids = [int(v) for v in column(res.stdout, "id")]
    assert ids == sorted(ids)
    assert len(ids) == 10000
