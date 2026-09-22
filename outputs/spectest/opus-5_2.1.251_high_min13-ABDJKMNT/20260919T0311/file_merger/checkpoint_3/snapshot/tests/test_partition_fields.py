"""Spec section: Partitioned Output / Partitioning by Fields."""
from conftest import data_rows, lines, parts, tree


# Phrase: "Rows for each unique combination of partition column values go into
#   separate directory"
# Context: one directory per distinct value of a single partition column.
def test_one_directory_per_distinct_value(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n2,FR\n3,US\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["c=FR/part-00000.csv", "c=US/part-00000.csv"]
    assert data_rows(tmp_path / "out" / "c=US" / "part-00000.csv") == [["US", "1"], ["US", "3"]]


# Phrase: "Emit directory tree inside --output using Hive-style segments:
#   <col1>=<val1>/<col2>=<val2>/.../"
# Context: several partition columns nest in the order given to --partition-by.
def test_hive_segments_nest_in_partition_by_order(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c,dt\n1,US,2024-01-01\n2,FR,2024-01-02\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c,dt", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == [
        "c=FR/dt=2024-01-02/part-00000.csv",
        "c=US/dt=2024-01-01/part-00000.csv",
    ]


# Phrase: "Values derived after casting to resolved schema types"
# Context: an int partition column is named by its canonical cast text, so
#   `007` and `7` land in the same directory.
def test_values_use_the_cast_representation(run, csv_file, tmp_path):
    csv_file("a.csv", "id,n\n1,007\n2,7\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "n", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["n=7/part-00000.csv"]


# Phrase: "Values derived after casting to resolved schema types"
# Context: a timestamp partition column is normalized to UTC before encoding.
def test_timestamp_values_are_normalized_before_encoding(run, csv_file, schema_file, tmp_path):
    csv_file("a.csv", "id,ts\n1,2024-01-01T05:00:00+02:00\n")
    schema = schema_file([("id", "int"), ("ts", "timestamp")])
    res = run("--output", "out", "--key", "id", "--partition-by", "ts",
              "--schema", schema, "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["ts=2024-01-01T03%3A00%3A00Z/part-00000.csv"]


# Phrase: "Apply percent-encoding of UTF-8 bytes for characters outside
#   [A-Za-z0-9._-]"
# Context: unreserved characters survive; everything else becomes %XX of its
#   UTF-8 bytes (T41: upper-case hex digits).
def test_percent_encoding_of_partition_values(run, csv_file, tmp_path):
    csv_file("a.csv", 'id,v\n1,"a.b_c-D9"\n2,café\n3,"a=b"\n4,100%\n')
    res = run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert res.returncode == 0, res.stderr
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "v=100%25", "v=a%3Db", "v=a.b_c-D9", "v=caf%C3%A9",
    ]


# Phrase: "space → %20"
# Context: a space never appears raw in a directory name.
def test_space_is_encoded(run, csv_file, tmp_path):
    csv_file("a.csv", 'id,v\n1,"new york"\n')
    res = run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["v=new%20york/part-00000.csv"]


# Phrase: "`/` encoded as %2F"
# Context: a value containing a separator stays a single directory level.
def test_slash_is_encoded_and_does_not_nest(run, csv_file, tmp_path):
    csv_file("a.csv", 'id,v\n1,"a/b"\n')
    res = run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["v=a%2Fb/part-00000.csv"]


# Phrase: "Null (missing) partition values use literal _null"
# Context: T43 - a column absent from a file, an empty cell and a cell spelled
#   as the null literal are all null for partitioning.
def test_null_partition_values(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n1,US\n2,\n")
    csv_file("b.csv", "id\n3\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "v", "a.csv", "b.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["v=US/part-00000.csv", "v=_null/part-00000.csv"]
    assert data_rows(tmp_path / "out" / "v=_null" / "part-00000.csv") == [["2", ""], ["3", ""]]


# Phrase: "Within each partition directory, write CSV files named sequentially:
#   part-00000.csv, part-00001.csv, … (zero-padded width 5)"
# Context: numbering restarts inside every partition directory.
def test_part_numbering_restarts_per_partition(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n2,US\n3,US\n4,FR\n5,FR\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c",
              "--max-rows-per-file", "2", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == [
        "c=FR/part-00000.csv",
        "c=US/part-00000.csv",
        "c=US/part-00001.csv",
    ]


# Phrase: "Each file contains header row (resolved schema header)"
# Context: every part file in every partition repeats the full header.
def test_every_partition_file_has_the_schema_header(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c,v\n1,US,x\n2,FR,y\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    for part in sorted((tmp_path / "out").rglob("part-*.csv")):
        assert lines(part.read_text())[0] == "c,id,v"


# Phrase: "Each file contains header row (resolved schema header)"
# Context: T39 - partition columns stay in the rows, they are not replaced by
#   the directory name.
def test_partition_columns_remain_in_the_rows(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n5,US\n")
    run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert lines((tmp_path / "out" / "c=US" / "part-00000.csv").read_text()) == ["c,id", "US,5"]


# Phrase: "Must respect size/row-based cutting rules if set (see below);
#   otherwise one file per partition"
# Context: with no cutting flags a partition holds exactly one file.
def test_one_file_per_partition_without_cutting_rules(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n" + "".join(f"{i},US\n" for i in range(50)))
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert [p.name for p in parts(tmp_path / "out" / "c=US")] == ["part-00000.csv"]
    assert len(data_rows(tmp_path / "out" / "c=US" / "part-00000.csv")) == 50


# Phrase: "--partition-by <col>[,<col>...]"
# Context: a partition column the resolved schema does not have is a schema
#   error (T45), like an unknown --key column.
def test_unknown_partition_column_fails(run, csv_file):
    csv_file("a.csv", "id\n1\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "nope", "a.csv")
    assert res.returncode == 3, res.stderr
    assert "nope" in res.stderr


# Phrase: "Rows for each unique combination of partition column values"
# Context: T40 - an input with no data rows produces no partition directories.
def test_no_rows_makes_no_partition_directories(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == []
