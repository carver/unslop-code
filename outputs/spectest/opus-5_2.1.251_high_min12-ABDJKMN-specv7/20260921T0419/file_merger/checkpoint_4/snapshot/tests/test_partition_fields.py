"""Spec section: Partitioned Output -> Partitioning by Fields."""
from conftest import read_csv_file, tree


# Phrase: "Rows for each unique combination of partition column values go into
#          separate directory"
# Context: Partitioning by Fields.
def test_one_directory_per_unique_combination(run, work):
    work.csv(
        "a.csv",
        ["id", "country", "dt"],
        [
            ["1", "US", "2024-01-01"],
            ["2", "US", "2024-01-02"],
            ["3", "FR", "2024-01-01"],
            ["4", "US", "2024-01-01"],
        ],
    )
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "country,dt",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == [
        "country=FR/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-02/part-00000.csv",
    ]


# Phrase: "Emit directory tree inside `--output` using Hive-style segments:
#          `<col1>=<val1>/<col2>=<val2>/.../`"
# Context: segment order follows the --partition-by order, not schema order.
def test_segment_order_follows_partition_by_order(run, work):
    work.csv("a.csv", ["id", "a", "b"], [["1", "x", "y"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "b,a",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["b=y/a=x/part-00000.csv"]


# Phrase: "--partition-by <col>[,<col>...]"
# Context: repeated flags accumulate, mirroring --key (AMBIGUITIES T16).
def test_repeated_partition_by_flags_accumulate(run, work):
    work.csv("a.csv", ["id", "a", "b"], [["1", "x", "y"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "a",
            "--partition-by", "b", work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["a=x/b=y/part-00000.csv"]


# Phrase: "Values derived after casting to resolved schema types"
# Context: a float column's partition value is the cast rendering (AMBIGUITIES T43).
def test_partition_value_uses_cast_rendering_float(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "1.50"], ["2", "1.5"]])
    schema = work.schema("s.json", [("id", "int"), ("v", "float")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=1.5/part-00000.csv"]
    assert len(read_csv_file(out / "v=1.5" / "part-00000.csv")) == 3


# Phrase: "Values derived after casting to resolved schema types"
# Context: bool renders with the tool's own bool output text.
def test_partition_value_uses_cast_rendering_bool(run, work):
    work.csv("a.csv", ["id", "f"], [["1", "1"], ["2", "true"], ["3", "0"]])
    schema = work.schema("s.json", [("id", "int"), ("f", "bool")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "f",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["f=false/part-00000.csv", "f=true/part-00000.csv"]
    assert len(read_csv_file(out / "f=true" / "part-00000.csv")) == 3


# Phrase: "Values use percent-encoding of UTF-8 bytes for characters outside
#          `[A-Za-z0-9._-]`"
# Context: the safe set is passed through untouched.
def test_safe_characters_are_not_encoded(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "Ab9._-"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=Ab9._-/part-00000.csv"]


# Phrase: "space -> `%20`"
# Context: Partitioning by Fields.
def test_space_is_encoded_as_percent20(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "new york"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=new%20york/part-00000.csv"]


# Phrase: "`/` encoded as `%2F`"
# Context: a slash must not create a nested directory level.
def test_slash_is_encoded_as_percent2f(run, work):
    work.write("a.csv", 'id,v\n1,"a/b"\n')
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=a%2Fb/part-00000.csv"]


# Phrase: "percent-encoding of UTF-8 bytes"
# Context: a non-ASCII character encodes byte by byte (AMBIGUITIES T36).
def test_non_ascii_encodes_each_utf8_byte(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "café"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=caf%C3%A9/part-00000.csv"]


# Phrase: "characters outside `[A-Za-z0-9._-]`"
# Context: `%` and `=` are outside the safe set, so they encode too
# (AMBIGUITIES T36) -- otherwise the encoding would not be reversible.
def test_percent_and_equals_are_encoded(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "a%b=c"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=a%25b%3Dc/part-00000.csv"]


# Phrase: "percent-encoding"
# Context: hex digits are upper case, as in the spec's own `%2F`/`%20`.
def test_hex_digits_are_uppercase(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "a+b"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=a%2Bb/part-00000.csv"]


# Phrase: "Null (missing) partition values use literal `_null`"
# Context: an empty CSV cell is missing.
def test_null_partition_value_uses_literal_null(run, work):
    work.write("a.csv", "id,v\n1,\n2,x\n")
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=_null/part-00000.csv", "v=x/part-00000.csv"]


# Phrase: "Null (missing) partition values use literal `_null`"
# Context: a JSONL key that is absent, and an explicit JSON null.
def test_null_partition_value_from_jsonl(run, work):
    work.jsonl("a.jsonl", [{"id": 1}, {"id": 2, "v": None}, {"id": 3, "v": "x"}])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=_null/part-00000.csv", "v=x/part-00000.csv"]
    assert len(read_csv_file(out / "v=_null" / "part-00000.csv")) == 3


# Phrase: "Null (missing) partition values use literal `_null`"
# Context: --on-type-error coerce-null makes the cell missing (AMBIGUITIES T43).
def test_coerced_null_partitions_as_null(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "7"], ["2", "nope"]])
    schema = work.schema("s.json", [("id", "int"), ("v", "int")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "v",
            "--schema", schema, "--on-type-error", "coerce-null",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["v=7/part-00000.csv", "v=_null/part-00000.csv"]


# Phrase: "Within each partition directory, write CSV files named sequentially:
#          `part-00000.csv`, ... otherwise one file per partition"
# Context: no size/row flags given.
def test_one_file_per_partition_without_size_flags(run, work):
    work.csv("a.csv", ["id", "g"], [[str(i), "g%d" % (i % 2)] for i in range(50)])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["g=g0/part-00000.csv", "g=g1/part-00000.csv"]


# Phrase: "Each file contains header row (resolved schema header)"
# Context: the header is the full resolved schema, partition columns included
# (AMBIGUITIES T35).
def test_partition_files_keep_full_schema_header(run, work):
    work.csv("a.csv", ["id", "country", "v"], [["7", "US", "x"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "country",
            work.path("a.csv"))
    assert r.ok, r.stderr
    rows = read_csv_file(out / "country=US" / "part-00000.csv")
    assert rows[0] == ["country", "id", "v"]
    assert rows[1] == ["US", "7", "x"]


# Phrase: "rows in each partition directory must be sorted by `--key` within
#          that partition"
# Context: Sorting Guarantees.
def test_rows_sorted_within_each_partition(run, work):
    rows = []
    for i in range(30):
        rows.append([str((i * 17) % 30), "g%d" % (i % 3)])
    work.csv("a.csv", ["id", "g"], rows)
    schema = work.schema("s.json", [("id", "int"), ("g", "string")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    for name in ("g=g0", "g=g1", "g=g2"):
        data = read_csv_file(out / name / "part-00000.csv")[1:]
        ids = [int(row[0]) for row in data]
        assert ids == sorted(ids)
        assert len(ids) == 10


# Phrase: "rows must be globally sorted by `--key` (and `--desc` if set)"
# Context: Sorting Guarantees, applied per partition with --desc.
def test_desc_sorting_within_partition(run, work):
    work.csv(
        "a.csv",
        ["created_at", "id", "account_id"],
        [
            ["2024-01-01", "1", "A"],
            ["2024-01-03", "2", "A"],
            ["2024-01-02", "3", "B"],
            ["2024-01-05", "4", "B"],
        ],
    )
    out = work.path("out")
    r = run("--output", out, "--key", "created_at,id", "--desc",
            "--partition-by", "account_id", work.path("a.csv"))
    assert r.ok, r.stderr
    a = read_csv_file(out / "account_id=A" / "part-00000.csv")[1:]
    assert [row[1] for row in a] == ["2024-01-03", "2024-01-01"]
    b = read_csv_file(out / "account_id=B" / "part-00000.csv")[1:]
    assert [row[1] for row in b] == ["2024-01-05", "2024-01-02"]


# Phrase: "Keys must exist in resolved schema (error 3 otherwise)"
# Context: applied to --partition-by too (AMBIGUITIES T41).
def test_unknown_partition_column_is_error_3(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "x"]])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "nope",
            work.path("a.csv"))
    assert r.returncode == 3
    assert not out.exists()


# Phrase: "Each partition file is independently valid CSV"
# Context: CSV Output Contents; quoting rules still apply inside a partition.
def test_partition_file_is_independently_valid_csv(run, work):
    work.write("a.csv", 'id,g,note\n1,x,"has, comma"\n2,x,"has ""quote"""\n')
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            work.path("a.csv"))
    assert r.ok, r.stderr
    rows = read_csv_file(out / "g=x" / "part-00000.csv")
    assert rows == [
        ["g", "id", "note"],
        ["x", "1", "has, comma"],
        ["x", "2", 'has "quote"'],
    ]


# Phrase: "Use same delimiter/quote/escape/line-ending/null-literal rules as before"
# Context: CSV Output Contents; --csv-null-literal reaches partition files.
def test_null_literal_applies_inside_partition_files(run, work):
    work.write("a.csv", "id,g,v\n7,x,\n")
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            "--csv-null-literal", "NA", work.path("a.csv"))
    assert r.ok, r.stderr
    rows = read_csv_file(out / "g=x" / "part-00000.csv")
    assert rows == [["g", "id", "v"], ["x", "7", "NA"]]


# Phrase: "Directory layout and file names follow exact rules"
# Context: a partition column may itself be part of --key.
def test_partition_column_may_also_be_a_key(run, work):
    work.csv("a.csv", ["g", "id"], [["b", "2"], ["a", "1"], ["b", "1"]])
    out = work.path("out")
    r = run("--output", out, "--key", "g,id", "--partition-by", "g",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["g=a/part-00000.csv", "g=b/part-00000.csv"]
    rows = read_csv_file(out / "g=b" / "part-00000.csv")[1:]
    assert [row[1] for row in rows] == ["1", "2"]


# Phrase: "Rows for each unique combination of partition column values"
# Context: works across heterogeneous inputs merged together.
def test_partitioning_across_multiple_input_formats(run, work):
    work.csv("a.csv", ["id", "g"], [["1", "x"], ["4", "y"]])
    work.jsonl("b.jsonl", [{"id": 2, "g": "x"}, {"id": 3, "g": "y"}])
    out = work.path("out")
    schema = work.schema("s.json", [("id", "int"), ("g", "string")])
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            "--schema", schema, work.path("a.csv"), work.path("b.jsonl"))
    assert r.ok, r.stderr
    x = read_csv_file(out / "g=x" / "part-00000.csv")[1:]
    assert [row[0] for row in x] == ["1", "2"]
    y = read_csv_file(out / "g=y" / "part-00000.csv")[1:]
    assert [row[0] for row in y] == ["3", "4"]
