"""Conformance tests for nested types (struct / array / map / json)."""
import datetime, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "merge_files.py")

EXIT_TYPE, EXIT_USAGE, EXIT_KEY, EXIT_IO, EXIT_DIALECT, EXIT_NESTED = 1, 2, 3, 4, 5, 6

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None


def run(args, expect=0):
    p = subprocess.run([sys.executable, SCRIPT] + args, capture_output=True,
                       text=True)
    if p.returncode != expect:
        raise AssertionError("exit %d (want %d)\nSTDERR: %s"
                             % (p.returncode, expect, p.stderr))
    return p


STRUCT_SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {"name": "user", "type": {"struct": {"fields": [
            {"name": "name", "type": "string"},
            {"name": "age", "type": "int"},
            {"name": "prefs", "type": {"map": {"key": "string",
                                               "value": "string"}}},
        ]}}},
        {"name": "items", "type": {"array": {"element": {"struct": {"fields": [
            {"name": "sku", "type": "string"},
            {"name": "qty", "type": "int"},
        ]}}}}},
        {"name": "attrs", "type": {"map": {"key": "string",
                                           "value": "string"}}},
        {"name": "event_time", "type": "timestamp"},
    ]
}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def w(self, name, text):
        p = os.path.join(self.d, name)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return p

    def jsonl(self, name, objs):
        return self.w(name, "".join(json.dumps(o) + "\n" for o in objs))

    def schema(self, doc, name="schema.json"):
        return self.w(name, json.dumps(doc))

    def aliases(self, table):
        return self.w("aliases.json", json.dumps({"aliases": table}))

    def lines(self, out):
        return out.rstrip("\n").split("\n") if out.strip() else []

    def cells(self, out):
        """Parsed CSV rows (the output is always RFC-4180 with doubled quotes)."""
        import csv
        import io as _io
        return list(csv.reader(_io.StringIO(out)))


# ----------------------------------------------------------------- schema

