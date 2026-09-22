"""Chosen readings of the checkpoint-4 spec (see AMBIGUITIES.md T51-T70)."""
import json

from conftest import (alias_file, array_t, cell, col, map_t, run_tool,
                      struct_t, tree_dirs, write_csv, write_file, write_json,
                      write_jsonl, write_nested_schema)


# --------------------------------------------------------------------------
# T51 — every error line has the shape "ERR <code> <text>".
# Spec text: `ERR 4 cannot cast ...`, `ERR 3 key column ... (exit 3)`
# --------------------------------------------------------------------------
def test_err_prefix_carries_the_exit_code(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "u", "--schema", schema, src)
    assert res.returncode == 3
    assert res.stderr.startswith("ERR 3 ")
    assert res.stderr.count("\n") == 1


def test_err_prefix_on_error_6(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6
    assert res.stderr.startswith("ERR 6 ")


def test_err_prefix_on_error_2(tmp_path):
    aliases = alias_file(tmp_path / "al.json", {"x": "y", "y": "x"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "int"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 2
    assert res.stderr.startswith("ERR 2 ")


# --------------------------------------------------------------------------
# T54 — objects inside a `json` value have their keys sorted.
# Spec text: "For json type: accept any JSON value without casting;
#             normalize only"
# --------------------------------------------------------------------------
def test_json_object_keys_are_sorted(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "v": {"z": 1, "a": {"y": 1, "b": 2}}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "v") == '{"a":{"b":2,"y":1},"z":1}'


# --------------------------------------------------------------------------
# T55 — invalid JSON for a nested target under `fail` is a cast error (4).
# Spec text: "Invalid JSON -> handled per --on-type-error/error 5"
# --------------------------------------------------------------------------
def test_invalid_json_under_fail_exits_4(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_csv(tmp_path / "a.csv", ["id,t", "1,[1,"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 4
    assert res.stderr.startswith("ERR 4 ")


# --------------------------------------------------------------------------
# T56 — a nested Parquet column declared flat follows --on-type-error.
# (covered for Parquet in test_nested_input.py; here for keep-string)
# --------------------------------------------------------------------------
def test_nested_against_flat_keeps_canonical_json_text(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "string"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": [2, 1]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "keep-string", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["[2,1]"]


# --------------------------------------------------------------------------
# T59 — the Hive label of a nested partition is the path as written.
# Spec text: "--partition-by attrs["country"]"
# --------------------------------------------------------------------------
def test_partition_label_is_the_whole_path(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("attrs", map_t("string")))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "attrs": {"country": "US"}}])
    out = tmp_path / "out"
    res = run_tool("--output", str(out), "--key", "id",
                   "--partition-by", 'attrs["country"]',
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert tree_dirs(out) == ['attrs["country"]=US']


# --------------------------------------------------------------------------
# T60 — undeclared members of an input struct are dropped.
# Spec text: "All struct fields included (even when null)"
# --------------------------------------------------------------------------
def test_undeclared_struct_members_are_dropped(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "u": {"a": 1, "extra": 9}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":1}'


# --------------------------------------------------------------------------
# T61 — a cyclic alias is rejected even when the schema never uses it, while
# an unknown alias target only fails where it is used.
# --------------------------------------------------------------------------
def test_cycle_detected_without_any_schema(tmp_path):
    aliases = alias_file(tmp_path / "al.json", {"x": "y", "y": "x"})
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a",
                   "--type-alias-file", aliases, src)
    assert res.returncode == 2


def test_unused_unknown_alias_target_is_harmless(tmp_path):
    aliases = alias_file(tmp_path / "al.json", {"weird": "widget"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "int"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 0, res.stderr


# --------------------------------------------------------------------------
# T62 — paths never enter a `json` column (static resolution).
# --------------------------------------------------------------------------
def test_json_column_itself_is_not_a_primitive_key(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": 5}])
    res = run_tool("--output", "-", "--key", "v", "--schema", schema, src)
    assert res.returncode == 3


# --------------------------------------------------------------------------
# T63 — bracket syntax is for maps only, dots for structs only.
# --------------------------------------------------------------------------
def test_bracket_on_a_struct_is_an_error(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run_tool("--output", "-", "--key", 'u["a"]', "--schema", schema,
                   src)
    assert res.returncode == 3


def test_bracket_on_an_array_is_an_error(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("t", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [1]}])
    res = run_tool("--output", "-", "--key", 't["0"]', "--schema", schema,
                   src)
    assert res.returncode == 3


# --------------------------------------------------------------------------
# T66 — only a value that is itself null prints the CSV null literal.
# --------------------------------------------------------------------------
def test_json_null_value_is_the_null_literal_not_the_text_null(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": None}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "id,v\n1,\n"


# --------------------------------------------------------------------------
# T67 — malformed path syntax is exit 3, like every other key problem.
# --------------------------------------------------------------------------
def test_empty_path_segment_is_error_3(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "u..a", "--schema", schema, src)
    assert res.returncode == 3


def test_unterminated_bracket_is_error_3(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("m", map_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"a": 1}}])
    res = run_tool("--output", "-", "--key", 'm["a"', "--schema", schema, src)
    assert res.returncode == 3


# --------------------------------------------------------------------------
# T70 — non-string map keys from Parquet are stringified, not discarded.
# (JSON objects always have string keys, so this only shows up via Parquet;
#  the JSONL side is pinned here through the textual form.)
# --------------------------------------------------------------------------
def test_numeric_looking_map_keys_sort_as_text(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("m", map_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "m": {"10": 1, "9": 2, "1": 3}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '{"1":3,"10":1,"9":2}'


# --------------------------------------------------------------------------
# T16 carried forward — a repeated field path is used once.
# --------------------------------------------------------------------------
def test_repeated_key_path_is_deduplicated(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 2, "u": {"a": 1}},
                                             {"id": 1, "u": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "u.a,u.a", "--schema", schema,
                   src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "1"]


# --------------------------------------------------------------------------
# Determinism checklist — "External sort/merge ... continue from prior
# checkpoints": nested values survive a spill to disk.
# --------------------------------------------------------------------------
def test_nested_values_survive_the_external_sort(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))),
                                 ("m", map_t("string")))
    rows = [{"id": n, "u": {"a": n}, "m": {"k": "v%d" % n}}
            for n in range(300, 0, -1)]
    src = write_jsonl(tmp_path / "a.jsonl", rows)
    res = run_tool("--output", "-", "--key", "u.a", "--schema", schema,
                   "--memory-limit-mb", "1", src)
    assert res.returncode == 0, res.stderr
    out = res.rows()
    assert col(out, "id")[:3] == ["1", "2", "3"]
    assert cell(out, "u") == '{"a":1}'
    assert cell(out, "m") == '{"k":"v1"}'
