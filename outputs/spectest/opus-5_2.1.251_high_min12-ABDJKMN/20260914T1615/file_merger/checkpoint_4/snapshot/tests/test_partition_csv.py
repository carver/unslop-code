"""Spec sections: Partitioned Output — "Sorting Guarantees", "CSV Output
Contents", "Memory & External Merge", "Determinism Checklist"."""

import csv
import io
import os

from conftest import read_text, rows_of, run, run_ok, write, write_schema


def parts(d):
    return sorted(p for p in os.listdir(d) if p.startswith("part-"))


def tree(root):
    out = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


# ---------------------------------------------------------------- Sorting

# --- Spec: "With no field partitioning: rows must be globally sorted by --key
#     (and --desc if set)" ---
# Context: Sorting Guarantees; concatenating shards reproduces the global order.
def test_global_sort_across_shards(ws):
    a = write(ws / "a.csv", "id,v\n" + "".join(f"{i},x\n" for i in [9, 2, 7, 1, 5]))
    b = write(ws / "b.csv", "id,v\n" + "".join(f"{i},y\n" for i in [3, 8, 4, 6]))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "2", a, b)
    seen = []
    for p in parts(out):
        seen += [int(r["id"]) for r in rows_of(read_text(out / p))]
    assert seen == sorted(seen)
    assert seen == list(range(1, 10))


# --- Spec: "rows must be globally sorted by --key (and --desc if set)" ---
# Context: Sorting Guarantees; descending applies to the whole stream.
def test_global_sort_descending_across_shards(ws):
    a = write(ws / "a.csv", "id,v\n" + "".join(f"{i},x\n" for i in [9, 2, 7, 1, 5]))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--desc",
           "--max-rows-per-file", "2", a)
    seen = []
    for p in parts(out):
        seen += [int(r["id"]) for r in rows_of(read_text(out / p))]
    assert seen == [9, 7, 5, 2, 1]


# --- Spec: "globally sorted by --key" with a multi-column key ---
# Context: Sorting Guarantees; the example uses `--key ts,id`.
def test_global_sort_multi_column_key(ws):
    a = write(ws / "a.csv",
              "ts,id\n2,20\n1,30\n2,10\n1,10\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "ts,id", "--max-rows-per-file", "1", a)
    seen = []
    for p in parts(out):
        seen += [(r["ts"], r["id"]) for r in rows_of(read_text(out / p))]
    assert seen == [("1", "10"), ("1", "30"), ("2", "10"), ("2", "20")]


# --- Spec: "With field partitioning: rows in each partition directory must be
#     sorted by --key within that partition" ---
# Context: Sorting Guarantees.
def test_rows_sorted_within_each_partition(ws):
    rows = [(7, "US"), (3, "CA"), (9, "US"), (1, "CA"), (5, "US")]
    a = write(ws / "a.csv", "id,c\n" + "".join(f"{i},{c}\n" for i, c in rows))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c", a)
    us = [int(r["id"]) for r in rows_of(read_text(out / "c=US" / "part-00000.csv"))]
    ca = [int(r["id"]) for r in rows_of(read_text(out / "c=CA" / "part-00000.csv"))]
    assert us == [5, 7, 9]
    assert ca == [1, 3]


# --- Spec: "rows in each partition directory must be sorted by --key within
#     that partition" ---
# Context: order must be continuous across the part files of one partition.
def test_partition_order_continues_across_part_files(ws):
    a = write(ws / "a.csv",
              "id,c\n" + "".join(f"{i},US\n" for i in [5, 1, 9, 3, 7, 11]))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c",
           "--max-rows-per-file", "2", a)
    d = out / "c=US"
    seen = []
    for p in parts(d):
        seen += [int(r["id"]) for r in rows_of(read_text(d / p))]
    assert seen == [1, 3, 5, 7, 9, 11]


# --- Spec: "rows in each partition ... sorted by --key" with --desc ---
# Context: the third example uses `--key created_at,id --desc --partition-by`.
def test_descending_within_partitions(ws):
    # acct values 10/11 keep the column an int (see T2: a 0/1 column is bool).
    a = write(ws / "a.csv",
              "id,acct\n" + "".join(f"{i},{10 + i % 2}\n" for i in range(1, 9)))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--desc",
           "--partition-by", "acct", a)
    got = [int(r["id"])
           for r in rows_of(read_text(out / "acct=11" / "part-00000.csv"))]
    assert got == [7, 5, 3, 1]


