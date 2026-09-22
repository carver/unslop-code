"""Chosen readings for under-specified points (AMBIGUITIES.md T37-T50)."""
import os

from conftest import (run_tool, write_csv, write_jsonl, write_schema,
                      read_rows, read_text,
                      part_files, tree_files, tree_dirs, concat_body, col)


# T37 - "When any partitioning flag provided"
# Context: all three new flags count; the usage error exits 2.
def test_partitioning_flag_set_is_the_three_new_flags(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,x"])
    for flag, value in (("--partition-by", "c"),
                        ("--max-rows-per-file", "5"),
                        ("--max-bytes-per-file", "500")):
        res = run_tool("--output", "-", "--key", "id", flag, value, src)
        assert res.returncode == 2, (flag, res.returncode, res.stderr)


# T37 - flags unrelated to partitioning keep single-file output
# Context: --desc alone must not switch to directory mode.
def test_desc_alone_is_not_a_partitioning_flag(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1", "2"])
    res = run_tool("--output", "-", "--key", "id", "--desc", src)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "id\n2\n1\n"


# T39 - percent-encoding uses uppercase hex digits
# Context: %2F and %20 in the spec are uppercase, so \x7f -> %7F not %7f.
def test_percent_encoding_uppercase_hex(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,a?b"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["c=a%3Fb"]


# T39 - only the value is encoded, never the column name
# Context: a column name containing a space stays verbatim in the segment.
def test_column_name_not_percent_encoded(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['id,"my col"', "1,x"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "my col", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["my col=x"]


# T39 - the segment value is the rendered (post-cast) cell text
# Context: a timestamp renders in ISO form, whose ':' is then encoded.
def test_timestamp_partition_value_is_rendered_then_encoded(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["id,ts", "1,2024-01-02T03:04:05Z"])
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("ts", "timestamp")])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--schema", schema,
                   "--partition-by", "ts", src)
    assert res.returncode == 0, res.stderr
    dirs = tree_dirs(out)
    assert len(dirs) == 1
    assert dirs[0].startswith("ts=2024-01-02T03%3A04%3A05")


# T40 - a cell is a null partition value exactly when it renders as the
# configured null literal
# Context: the literal string "_null" therefore shares the null directory.
def test_literal_underscore_null_shares_null_directory(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,_null", "2,"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ["c=_null"]
    assert col(read_rows(out / "c=_null" / "part-00000.csv"),
               "id") == ["1", "2"]


# T40 - nullness comes from the value, not from its rendered text
# Context: a JSONL empty string is not missing (T33), so it gets its own
# empty segment while an omitted field gets _null.
def test_typed_empty_string_is_not_the_null_partition(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "c": ""}, {"id": 2}])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["c=", "c=_null"]


# T40 - every CSV cell that the tool treats as missing maps to _null
# Context: with --csv-null-literal NULL both "" and "NULL" are missing.
def test_csv_empty_and_null_literal_share_null_partition(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,", "2,NULL", "3,us"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--csv-null-literal", "NULL", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["c=_null", "c=us"]
    assert col(read_rows(out / "c=_null" / "part-00000.csv"),
               "id") == ["1", "2"]


# T41 - the output directory is replaced, not merged into
# Context: files left by an earlier run do not survive the next one.
def test_existing_output_contents_replaced(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("old\n", encoding="utf-8")
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "5", src)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == ["part-00000.csv"]


# T43 - zero data rows with sharding only
# Context: one header-only part file, mirroring the single-CSV behaviour.
def test_empty_input_sharding_only_writes_header_file(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,v"])
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--schema", schema,
                   "--max-rows-per-file", "5", src)
    assert res.returncode == 0, res.stderr
    assert part_files(out) == ["part-00000.csv"]
    assert read_text(out / "part-00000.csv") == "id,v\n"


# T43 - zero data rows with field partitioning
# Context: no partition exists, so the output directory is created empty.
def test_empty_input_field_partitioning_empty_directory(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c"])
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("c", "string")])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--schema", schema,
                   "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    assert out.is_dir()
    assert tree_files(out) == []


# T46 - duplicate partition columns are collapsed
# Context: --partition-by c,c nests only one level.
def test_duplicate_partition_columns_collapsed(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,x"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "c,c", src)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == ["c=x/part-00000.csv"]


# T46 - --partition-by may be repeated and accumulates left to right
# Context: two flags behave like one comma separated list.
def test_partition_by_flag_repeats_accumulate(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,a,b", "1,x,y"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "a", "--partition-by", "b", src)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == ["a=x/b=y/part-00000.csv"]


# T46 - an empty partition column name is rejected
# Context: --partition-by "a," has a trailing empty entry.
def test_empty_partition_column_name_rejected(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,a", "1,x"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "a,", src)
    assert res.returncode == 3, (res.returncode, res.stderr)


# T47 - negative shard limits are usage errors
# Context: both limits must be positive integers.
def test_negative_limits_rejected(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    out = tmp_path / "out"
    for flag in ("--max-rows-per-file", "--max-bytes-per-file"):
        res = run_tool("--output", out, "--key", "id", flag, "-5", src)
        assert res.returncode == 2, (flag, res.returncode, res.stderr)


# T47 - a non-integer shard limit is an argparse usage error
# Context: argparse rejects it with exit code 2.
def test_non_integer_limit_rejected(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "big", src)
    assert res.returncode == 2, (res.returncode, res.stderr)


# T42 - a byte limit smaller than the header alone
# Context: each file still carries the header and exactly one row.
def test_byte_limit_below_header_size(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["identifier", "1", "2"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "identifier",
                   "--max-bytes-per-file", "3", src)
    assert res.returncode == 0, res.stderr
    assert part_files(out) == ["part-00000.csv", "part-00001.csv"]
    assert read_text(out / "part-00000.csv") == "identifier\n1\n"


# T50 - directory mode reports failures on stderr with the usual shape
# Context: the "ERR <code> " prefix (T51) and a non-zero exit code.
def test_error_message_shape(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,x"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "nope", src)
    assert res.returncode == 3
    assert res.stderr.startswith("ERR 3 ")
    assert res.stderr.endswith("\n")


# T38 - partition columns are part of the resolved schema header
# Context: the header is identical in single-file and partitioned modes.
def test_header_identical_to_single_file_mode(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c,v", "1,x,9"])
    single = run_tool("--output", "-", "--key", "id", src)
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert read_rows(out / "c=x" / "part-00000.csv")[0] == single.rows()[0]
