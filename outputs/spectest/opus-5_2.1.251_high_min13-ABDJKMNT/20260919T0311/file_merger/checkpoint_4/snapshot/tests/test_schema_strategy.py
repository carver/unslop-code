"""Spec section: Schema Resolution Across Heterogeneous Inputs."""
import pyarrow as pa
from conftest import column, table


# Phrase: "--schema-strategy=authoritative (default): prefer typed sources in precedence order"
# Context: T21 — JSONL outranks CSV, so its string type wins and CSV text is not
#   renormalised (007 stays 007 instead of becoming 7).
def test_authoritative_prefers_jsonl_over_csv(run, csv_file, jsonl_file):
    csv_file("a.csv", "id,v\n1,007\n")
    jsonl_file("b.jsonl", [{"id": 2, "v": "008"}])
    res = run("--output", "-", "--key", "id", "a.csv", "b.jsonl")
    assert column(res.stdout, "v") == ["007", "008"]


# Phrase: "prefer typed sources in precedence order"
# Context: T21 — Parquet's declared schema outranks JSONL's per-value types.
def test_authoritative_prefers_parquet_over_jsonl(run, parquet_file, jsonl_file):
    parquet_file("a.parquet", {"id": ([1], pa.int64()), "n": ([1.0], pa.float64())})
    jsonl_file("b.jsonl", [{"id": 2, "n": 2}])
    res = run("--output", "-", "--key", "id", "a.parquet", "b.jsonl")
    assert column(res.stdout, "n") == ["1.0", "2.0"]


# Phrase: "--schema-strategy=authoritative (default)"
# Context: the default is authoritative when the flag is omitted.
def test_authoritative_is_the_default(run, csv_file, jsonl_file):
    csv_file("a.csv", "id,v\n1,007\n")
    jsonl_file("b.jsonl", [{"id": 2, "v": "008"}])
    default = run("--output", "-", "--key", "id", "a.csv", "b.jsonl")
    explicit = run("--output", "-", "--key", "id",
                   "--schema-strategy", "authoritative", "a.csv", "b.jsonl")
    assert default.stdout == explicit.stdout


# Phrase: "prefer typed sources in precedence order"
# Context: T24 — with no typed source present, authoritative reproduces the
#   checkpoint 1 rule: disagreeing CSVs under strict fall back to string.
def test_authoritative_on_csv_only_keeps_checkpoint_one_behaviour(run, csv_file):
    csv_file("a.csv", "n,k\n2,1\n")
    csv_file("b.csv", "n,k\n1.50,2\n")
    res = run("--output", "-", "--key", "k", "a.csv", "b.csv")
    assert column(res.stdout, "n") == ["2", "1.50"]


# Phrase: "--schema-strategy=consensus: choose type that majority of files support"
# Context: T22 — two int files outvote one string file.
def test_consensus_takes_the_majority_type(run, csv_file, jsonl_file):
    csv_file("a.csv", "id,v\n1,007\n")
    csv_file("b.csv", "id,v\n2,10\n")
    jsonl_file("c.jsonl", [{"id": 3, "v": "x"}])
    res = run("--output", "-", "--key", "id", "--schema-strategy", "consensus",
              "a.csv", "b.csv", "c.jsonl")
    assert column(res.stdout, "v") == ["7", "10", ""]


# Phrase: "choose type that majority of files support"
# Context: T22 — a plurality is enough; no type here holds an absolute majority.
def test_consensus_takes_a_plurality(run, csv_file):
    csv_file("a.csv", "id,v\n1,1.5\n")
    csv_file("b.csv", "id,v\n2,2.5\n")
    csv_file("c.csv", "id,v\n3,x\n")
    res = run("--output", "-", "--key", "id", "--schema-strategy", "consensus",
              "a.csv", "b.csv", "c.csv")
    assert column(res.stdout, "v") == ["1.5", "2.5", ""]


