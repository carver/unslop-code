"""Hive-style field partitioning: directory tree, value encoding, per-partition files."""

import csv

from conftest import rows_of


# Spec: "Rows for each unique combination of partition column values go into
# separate directory"
def test_each_value_combination_gets_its_own_directory(make_csv, run, tree):
    make_csv("a.csv", "id,country,dt\n1,us,d1\n2,fr,d1\n3,us,d2\n")
    run("--output", "out", "--key", "id", "--partition-by", "country,dt", "a.csv")
    assert tree("out") == [
        "country=fr/dt=d1/part-00000.csv",
        "country=us/dt=d1/part-00000.csv",
        "country=us/dt=d2/part-00000.csv",
    ]


# Spec: "Rows for each unique combination of partition column values go into
# separate directory"
# Context: every row lands in the directory its own values name.
def test_rows_land_in_the_directory_of_their_values(make_csv, run, read):
    make_csv("a.csv", "id,country\n1,us\n2,fr\n3,us\n")
    run("--output", "out", "--key", "id", "--partition-by", "country", "a.csv")
    assert rows_of(read("out/country=us/part-00000.csv")) == [["country", "id"], ["us", "1"], ["us", "3"]]
    assert rows_of(read("out/country=fr/part-00000.csv")) == [["country", "id"], ["fr", "2"]]


# Spec: "Emit directory tree inside `--output` using Hive-style segments:
# `<col1>=<val1>/<col2>=<val2>/.../`"
# Context: segments nest in the order given to --partition-by.
def test_segments_nest_in_partition_by_order(make_csv, run, tree):
    make_csv("a.csv", "id,b,a\n1,bee,ay\n")
    run("--output", "out", "--key", "id", "--partition-by", "b,a", "a.csv")
    assert tree("out") == ["b=bee/a=ay/part-00000.csv"]


# Spec: "Values derived after casting to resolved schema types"
# Context: 007 and 7 cast to the same int, so they share one directory.
def test_values_are_the_cast_values(make_csv, run, tree):
    make_csv("a.csv", "id,n\n1,007\n2,7\n")
    run("--output", "out", "--key", "id", "--partition-by", "n", "a.csv")
    assert tree("out") == ["n=7/part-00000.csv"]


# Spec: "Values derived after casting to resolved schema types"
# Context: a float column's directory name is the rendered float, not the input text.
def test_float_partition_values_are_rendered_from_the_cast_value(make_csv, run, tree):
    make_csv("a.csv", "id,n\n1,1.50\n2,0.5\n")
    run("--output", "out", "--key", "id", "--partition-by", "n", "a.csv")
    assert tree("out") == ["n=0.5/part-00000.csv", "n=1.5/part-00000.csv"]


