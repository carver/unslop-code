"""Spec section: Sorting, plus the null-ordering rule under Casting & Validation."""
from conftest import column, table


# Phrase: "sorted globally by the key(s)"
# Context: ordering spans files, not just within each file.
def test_sort_is_global_across_files(run, csv_file):
    csv_file("a.csv", "id\n1\n4\n")
    csv_file("b.csv", "id\n2\n3\n")
    res = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert column(res.stdout, "id") == ["1", "2", "3", "4"]


# Phrase: "Default order is ascending"
# Context: ascending is what you get with no --desc.
def test_default_order_is_ascending(run, csv_file):
    csv_file("a.csv", "id\n3\n1\n2\n")
    assert column(run("--output", "-", "--key", "id", "a.csv").stdout, "id") == ["1", "2", "3"]


# Phrase: "--desc applies to all keys"
# Context: every key column reverses together.
def test_desc_reverses_every_key(run, csv_file):
    csv_file("a.csv", "g,n\na,1\na,2\nb,1\nb,2\n")
    res = run("--output", "-", "--key", "g,n", "--desc", "a.csv")
    assert table(res.stdout)[1:] == [["b", "2"], ["b", "1"], ["a", "2"], ["a", "1"]]


# Phrase: "Sort by composite key specified via --key (one or more columns)"
# Context: later key columns break ties in earlier ones.
def test_composite_key_ordering(run, csv_file):
    csv_file("a.csv", "ts,id\n2024-01-02,2\n2024-01-01,9\n2024-01-02,1\n")
    res = run("--output", "-", "--key", "ts,id", "a.csv")
    # Inferred column order is lexicographic, so the row is (id, ts).
    assert table(res.stdout)[1:] == [["9", "2024-01-01"], ["1", "2024-01-02"], ["2", "2024-01-02"]]


# Phrase: "Sort must be stable with respect to input appearance for equal keys"
# Context: ties keep file order (as given on the command line) then row order.
def test_stability_follows_input_appearance(run, csv_file):
    csv_file("a.csv", "k,src\n1,a1\n1,a2\n")
    csv_file("b.csv", "k,src\n1,b1\n1,b2\n")
    res = run("--output", "-", "--key", "k", "b.csv", "a.csv")
    assert column(res.stdout, "src") == ["b1", "b2", "a1", "a2"]


# Phrase: "Sort must be stable ... Default order is ascending; --desc applies to all keys"
# Context: T16 — stability holds in descending order too; ties are not reversed.
def test_stability_holds_under_desc(run, csv_file):
    csv_file("a.csv", "k,src\n1,a1\n1,a2\n")
    csv_file("b.csv", "k,src\n1,b1\n1,b2\n")
    res = run("--output", "-", "--key", "k", "--desc", "b.csv", "a.csv")
    assert column(res.stdout, "src") == ["b1", "b2", "a1", "a2"]


# Phrase: "Nulls always compare less than non-null values ... (first in ascending)"
# Context: ascending order puts nulls at the top.
def test_nulls_sort_first_ascending(run, csv_file):
    csv_file("a.csv", "k,src\n2,x\n,y\n1,z\n")
    res = run("--output", "-", "--key", "k", "a.csv")
    assert column(res.stdout, "src") == ["y", "z", "x"]


# Phrase: "Nulls always compare less than non-null values, regardless of sort
#   direction (... last in descending)"
# Context: --desc moves nulls to the bottom rather than the top.
def test_nulls_sort_last_descending(run, csv_file):
    csv_file("a.csv", "k,src\n2,x\n,y\n1,z\n")
    res = run("--output", "-", "--key", "k", "--desc", "a.csv")
    assert column(res.stdout, "src") == ["x", "z", "y"]


# Phrase: "Nulls always compare less than non-null values"
# Context: a column missing from a file is null for those rows.
def test_absent_key_column_rows_are_null_keyed(run, csv_file):
    csv_file("a.csv", "k,src\n5,present\n")
    csv_file("b.csv", "src\nabsent\n")
    res = run("--output", "-", "--key", "k", "a.csv", "b.csv")
    assert column(res.stdout, "src") == ["absent", "present"]


# Phrase: "sorted globally by the key(s)"
# Context: an int key compares numerically, not as text.
def test_int_key_compares_numerically(run, csv_file):
    csv_file("a.csv", "k\n2\n10\n")
    assert column(run("--output", "-", "--key", "k", "a.csv").stdout, "k") == ["2", "10"]


# Phrase: "sorted globally by the key(s)"
# Context: a string key compares lexicographically.
def test_string_key_compares_lexicographically(run, csv_file, schema_file):
    schema = schema_file([("k", "string")])
    csv_file("a.csv", "k\n2\n10\n")
    res = run("--output", "-", "--key", "k", "--schema", schema, "a.csv")
    assert column(res.stdout, "k") == ["10", "2"]


# Phrase: "timestamp: ... normalize to UTC"
# Context: timestamps compare as instants, across differing source offsets.
def test_timestamp_key_compares_as_instants(run, csv_file, schema_file):
    schema = schema_file([("t", "timestamp"), ("src", "string")])
    csv_file("a.csv", "t,src\n2024-07-01T12:00:00+02:00,later\n2024-07-01T09:30:00Z,earlier\n")
    res = run("--output", "-", "--key", "t", "--schema", schema, "a.csv")
    assert column(res.stdout, "src") == ["earlier", "later"]


# Phrase: "Sort by composite key"
# Context: a bool key orders false before true.
def test_bool_key_orders_false_before_true(run, csv_file, schema_file):
    schema = schema_file([("b", "bool"), ("src", "string")])
    csv_file("a.csv", "b,src\n1,yes\n0,no\n")
    res = run("--output", "-", "--key", "b", "--schema", schema, "a.csv")
    assert column(res.stdout, "src") == ["no", "yes"]


# Phrase: "keep-string: emit original text as string"
# Context: T8 — kept text sorts after every well-typed value, ascending.
def test_keep_string_values_sort_after_typed_values(run, csv_file, schema_file):
    schema = schema_file([("k", "int"), ("src", "string")])
    csv_file("a.csv", "k,src\nzz,kept\n10,ten\n,null\n2,two\n")
    res = run("--output", "-", "--key", "k", "--schema", schema, "--on-type-error", "keep-string", "a.csv")
    assert column(res.stdout, "src") == ["null", "two", "ten", "kept"]


# Phrase: "--key <col>[,<col>...]"
# Context: a single key column is the degenerate composite key.
def test_single_key_column(run, csv_file):
    csv_file("a.csv", "id,v\n2,b\n1,a\n")
    res = run("--output", "-", "--key", "id", "a.csv")
    assert column(res.stdout, "v") == ["a", "b"]


# Phrase: "Sort by composite key specified via --key"
# Context: the key column need not be first in the output.
def test_key_column_position_is_independent_of_order(run, csv_file, schema_file):
    schema = schema_file([("v", "string"), ("id", "int")])
    csv_file("a.csv", "id,v\n2,b\n1,a\n")
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.csv")
    assert table(res.stdout) == [["v", "id"], ["a", "1"], ["b", "2"]]