# ------------------------------------------------------- CSV Output Contents

# --- Spec: "Every output CSV includes header row in resolved schema column
#     order" ---
# Context: CSV Output Contents; every file in every partition.
def test_every_partition_file_has_the_header(ws):
    a = write(ws / "a.csv",
              "id,c,v\n" + "".join(f"{i},{i % 3},x\n" for i in range(1, 13)))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c",
           "--max-rows-per-file", "2", a)
    rels = tree(out)
    assert len(rels) >= 6
    for rel in rels:
        assert read_text(out / rel).split("\n")[0] == "c,id,v"


# --- Spec: "Every output CSV includes header row in resolved schema column
#     order" ---
# Context: column order comes from the schema document, not the input files.
def test_header_order_follows_schema_document(ws):
    a = write(ws / "a.csv", "b,a\n2,1\n")
    s = write_schema(ws / "s.json", [("a", "int"), ("b", "int")])
    out = ws / "out"
    run_ok("--output", str(out), "--key", "a", "--schema", s,
           "--partition-by", "b", a)
    assert read_text(out / "b=2" / "part-00000.csv") == "a,b\n1,2\n"


# --- Spec: "Use same delimiter/quote/escape/line-ending/null-literal rules as
#     before" ---
# Context: CSV Output Contents; commas/quotes are quoted per the base dialect.
def test_quoting_rules_carry_into_partition_files(ws):
    a = write(ws / "a.csv", 'id,v\n1,"x,y"\n2,"he said ""hi"""\n')
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "5", a)
    assert read_text(out / "part-00000.csv") == (
        'id,v\n1,"x,y"\n2,"he said ""hi"""\n')


# --- Spec: "Use same ... line-ending ... rules as before" ---
# Context: LF only, including the final line of every part file.
def test_line_endings_are_lf_and_file_ends_with_newline(ws):
    a = write(ws / "a.csv", "id,v\n1,a\n2,b\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "1", a)
    for p in parts(out):
        raw = open(out / p, "rb").read()
        assert b"\r" not in raw
        assert raw.endswith(b"\n")


# --- Spec: "Use same ... null-literal rules as before" ---
# Context: --csv-null-literal governs cells inside partition files ...
def test_null_literal_applies_inside_partition_files(ws):
    a = write(ws / "a.csv", "id,c,v\n5,US,\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c",
           "--csv-null-literal", "NA", a)
    assert read_text(out / "c=US" / "part-00000.csv") == "c,id,v\nUS,5,NA\n"


# --- Spec: "Null (missing) partition values use literal `_null`" ---
# Context: ... but the directory segment stays `_null` regardless of it.
def test_null_literal_does_not_change_the_null_segment(ws):
    a = write(ws / "a.csv", "id,c\n1,\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c",
           "--csv-null-literal", "NA", a)
    assert tree(out) == ["c=_null/part-00000.csv"]


# --- Spec: "Use same ... quote ... rules as before" ---
# Context: --csv-quotechar is honoured by partition writers too.
def test_custom_quotechar_in_partition_files(ws):
    a = write(ws / "a.csv", "id,v\n7,a|b\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "5",
           "--csv-quotechar", "'", a)
    assert read_text(out / "part-00000.csv") == "id,v\n7,a|b\n"


# --- Spec: "Each partition file is independently valid CSV" ---
# Context: CSV Output Contents; parsing any one file standalone works.
def test_each_part_file_parses_standalone(ws):
    a = write(ws / "a.csv",
              'id,c,v\n1,US,"a,b"\n2,US,plain\n3,CA,"q""q"\n4,CA,z\n')
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c",
           "--max-rows-per-file", "1", a)
    total = 0
    for rel in tree(out):
        rows = list(csv.reader(io.StringIO(read_text(out / rel))))
        assert rows[0] == ["c", "id", "v"]
        assert len(rows) == 2
        assert len(rows[1]) == 3
        total += 1
    assert total == 4


# --------------------------------------------- Memory & External Merge