# Spec: "Values use percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`"
def test_unreserved_characters_are_left_alone(make_csv, run, tree):
    make_csv("a.csv", "id,v\n1,Az09._-\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert tree("out") == ["v=Az09._-/part-00000.csv"]


# Spec: "Values use percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`"
# Context: a non-ASCII character is encoded byte by byte, upper-case hex.
def test_non_ascii_values_are_percent_encoded_per_utf8_byte(make_csv, run, tree):
    make_csv("a.csv", "id,v\n1,café\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert tree("out") == ["v=caf%C3%A9/part-00000.csv"]


# Spec: "characters outside `[A-Za-z0-9._-]`"
# Context: ~ is outside the set even though URL encoders often leave it alone.
def test_tilde_is_encoded(make_csv, run, tree):
    make_csv("a.csv", "id,v\n1,a~b\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert tree("out") == ["v=a%7Eb/part-00000.csv"]


# Spec: "space -> `%20`"
def test_space_is_encoded_as_percent_20(make_csv, run, tree):
    make_csv("a.csv", "id,v\n1,new york\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert tree("out") == ["v=new%20york/part-00000.csv"]


# Spec: "`/` encoded as `%2F`"
def test_slash_is_encoded_and_does_not_nest(make_csv, run, tree):
    make_csv("a.csv", "id,v\n1,a/b\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert tree("out") == ["v=a%2Fb/part-00000.csv"]


# Spec: "Null (missing) partition values use literal `_null`"
def test_missing_partition_value_uses_the_null_segment(make_csv, run, tree):
    make_csv("a.csv", "id,v\n1,x\n2,\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert tree("out") == ["v=_null/part-00000.csv", "v=x/part-00000.csv"]


# Spec: "Null (missing) partition values use literal `_null`"
# Context: a column absent from one input is null for that input's rows.
def test_column_absent_from_an_input_partitions_as_null(make_csv, run, read):
    make_csv("a.csv", "id,v\n1,x\n")
    make_csv("b.csv", "id\n2\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv", "b.csv")
    assert rows_of(read("out/v=_null/part-00000.csv")) == [["id", "v"], ["2", ""]]


# Spec: "Null (missing) partition values use literal `_null`"
# Context: the segment stays `_null` even when --csv-null-literal renames the cell text.
def test_null_segment_ignores_the_null_literal_flag(make_csv, run, tree, read):
    make_csv("a.csv", "id,v\n7,\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "--csv-null-literal", "NA", "a.csv")
    assert tree("out") == ["v=_null/part-00000.csv"]
    assert read("out/v=_null/part-00000.csv") == "id,v\n7,NA\n"


# Spec: "Within each partition directory, write CSV files named sequentially:
# `part-00000.csv`, `part-00001.csv`, ... (zero-padded width 5)"
def test_part_names_are_zero_padded_and_sequential_per_partition(make_csv, run, tree):
    rows = "".join(f"{i},x\n" for i in range(5))
    make_csv("a.csv", "id,v\n" + rows)
    run("--output", "out", "--key", "id", "--partition-by", "v", "--max-rows-per-file", "2", "a.csv")
    assert tree("out") == [
        "v=x/part-00000.csv",
        "v=x/part-00001.csv",
        "v=x/part-00002.csv",
    ]


# Spec: "Each file contains header row (resolved schema header)"
def test_every_partition_file_starts_with_the_resolved_header(make_csv, run, read):
    make_csv("a.csv", "id,v\n1,x\n2,x\n")
    run("--output", "out", "--key", "id", "--partition-by", "v", "--max-rows-per-file", "1", "a.csv")
    assert read("out/v=x/part-00000.csv") == "id,v\n1,x\n"
    assert read("out/v=x/part-00001.csv") == "id,v\n2,x\n"


# Spec: "Each file contains header row (resolved schema header)"
# Context: the header is the schema's column order, partition columns included.
def test_partition_columns_stay_in_the_file_header(make_csv, make_schema, run, read):
    make_csv("a.csv", "v,id\nx,1\n")
    make_schema("s.json", [("id", "int"), ("v", "string")])
    run("--output", "out", "--key", "id", "--partition-by", "v", "--schema", "s.json", "a.csv")
    assert read("out/v=x/part-00000.csv") == "id,v\n1,x\n"


# Spec: "Must respect size/row-based cutting rules if set (see below); otherwise
# one file per partition"
def test_without_cutting_rules_each_partition_holds_one_file(make_csv, run, tree):
    rows = "".join(f"{i},x\n" for i in range(50))
    make_csv("a.csv", "id,v\n" + rows)
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert tree("out") == ["v=x/part-00000.csv"]


# Spec: "With field partitioning: rows in each partition directory must be
# sorted by `--key` within that partition"
def test_rows_are_sorted_by_key_inside_each_partition(make_csv, run, read):
    make_csv("a.csv", "ts,g\n3,a\n1,b\n2,a\n1,a\n")
    run("--output", "out", "--key", "ts", "--partition-by", "g", "a.csv")
    assert rows_of(read("out/g=a/part-00000.csv")) == [["g", "ts"], ["a", "1"], ["a", "2"], ["a", "3"]]
    assert rows_of(read("out/g=b/part-00000.csv")) == [["g", "ts"], ["b", "1"]]


# Spec: "rows in each partition directory must be sorted by `--key` within that
# partition" plus "--desc"
def test_desc_reverses_the_order_inside_each_partition(make_csv, run, read):
    make_csv("a.csv", "ts,g\n1,a\n3,a\n2,a\n")
    run("--output", "out", "--key", "ts", "--desc", "--partition-by", "g", "a.csv")
    assert rows_of(read("out/g=a/part-00000.csv")) == [["g", "ts"], ["a", "3"], ["a", "2"], ["a", "1"]]


# Spec: "rows in each partition directory must be sorted by `--key`"
# Context: a multi-column key orders by each column in turn.
def test_multi_column_key_orders_inside_the_partition(make_csv, run, read):
    make_csv("a.csv", "ts,id,g\n10,9,a\n10,2,a\n5,5,a\n")
    run("--output", "out", "--key", "ts,id", "--partition-by", "g", "a.csv")
    assert rows_of(read("out/g=a/part-00000.csv"))[1:] == [["a", "5", "5"], ["a", "2", "10"], ["a", "9", "10"]]


# Spec: "Each partition file is independently valid CSV"
def test_partition_files_round_trip_through_a_csv_reader(make_csv, run, read):
    make_csv("a.csv", 'id,v,note\n1,x,"a,b"\n2,x,"line\nbreak"\n')
    run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    parsed = list(csv.reader(read("out/v=x/part-00000.csv").splitlines(keepends=True)))
    assert parsed == [["id", "note", "v"], ["1", "a,b", "x"], ["2", "line\nbreak", "x"]]


# Spec: "Use same delimiter/quote/escape/line-ending/null-literal rules as before"
def test_dialect_flags_reach_the_partition_files(make_csv, run, read):
    make_csv("a.csv", "id,v,note\n7,x,\n")
    run(
        "--output", "out", "--key", "id", "--partition-by", "v",
        "--csv-quotechar", "'", "--csv-null-literal", "NULL", "a.csv",
    )
    assert read("out/v=x/part-00000.csv") == "id,note,v\n7,NULL,x\n"


# Spec: "Continue to honor small `--memory-limit-mb` values"
# Context: partitioned output still comes out sorted when the sort spills to disk.
def test_small_memory_limit_still_partitions_and_sorts(make_csv, run, read):
    rows = "".join(f"{i % 100},{i % 3}\n" for i in range(2000))
    make_csv("a.csv", "ts,g\n" + rows)
    run("--output", "out", "--key", "ts", "--partition-by", "g", "--memory-limit-mb", "1", "a.csv")
    for group in ("0", "1", "2"):
        values = [int(row[0]) for row in rows_of(read(f"out/g={group}/part-00000.csv"))[1:]]
        assert values == sorted(values)
    assert sum(len(rows_of(read(f"out/g={g}/part-00000.csv"))) - 1 for g in "012") == 2000