class TestSchemaParsing(Base):
    def test_struct_array_map_round_trip(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [{
            "id": 1,
            "user": {"name": "amy", "age": 30, "prefs": {"b": "2", "a": "1"}},
            "items": [{"sku": "x", "qty": 2}],
            "attrs": {"country": "DE"},
            "event_time": "2024-05-01T00:00:00Z",
        }])
        out = run(["--output", "-", "--key", "id", "--schema", s, a]).stdout
        row = self.cells(out)[1]
        self.assertEqual(row[1],
                         '{"name":"amy","age":30,"prefs":{"a":"1","b":"2"}}')
        self.assertEqual(row[2], '[{"sku":"x","qty":2}]')
        self.assertEqual(row[3], '{"country":"DE"}')

    def test_struct_field_order_is_schema_order(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "s", "type": {"struct": {"fields": [
                {"name": "z", "type": "int"},
                {"name": "a", "type": "int"}]}}}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "s": {"a": 1, "z": 2}}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '{"z":2,"a":1}')

    def test_map_keys_sorted(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "m", "type": {"map": {"key": "string", "value": "int"}}}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "m": {"b": 1, "A": 2, "a": 3}}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '{"A":2,"a":3,"b":1}')

    def test_arrays_keep_order(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "xs", "type": {"array": {"element": "int"}}}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "xs": [3, 1, 2]}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], "[3,1,2]")

    def test_all_struct_fields_emitted_with_nulls(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [{"id": 1, "user": {"name": "amy"}}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '{"name":"amy","age":null,"prefs":null}')

    def test_entirely_null_column_uses_null_literal(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [{"id": 1, "user": None}])
        out = run(["--output", "-", "--key", "id", "--schema", s,
                   "--csv-null-literal", "NULL", a]).stdout
        self.assertEqual(self.cells(out)[1][1], "NULL")

    def test_empty_struct_and_array_are_not_null(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "xs", "type": {"array": {"element": "int"}}},
            {"name": "m", "type": {"map": {"key": "string", "value": "int"}}}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "xs": [], "m": {}}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1:], ["[]", "{}"])

    def test_nested_casting_is_recursive(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [{
            "id": "1",
            "user": {"name": 7, "age": "30", "prefs": {"a": 1}},
            "items": [{"sku": "x", "qty": "4"}],
        }])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '{"name":"7","age":30,"prefs":{"a":"1"}}')
        self.assertEqual(row[2], '[{"sku":"x","qty":4}]')

    def test_temporal_normalised_inside_nested(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "s", "type": {"struct": {"fields": [
                {"name": "t", "type": "timestamp"},
                {"name": "d", "type": "date"}]}}}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "s": {"t": "2024-07-01 12:00:00+02:00",
                                                   "d": "2024-07-01"}}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '{"t":"2024-07-01T10:00:00Z","d":"2024-07-01"}')

    def test_unicode_is_not_escaped(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "m", "type": {"map": {"key": "string",
                                           "value": "string"}}}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "m": {"k": "héllo ✓"}}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '{"k":"héllo ✓"}')

    def test_control_characters_escaped(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "m", "type": {"map": {"key": "string",
                                           "value": "string"}}}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "m": {"k": "a\nb\"c"}}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '{"k":"a\\nb\\"c"}')

    def test_extra_input_fields_dropped(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [{"id": 1, "user": {"name": "n", "zz": 1}}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertNotIn("zz", row[1])

    def test_duplicate_struct_field_rejected(self):
        s = self.schema({"columns": [{"name": "s", "type": {"struct": {"fields": [
            {"name": "a", "type": "int"}, {"name": "a", "type": "int"}]}}}]})
        a = self.w("a.csv", "s\n\n")
        run(["--output", "-", "--key", "s", "--schema", s, a], expect=EXIT_USAGE)

    def test_non_string_map_key_rejected(self):
        s = self.schema({"columns": [{"name": "m", "type": {"map": {
            "key": "int", "value": "int"}}}]})
        a = self.w("a.csv", "m\n\n")
        run(["--output", "-", "--key", "m", "--schema", s, a], expect=EXIT_USAGE)

    def test_unknown_type_rejected(self):
        s = self.schema({"columns": [{"name": "a", "type": "widget"}]})
        f = self.w("a.csv", "a\n1\n")
        p = run(["--output", "-", "--key", "a", "--schema", s, f],
                expect=EXIT_USAGE)
        self.assertIn("widget", p.stderr)

    def test_deeply_nested_types(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "x", "type": {"array": {"element": {"map": {
                "key": "string",
                "value": {"array": {"element": "int"}}}}}}}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "x": [{"b": [1], "a": ["2"]}]}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '[{"a":[2],"b":[1]}]')


# ----------------------------------------------------------------- aliases

