"""Spec section: Partitioned Output -> Output Location & Mode."""
import os

from conftest import parse_csv_text, read_csv_file, siblings, tree


def sample(work, name="a.csv"):
    return work.csv(
        name,
        ["id", "country", "dt", "v"],
        [
            ["3", "US", "2024-01-01", "c"],
            ["1", "FR", "2024-01-02", "a"],
            ["2", "US", "2024-01-01", "b"],
        ],
    )


# Phrase: "When no partitioning flags provided: write single CSV to `--output`
#          (file path or `-` for stdout)"
# Context: Output Location & Mode. The checkpoint-1 behaviour must survive.
def test_no_partition_flags_writes_single_file(run, work):
    sample(work)
    out = work.path("merged.csv")
    r = run("--output", out, "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.is_file()
    rows = read_csv_file(out)
    # Inferred schemas order columns lexicographically (checkpoint 1).
    assert rows[0] == ["country", "dt", "id", "v"]
    assert [row[2] for row in rows[1:]] == ["1", "2", "3"]


def test_no_partition_flags_writes_stdout(run, work):
    sample(work)
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[2] for row in r.rows()[1:]] == ["1", "2", "3"]


# Phrase: "When any partitioning flag provided: `--output` must be directory path"
# Context: Output Location & Mode; --partition-by is a partitioning flag.
def test_partition_by_makes_output_a_directory(run, work):
    sample(work)
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "country",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.is_dir()


# Phrase: "When any partitioning flag provided"
# Context: --max-rows-per-file alone is also a partitioning flag (see the spec's
# second example, which writes out/ with no --partition-by).
def test_max_rows_alone_makes_output_a_directory(run, work):
    sample(work)
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "2",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.is_dir()
    assert tree(out) == ["part-00000.csv", "part-00001.csv"]


# Phrase: "When any partitioning flag provided"
# Context: --max-bytes-per-file alone is also a partitioning flag.
def test_max_bytes_alone_makes_output_a_directory(run, work):
    sample(work)
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-bytes-per-file", "100000",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.is_dir()
    assert tree(out) == ["part-00000.csv"]


# Phrase: "Create directory if doesn't exist"
# Context: Output Location & Mode.
def test_output_directory_created_when_missing(run, work):
    sample(work)
    out = work.path("nested/deeper/out")
    assert not out.exists()
    r = run("--output", out, "--key", "id", "--partition-by", "country",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.is_dir()


# Phrase: "Create directory if doesn't exist"
# Context: an existing (empty) directory is accepted, not an error.
def test_existing_empty_output_directory_is_reused(run, work):
    sample(work)
    out = work.path("out")
    out.mkdir(parents=True)
    r = run("--output", out, "--key", "id", "--partition-by", "country",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert sorted(tree(out)) == [
        "country=FR/part-00000.csv",
        "country=US/part-00000.csv",
    ]


# Phrase: "`--output` must be directory path (not `-`)"
# Context: Output Location & Mode; see AMBIGUITIES T34 for the exit code.
def test_stdout_rejected_with_partition_by(run, work):
    sample(work)
    r = run("--output", "-", "--key", "id", "--partition-by", "country",
            work.path("a.csv"))
    assert r.returncode == 2
    assert r.stderr.strip()
    assert r.stdout == ""


def test_stdout_rejected_with_max_rows(run, work):
    sample(work)
    r = run("--output", "-", "--key", "id", "--max-rows-per-file", "1",
            work.path("a.csv"))
    assert r.returncode == 2
    assert r.stdout == ""


def test_stdout_rejected_with_max_bytes(run, work):
    sample(work)
    r = run("--output", "-", "--key", "id", "--max-bytes-per-file", "1000",
            work.path("a.csv"))
    assert r.returncode == 2
    assert r.stdout == ""


# Phrase: "Perform atomic write by creating sibling temp directory and renaming
#          on success"
# Context: on success nothing but the destination is left behind.
def test_no_temp_siblings_left_after_success(run, work):
    sample(work)
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "country",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert siblings(out) == ["a.csv"]


# Phrase: "On failure, remove temp directory and partial files"
# Context: a cast failure under --on-type-error fail aborts the run.
def test_failure_leaves_no_output_and_no_temp_dir(run, work):
    work.csv("a.csv", ["id", "country"], [["1", "US"], ["oops", "FR"]])
    schema = work.schema("s.json", [("id", "int"), ("country", "string")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "country",
            "--schema", schema, "--on-type-error", "fail", work.path("a.csv"))
    assert r.returncode != 0
    assert not out.exists()
    assert siblings(out) == ["a.csv", "s.json"]


# Phrase: "On failure, remove temp directory and partial files"
# Context: an unreadable input aborts before any directory is installed.
def test_missing_input_leaves_no_output_directory(run, work):
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "country",
            work.path("nope.csv"))
    assert r.returncode != 0
    assert not out.exists()


# Phrase: "Perform atomic write by creating sibling temp directory and renaming
#          on success"
# Context: AMBIGUITIES T38 -- the destination holds exactly this run's files.
def test_existing_output_contents_are_replaced(run, work):
    sample(work)
    out = work.path("out")
    (out / "country=ZZ").mkdir(parents=True)
    (out / "country=ZZ" / "part-00000.csv").write_text("stale\n", encoding="utf-8")
    r = run("--output", out, "--key", "id", "--partition-by", "country",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == [
        "country=FR/part-00000.csv",
        "country=US/part-00000.csv",
    ]
    assert siblings(out) == ["a.csv"]


# Phrase: "--output <PATH|->"
# Context: a trailing separator on the directory path is accepted.
def test_trailing_slash_on_output_directory(run, work):
    sample(work)
    out = work.path("out")
    r = run("--output", str(out) + os.sep, "--key", "id",
            "--partition-by", "country", work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == [
        "country=FR/part-00000.csv",
        "country=US/part-00000.csv",
    ]
