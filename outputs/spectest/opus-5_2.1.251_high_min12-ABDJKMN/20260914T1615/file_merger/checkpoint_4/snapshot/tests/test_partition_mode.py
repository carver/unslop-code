"""Spec section: Partitioned Output — "Output Location & Mode"."""

import os

from conftest import read_text, run, run_ok, write

A = "id,country,dt,v\n2,US,2024-01-01,b\n1,CA,2024-01-02,a\n3,US,2024-01-01,c\n"


def part_files(root):
    """Every part-*.csv under `root`, as sorted root-relative posix paths."""
    out = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


# --- Spec: "When no partitioning flags provided: write single CSV to --output
#     (file path or `-` for stdout)" ---
# Context: Output Location & Mode. Absent partitioning, nothing changes.
def test_no_partitioning_flags_writes_single_csv_file(ws):
    a = write(ws / "a.csv", A)
    out = ws / "merged.csv"
    run_ok("--output", str(out), "--key", "id", a)
    assert os.path.isfile(out)
    assert read_text(out) == (
        "country,dt,id,v\n"
        "CA,2024-01-02,1,a\nUS,2024-01-01,2,b\nUS,2024-01-01,3,c\n")


# --- Spec: "write single CSV to --output (file path or `-` for stdout)" ---
# Context: Output Location & Mode; `-` still means stdout when unpartitioned.
def test_no_partitioning_flags_dash_still_stdout(ws):
    a = write(ws / "a.csv", A)
    res = run_ok("--output", "-", "--key", "id", a)
    assert res.stdout.startswith("country,dt,id,v\n")


# --- Spec: "When any partitioning flag provided: --output must be directory
#     path" ---
# Context: Output Location & Mode; --partition-by is a partitioning flag.
def test_partition_by_makes_output_a_directory(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    assert os.path.isdir(out)


# --- Spec: "When any partitioning flag provided: --output must be directory
#     path" ---
# Context: Output Location & Mode; --max-rows-per-file alone also triggers it.
def test_max_rows_alone_makes_output_a_directory(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "2", a)
    assert os.path.isdir(out)
    assert part_files(out) == ["part-00000.csv", "part-00001.csv"]


# --- Spec: "When any partitioning flag provided: --output must be directory
#     path" ---
# Context: Output Location & Mode; --max-bytes-per-file alone also triggers it.
def test_max_bytes_alone_makes_output_a_directory(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-bytes-per-file", "1000", a)
    assert os.path.isdir(out)
    assert part_files(out) == ["part-00000.csv"]


# --- Spec: "--output must be directory path (not `-`)" ---
# Context: Output Location & Mode. See AMBIGUITIES T50 (exit 2).
def test_dash_output_with_partition_by_is_usage_error(ws):
    a = write(ws / "a.csv", A)
    res = run("--output", "-", "--key", "id", "--partition-by", "country", a)
    assert res.returncode == 2, res
    assert res.stderr.startswith("merge_files.py: error: ")


# --- Spec: "--output must be directory path (not `-`)" ---
# Context: Output Location & Mode; the sharding flags are equally incompatible.
def test_dash_output_with_max_rows_is_usage_error(ws):
    a = write(ws / "a.csv", A)
    res = run("--output", "-", "--key", "id", "--max-rows-per-file", "1", a)
    assert res.returncode == 2, res


def test_dash_output_with_max_bytes_is_usage_error(ws):
    a = write(ws / "a.csv", A)
    res = run("--output", "-", "--key", "id", "--max-bytes-per-file", "100", a)
    assert res.returncode == 2, res


# --- Spec: "Create directory if doesn't exist" ---
# Context: Output Location & Mode.
def test_output_directory_created_when_absent(ws):
    a = write(ws / "a.csv", A)
    out = ws / "deep" / "nested" / "out"
    assert not out.exists()
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    assert os.path.isdir(out)


# --- Spec: "Create directory if doesn't exist" ---
# Context: an already-existing empty directory is fine, not an error.
def test_existing_empty_output_directory_is_reused(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    out.mkdir()
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    assert sorted(p.name for p in out.iterdir()) == ["country=CA", "country=US"]


# --- Spec: "Perform atomic write by creating sibling temp directory and
#     renaming on success" ---
# Context: Output Location & Mode; no temp artifacts survive a successful run.
def test_no_temp_directory_left_after_success(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    siblings = sorted(p.name for p in ws.iterdir())
    assert siblings == ["a.csv", "out"], siblings


# --- Spec: "Perform atomic write by creating sibling temp directory and
#     renaming on success" ---
# Context: the destination is replaced wholesale. See AMBIGUITIES T48.
def test_rerun_replaces_previous_contents(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    stale = out / "country=ZZ"
    stale.mkdir()
    write(stale / "part-00000.csv", "id,country,dt,v\n9,ZZ,x,y\n")
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    assert sorted(p.name for p in out.iterdir()) == ["country=CA", "country=US"]


# --- Spec: "On failure, remove temp directory and partial files" ---
# Context: Output Location & Mode; a mid-run cast failure must leave no debris.
def test_failure_leaves_no_temp_directory(ws):
    a = write(ws / "a.csv", "id,country,n\n1,US,5\n2,CA,notanint\n")
    s = write(ws / "s.json",
              '{"columns":[{"name":"id","type":"int"},'
              '{"name":"country","type":"string"},{"name":"n","type":"int"}]}')
    out = ws / "out"
    res = run("--output", str(out), "--key", "id", "--schema", s,
              "--on-type-error", "fail", "--partition-by", "country", a)
    assert res.returncode == 4, res
    leftovers = [p.name for p in ws.iterdir() if p.name not in ("a.csv", "s.json")]
    assert leftovers in ([], ["out"]), leftovers
    if (ws / "out").exists():
        assert part_files(ws / "out") == []


# --- Spec: "On failure, remove temp directory and partial files" ---
# Context: a pre-existing destination must not be destroyed by a failed run.
def test_failure_preserves_previous_output_directory(ws):
    good = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", good)
    before = part_files(out)

    bad = write(ws / "b.csv", "id,country,dt,v\n1,US,2024-01-01,x\n")
    s = write(ws / "s.json",
              '{"columns":[{"name":"id","type":"int"},'
              '{"name":"country","type":"int"},'
              '{"name":"dt","type":"string"},{"name":"v","type":"string"}]}')
    res = run("--output", str(out), "--key", "id", "--schema", s,
              "--on-type-error", "fail", "--partition-by", "country", bad)
    assert res.returncode == 4, res
    assert part_files(out) == before