class TestAliases(Base):
    def _one(self, typ, value, alias_file=None):
        s = self.schema({"columns": [{"name": "a", "type": typ}]})
        f = self.w("a.csv", "a\n%s\n" % value)
        args = ["--output", "-", "--key", "a", "--schema", s]
        if alias_file:
            args += ["--type-alias-file", alias_file]
        return self.lines(run(args + [f]).stdout)[1]

    def test_builtin_scalar_aliases(self):
        for alias, value, want in (("integer", "5", "5"), ("long", "5", "5"),
                                   ("double", "5", "5.0"), ("number", "5", "5.0"),
                                   ("boolean", "1", "true"),
                                   ("datetime", "2024-01-01T00:00:00Z",
                                    "2024-01-01T00:00:00Z"),
                                   ("timestamptz", "2024-01-01T00:00:00Z",
                                    "2024-01-01T00:00:00Z"),
                                   ("text", "hi", "hi"), ("varchar", "hi", "hi")):
            self.assertEqual(self._one(alias, value), want, alias)

    def test_aliases_are_case_insensitive(self):
        self.assertEqual(self._one("INTEGER", "5"), "5")
        self.assertEqual(self._one("Long", "5"), "5")

    def test_list_alias_is_array(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "xs", "type": "list<integer>"}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "xs": ["1", 2]}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], "[1,2]")

    def test_json_alias_accepts_anything(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "p", "type": "json"}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "p": {"b": 1, "a": [1, "x", None]}},
                                   {"id": 2, "p": "plain"},
                                   {"id": 3, "p": 7}])
        rows = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                               a]).stdout)[1:]
        self.assertEqual([r[1] for r in rows],
                         ['{"a":[1,"x",null],"b":1}', '"plain"', "7"])

    def test_user_alias_file(self):
        al = self.aliases({"smallint": "int", "decimal": "float",
                           "uuid": "string", "myts": "timestamp"})
        self.assertEqual(self._one("smallint", "5", al), "5")
        self.assertEqual(self._one("decimal", "5", al), "5.0")
        self.assertEqual(self._one("uuid", "ab", al), "ab")
        self.assertEqual(self._one("myts", "2024-01-01T00:00:00Z", al),
                         "2024-01-01T00:00:00Z")

    def test_user_alias_is_transitive(self):
        al = self.aliases({"tiny": "smallint", "smallint": "integer"})
        self.assertEqual(self._one("tiny", "5", al), "5")

    def test_user_alias_case_insensitive(self):
        al = self.aliases({"SmallInt": "INT"})
        self.assertEqual(self._one("smallint", "5", al), "5")
        self.assertEqual(self._one("SMALLINT", "5", al), "5")

    def test_alias_of_generic(self):
        al = self.aliases({"ints": "list<int>"})
        s = self.schema({"columns": [{"name": "id", "type": "int"},
                                     {"name": "xs", "type": "ints"}]})
        a = self.jsonl("a.jsonl", [{"id": 1, "xs": [1, 2]}])
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              "--type-alias-file", al, a]).stdout)[1]
        self.assertEqual(row[1], "[1,2]")

    def test_alias_cycle_detected(self):
        al = self.aliases({"a": "b", "b": "c", "c": "a"})
        s = self.schema({"columns": [{"name": "x", "type": "int"}]})
        f = self.w("a.csv", "x\n1\n")
        p = run(["--output", "-", "--key", "x", "--schema", s,
                 "--type-alias-file", al, f], expect=EXIT_USAGE)
        self.assertIn("cycle", p.stderr)

    def test_self_referential_alias_detected(self):
        al = self.aliases({"a": "a"})
        s = self.schema({"columns": [{"name": "x", "type": "int"}]})
        f = self.w("a.csv", "x\n1\n")
        run(["--output", "-", "--key", "x", "--schema", s,
             "--type-alias-file", al, f], expect=EXIT_USAGE)

    def test_missing_alias_file_is_inline_json(self):
        s = self.schema({"columns": [{"name": "x", "type": "tiny"}]})
        f = self.w("a.csv", "x\n1\n")
        out = run(["--output", "-", "--key", "x", "--schema", s,
                   "--type-alias-file", '{"aliases":{"tiny":"int"}}', f]).stdout
        self.assertEqual(out, "x\n1\n")


# ------------------------------------------------------------ field paths