# Phrase: "choose type that majority of files support"
# Context: T22 — an even split is broken by the checkpoint 1 type priority, so
#   int beats float and the float value fails its cast.
def test_consensus_tie_breaks_by_type_priority(run, csv_file):
    csv_file("a.csv", "id,v\n5,3\n")
    csv_file("b.csv", "id,v\n6,2.5\n")
    res = run("--output", "-", "--key", "id", "--schema-strategy", "consensus",
              "a.csv", "b.csv")
    assert column(res.stdout, "v") == ["3", ""]


# Phrase: "--schema-strategy=union: choose simplest common type that can hold all observed values"
# Context: T23 — int and float widen to float rather than collapsing to string.
def test_union_widens_int_and_float(run, csv_file):
    csv_file("a.csv", "id,v\n1,2\n")
    csv_file("b.csv", "id,v\n2,1.50\n")
    res = run("--output", "-", "--key", "id", "--schema-strategy", "union", "a.csv", "b.csv")
    assert column(res.stdout, "v") == ["2.0", "1.5"]


# Phrase: "choose simplest common type that can hold all observed values"
# Context: T23 — date and timestamp widen to timestamp.
def test_union_widens_date_and_timestamp(run, csv_file):
    csv_file("a.csv", "id,v\n1,2024-07-01\n")
    csv_file("b.csv", "id,v\n2,2024-07-02T06:00:00Z\n")
    res = run("--output", "-", "--key", "id", "--schema-strategy", "union", "a.csv", "b.csv")
    assert column(res.stdout, "v") == ["2024-07-01T00:00:00Z", "2024-07-02T06:00:00Z"]


# Phrase: "choose simplest common type that can hold all observed values"
# Context: T23 — unrelated types have no common type but string.
def test_union_falls_back_to_string(run, csv_file, jsonl_file):
    csv_file("a.csv", "id,v\n1,2\n")
    jsonl_file("b.jsonl", [{"id": 2, "v": "abc"}])
    res = run("--output", "-", "--key", "id", "--schema-strategy", "union", "a.csv", "b.jsonl")
    assert column(res.stdout, "v") == ["2", "abc"]


# Phrase: "choose simplest common type that can hold all observed values"
# Context: T23 — bool does not widen into the numeric tower, because true/false
#   is not an int spelling.
def test_union_does_not_widen_bool_into_int(run, csv_file):
    csv_file("a.csv", "id,v\n1,true\n")
    csv_file("b.csv", "id,v\n2,7\n")
    res = run("--output", "-", "--key", "id", "--schema-strategy", "union", "a.csv", "b.csv")
    assert column(res.stdout, "v") == ["true", "7"]


# Phrase: "If --schema not provided: infer from all inputs ... Column set: union of all
#   encountered field names"
# Context: across formats, not just across CSV headers.
def test_column_set_unions_across_formats(run, csv_file, jsonl_file, parquet_file):
    csv_file("a.csv", "id,c\n1,x\n")
    jsonl_file("b.jsonl", [{"id": 2, "j": "y"}])
    parquet_file("d.parquet", {"id": ([3], pa.int64()), "p": (["z"], pa.string())})
    res = run("--output", "-", "--key", "id", "a.csv", "b.jsonl", "d.parquet")
    assert table(res.stdout)[0] == ["c", "id", "j", "p"]


# Phrase: "Column order: ascending lexicographic by column name"
def test_inferred_column_order_is_lexicographic(run, jsonl_file):
    jsonl_file("a.jsonl", [{"zeta": 1, "Alpha": 2, "mid": 3}])
    assert table(run("--output", "-", "--key", "mid", "a.jsonl").stdout)[0] == [
        "Alpha", "mid", "zeta",
    ]


# Phrase: "Type inference per --infer mode (strict or loose)"
# Context: loose still ignores nulls when typing a heterogeneous set of files.
def test_infer_loose_across_formats(run, csv_file, jsonl_file):
    csv_file("a.csv", "id,n\n1,\n2,10\n")
    jsonl_file("b.jsonl", [{"id": 3, "n": 9}])
    res = run("--output", "-", "--key", "n", "--infer", "loose",
              "--schema-strategy", "union", "a.csv", "b.jsonl")
    assert column(res.stdout, "n") == ["", "9", "10"]
