"""Spec section: Partitioning by Fields — Hive directories, encoding, part files."""

import json

from conftest import read, rows_of, tree


# Phrase: "Rows for each unique combination of partition column values go into
#          separate directory"
# Context: Partitioning by Fields.
def test_each_value_gets_its_own_directory(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n2,FR\n3,US\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "country=FR/part-00000.csv",
        "country=US/part-00000.csv",
    ]
    assert rows_of(read(workdir / "out/country=US/part-00000.csv")) == [
        ["US", "1"],
        ["US", "3"],
    ]
    assert rows_of(read(workdir / "out/country=FR/part-00000.csv")) == [["FR", "2"]]


# Phrase: "Emit directory tree ... using Hive-style segments: <col1>=<val1>/<col2>=<val2>/"
# Context: Partitioning by Fields, two partition columns.
def test_nested_segments_follow_the_partition_column_order(csv_file, run_tool, workdir):
    csv_file(
        "a.csv",
        "id,country,dt\n1,US,2024-01-01\n2,US,2024-01-02\n3,FR,2024-01-01\n",
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country,dt", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "country=FR/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-02/part-00000.csv",
    ]


# Phrase: "Emit directory tree ... <col1>=<val1>/<col2>=<val2>"
# Context: Partitioning by Fields. The flag's order decides the nesting order.
def test_segment_order_follows_the_flag_not_the_schema(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country,dt\n1,US,2024-01-01\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "dt,country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["dt=2024-01-01/country=US/part-00000.csv"]


# Phrase: "Values derived after casting to resolved schema types"
# Context: Partitioning by Fields. An int column partitions on its canonical spelling.
def test_values_are_the_casted_spelling(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,bucket\n1,007\n2,7\n")
    csv_file(
        "schema.json",
        json.dumps(
            {
                "columns": [
                    {"name": "bucket", "type": "int"},
                    {"name": "id", "type": "int"},
                ]
            }
        ),
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--schema", "schema.json",
        "--partition-by", "bucket", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["bucket=7/part-00000.csv"]
    assert rows_of(read(workdir / "out/bucket=7/part-00000.csv")) == [
        ["7", "1"],
        ["7", "2"],
    ]


# Phrase: "Values derived after casting to resolved schema types"
# Context: Partitioning by Fields. A timestamp partitions on its normalised text.
def test_timestamp_values_are_normalised_before_encoding(
    csv_file, run_tool, workdir
):
    csv_file("a.csv", "id,ts\n1,2024-07-01T09:00:00+02:00\n")
    csv_file(
        "schema.json",
        json.dumps(
            {
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "ts", "type": "timestamp"},
                ]
            }
        ),
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--schema", "schema.json",
        "--partition-by", "ts", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["ts=2024-07-01T07%3A00%3A00Z/part-00000.csv"]


# Phrase: "Values use percent-encoding of UTF-8 bytes for characters outside [A-Za-z0-9._-]"
# Context: Partitioning by Fields. Unreserved characters are kept verbatim.
def test_unreserved_characters_are_not_encoded(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,tag\n1,aZ9._-\n")
    result = run_tool("--output", "out", "--key", "id", "--partition-by", "tag", "a.csv")
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["tag=aZ9._-/part-00000.csv"]


# Phrase: "space → %20"
# Context: Partitioning by Fields.
def test_space_is_encoded_as_percent_20(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,city\n1,New York\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "city", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["city=New%20York/part-00000.csv"]


# Phrase: "`/` encoded as %2F"
# Context: Partitioning by Fields. A slash must not create a nested directory.
def test_slash_is_encoded_and_does_not_nest(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,path\n1,a/b\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "path", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["path=a%2Fb/part-00000.csv"]


# Phrase: "percent-encoding of UTF-8 bytes"
# Context: Partitioning by Fields. Ambiguity T44: one %XX per UTF-8 byte, uppercase hex.
def test_non_ascii_values_encode_every_utf8_byte(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,name\n1,café\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "name", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["name=caf%C3%A9/part-00000.csv"]


# Phrase: "characters outside [A-Za-z0-9._-]"
# Context: Partitioning by Fields. Ambiguity T44: =, % and ~ are all outside the set.
def test_equals_percent_and_tilde_are_encoded(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,raw\n1,a=b%c~d\n")
    result = run_tool("--output", "out", "--key", "id", "--partition-by", "raw", "a.csv")
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["raw=a%3Db%25c%7Ed/part-00000.csv"]


# Phrase: "Null (missing) partition values use literal _null"
# Context: Partitioning by Fields. A column absent from a file is null for its rows.
def test_missing_partition_value_uses_the_null_segment(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n")
    csv_file("b.csv", "id\n2\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv", "b.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "country=US/part-00000.csv",
        "country=_null/part-00000.csv",
    ]
    assert rows_of(read(workdir / "out/country=_null/part-00000.csv")) == [["", "2"]]


# Phrase: "Null (missing) partition values use literal _null"
# Context: Partitioning by Fields. Ambiguity T45: an empty cell is a missing value.
def test_empty_partition_value_uses_the_null_segment(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["country=_null/part-00000.csv"]


# Phrase: "Null (missing) partition values use literal _null"
# Context: Partitioning by Fields. Ambiguity T45: coerce-null makes a bad cast null.
def test_uncastable_partition_value_is_null_under_coerce_null(
    csv_file, run_tool, workdir
):
    csv_file("a.csv", "id,bucket\n1,nope\n")
    csv_file(
        "schema.json",
        json.dumps(
            {
                "columns": [
                    {"name": "bucket", "type": "int"},
                    {"name": "id", "type": "int"},
                ]
            }
        ),
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--schema", "schema.json",
        "--partition-by", "bucket", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["bucket=_null/part-00000.csv"]


# Phrase: "write CSV files named sequentially: part-00000.csv, part-00001.csv, …
#          (zero-padded width 5)"
# Context: Partitioning by Fields, with a row limit forcing a second file.
def test_part_names_are_zero_padded_to_width_five(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n2,US\n3,US\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country",
        "--max-rows-per-file", "1", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "country=US/part-00000.csv",
        "country=US/part-00001.csv",
        "country=US/part-00002.csv",
    ]


# Phrase: "Each file contains header row (resolved schema header)"
# Context: Partitioning by Fields. Every part file repeats the header.
def test_every_part_file_starts_with_the_header(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country,note\n1,US,a\n2,FR,b\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    for name in tree(workdir / "out"):
        assert read(workdir / "out" / name).splitlines()[0] == "country,id,note"


# Phrase: "Must respect size/row-based cutting rules if set ...; otherwise one file
#          per partition"
# Context: Partitioning by Fields, with no cutting rules.
def test_one_file_per_partition_without_cutting_rules(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n" + "".join(f"{i},US\n" for i in range(50)))
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["country=US/part-00000.csv"]
    assert len(rows_of(read(workdir / "out/country=US/part-00000.csv"))) == 50


# Phrase: "Rows for each unique combination of partition column values"
# Context: Partitioning by Fields. Rows are placed by the combination, not by column.
def test_rows_are_grouped_by_the_whole_combination(csv_file, run_tool, workdir):
    csv_file(
        "a.csv",
        "id,country,dt\n1,US,2024-01-01\n2,US,2024-01-02\n3,US,2024-01-01\n",
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country,dt", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    first = read(workdir / "out/country=US/dt=2024-01-01/part-00000.csv")
    second = read(workdir / "out/country=US/dt=2024-01-02/part-00000.csv")
    assert [row[2] for row in rows_of(first)] == ["1", "3"]
    assert [row[2] for row in rows_of(second)] == ["2"]