class TestFieldPaths(Base):
    def setUp(self):
        super().setUp()
        self.s = self.schema(STRUCT_SCHEMA)
        self.a = self.jsonl("a.jsonl", [
            {"id": 1, "user": {"name": "bob", "age": 41},
             "items": [{"sku": "s1", "qty": 9}],
             "attrs": {"country": "US"}, "event_time": "2024-01-02T00:00:00Z"},
            {"id": 2, "user": {"name": "amy", "age": 7},
             "items": [{"sku": "s0", "qty": 3}],
             "attrs": {"country": "DE"}, "event_time": "2024-01-01T00:00:00Z"},
        ])

    def ids(self, out):
        return [r[0] for r in self.cells(out)[1:]]

    def test_struct_leaf_key(self):
        out = run(["--output", "-", "--key", "user.name", "--schema", self.s,
                   self.a]).stdout
        self.assertEqual(self.ids(out), ["2", "1"])

    def test_array_index_key(self):
        out = run(["--output", "-", "--key", "items.0.qty", "--schema", self.s,
                   self.a]).stdout
        self.assertEqual(self.ids(out), ["2", "1"])

    def test_map_lookup_key(self):
        out = run(["--output", "-", "--key", 'attrs["country"]', "--schema",
                   self.s, self.a]).stdout
        self.assertEqual(self.ids(out), ["2", "1"])

    def test_numeric_key_sorts_numerically(self):
        out = run(["--output", "-", "--key", "user.age", "--schema", self.s,
                   self.a]).stdout
        self.assertEqual(self.ids(out), ["2", "1"])

    def test_timestamp_leaf_key(self):
        out = run(["--output", "-", "--key", "event_time", "--desc",
                   "--schema", self.s, self.a]).stdout
        self.assertEqual(self.ids(out), ["1", "2"])

    def test_multiple_key_paths(self):
        out = run(["--output", "-", "--key", 'attrs["country"],user.age',
                   "--schema", self.s, self.a]).stdout
        self.assertEqual(self.ids(out), ["2", "1"])

    def test_desc_reverses(self):
        out = run(["--output", "-", "--key", "user.name", "--desc",
                   "--schema", self.s, self.a]).stdout
        self.assertEqual(self.ids(out), ["1", "2"])

    def test_missing_map_key_is_null_and_sorts_first(self):
        b = self.jsonl("b.jsonl", [{"id": 3, "attrs": {}}])
        out = run(["--output", "-", "--key", 'attrs["country"]', "--schema",
                   self.s, self.a, b]).stdout
        self.assertEqual(self.ids(out), ["3", "2", "1"])

    def test_out_of_range_index_is_null(self):
        out = run(["--output", "-", "--key", "items.5.qty", "--schema",
                   self.s, self.a]).stdout
        self.assertEqual(self.ids(out), ["1", "2"])  # all null: stable order

    def test_null_element_is_null_fragment(self):
        b = self.jsonl("b.jsonl", [{"id": 3, "items": [None]}])
        out = run(["--output", "-", "--key", "items.0.qty", "--schema",
                   self.s, self.a, b]).stdout
        self.assertEqual(self.ids(out), ["3", "2", "1"])

    def test_struct_key_is_error_3(self):
        p = run(["--output", "-", "--key", "user", "--schema", self.s, self.a],
                expect=EXIT_KEY)
        self.assertIn("does not resolve to a primitive", p.stderr)
        self.assertIn('"user"', p.stderr)

    def test_array_key_is_error_3(self):
        run(["--output", "-", "--key", "items", "--schema", self.s, self.a],
            expect=EXIT_KEY)

    def test_map_key_is_error_3(self):
        run(["--output", "-", "--key", "attrs", "--schema", self.s, self.a],
            expect=EXIT_KEY)

    def test_partial_path_is_error_3(self):
        run(["--output", "-", "--key", "items.0", "--schema", self.s, self.a],
            expect=EXIT_KEY)

    def test_unknown_struct_field_is_error_3(self):
        run(["--output", "-", "--key", "user.nope", "--schema", self.s, self.a],
            expect=EXIT_KEY)

    def test_unquoted_map_key_rejected(self):
        run(["--output", "-", "--key", "attrs[country]", "--schema", self.s,
             self.a], expect=EXIT_KEY)

    def test_single_quoted_map_key_rejected(self):
        run(["--output", "-", "--key", "attrs['country']", "--schema", self.s,
             self.a], expect=EXIT_KEY)

    def test_negative_index_rejected(self):
        run(["--output", "-", "--key", "items[-1].qty", "--schema", self.s,
             self.a], expect=EXIT_KEY)

    def test_unknown_base_column_is_error_3(self):
        run(["--output", "-", "--key", "nope.x", "--schema", self.s, self.a],
            expect=EXIT_KEY)

    def test_bracket_index_form_accepted(self):
        out = run(["--output", "-", "--key", "items[0].qty", "--schema",
                   self.s, self.a]).stdout
        self.assertEqual(self.ids(out), ["2", "1"])

    def test_map_key_may_contain_a_comma(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "m", "type": {"map": {"key": "string",
                                           "value": "int"}}}]}, "s2.json")
        a = self.jsonl("c.jsonl", [{"id": 1, "m": {"a,b": 5}},
                                   {"id": 2, "m": {"a,b": 1}}])
        out = run(["--output", "-", "--key", 'm["a,b"]', "--schema", s,
                   a]).stdout
        self.assertEqual([r[0] for r in self.cells(out)[1:]], ["2", "1"])

    def test_json_column_path_is_error_3(self):
        s = self.schema({"columns": [{"name": "id", "type": "int"},
                                     {"name": "p", "type": "json"}]}, "s3.json")
        a = self.jsonl("d.jsonl", [{"id": 1, "p": {"x": 1}}])
        run(["--output", "-", "--key", "p.x", "--schema", s, a],
            expect=EXIT_KEY)


# ---------------------------------------------------------- partitioning

