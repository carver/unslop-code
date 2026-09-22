"""Spec section: Nested Types Support — "Determinism Checklist"."""

import os

from conftest import (array_t, body, col, map_t, run, run_ok, struct_t, write,
                      write_aliases, write_jsonl, write_nested_schema)


# --- Spec: "Nested casting/normalization yields canonical JSON per ordering
#           rules" ---
# Context: Determinism Checklist; two runs of the same input agree.
def test_repeated_runs_are_byte_identical(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("m", map_t("int")),
        ("u", struct_t(("b", "int"), ("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 2, "m": {"z": 1, "a": 2}, "u": {"a": 1, "b": 2}},
        {"id": 1, "m": {"b": 3}, "u": {"b": 4}},
    ])
    first = run_ok("--output", "-", "--key", "id", "--schema", s, a).stdout
    second = run_ok("--output", "-", "--key", "id", "--schema", s, a).stdout
    assert first == second


# --- Spec: "CSV null literal applies only when entire cell is null" ---
# Context: Determinism Checklist.
def test_null_literal_only_for_entirely_null_cells(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": None},
                                     {"id": 2, "xs": [None]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NA", a)
    assert col(res.stdout, "xs") == ["NA", "[null]"]


# --- Spec: "External sort/merge, partitioning, stability, and exit
#           codes/messages continue from prior checkpoints" ---
# Context: Determinism Checklist; spilling with nested columns present.
def test_external_sort_with_nested_columns(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("n", "int"), ("pad", "string")))])
    rows = [{"id": i, "u": {"n": (i * 7919) % 500, "pad": "p" * 40}}
            for i in range(500)]
    a = write_jsonl(ws / "a.jsonl", rows)
    res = run_ok("--output", "-", "--key", "u.n,id", "--schema", s,
                 "--memory-limit-mb", "1", a)
    got = [int(c) for c in col(res.stdout, "id")]
    expected = [r["id"] for r in sorted(rows, key=lambda r: (r["u"]["n"],
                                                             r["id"]))]
    assert got == expected


# --- Spec: "stability ... continue from prior checkpoints" ---
# Context: Determinism Checklist; equal nested fragments keep input order.
def test_stability_with_nested_keys(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("g", "string")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 3, "u": {"g": "k"}},
                                     {"id": 1, "u": {"g": "k"}},
                                     {"id": 2, "u": {"g": "k"}}])
    res = run_ok("--output", "-", "--key", "u.g", "--schema", s, a)
    assert col(res.stdout, "id") == ["3", "1", "2"]


# --- Spec: "Alias resolution is case-insensitive, transitive, cycle-checked" ---
# Context: Determinism Checklist; a cycle is reported even when unused (T68).
def test_unused_alias_cycle_is_still_error_2(ws):
    al = write_aliases(ws / "al.json", {"p": "q", "q": "p"})
    s = write_nested_schema(ws / "s.json", [("id", "int")])
    x = write(ws / "x.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--type-alias-file", al, x)
    assert res.returncode == 2


# --- Spec: "Optional alias file via `--type-alias-file <ALIASES_JSON>`" ---
# Context: Type Aliases; a missing alias file is an I/O error (T84).
def test_missing_alias_file_is_an_error(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int")])
    x = write(ws / "x.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--type-alias-file", str(ws / "nope.json"), x)
    assert res.returncode != 0
    assert res.stderr != ""


# --- Spec: "Optional alias file via `--type-alias-file <ALIASES_JSON>`:
#           {"aliases": {...}}" ---
# Context: Type Aliases; a malformed alias document is rejected (T84).
def test_malformed_alias_file_is_an_error(ws):
    bad = write(ws / "al.json", "{\"aliases\": 5}")
    s = write_nested_schema(ws / "s.json", [("id", "int")])
    x = write(ws / "x.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--type-alias-file", bad, x)
    assert res.returncode != 0


# --- Spec: "Without `--schema`, nested inputs rejected (error 6)" ---
# Context: Determinism Checklist; the alias file alone does not enable nesting.
def test_alias_file_without_schema_does_not_allow_nesting(ws):
    al = write_aliases(ws / "al.json", {"smallint": "int"})
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run("--output", "-", "--key", "id", "--type-alias-file", al, a)
    assert res.returncode == 6


# --- Spec: "Inferred columns remain flat" ---
# Context: Schema Inference (Unchanged, Flat-Only); alias file is harmless.
def test_alias_file_without_schema_is_accepted(ws):
    al = write_aliases(ws / "al.json", {"smallint": "int"})
    x = write(ws / "x.csv", "id,v\n7,a\n")
    res = run_ok("--output", "-", "--key", "id", "--type-alias-file", al, x)
    assert body(res.stdout) == ["7,a"]


# --- Spec: "Dotted/bracketed field paths resolve to primitives or error 3" ---
# Context: Determinism Checklist; the check happens before any data is read.
def test_path_check_precedes_reading_data(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [])
    res = run("--output", "-", "--key", "u", "--schema", s, a)
    assert res.returncode == 3
