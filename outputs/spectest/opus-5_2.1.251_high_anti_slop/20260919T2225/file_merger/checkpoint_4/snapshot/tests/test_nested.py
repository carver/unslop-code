"""End-to-end tests of nested schemas, type aliases and field paths."""

from __future__ import annotations

import csv
import json
import unittest
from datetime import date, datetime, timezone

import pyarrow

from support import MergeTestCase
from test_formats import FormatTestCase

#: A struct holding a map, an array of structs, and a catch-all json column.
NESTED_COLUMNS = [
    {"name": "id", "type": "int"},
    {"name": "user", "type": {"struct": {"fields": [
        {"name": "name", "type": "string"},
        {"name": "age", "type": "int"},
        {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}},
    ]}}},
    {"name": "items", "type": {"array": {"element": {"struct": {"fields": [
        {"name": "sku", "type": "string"},
        {"name": "qty", "type": "int"},
    ]}}}}},
]


class NestedTestCase(FormatTestCase):
    """Adds the nested schema the rest of the cases are written against."""

    def setUp(self) -> None:
        super().setUp()
        self.schema = self.write("nested.json", json.dumps({"columns": NESTED_COLUMNS}))

    def merge(self, *argv: str) -> list[str]:
        return self.run_merge("--schema", self.schema, *argv)


class SchemaDeclarationTests(MergeTestCase):
    def test_nested_types_may_be_written_as_text(self) -> None:
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "tags", "type": "array<string>"},
            {"name": "counts", "type": "map<string,array<int>>"},
        ]}))
        source = self.write("a.jsonl", '{"id": 1, "tags": ["x"], "counts": {"b": [2], "a": [1]}}\n')
        rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1], '1,"[""x""]","{""a"":[1],""b"":[2]}"')

    def test_builtin_aliases_are_case_insensitive(self) -> None:
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "ratio", "type": "Double"},
            {"name": "when", "type": "datetime"},
            {"name": "tags", "type": "LIST<text>"},
        ]}))
        source = self.write("a.jsonl", '{"id": 1, "ratio": 2.5, "when": "2024-07-01", "tags": ["a"]}\n')
        self.assertEqual(self.run_merge("--key", "id", "--schema", schema, source)[1],
                         '1,2.5,2024-07-01T00:00:00Z,"[""a""]"')

    def test_an_alias_file_extends_the_builtins_transitively(self) -> None:
        aliases = self.write("aliases.json", json.dumps({"aliases": {
            "smallint": "int", "tiny": "smallint", "myts": "timestamp",
        }}))
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "tiny"},
            {"name": "seen", "type": "myts"},
        ]}))
        source = self.write("a.csv", "id,seen\n1,2024-07-01T00:00:00Z\n")
        rows = self.run_merge("--key", "id", "--schema", schema, "--type-alias-file", aliases, source)
        self.assertEqual(rows[1], "1,2024-07-01T00:00:00Z")

    def test_a_cyclic_alias_is_a_usage_error(self) -> None:
        aliases = self.write("aliases.json", json.dumps({"aliases": {"a": "b", "b": "a"}}))
        schema = self.write("s.json", json.dumps({"columns": [{"name": "id", "type": "int"}]}))
        source = self.write("a.csv", "id\n1\n")
        exit_code, stderr = self.run_failing(
            "--key", "id", "--schema", schema, "--type-alias-file", aliases, source
        )
        self.assertEqual(exit_code, 2)
        self.assertIn("ERR 2 type alias", stderr)

    def test_an_unknown_or_malformed_type_is_a_schema_error(self) -> None:
        source = self.write("a.csv", "id\n1\n")
        for spec in ["nope", "array", {"map": {"key": "int", "value": "int"}},
                     {"struct": {"fields": [{"name": "a", "type": "int"}, {"name": "a", "type": "int"}]}}]:
            schema = self.write("s.json", json.dumps({"columns": [{"name": "id", "type": spec}]}))
            with self.subTest(spec=spec):
                self.assertEqual(self.run_failing("--key", "id", "--schema", schema, source)[0], 3)