class TestNestedPartitioning(Base):
    def test_partition_by_map_value(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [
            {"id": 1, "attrs": {"country": "US"}},
            {"id": 2, "attrs": {"country": "DE"}},
            {"id": 3, "attrs": {}},
        ])
        o = os.path.join(self.d, "out")
        run(["--output", o, "--key", "id", "--partition-by",
             'attrs["country"]', "--schema", s, a])
        got = sorted(os.listdir(o))
        self.assertEqual(got, ['attrs["country"]=DE', 'attrs["country"]=US',
                               'attrs["country"]=_null'])

    def test_partition_by_struct_leaf(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [{"id": 1, "user": {"name": "a b"}},
                                   {"id": 2, "user": {"name": "a b"}}])
        o = os.path.join(self.d, "out")
        run(["--output", o, "--key", "id", "--partition-by", "user.name",
             "--schema", s, a])
        self.assertEqual(os.listdir(o), ["user.name=a%20b"])
        with open(os.path.join(o, "user.name=a%20b", "part-00000.csv"),
                  encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().rstrip("\n").split("\n")), 3)

    def test_partition_on_nested_column_is_error_3(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [{"id": 1}])
        p = run(["--output", os.path.join(self.d, "o"), "--key", "id",
                 "--partition-by", "user", "--schema", s, a], expect=EXIT_KEY)
        self.assertIn("does not resolve to a primitive", p.stderr)


# ------------------------------------------------------------- input: csv

class TestCsvNestedCells(Base):
    def setUp(self):
        super().setUp()
        self.s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "xs", "type": {"array": {"element": "int"}}}]})

    def test_json_literal_in_cell(self):
        a = self.w("a.csv", 'id,xs\n1,"[1, 2]"\n')
        row = self.cells(run(["--output", "-", "--key", "id", "--schema",
                              self.s, a]).stdout)[1]
        self.assertEqual(row[1], "[1,2]")

    def test_tsv_json_literal(self):
        a = self.w("a.tsv", "id\txs\n1\t[1,2]\n")
        row = self.cells(run(["--output", "-", "--key", "id", "--schema",
                              self.s, a]).stdout)[1]
        self.assertEqual(row[1], "[1,2]")

    def test_empty_cell_is_null(self):
        a = self.w("a.csv", "id,xs\n1,\n")
        out = run(["--output", "-", "--key", "id", "--schema", self.s,
                   "--csv-null-literal", "NULL", a]).stdout
        self.assertEqual(self.cells(out)[1][1], "NULL")

    def test_json_null_literal_is_null(self):
        a = self.w("a.csv", "id,xs\n1,null\n")
        self.assertEqual(self.cells(run(["--output", "-", "--key", "id",
                                         "--schema", self.s, a]).stdout)[1][1],
                         "")

    def test_invalid_json_coerce_null(self):
        a = self.w("a.csv", "id,xs\n1,nope\n")
        self.assertEqual(self.cells(run(["--output", "-", "--key", "id",
                                         "--schema", self.s, a]).stdout)[1][1],
                         "")

    def test_invalid_json_keep_string(self):
        a = self.w("a.csv", "id,xs\n1,nope\n")
        out = run(["--output", "-", "--key", "id", "--schema", self.s,
                   "--on-type-error", "keep-string", a]).stdout
        self.assertEqual(self.cells(out)[1][1], "nope")

    def test_invalid_json_fail(self):
        a = self.w("a.csv", "id,xs\n1,nope\n")
        p = run(["--output", "-", "--key", "id", "--schema", self.s,
                 "--on-type-error", "fail", a], expect=EXIT_TYPE)
        self.assertIn("nope", p.stderr)
        self.assertIn('field "xs"', p.stderr)

    def test_trailing_garbage_is_not_a_json_literal(self):
        a = self.w("a.csv", 'id,xs\n1,"[1] junk"\n')
        self.assertEqual(self.cells(run(["--output", "-", "--key", "id",
                                         "--schema", self.s, a]).stdout)[1][1],
                         "")

    def test_no_schema_treats_json_cell_as_string(self):
        a = self.w("a.csv", 'id,xs\n1,"[1, 2]"\n')
        row = self.cells(run(["--output", "-", "--key", "id", a]).stdout)[1]
        self.assertEqual(row[1], "[1, 2]")


