"""Spec section: Partitioned Output — "Partitioning by Fields"."""

import os

from conftest import read_text, rows_of, run, run_ok, write, write_schema


def tree(root):
    out = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


A = ("id,country,dt,v\n"
     "2,US,2024-01-01,b\n"
     "1,CA,2024-01-02,a\n"
     "3,US,2024-01-01,c\n"
     "4,US,2024-01-02,d\n")


# --- Spec: "Rows for each unique combination of partition column values go
#     into separate directory" ---
# Context: Partitioning by Fields; one column.
def test_one_partition_column_one_directory_per_value(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    assert tree(out) == ["country=CA/part-00000.csv", "country=US/part-00000.csv"]


# --- Spec: "Rows for each unique combination of partition column values" ---
# Context: only combinations present in the data get a directory (T59).
def test_multi_column_uses_observed_combinations_only(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id",
           "--partition-by", "country,dt", a)
    assert tree(out) == [
        "country=CA/dt=2024-01-02/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-02/part-00000.csv",
    ]


# --- Spec: "Emit directory tree inside --output using Hive-style segments:
#     <col1>=<val1>/<col2>=<val2>/.../" ---
# Context: nesting order follows the --partition-by order, not alphabetical.
def test_segment_nesting_follows_flag_order(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id",
           "--partition-by", "dt,country", a)
    assert tree(out) == [
        "dt=2024-01-01/country=US/part-00000.csv",
        "dt=2024-01-02/country=CA/part-00000.csv",
        "dt=2024-01-02/country=US/part-00000.csv",
    ]


# --- Spec: "--partition-by <col>[,<col>...]" ---
# Context: Usage; the list may also be spelled as repeated flags (T56).
def test_partition_by_flag_may_be_repeated(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id",
           "--partition-by", "country", "--partition-by", "dt", a)
    assert tree(out) == [
        "country=CA/dt=2024-01-02/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-02/part-00000.csv",
    ]


# --- Spec: "Values derived after casting to resolved schema types" ---
# Context: the segment shows the cast/rendered value, not the raw source text.
def test_partition_value_is_the_cast_rendering_int(ws):
    a = write(ws / "a.csv", "id,n\n1,007\n2,7\n3,+7\n")
    s = write_schema(ws / "s.json", [("id", "int"), ("n", "int")])
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--schema", s,
           "--partition-by", "n", a)
    assert tree(out) == ["n=7/part-00000.csv"]


# --- Spec: "Values derived after casting to resolved schema types" ---
# Context: a timestamp partition column uses the normalized UTC rendering,
# whose `:` characters are then percent-encoded.
def test_partition_value_is_the_cast_rendering_timestamp(ws):
    a = write(ws / "a.csv", "id,ts\n1,2024-07-01T12:00:00+00:00\n")
    s = write_schema(ws / "s.json", [("id", "int"), ("ts", "timestamp")])
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--schema", s,
           "--partition-by", "ts", a)
    assert tree(out) == ["ts=2024-07-01T12%3A00%3A00Z/part-00000.csv"]


# --- Spec: "Values derived after casting to resolved schema types" ---
# Context: a bool partition column collapses 1/true into one directory.
def test_partition_value_is_the_cast_rendering_bool(ws):
    a = write(ws / "a.csv", "id,flag\n1,true\n2,1\n3,false\n")
    s = write_schema(ws / "s.json", [("id", "int"), ("flag", "bool")])
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--schema", s,
           "--partition-by", "flag", a)
    assert tree(out) == ["flag=false/part-00000.csv", "flag=true/part-00000.csv"]


