"""Spec section: Schema Resolution Across Heterogeneous Inputs."""

from conftest import (body, col, header, pa, run, run_ok, write, write_jsonl,
                      write_parquet, write_schema, write_tsv)


# --- Spec: "If `--schema` provided, it defines exact output columns, types,
#            and order" ---
# Context: Schema Resolution; holds across formats.
def test_provided_schema_defines_columns_and_order_across_formats(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "amt": 2, "extra": "x"}])
    b = write(ws / "b.csv", "amt,id\n3.5,2\n")
    s = write_schema(ws / "s.json", [("id", "int"), ("amt", "float")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a, b)
    assert header(res.stdout) == ["id", "amt"]
    assert body(res.stdout) == ["1,2.0", "2,3.5"]


# --- Spec: "Extra input columns ignored" ---
# Context: Schema Resolution with --schema.
def test_provided_schema_ignores_extra_columns(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "junk": "j"}])
    s = write_schema(ws / "s.json", [("id", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert header(res.stdout) == ["id"]


# --- Spec: "missing columns filled with null literal" ---
# Context: Schema Resolution with --schema.
def test_provided_schema_fills_missing_columns(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1}])
    s = write_schema(ws / "s.json", [("id", "int"), ("absent", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NA", a)
    assert body(res.stdout) == ["1,NA"]


# --- Spec: "If `--schema` not provided ... Column set: union of all
#            encountered field names" ---
# Context: Schema Resolution; names come from every format.
def test_inferred_column_set_is_the_union(ws):
    a = write(ws / "a.csv", "b,a\n1,2\n")
    b = write_jsonl(ws / "b.jsonl", [{"c": 3, "a": 4}])
    c = write_parquet(ws / "c.parquet", {"d": [5], "a": [6]})
    res = run_ok("--output", "-", "--key", "a", a, b, c)
    assert header(res.stdout) == ["a", "b", "c", "d"]


# --- Spec: "Column order: ascending lexicographic by column name" ---
# Context: Schema Resolution when inferring.
def test_inferred_column_order_is_lexicographic(ws):
    a = write_jsonl(ws / "a.jsonl", [{"zz": 1, "Ab": 2, "aa": 3, "id": 4}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["Ab", "aa", "id", "zz"]


# --- Spec: "Type inference per `--infer` mode (strict or loose)" ---
# Context: Schema Resolution; a single CSV source behaves as in checkpoint 1.
def test_inference_still_applies_to_single_csv(ws):
    a = write(ws / "a.csv", "id,amt\n2,1.5\n10,2\n")
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "id") == ["2", "10"]
    assert col(res.stdout, "amt") == ["1.5", "2.0"]


# --- Spec: "--schema-strategy=authoritative (default): prefer typed sources in
#            precedence order" ---
# Context: Schema disagreement; JSONL's typed int beats CSV text (see T31).
def test_authoritative_prefers_jsonl_over_csv(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": 5}])
    b = write(ws / "b.csv", "id,v\n2,007\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    # The JSONL source types `v` as int, so the CSV "007" casts to 7.
    assert col(res.stdout, "v") == ["5", "7"]


# --- Spec: "prefer typed sources in precedence order" ---
# Context: Schema disagreement; Parquet outranks JSONL (see T31).
def test_authoritative_prefers_parquet_over_jsonl(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()), ("v", pyarrow.string())])
    a = write_parquet(ws / "a.parquet", {"id": [1], "v": ["abc"]}, schema=schema)
    b = write_jsonl(ws / "b.jsonl", [{"id": 2, "v": 9}])
    res = run_ok("--output", "-", "--key", "id", a, b)
    # Parquet declares `v` as string, so the JSONL 9 renders as text "9".
    assert col(res.stdout, "v") == ["abc", "9"]


# --- Spec: "prefer typed sources in precedence order" ---
# Context: Schema disagreement; with only CSV inputs this is checkpoint 1's
# strict rule — conflicting types fall back to string (see T34).
def test_authoritative_strict_csv_conflict_falls_back_to_string(ws):
    a = write(ws / "a.csv", "id,v\n1,5\n")
    b = write(ws / "b.csv", "id,v\n2,hello\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert col(res.stdout, "v") == ["5", "hello"]


# --- Spec: "--schema-strategy=consensus: choose type that majority of files
#            support" ---
# Context: Schema disagreement; two int files outvote one string file.
def test_consensus_majority_wins(ws):
    a = write(ws / "a.csv", "id,v\n1,10\n")
    b = write(ws / "b.csv", "id,v\n2,20\n")
    c = write(ws / "c.csv", "id,v\n3,zzz\n")
    res = run_ok("--output", "-", "--key", "v", "--schema-strategy", "consensus",
                 a, b, c)
    # `v` resolves to int; the non-numeric value becomes null (coerce-null),
    # and nulls sort first.
    assert col(res.stdout, "v") == ["", "10", "20"]


# --- Spec: "choose type that majority of files support" ---
# Context: Schema disagreement; a lone typed source does not outvote two
# agreeing text sources.
def test_consensus_outvotes_a_single_typed_source(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": "text"}])
    b = write(ws / "b.csv", "id,v\n2,10\n")
    c = write(ws / "c.csv", "id,v\n3,20\n")
    res = run_ok("--output", "-", "--key", "id", "--schema-strategy", "consensus",
                 a, b, c)
    assert col(res.stdout, "v") == ["", "10", "20"]


# --- Spec: "--schema-strategy=union: choose simplest common type that can hold
#            all observed values" ---
# Context: Schema disagreement; int + float widens to float (see T33).
def test_union_widens_int_and_float_to_float(ws):
    a = write(ws / "a.csv", "id,v\n1,3\n")
    b = write(ws / "b.csv", "id,v\n2,2.5\n")
    res = run_ok("--output", "-", "--key", "id", "--schema-strategy", "union",
                 a, b)
    assert col(res.stdout, "v") == ["3.0", "2.5"]


# --- Spec: "choose simplest common type that can hold all observed values" ---
# Context: Schema disagreement; nothing but string holds a number and a word.
def test_union_falls_back_to_string(ws):
    a = write(ws / "a.csv", "id,v\n1,3\n")
    b = write(ws / "b.csv", "id,v\n2,word\n")
    res = run_ok("--output", "-", "--key", "id", "--schema-strategy", "union",
                 a, b)
    assert col(res.stdout, "v") == ["3", "word"]


# --- Spec: "choose simplest common type that can hold all observed values" ---
# Context: Schema disagreement; a typed JSONL int plus CSV floats widen.
def test_union_across_formats(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": 3}])
    b = write(ws / "b.csv", "id,v\n2,2.5\n")
    res = run_ok("--output", "-", "--key", "id", "--schema-strategy", "union",
                 a, b)
    assert col(res.stdout, "v") == ["3.0", "2.5"]


# --- Spec: "--schema-strategy {authoritative,consensus,union}" ---
# Context: Usage; unknown values are rejected by the CLI.
def test_unknown_schema_strategy_is_rejected(ws):
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--schema-strategy", "vote", a)
    assert res.returncode == 2


# --- Spec: "If `--schema` provided, it defines exact output columns, types,
#            and order" ---
# Context: Schema Resolution; --schema-strategy is inert when a schema is given.
def test_schema_strategy_ignored_when_schema_given(ws):
    a = write(ws / "a.csv", "id,v\n1,3\n")
    b = write_jsonl(ws / "b.jsonl", [{"id": 2, "v": "x"}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--schema-strategy", "consensus", a, b)
    assert col(res.stdout, "v") == ["3", "x"]


# --- Spec: "Type inference per `--infer` mode" combined with the strategy ---
# Context: Schema Resolution; loose widening among equally-ranked sources (T34).
def test_infer_loose_widens_conflicting_csv_sources(ws):
    a = write(ws / "a.csv", "id,v\n1,3\n")
    b = write(ws / "b.csv", "id,v\n2,2.5\n")
    res = run_ok("--output", "-", "--key", "id", "--infer", "loose", a, b)
    assert col(res.stdout, "v") == ["3.0", "2.5"]


# --- Spec: "Column set: union of all encountered field names" ---
# Context: Schema Resolution; a column present in only one file is filled with
# nulls elsewhere.
def test_columns_absent_from_a_source_are_null(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "only_a": "x"}])
    b = write(ws / "b.csv", "id\n2\n")
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "NA", a, b)
    assert header(res.stdout) == ["id", "only_a"]
    assert body(res.stdout) == ["1,x", "2,NA"]


# --- Spec: "prefer typed sources in precedence order" ---
# Context: Schema disagreement; TSV is a text source like CSV.
def test_tsv_is_a_text_source_for_precedence(ws):
    a = write_tsv(ws / "a.tsv", ["id", "v"], [["1", "0012"]])
    b = write_jsonl(ws / "b.jsonl", [{"id": 2, "v": 7}])
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert col(res.stdout, "v") == ["12", "7"]


# --- Spec: "Column set: union of all encountered field names" + Parquet types ---
# Context: Schema Resolution; a Parquet timestamp column types the merged column
# and a CSV ISO string casts into it.
def test_parquet_declared_type_casts_csv_text(ws):
    import datetime as dt
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("ts", pyarrow.timestamp("us"))])
    a = write_parquet(ws / "a.parquet",
                      {"id": [1], "ts": [dt.datetime(2024, 7, 1, 12)]},
                      schema=schema)
    b = write(ws / "b.csv", "id,ts\n2,2024-07-02\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert col(res.stdout, "ts") == ["2024-07-01T12:00:00Z",
                                     "2024-07-02T00:00:00Z"]