# ----------------------------------------------------------- input: jsonl

class TestJsonlNested(Base):
    def test_nested_without_schema_is_error_6(self):
        a = self.w("a.jsonl", '{"a": 1, "b": {"c": 2}}\n')
        p = run(["--output", "-", "--key", "a", a], expect=EXIT_NESTED)
        self.assertIn("nested structure requires provided --schema", p.stderr)

    def test_nested_array_without_schema_is_error_6(self):
        a = self.w("a.jsonl", '{"a": 1, "b": [1]}\n')
        run(["--output", "-", "--key", "a", a], expect=EXIT_NESTED)

    def test_top_level_array_still_error_6(self):
        a = self.w("a.jsonl", "[1, 2]\n")
        run(["--output", "-", "--key", "a", a], expect=EXIT_NESTED)

    def test_flat_declared_but_nested_input_coerce_null(self):
        s = self.schema({"columns": [{"name": "a", "type": "int"},
                                     {"name": "b", "type": "int"}]})
        a = self.w("a.jsonl", '{"a": 1, "b": {"c": 2}}\n')
        self.assertEqual(run(["--output", "-", "--key", "a", "--schema", s,
                              a]).stdout, "a,b\n1,\n")

    def test_flat_declared_but_nested_input_keep_string(self):
        s = self.schema({"columns": [{"name": "a", "type": "int"},
                                     {"name": "b", "type": "int"}]})
        a = self.w("a.jsonl", '{"a": 1, "b": {"c": 2}}\n')
        out = run(["--output", "-", "--key", "a", "--schema", s,
                   "--on-type-error", "keep-string", a]).stdout
        self.assertEqual(self.cells(out)[1][1], '{"c":2}')

    def test_flat_declared_but_nested_input_fail(self):
        s = self.schema({"columns": [{"name": "a", "type": "int"},
                                     {"name": "b", "type": "int"}]})
        a = self.w("a.jsonl", '{"a": 1, "b": {"c": 2}}\n')
        run(["--output", "-", "--key", "a", "--schema", s,
             "--on-type-error", "fail", a], expect=EXIT_TYPE)

    def test_nested_column_absent_from_schema_is_dropped(self):
        s = self.schema({"columns": [{"name": "a", "type": "int"}]})
        a = self.w("a.jsonl", '{"a": 1, "b": {"c": 2}}\n')
        self.assertEqual(run(["--output", "-", "--key", "a", "--schema", s,
                              a]).stdout, "a\n1\n")

    def test_scalar_where_struct_declared(self):
        s = self.schema(STRUCT_SCHEMA)
        a = self.w("a.jsonl", '{"id": 1, "user": 5}\n')
        self.assertEqual(self.cells(run(["--output", "-", "--key", "id",
                                         "--schema", s, a]).stdout)[1][1], "")

    def test_json_column_keeps_float(self):
        s = self.schema({"columns": [{"name": "id", "type": "int"},
                                     {"name": "p", "type": "json"}]})
        a = self.w("a.jsonl", '{"id": 1, "p": 1.0}\n')
        self.assertEqual(self.cells(run(["--output", "-", "--key", "id",
                                         "--schema", s, a]).stdout)[1][1],
                         "1.0")


# --------------------------------------------------------- input: parquet