# --- Spec: "Apply percent-encoding of UTF-8 bytes for characters outside
#     [A-Za-z0-9._-]" ---
# Context: safe characters pass through untouched.
def test_safe_characters_are_not_encoded(ws):
    a = write(ws / "a.csv", "id,p\n1,aZ0._-\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a)
    assert tree(out) == ["p=aZ0._-/part-00000.csv"]


# --- Spec: "space → %20" ---
# Context: Partitioning by Fields; explicit example in the spec.
def test_space_encodes_as_percent_20(ws):
    a = write(ws / "a.csv", "id,p\n1,new york\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a)
    assert tree(out) == ["p=new%20york/part-00000.csv"]


# --- Spec: "`/` encoded as %2F" ---
# Context: the separator must not create a spurious directory level.
def test_slash_encodes_as_percent_2f(ws):
    a = write(ws / "a.csv", "id,p\n1,a/b\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a)
    assert tree(out) == ["p=a%2Fb/part-00000.csv"]


# --- Spec: "Apply percent-encoding of UTF-8 bytes" ---
# Context: non-ASCII is encoded byte-by-byte from its UTF-8 form, uppercase hex.
def test_non_ascii_encodes_per_utf8_byte(ws):
    a = write(ws / "a.csv", "id,p\n1,café\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a)
    assert tree(out) == ["p=caf%C3%A9/part-00000.csv"]


# --- Spec: "Apply percent-encoding of UTF-8 bytes for characters outside
#     [A-Za-z0-9._-]" ---
# Context: `%` itself, `=`, and other punctuation are outside the safe set.
def test_percent_and_equals_are_encoded(ws):
    a = write(ws / "a.csv", "id,p\n1,x%y=z\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a)
    assert tree(out) == ["p=x%25y%3Dz/part-00000.csv"]


# --- Spec: "Apply percent-encoding" ---
# Context: distinct raw values must not collide after encoding.
def test_encoding_is_injective_across_values(ws):
    a = write(ws / "a.csv", "id,p\n1,a b\n2,a%20b\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a)
    assert tree(out) == ["p=a%20b/part-00000.csv", "p=a%2520b/part-00000.csv"]


# --- Spec: "Null (missing) partition values use literal `_null`" ---
# Context: an empty CSV cell is null (see T8/T54).
def test_empty_cell_partitions_as_null_literal(ws):
    a = write(ws / "a.csv", "id,p\n1,\n2,x\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a)
    assert tree(out) == ["p=_null/part-00000.csv", "p=x/part-00000.csv"]


# --- Spec: "Null (missing) partition values use literal `_null`" ---
# Context: a column absent from one input is missing there.
def test_missing_column_partitions_as_null_literal(ws):
    a = write(ws / "a.csv", "id,p\n1,x\n")
    b = write(ws / "b.jsonl", '{"id": 2}\n')
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a, b)
    assert tree(out) == ["p=_null/part-00000.csv", "p=x/part-00000.csv"]


# --- Spec: "Null (missing) partition values use literal `_null`" ---
# Context: `_null` is written literally, i.e. not percent-encoded.
def test_null_literal_is_not_percent_encoded(ws):
    a = write(ws / "a.csv", "id,p\n1,\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "p", a)
    assert tree(out) == ["p=_null/part-00000.csv"]


# --- Spec: "Within each partition directory, write CSV files named
#     sequentially: part-00000.csv, part-00001.csv, … (zero-padded width 5)" ---
# Context: with no cutting rules there is exactly one file per partition.
def test_single_file_per_partition_without_cutting_rules(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    assert sorted(os.listdir(out / "country=US")) == ["part-00000.csv"]


# --- Spec: "Each file contains header row (resolved schema header)" ---
# Context: every partition file carries the full resolved header (T46).
def test_partition_file_has_full_resolved_header(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    text = read_text(out / "country=US" / "part-00000.csv")
    assert text.split("\n")[0] == "country,dt,id,v"


# --- Spec: "Each file contains header row (resolved schema header)" ---
# Context: the partition column is still a data column inside the file (T46).
def test_partition_column_values_still_present_in_rows(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country", a)
    rows = rows_of(read_text(out / "country=US" / "part-00000.csv"))
    assert [r["country"] for r in rows] == ["US", "US", "US"]
    assert [r["id"] for r in rows] == ["2", "3", "4"]


# --- Spec: "Rows for each unique combination ... go into separate directory" ---
# Context: partitioning is a total routing — every input row lands exactly once.
def test_every_row_appears_exactly_once_across_partitions(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "country,dt", a)
    seen = []
    for rel in tree(out):
        seen += [r["id"] for r in rows_of(read_text(out / rel))]
    assert sorted(seen) == ["1", "2", "3", "4"]


# --- Spec: "Rows for each unique combination of partition column values" ---
# Context: rows sharing a value land in the same directory even when the sorted
# stream interleaves them (forces append/reopen behaviour).
def test_interleaved_partitions_accumulate_in_one_file(ws):
    rows = "".join(f"{i},{'US' if i % 2 else 'CA'}\n" for i in range(1, 21))
    a = write(ws / "a.csv", "id,c\n" + rows)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c", a)
    us = rows_of(read_text(out / "c=US" / "part-00000.csv"))
    ca = rows_of(read_text(out / "c=CA" / "part-00000.csv"))
    assert [r["id"] for r in us] == [str(i) for i in range(1, 21) if i % 2]
    assert [r["id"] for r in ca] == [str(i) for i in range(1, 21) if not i % 2]


# --- Spec: "--partition-by <col,...>" names resolved-schema columns ---
# Context: an unknown partition column is a schema error (T52).
def test_unknown_partition_column_is_schema_error(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    res = run("--output", str(out), "--key", "id", "--partition-by", "nope", a)
    assert res.returncode == 3, res
    assert res.stderr.startswith("merge_files.py: error: ")


# --- Spec: sorting and partitioning are independent (T58) ---
# Context: a column may be both a key and a partition column.
def test_partition_column_may_also_be_a_key(ws):
    a = write(ws / "a.csv", A)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "country,id",
           "--partition-by", "country", a)
    rows = rows_of(read_text(out / "country=US" / "part-00000.csv"))
    assert [r["id"] for r in rows] == ["2", "3", "4"]