# --- Spec: "Continue to honor small --memory-limit-mb values" ---
# Context: Memory & External Merge; spilling must not disturb the layout.
def test_small_memory_limit_still_partitions_correctly(ws):
    n = 400
    rows = "".join(f"{(i * 7919) % n},{i % 5},{'p' * 40}\n" for i in range(n))
    a = write(ws / "a.csv", "id,c,pad\n" + rows)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--memory-limit-mb", "1",
           "--partition-by", "c", "--max-rows-per-file", "17", a)
    total = 0
    for rel in tree(out):
        seg = rel.split("/")[0]
        rows_here = rows_of(read_text(out / rel))
        assert len(rows_here) <= 17
        assert all(f"c={r['c']}" == seg for r in rows_here)
        total += len(rows_here)
    assert total == n


# --- Spec: "Tool must work on arbitrarily large inputs" ---
# Context: Memory & External Merge; external merge feeds the partition writer,
# and the per-partition order survives the spill/merge path.
def test_spilled_run_keeps_partitions_sorted(ws):
    n = 300
    rows = "".join(f"{(i * 131) % n},{i % 3},{'q' * 60}\n" for i in range(n))
    a = write(ws / "a.csv", "id,c,pad\n" + rows)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--memory-limit-mb", "1",
           "--partition-by", "c", a)
    for rel in tree(out):
        ids = [int(r["id"]) for r in rows_of(read_text(out / rel))]
        assert ids == sorted(ids)


# ------------------------------------------------- Determinism Checklist

# --- Spec: "Directory layout and file names follow exact rules" ---
# Context: Determinism Checklist; two identical runs agree byte for byte.
def test_two_runs_produce_identical_trees(ws):
    a = write(ws / "a.csv",
              "id,c,v\n" + "".join(f"{i},{i % 4},v{i}\n" for i in range(1, 30)))
    o1, o2 = ws / "o1", ws / "o2"
    for out in (o1, o2):
        run_ok("--output", str(out), "--key", "id", "--partition-by", "c",
               "--max-rows-per-file", "3", a)
    assert tree(o1) == tree(o2)
    for rel in tree(o1):
        assert read_text(o1 / rel) == read_text(o2 / rel)


# --- Spec: "Exact exit codes and stderr message shapes as specified" ---
# Context: Determinism Checklist; a successful partitioned run is silent.
def test_successful_partitioned_run_is_silent_and_zero(ws):
    a = write(ws / "a.csv", "id,c\n1,US\n")
    res = run("--output", str(ws / "out"), "--key", "id",
              "--partition-by", "c", a)
    assert res.returncode == 0
    assert res.stderr == ""
    assert res.stdout == ""


# --- Spec: "Exact exit codes and stderr message shapes as specified" ---
# Context: an unreadable input still fails with the I/O code in partition mode.
def test_missing_input_is_io_error_in_partition_mode(ws):
    res = run("--output", str(ws / "out"), "--key", "id",
              "--partition-by", "c", str(ws / "nope.csv"))
    assert res.returncode == 1, res
    assert res.stderr.startswith("merge_files.py: error: ")


# --- Spec: "--output must be directory path" ---
# Context: an existing regular file at that path cannot become one (T51).
def test_output_path_is_an_existing_file(ws):
    a = write(ws / "a.csv", "id,c\n1,US\n")
    out = write(ws / "out", "not a directory\n")
    res = run("--output", str(out), "--key", "id", "--partition-by", "c", a)
    assert res.returncode == 1, res


# --- Spec: examples — the flags compose as documented ---
# Context: Examples; field partitioning plus a byte cap, mirroring example 1.
def test_example_country_dt_with_byte_cap(ws):
    a = write(ws / "a.csv",
              "ts,id,country,dt\n"
              "3,c,US,2024-01-01\n1,a,US,2024-01-01\n2,b,CA,2024-01-02\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "ts,id",
           "--partition-by", "country,dt", "--max-bytes-per-file", "52428800", a)
    assert tree(out) == [
        "country=CA/dt=2024-01-02/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
    ]
    us = rows_of(read_text(out / "country=US" / "dt=2024-01-01" / "part-00000.csv"))
    assert [r["id"] for r in us] == ["a", "c"]