@unittest.skipIf(pa is None, "pyarrow not installed")
class TestParquetNested(Base):
    def wpq(self, name, table):
        p = os.path.join(self.d, name)
        pq.write_table(table, p)
        return p

    def table(self):
        return pa.table({
            "id": pa.array([2, 1]),
            "user": pa.array([{"name": "bob", "age": 41},
                              {"name": "amy", "age": None}]),
            "items": pa.array([[{"sku": "x", "qty": 2}], []]),
            "attrs": pa.array([[("country", "US")], [("country", "DE")]],
                              pa.map_(pa.string(), pa.string())),
        })

    def pschema(self):
        return self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "user", "type": {"struct": {"fields": [
                {"name": "name", "type": "string"},
                {"name": "age", "type": "int"}]}}},
            {"name": "items", "type": {"array": {"element": {"struct": {
                "fields": [{"name": "sku", "type": "string"},
                           {"name": "qty", "type": "int"}]}}}}},
            {"name": "attrs", "type": {"map": {"key": "string",
                                               "value": "string"}}}]})

    def test_struct_list_map_with_schema(self):
        a = self.wpq("a.parquet", self.table())
        out = run(["--output", "-", "--key", "id", "--schema", self.pschema(),
                   a]).stdout
        rows = self.cells(out)[1:]
        self.assertEqual(rows[0], ["1", '{"name":"amy","age":null}', "[]",
                                   '{"country":"DE"}'])
        self.assertEqual(rows[1], ["2", '{"name":"bob","age":41}',
                                   '[{"sku":"x","qty":2}]', '{"country":"US"}'])

    def test_key_into_parquet_struct(self):
        a = self.wpq("a.parquet", self.table())
        out = run(["--output", "-", "--key", "user.name", "--schema",
                   self.pschema(), a]).stdout
        self.assertEqual([r[0] for r in self.cells(out)[1:]], ["1", "2"])

    def test_key_into_parquet_map(self):
        a = self.wpq("a.parquet", self.table())
        out = run(["--output", "-", "--key", 'attrs["country"]', "--schema",
                   self.pschema(), a]).stdout
        self.assertEqual([r[0] for r in self.cells(out)[1:]], ["1", "2"])

    def test_nested_without_schema_is_error_6(self):
        a = self.wpq("a.parquet", self.table())
        p = run(["--output", "-", "--key", "id", a], expect=EXIT_NESTED)
        self.assertIn("nested structure requires provided --schema", p.stderr)

    def test_parquet_timestamp_inside_struct(self):
        tbl = pa.table({"id": pa.array([1]), "s": pa.array([
            {"t": datetime.datetime(2024, 7, 1, 12, 0, 0)}])})
        a = self.wpq("b.parquet", tbl)
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "s", "type": {"struct": {"fields": [
                {"name": "t", "type": "timestamp"}]}}}]}, "s2.json")
        row = self.cells(run(["--output", "-", "--key", "id", "--schema", s,
                              a]).stdout)[1]
        self.assertEqual(row[1], '{"t":"2024-07-01T12:00:00Z"}')

    def test_parquet_nested_into_json_column(self):
        a = self.wpq("a.parquet", self.table())
        s = self.schema({"columns": [{"name": "id", "type": "int"},
                                     {"name": "user", "type": "json"}]},
                        "s3.json")
        out = run(["--output", "-", "--key", "id", "--schema", s, a]).stdout
        self.assertEqual(self.cells(out)[1][1], '{"age":null,"name":"amy"}')


# ------------------------------------------------------------- end-to-end

class TestMixedSources(Base):
    def test_jsonl_and_parquet_merge_on_nested_key(self):
        if pa is None:
            self.skipTest("pyarrow not installed")
        s = self.schema(STRUCT_SCHEMA)
        a = self.jsonl("a.jsonl", [
            {"id": 1, "user": {"name": "z", "age": 1},
             "attrs": {"country": "US"}, "event_time": "2024-01-03T00:00:00Z"}])
        tbl = pa.table({"id": pa.array([2]),
                        "user": pa.array([{"name": "a", "age": 2}]),
                        "event_time": pa.array(["2024-01-01T00:00:00Z"])})
        b = os.path.join(self.d, "b.parquet")
        pq.write_table(tbl, b)
        out = run(["--output", "-", "--key", "user.name", "--schema", s,
                   a, b]).stdout
        self.assertEqual([r[0] for r in self.cells(out)[1:]], ["2", "1"])

    def test_spilling_preserves_nested_columns(self):
        s = self.schema({"columns": [
            {"name": "id", "type": "int"},
            {"name": "s", "type": {"struct": {"fields": [
                {"name": "v", "type": "int"}]}}}]})
        a = self.jsonl("a.jsonl", [{"id": i, "s": {"v": i}}
                                   for i in range(2000, 0, -1)])
        out = run(["--output", "-", "--key", "s.v", "--memory-limit-mb", "1",
                   "--schema", s, a]).stdout
        rows = self.cells(out)[1:]
        self.assertEqual(len(rows), 2000)
        self.assertEqual(rows[0], ["1", '{"v":1}'])
        self.assertEqual(rows[-1], ["2000", '{"v":2000}'])


if __name__ == "__main__":
    unittest.main()