class NestedOutputTests(NestedTestCase):
    def test_nested_values_are_written_as_canonical_json(self) -> None:
        source = self.write_jsonl("a.jsonl", [{
            "id": 1,
            "user": {"prefs": {"z": "last", "a": "first"}, "name": "ann"},
            "items": [{"sku": "b", "qty": 2}, {"sku": "a", "qty": "3"}],
        }])
        _id, user, items = next(csv.reader(self.merge("--key", "id", source)[1:]))
        self.assertEqual(user, '{"name":"ann","age":null,"prefs":{"a":"first","z":"last"}}')
        self.assertEqual(items, '[{"sku":"b","qty":2},{"sku":"a","qty":3}]')

    def test_struct_fields_keep_schema_order_and_map_keys_are_sorted(self) -> None:
        source = self.write_jsonl("a.jsonl", [{"id": 1, "user": {"prefs": {"b": "2", "A": "1"}, "age": 4, "name": "n"}}])
        self.assertEqual(
            self.merge("--key", "id", source)[1],
            '1,"{""name"":""n"",""age"":4,""prefs"":{""A"":""1"",""b"":""2""}}",',
        )

    def test_a_wholly_null_column_uses_the_null_literal(self) -> None:
        source = self.write_jsonl("a.jsonl", [{"id": 1, "user": None}])
        rows = self.run_merge("--key", "id", "--schema", self.schema, "--csv-null-literal", "NULL", source)
        self.assertEqual(rows[1], "1,NULL,NULL")

    def test_temporal_values_inside_nested_columns_are_normalised(self) -> None:
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "when", "type": {"struct": {"fields": [
                {"name": "day", "type": "date"},
                {"name": "at", "type": "timestamp"},
            ]}}},
        ]}))
        source = self.write_jsonl("a.jsonl", [{"id": 1, "when": {"day": "2024-07-01", "at": "2024-07-01T08:30:00+02:00"}}])
        rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1], '1,"{""day"":""2024-07-01"",""at"":""2024-07-01T06:30:00Z""}"')

    def test_non_ascii_text_is_written_as_utf8_rather_than_escaped(self) -> None:
        source = self.write_jsonl("a.jsonl", [{"id": 1, "items": [{"sku": "café", "qty": 1}]}])
        self.assertIn("café", self.merge("--key", "id", source)[1])


class JsonColumnTests(MergeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "payload", "type": "json"},
        ]}))

    def test_any_json_value_is_accepted_and_normalised(self) -> None:
        source = self.write("a.jsonl", "".join([
            '{"id": 1, "payload": {"b": 1, "a": [true, null]}}\n',
            '{"id": 2, "payload": "text"}\n',
            '{"id": 3, "payload": 7}\n',
            '{"id": 4, "payload": null}\n',
        ]))
        rows = self.run_merge("--key", "id", "--schema", self.schema, source)
        self.assertEqual(rows[1:], [
            '1,"{""a"":[true,null],""b"":1}"',
            '2,"""text"""',
            "3,7",
            "4,",
        ])

    def test_a_tsv_cell_must_hold_one_json_literal(self) -> None:
        source = self.write("a.tsv", 'id\tpayload\n1\t{"a": 1}\n2\t\n3\tbare\n')
        self.assertEqual(
            self.run_merge("--key", "id", "--schema", self.schema, source)[1:],
            ['1,"{""a"":1}"', "2,", "3,"],
        )

    def test_an_invalid_json_cell_follows_the_type_error_policy(self) -> None:
        source = self.write("a.csv", "id,payload\n1,bare\n")
        rows = self.run_merge("--key", "id", "--schema", self.schema, "--on-type-error", "keep-string", source)
        self.assertEqual(rows[1], "1,bare")
        exit_code, stderr = self.run_failing(
            "--key", "id", "--schema", self.schema, "--on-type-error", "fail", source
        )
        self.assertEqual(exit_code, 1)
        self.assertIn('ERR 4 cannot cast "bare" to json in field "payload"', stderr)


