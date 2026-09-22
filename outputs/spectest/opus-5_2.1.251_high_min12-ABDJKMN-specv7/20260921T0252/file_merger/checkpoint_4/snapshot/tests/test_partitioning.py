"""Spec section: Partitioned Output -> Partitioning by Fields."""
from conftest import (run_tool, write_csv, write_jsonl, write_schema,
                      read_rows, part_files, tree_files, tree_dirs, col,
                      concat_body, concat_col)


# Phrase: "Rows for each unique combination of partition column values go into
#          separate directory"
# Context: one partition column, three distinct values.
def test_one_directory_per_distinct_value(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["id,c", "1,us", "2,de", "3,us", "4,fr"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["c=de", "c=fr", "c=us"]


# Phrase: "Rows for each unique combination of partition column values"
# Context: every row lands in the directory matching its own value.
def test_rows_routed_to_matching_directory(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["id,c", "1,us", "2,de", "3,us", "4,fr"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert col(read_rows(out / "c=us" / "part-00000.csv"), "id") == ["1", "3"]
    assert col(read_rows(out / "c=de" / "part-00000.csv"), "id") == ["2"]
    assert col(read_rows(out / "c=fr" / "part-00000.csv"), "id") == ["4"]


# Phrase: "Emit directory tree inside --output using Hive-style segments:
#          <col1>=<val1>/<col2>=<val2>/.../"
# Context: two partition columns nest in the order they were given.
def test_two_columns_nest_in_flag_order(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["id,country,dt", "1,us,2024-01-01", "2,us,2024-01-02"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "country,dt", src)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == [
        "country=us/dt=2024-01-01/part-00000.csv",
        "country=us/dt=2024-01-02/part-00000.csv",
    ]


# Phrase: "<col1>=<val1>/<col2>=<val2>/.../"
# Context: the nesting order follows --partition-by, not schema order.
def test_nesting_follows_partition_by_order_not_schema(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,a,b", "1,x,y"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--partition-by", "b,a", src)
    assert tree_files(out) == ["b=y/a=x/part-00000.csv"]


# Phrase: "Values derived after casting to resolved schema types"
# Context: an int column partitions on the casted value, so "007" -> "7".
def test_values_are_post_cast(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,n", "1,007", "2,7"])
    schema = write_schema(tmp_path / "s.json", [("id", "int"), ("n", "int")])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--schema", schema,
                   "--partition-by", "n", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["n=7"]
    assert col(read_rows(out / "n=7" / "part-00000.csv"), "id") == ["1", "2"]


# Phrase: "Values derived after casting to resolved schema types"
# Context: a bool column normalises to the rendered form.
def test_bool_partition_values_use_rendered_form(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,f", "1,1", "2,true", "3,0"])
    schema = write_schema(tmp_path / "s.json", [("id", "int"), ("f", "bool")])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--schema", schema,
                   "--partition-by", "f", src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["f=false", "f=true"]


# Phrase: "Values use percent-encoding of UTF-8 bytes for characters outside
#          [A-Za-z0-9._-]"
# Context: unreserved characters are passed through verbatim.
def test_safe_characters_not_encoded(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,aZ9._-"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["c=aZ9._-"]


# Phrase: "space -> %20"
# Context: a literal space in a value.
def test_space_encoded_as_percent_20(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,new york"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["c=new%20york"]


# Phrase: "/ encoded as %2F"
# Context: a slash must not create an extra directory level.
def test_slash_encoded_as_percent_2f(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,a/b"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["c=a%2Fb"]
    assert tree_files(out) == ["c=a%2Fb/part-00000.csv"]


# Phrase: "percent-encoding of UTF-8 bytes"
# Context: non-ASCII characters are encoded byte by byte, uppercase hex.
def test_non_ascii_encoded_per_utf8_byte(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,é"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["c=%C3%A9"]


# Phrase: "percent-encoding of UTF-8 bytes"
# Context: '%' itself is outside the safe set and must be encoded.
def test_percent_sign_itself_encoded(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,100%"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["c=100%25"]


# Phrase: "percent-encoding ... ; / encoded as %2F"
# Context: '=' inside a value must be encoded so the segment stays parseable.
def test_equals_sign_encoded(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", '1,"a=b"'])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["c=a%3Db"]


# Phrase: "Null (missing) partition values use literal _null"
# Context: an empty CSV field is the tool's null and becomes _null.
def test_null_partition_value_directory(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,", "2,us"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["c=_null", "c=us"]
    assert col(read_rows(out / "c=_null" / "part-00000.csv"), "id") == ["1"]


# Phrase: "Null (missing) partition values use literal _null"
# Context: a JSONL row that omits the partition key is missing, not empty.
def test_missing_jsonl_field_is_null_partition(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "c": "us"}, {"id": 2}])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["c=_null", "c=us"]


# Phrase: "Null (missing) partition values use literal _null"
# Context: with a custom null literal, the null cell still maps to _null.
def test_custom_null_literal_still_uses_underscore_null(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,NULL", "2,us"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--csv-null-literal", "NULL", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["c=_null", "c=us"]


# Phrase: "Within each partition directory, write CSV files named
#          sequentially: part-00000.csv, part-00001.csv, ... (zero-padded
#          width 5)"
# Context: the very first file of a partition is part-00000.csv.
def test_first_file_name_is_part_00000(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,us"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert part_files(out / "c=us") == ["part-00000.csv"]


# Phrase: "part-00000.csv, part-00001.csv, ... (zero-padded width 5)"
# Context: the counter restarts at zero inside each partition directory.
def test_part_counter_restarts_per_partition(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["id,c", "1,us", "2,us", "3,de", "4,de"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c",
                   "--max-rows-per-file", "1", src)
    assert res.returncode == 0, res.stderr
    assert part_files(out / "c=us") == ["part-00000.csv", "part-00001.csv"]
    assert part_files(out / "c=de") == ["part-00000.csv", "part-00001.csv"]


# Phrase: "Each file contains header row (resolved schema header)"
# Context: every partition file repeats the full schema header.
def test_every_partition_file_has_header(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c,x", "1,us,a", "2,de,b"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    for part in ("c=us", "c=de"):
        rows = read_rows(out / part / "part-00000.csv")
        assert sorted(rows[0]) == ["c", "id", "x"]
        assert len(rows[1]) == 3


# Phrase: "Each file contains header row (resolved schema header)"
# Context: the header honours the resolved schema column order.
def test_partition_header_follows_schema_order(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["b,a,c", "1,2,x"])
    schema = write_schema(tmp_path / "s.json",
                          [("c", "string"), ("a", "int"), ("b", "int")])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "a", "--schema", schema,
                   "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert read_rows(out / "c=x" / "part-00000.csv")[0] == ["c", "a", "b"]


# Phrase: "Must respect size/row-based cutting rules if set (see below);
#          otherwise one file per partition"
# Context: without any cutting flag each partition holds exactly one file.
def test_one_file_per_partition_without_cutting(tmp_path):
    lines = ["id,c"] + ["%d,%s" % (i, "us" if i % 2 else "de")
                        for i in range(20)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert part_files(out / "c=us") == ["part-00000.csv"]
    assert part_files(out / "c=de") == ["part-00000.csv"]


# Phrase: "Must respect size/row-based cutting rules if set"
# Context: cutting applies inside partition directories too.
def test_cutting_applies_within_partitions(tmp_path):
    lines = ["id,c"] + ["%d,us" % i for i in range(5)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c",
                   "--max-rows-per-file", "2", src)
    assert res.returncode == 0, res.stderr
    assert part_files(out / "c=us") == ["part-00000.csv", "part-00001.csv",
                                        "part-00002.csv"]


# Phrase: "Rows for each unique combination of partition column values go into
#          separate directory"
# Context: the partition column itself stays in the output rows.
def test_partition_column_retained_in_rows(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "7,us"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    rows = read_rows(out / "c=us" / "part-00000.csv")
    assert "c" in rows[0]
    assert rows[1][rows[0].index("c")] == "us"
    assert rows[1][rows[0].index("id")] == "7"


# Phrase: "--partition-by <col>[,<col>...]"
# Context: an unknown partition column is a schema error.
def test_unknown_partition_column_errors(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,us"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "missing", src)
    assert res.returncode == 3, (res.returncode, res.stderr)
    assert res.stderr.startswith("ERR 3 ")


# Phrase: "--partition-by <col>[,<col>...]"
# Context: a partition column may also be a sort key column.
def test_partition_column_may_be_key(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "2", "1"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "id", src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["id=1", "id=2"]


# Phrase: "Rows for each unique combination"
# Context: every input row appears exactly once across the whole tree.
def test_every_row_appears_exactly_once(tmp_path):
    lines = ["id,c"] + ["%d,%s" % (i, "abc"[i % 3]) for i in range(30)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c",
                   "--max-rows-per-file", "4", src)
    assert res.returncode == 0, res.stderr
    seen = []
    for name in sorted(tree_dirs(out)):
        seen.extend(concat_col(out / name, "id"))
    assert sorted(seen, key=int) == [str(i) for i in range(30)]
