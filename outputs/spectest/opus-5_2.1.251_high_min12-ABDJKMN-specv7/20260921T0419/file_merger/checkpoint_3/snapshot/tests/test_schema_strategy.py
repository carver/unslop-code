"""Spec section: Schema Resolution Across Heterogeneous Inputs."""
from conftest import body, header


# Phrase: "--schema-strategy {authoritative,consensus,union}"
# Context: Usage; flag choices.
def test_schema_strategy_accepts_all_choices(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    for mode in ("authoritative", "consensus", "union"):
        r = run(
            "--output", "-", "--key", "id", "--schema-strategy", mode,
            work.path("a.csv"),
        )
        assert r.ok, r.stderr


def test_schema_strategy_rejects_unknown_choice(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema-strategy", "bogus", work.path("a.csv")
    )
    assert r.returncode != 0


# Phrase: "`--schema-strategy=authoritative` (default): prefer typed sources in
#          precedence order; JSONL ranks equal to CSV."
# Context: Schema disagreement strategy; Parquet is the typed source that outranks text.
def test_authoritative_prefers_parquet_type(run, work):
    work.parquet("p.parquet", [{"id": 1, "n": 10}])
    work.csv("a.csv", ["id", "n"], [["2", "abc"]])
    r = run(
        "--output", "-", "--key", "id", work.path("p.parquet"), work.path("a.csv")
    )
    assert r.ok, r.stderr
    # parquet says int, so the csv text that cannot cast becomes null
    assert body(r) == [["1", "10"], ["2", ""]]


def test_authoritative_is_the_default(run, work):
    work.parquet("p.parquet", [{"id": 1, "n": 10}])
    work.csv("a.csv", ["id", "n"], [["2", "abc"]])
    default = run(
        "--output", "-", "--key", "id", work.path("p.parquet"), work.path("a.csv")
    )
    explicit = run(
        "--output", "-", "--key", "id", "--schema-strategy", "authoritative",
        work.path("p.parquet"), work.path("a.csv"),
    )
    assert default.ok and explicit.ok, default.stderr + explicit.stderr
    assert default.stdout == explicit.stdout


# Phrase: "JSONL ranks equal to CSV"
# Context: Schema disagreement strategy; neither wins, so the conflict falls back
# to the --infer rule (strict: string).
def test_authoritative_jsonl_does_not_outrank_csv(run, work):
    work.csv("a.csv", ["id", "n"], [["4", "abc"]])
    work.jsonl("b.jsonl", [{"id": 5, "n": 7}])
    r = run("--output", "-", "--key", "id", work.path("a.csv"), work.path("b.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["4", "abc"], ["5", "7"]]


# Phrase: "`--schema-strategy=consensus`: choose type that majority of files support"
# Context: Schema disagreement strategy.
def test_consensus_majority_wins(run, work):
    work.csv("a.csv", ["id", "n"], [["4", "10"]])
    work.csv("b.csv", ["id", "n"], [["5", "20"]])
    work.jsonl("c.jsonl", [{"id": 6, "n": "abc"}])
    r = run(
        "--output", "-", "--key", "id", "--schema-strategy", "consensus",
        work.path("a.csv"), work.path("b.csv"), work.path("c.jsonl"),
    )
    assert r.ok, r.stderr
    # two of three files say int; the string value cannot cast and becomes null
    assert body(r) == [["4", "10"], ["5", "20"], ["6", ""]]


def test_consensus_majority_string(run, work):
    work.csv("a.csv", ["id", "n"], [["4", "abc"]])
    work.csv("b.csv", ["id", "n"], [["5", "def"]])
    work.jsonl("c.jsonl", [{"id": 6, "n": 7}])
    r = run(
        "--output", "-", "--key", "id", "--schema-strategy", "consensus",
        work.path("a.csv"), work.path("b.csv"), work.path("c.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["4", "abc"], ["5", "def"], ["6", "7"]]


# Phrase: "choose type that majority of files support"
# Context: with no majority the type priority list breaks the tie (int > float).
def test_consensus_tie_broken_by_type_priority(run, work):
    work.csv("a.csv", ["id", "n"], [["4", "10"]])
    work.jsonl("b.jsonl", [{"id": 5, "n": 9.5}])
    r = run(
        "--output", "-", "--key", "id", "--schema-strategy", "consensus",
        work.path("a.csv"), work.path("b.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["4", "10"], ["5", ""]]


# Phrase: "`--schema-strategy=union`: choose simplest common type that can hold all
#          observed values"
# Context: Schema disagreement strategy.
def test_union_widens_int_and_float_to_float(run, work):
    work.csv("a.csv", ["id", "n"], [["4", "10"]])
    work.jsonl("b.jsonl", [{"id": 5, "n": 9.5}])
    r = run(
        "--output", "-", "--key", "id", "--schema-strategy", "union",
        work.path("a.csv"), work.path("b.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["4", "10.0"], ["5", "9.5"]]


def test_union_falls_back_to_string(run, work):
    work.csv("a.csv", ["id", "n"], [["4", "10"]])
    work.jsonl("b.jsonl", [{"id": 5, "n": "abc"}])
    r = run(
        "--output", "-", "--key", "id", "--schema-strategy", "union",
        work.path("a.csv"), work.path("b.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["4", "10"], ["5", "abc"]]


def test_union_keeps_agreed_type(run, work):
    work.csv("a.csv", ["id", "n"], [["4", "10"]])
    work.jsonl("b.jsonl", [{"id": 5, "n": 6}])
    r = run(
        "--output", "-", "--key", "id", "--schema-strategy", "union",
        work.path("a.csv"), work.path("b.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["4", "10"], ["5", "6"]]


# Phrase: "If `--schema` provided, it defines exact output columns, types, and order"
# Context: Schema Resolution; the strategy is irrelevant when a schema is given.
def test_explicit_schema_overrides_strategy(run, work):
    work.schema("s.json", [("id", "int"), ("n", "string")])
    work.parquet("p.parquet", [{"id": 1, "n": 10}])
    work.csv("a.csv", ["id", "n"], [["2", "abc"]])
    for mode in ("authoritative", "consensus", "union"):
        r = run(
            "--output", "-", "--key", "id", "--schema", work.path("s.json"),
            "--schema-strategy", mode,
            work.path("p.parquet"), work.path("a.csv"),
        )
        assert r.ok, r.stderr
        assert header(r) == ["id", "n"]
        assert body(r) == [["1", "10"], ["2", "abc"]]


# Phrase: "Column set: union of all encountered field names. Column order: ascending
#          lexicographic by column name"
# Context: Schema Resolution across heterogeneous inputs.
def test_column_union_and_order_across_formats(run, work):
    work.csv("a.csv", ["zed", "id"], [["z", "4"]])
    work.jsonl("b.jsonl", [{"id": 5, "alpha": "a"}])
    work.parquet("c.parquet", [{"id": 6, "mid": "m"}])
    r = run(
        "--output", "-", "--key", "id",
        work.path("a.csv"), work.path("b.jsonl"), work.path("c.parquet"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["alpha", "id", "mid", "zed"]
    assert body(r) == [
        ["", "4", "", "z"],
        ["a", "5", "", ""],
        ["", "6", "m", ""],
    ]


# Phrase: "Keys must exist in resolved schema (error 3 otherwise)"
# Context: Sorting and Stability.
def test_missing_key_column_is_error_3(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", "-", "--key", "nope", work.path("a.csv"))
    assert r.returncode == 3
    assert r.stderr.strip()


def test_key_dropped_by_explicit_schema_is_error_3(run, work):
    work.schema("s.json", [("id", "int")])
    work.jsonl("a.jsonl", [{"id": 1, "ts": "2024-07-01"}])
    r = run(
        "--output", "-", "--key", "ts", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3