class NestedCastingTests(NestedTestCase):
    def test_a_failed_cast_inside_a_structure_becomes_json_null(self) -> None:
        source = self.write_jsonl("a.jsonl", [{"id": 1, "items": [{"sku": "a", "qty": "oops"}]}])
        self.assertIn('[{""sku"":""a"",""qty"":null}]', self.merge("--key", "id", source)[1])

    def test_keep_string_holds_the_original_text_inside_the_structure(self) -> None:
        source = self.write_jsonl("a.jsonl", [{"id": 1, "items": [{"sku": "a", "qty": "oops"}]}])
        rows = self.merge("--key", "id", "--on-type-error", "keep-string", source)
        self.assertIn('[{""sku"":""a"",""qty"":""oops""}]', rows[1])

    def test_fail_names_the_field_path_and_the_line_it_came_from(self) -> None:
        source = self.write_jsonl("a.jsonl", [{"id": 1}, {"id": 2, "items": [{"sku": "a"}, {"qty": "oops"}]}])
        exit_code, stderr = self.run_failing(
            "--key", "id", "--schema", self.schema, "--on-type-error", "fail", source
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.strip(),
            'merge_files.py: error: ERR 4 cannot cast "oops" to int'
            f' in field "items.1.qty" (file={source} line=2)',
        )

    def test_a_structure_that_does_not_match_the_schema_is_a_cast_failure(self) -> None:
        source = self.write_jsonl("a.jsonl", [{"id": 1, "user": [1, 2], "items": {"sku": "a"}}])
        self.assertEqual(self.merge("--key", "id", source)[1], "1,,")
        rows = self.merge("--key", "id", "--on-type-error", "keep-string", source)
        self.assertEqual(rows[1], '1,"[1,2]","{""sku"":""a""}"')

    def test_a_nested_value_in_a_flat_column_still_follows_the_policy(self) -> None:
        schema = self.write("flat.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "tags", "type": "string"},
            {"name": "n", "type": "int"},
        ]}))
        source = self.write_jsonl("a.jsonl", [{"id": 1, "tags": ["a", "b"], "n": {"x": 1}}])
        rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1], '1,"[""a"",""b""]",')


class FieldPathTests(NestedTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.source = self.write_jsonl("a.jsonl", [
            {"id": 1, "user": {"name": "c", "age": 30, "prefs": {"country": "FR"}}, "items": [{"sku": "s", "qty": 9}]},
            {"id": 2, "user": {"name": "a", "age": 20, "prefs": {}}, "items": []},
            {"id": 3, "user": {"name": "b", "prefs": {"country": "US"}}, "items": [{"sku": "t", "qty": 4}]},
        ])

    def ids(self, *argv: str) -> list[str]:
        return [row.split(",")[0] for row in self.merge(*argv)[1:]]

    def test_a_path_into_a_struct_orders_the_rows(self) -> None:
        self.assertEqual(self.ids("--key", "user.name", self.source), ["2", "3", "1"])

    def test_a_path_into_an_array_element_orders_the_rows(self) -> None:
        self.assertEqual(self.ids("--key", "items.0.qty", self.source), ["2", "3", "1"])

    def test_an_index_past_the_end_of_an_array_is_a_null_key(self) -> None:
        self.assertEqual(self.ids("--key", "items.7.qty,id", self.source), ["1", "2", "3"])

    def test_a_map_key_may_be_bracketed_or_dotted(self) -> None:
        self.assertEqual(self.ids("--key", 'user.prefs["country"]', self.source), ["2", "1", "3"])
        self.assertEqual(self.ids("--key", "user.prefs.country", self.source), ["2", "1", "3"])

    def test_a_missing_map_key_is_a_null_key(self) -> None:
        self.assertEqual(self.ids("--key", 'user.prefs["nope"],id', self.source), ["1", "2", "3"])

    def test_a_path_that_stops_short_of_a_primitive_is_a_schema_error(self) -> None:
        for path in ["user", "items", "items.0", "user.prefs", "user.name.deeper", "items.first.qty"]:
            with self.subTest(path=path):
                exit_code, stderr = self.run_failing("--key", path, "--schema", self.schema, self.source)
                self.assertEqual(exit_code, 3)
                self.assertIn(f'ERR 3 key column "{path}"', stderr)

    def test_partitioning_on_a_map_value_names_the_directories_by_path(self) -> None:
        tree = self.run_tree(
            "--key", "id", "--partition-by", 'user.prefs["country"]', "--schema", self.schema, self.source
        )
        self.assertEqual(sorted(tree), [
            "user.prefs.country=FR/part-00000.csv",
            "user.prefs.country=US/part-00000.csv",
            "user.prefs.country=_null/part-00000.csv",
        ])

    def test_partitioning_on_a_struct_field_spells_the_value_as_the_schema_does(self) -> None:
        tree = self.run_tree("--key", "id", "--partition-by", "user.age", "--schema", self.schema, self.source)
        self.assertEqual(sorted(tree), [
            "user.age=20/part-00000.csv", "user.age=30/part-00000.csv", "user.age=_null/part-00000.csv",
        ])


class NestedInputTests(NestedTestCase):
    def test_json_lines_and_parquet_merge_onto_one_nested_schema(self) -> None:
        events = self.write_jsonl("a.jsonl", [{"id": 2, "user": {"name": "b"}, "items": [{"sku": "x", "qty": 1}]}])
        users = self.write_parquet(
            "b.parquet",
            {
                "id": [1],
                "user": pyarrow.array(
                    [{"name": "a", "age": 7, "prefs": [("k", "v")]}],
                    pyarrow.struct([
                        ("name", pyarrow.string()),
                        ("age", pyarrow.int32()),
                        ("prefs", pyarrow.map_(pyarrow.string(), pyarrow.string())),
                    ]),
                ),
                "items": pyarrow.array(
                    [[{"sku": "y", "qty": 2}]],
                    pyarrow.list_(pyarrow.struct([("sku", pyarrow.string()), ("qty", pyarrow.int64())])),
                ),
            },
        )
        rows = self.merge("--key", "id", events, users)
        self.assertEqual(rows[1:], [
            '1,"{""name"":""a"",""age"":7,""prefs"":{""k"":""v""}}","[{""sku"":""y"",""qty"":2}]"',
            '2,"{""name"":""b"",""age"":null,""prefs"":null}","[{""sku"":""x"",""qty"":1}]"',
        ])

    def test_a_csv_cell_holding_json_is_read_as_the_nested_value(self) -> None:
        source = self.write("a.csv", 'id,items\n1,"[{""sku"": ""a"", ""qty"": 2}]"\n2,\n')
        self.assertEqual(self.merge("--key", "id", source)[1:], ['1,,"[{""sku"":""a"",""qty"":2}]"', "2,,"])

    def test_parquet_temporal_values_inside_a_struct_are_normalised(self) -> None:
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "when", "type": {"struct": {"fields": [
                {"name": "day", "type": "date"}, {"name": "at", "type": "timestamp"},
            ]}}},
        ]}))
        source = self.write_parquet("a.parquet", {
            "id": [1],
            "when": pyarrow.array(
                [{"day": date(2024, 1, 2), "at": datetime(2024, 7, 1, 6, 30, tzinfo=timezone.utc)}],
                pyarrow.struct([("day", pyarrow.date32()), ("at", pyarrow.timestamp("us", "UTC"))]),
            ),
        })
        rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1], '1,"{""day"":""2024-01-02"",""at"":""2024-07-01T06:30:00Z""}"')

    def test_nested_inputs_without_a_schema_are_rejected(self) -> None:
        events = self.write_jsonl("a.jsonl", [{"id": 1, "items": [{"sku": "x"}]}])
        users = self.write_parquet("b.parquet", {"id": [1], "tags": [["x"]]})
        for source in (events, users):
            with self.subTest(source=source):
                exit_code, stderr = self.run_failing("--key", "id", source)
                self.assertEqual(exit_code, 6)
                self.assertIn("ERR 6 nested structure requires provided --schema", stderr)

    def test_without_a_schema_a_csv_cell_holding_json_stays_a_string(self) -> None:
        source = self.write("a.csv", 'id,payload\n1,"{""a"": 1}"\n')
        self.assertEqual(self.run_merge("--key", "id", source)[1], '1,"{""a"": 1}"')


if __name__ == "__main__":
    unittest.main()
