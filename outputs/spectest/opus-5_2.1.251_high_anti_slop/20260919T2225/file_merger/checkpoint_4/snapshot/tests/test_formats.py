"""End-to-end tests of the heterogeneous inputs: TSV, JSON Lines, Parquet and gzip."""

from __future__ import annotations

import gzip
import json
import unittest
from datetime import date, datetime, timezone
from typing import Any

import pyarrow
import pyarrow.parquet

from support import MergeTestCase, merge_files


class FormatTestCase(MergeTestCase):
    """Adds writers for the formats that are not plain text."""

    def write_gzip(self, name: str, text: str) -> str:
        path = self.root / name
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            stream.write(text)
        return str(path)

    def write_jsonl(self, name: str, records: list[dict[str, Any]]) -> str:
        return self.write(name, "".join(json.dumps(record) + "\n" for record in records))

    def write_parquet(self, name: str, columns: dict[str, Any], schema: pyarrow.Schema | None = None) -> str:
        path = self.root / name
        pyarrow.parquet.write_table(pyarrow.table(columns, schema=schema), path)
        return str(path)


class DetectionTests(FormatTestCase):
    def test_each_extension_selects_its_reader(self) -> None:
        csv_input = self.write("a.csv", "id,src\n1,csv\n")
        tsv_input = self.write("b.tsv", "id\tsrc\n2\ttsv\n")
        jsonl_input = self.write_jsonl("c.ndjson", [{"id": 3, "src": "jsonl"}])
        parquet_input = self.write_parquet("d.parquet", {"id": [4], "src": ["parquet"]})
        rows = self.run_merge("--key", "id", csv_input, tsv_input, jsonl_input, parquet_input)
        self.assertEqual(rows, ["id,src", "1,csv", "2,tsv", "3,jsonl", "4,parquet"])

    def test_gzip_is_detected_after_the_base_extension(self) -> None:
        source = self.write_gzip("a.csv.gz", "id,src\n1,zipped\n")
        self.assertEqual(self.run_merge("--key", "id", source)[1:], ["1,zipped"])

    def test_parquet_is_recognised_by_its_magic_bytes(self) -> None:
        source = self.write_parquet("payload.bin", {"id": [1]})
        self.assertEqual(self.run_merge("--key", "id", source), ["id", "1"])

    def test_an_undetectable_format_exits_with_the_usage_code(self) -> None:
        source = self.write("mystery.dat", "id\n1\n")
        self.assertEqual(merge_files.main(["--output", "-", "--key", "id", source]), 2)

    def test_forced_format_overrides_the_extension(self) -> None:
        source = self.write("a.csv", "id\tsrc\n1\ttabbed\n")
        rows = self.run_merge("--key", "id", "--input-format", "tsv", source)
        self.assertEqual(rows[1:], ["1,tabbed"])

    def test_compression_mismatch_is_rejected_in_both_directions(self) -> None:
        zipped = self.write_gzip("a.csv.gz", "id\n1\n")
        plain = self.write("b.csv", "id\n1\n")
        self.assertEqual(
            merge_files.main(["--output", "-", "--key", "id", "--compression", "none", zipped]), 5
        )
        self.assertEqual(
            merge_files.main(["--output", "-", "--key", "id", "--compression", "gzip", plain]), 5
        )


class TsvTests(FormatTestCase):
    def test_tsv_is_never_quoted(self) -> None:
        source = self.write("a.tsv", 'id\tnote\n1\t"quoted, really"\n')
        self.assertEqual(self.run_merge("--key", "id", source)[1:], ['1,"""quoted, really"""'])

    def test_a_literal_tab_inside_a_field_is_malformed(self) -> None:
        source = self.write("a.tsv", "id\tnote\n1\thas\ta tab\n")
        self.assertEqual(merge_files.main(["--output", "-", "--key", "id", source]), 5)


class JsonLinesTests(FormatTestCase):
    def test_blank_lines_are_ignored_and_missing_fields_become_nulls(self) -> None:
        source = self.write("a.jsonl", '{"id": 1, "note": "x"}\n\n   \n{"id": 2}\n')
        self.assertEqual(self.run_merge("--key", "id", source), ["id,note", "1,x", "2,"])

    def test_json_null_is_a_missing_value(self) -> None:
        source = self.write_jsonl("a.jsonl", [{"id": 1, "note": None}])
        self.assertEqual(self.run_merge("--key", "id", "--csv-null-literal", "NULL", source)[1:], ["1,NULL"])

    def test_typed_values_are_cast_to_the_declared_schema(self) -> None:
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "amount", "type": "int"},
            {"name": "flag", "type": "bool"},
            {"name": "ts", "type": "timestamp"},
        ]}))
        source = self.write_jsonl("a.jsonl", [
            {"id": 1, "amount": 3.0, "flag": True, "ts": "2024-07-01T08:30:00+02:00"},
            {"id": 2, "amount": 3.5, "flag": False, "ts": "2024-07-02"},
        ])
        rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1:], ["1,3,true,2024-07-01T06:30:00Z", "2,,false,2024-07-02T00:00:00Z"])

    def test_nested_values_exit_with_the_nested_code(self) -> None:
        nested = self.write("a.jsonl", '{"id": 1, "tags": ["a"]}\n')
        self.assertEqual(merge_files.main(["--output", "-", "--key", "id", nested]), 6)
        array = self.write("b.jsonl", "[1, 2]\n")
        self.assertEqual(merge_files.main(["--output", "-", "--key", "id", array]), 6)

    def test_invalid_json_is_malformed(self) -> None:
        source = self.write("a.jsonl", '{"id": 1\n')
        self.assertEqual(merge_files.main(["--output", "-", "--key", "id", source]), 5)


class ParquetTests(FormatTestCase):
    def test_column_types_come_from_the_parquet_schema(self) -> None:
        source = self.write_parquet("a.parquet", {
            "id": [2, 1],
            "ratio": [0.5, 1.25],
            "flag": [True, False],
            "day": [date(2024, 1, 2), date(2024, 1, 3)],
            "ts": [datetime(2024, 7, 1, 6, 30, tzinfo=timezone.utc)] * 2,
        })
        rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows, [
            "day,flag,id,ratio,ts",
            "2024-01-03,false,1,1.25,2024-07-01T06:30:00Z",
            "2024-01-02,true,2,0.5,2024-07-01T06:30:00Z",
        ])

    def test_nested_columns_exit_with_the_nested_code(self) -> None:
        source = self.write_parquet("a.parquet", {"id": [1], "tags": [["x", "y"]]})
        self.assertEqual(merge_files.main(["--output", "-", "--key", "id", source]), 6)

    def test_a_file_that_is_not_parquet_is_malformed(self) -> None:
        source = self.write("a.csv", "id\n1\n")
        self.assertEqual(
            merge_files.main(["--output", "-", "--key", "id", "--input-format", "parquet", source]), 5
        )

    def test_row_group_batching_does_not_change_the_result(self) -> None:
        source = self.write_parquet("a.parquet", {"id": list(range(5000, 0, -1))})
        batched = self.run_merge("--key", "id", "--parquet-row-group-bytes", "1024", source)
        whole = self.run_merge("--key", "id", "--parquet-row-group-bytes", "67108864", source)
        self.assertEqual(batched, whole)
        self.assertEqual(batched[1], "1")


class SchemaStrategyTests(FormatTestCase):
    """The three ways of settling a column that inputs disagree about."""

    def setUp(self) -> None:
        super().setUp()
        self.text = self.write("a.csv", "v\nabc\n")
        self.typed = self.write_jsonl("b.jsonl", [{"v": 5}])

    def test_authoritative_defers_to_the_typed_source(self) -> None:
        rows = self.run_merge("--key", "v", "--schema-strategy", "authoritative", self.text, self.typed)
        self.assertEqual(rows, ["v", '""', "5"])

    def test_union_widens_to_the_type_that_holds_every_value(self) -> None:
        rows = self.run_merge("--key", "v", "--schema-strategy", "union", self.text, self.typed)
        self.assertEqual(rows, ["v", "5", "abc"])

    def test_consensus_follows_the_majority_of_files(self) -> None:
        first = self.write("a.csv", "v\n1\n")
        second = self.write("b.csv", "v\n2\n")
        third = self.write("c.csv", "v\nx\n")
        rows = self.run_merge("--key", "v", "--schema-strategy", "consensus", first, second, third)
        self.assertEqual(rows, ["v", '""', "1", "2"])

    def test_consensus_falls_back_to_the_union_when_files_tie(self) -> None:
        rows = self.run_merge("--key", "v", "--schema-strategy", "consensus", self.text, self.typed)
        self.assertEqual(rows, ["v", "5", "abc"])


class MixedInputTests(FormatTestCase):
    """The worked examples from the specification."""

    def test_mixed_sources_share_one_inferred_schema_and_sort_order(self) -> None:
        users = self.write("users.csv", "ts,id,src\n2024-07-01T00:00:00Z,2,csv\n2024-07-01T00:00:00Z,1,csv\n")
        events = self.write_gzip(
            "events.jsonl.gz",
            '{"ts": "2024-06-30T23:00:00Z", "id": 9, "src": "jsonl"}\n'
            '{"ts": "2024-07-01T00:00:00Z", "id": 1, "src": "jsonl"}\n',
        )
        metrics = self.write_parquet("metrics.parquet", {
            "ts": [datetime(2024, 7, 2, tzinfo=timezone.utc)],
            "id": [3],
            "src": ["parquet"],
        })
        rows = self.run_merge("--key", "ts,id", "--schema-strategy", "consensus", users, events, metrics)
        self.assertEqual(rows, [
            "id,src,ts",
            "9,jsonl,2024-06-30T23:00:00Z",
            "1,csv,2024-07-01T00:00:00Z",
            "1,jsonl,2024-07-01T00:00:00Z",
            "2,csv,2024-07-01T00:00:00Z",
            "3,parquet,2024-07-02T00:00:00Z",
        ])

    def test_forced_tsv_and_gzip_with_an_explicit_schema(self) -> None:
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "created_at", "type": "timestamp"},
            {"name": "id", "type": "int"},
        ]}))
        first = self.write_gzip("part-1.tsv.gz", "created_at\tid\tnote\n2024-01-01T00:00:00Z\t1\tone\n")
        second = self.write_gzip("part-2.tsv.gz", "created_at\tid\tnote\n2024-01-02T00:00:00Z\t2\ttwo\n")
        rows = self.run_merge(
            "--key", "created_at,id", "--desc", "--schema", schema,
            "--input-format", "tsv", "--compression", "gzip", first, second,
        )
        self.assertEqual(rows, ["created_at,id", "2024-01-02T00:00:00Z,2", "2024-01-01T00:00:00Z,1"])

    def test_every_row_appears_once_and_spilling_keeps_the_order(self) -> None:
        csv_input = self.write("a.csv", "id\n" + "".join(f"{index}\n" for index in range(0, 3000, 2)))
        jsonl_input = self.write_jsonl("b.jsonl", [{"id": index} for index in range(1, 3000, 2)])
        parquet_input = self.write_parquet("c.parquet", {"id": list(range(3000, 4000))})
        rows = self.run_merge(
            "--key", "id", "--memory-limit-mb", "64", "--temp-dir", str(self.root),
            csv_input, jsonl_input, parquet_input,
        )
        self.assertEqual(rows, ["id"] + [str(index) for index in range(4000)])


class OutputTests(FormatTestCase):
    def test_a_failed_run_leaves_the_previous_output_untouched(self) -> None:
        source = self.write("a.csv", "id,amount\n1,oops\n")
        schema = self.write("s.json", json.dumps({"columns": [{"name": "amount", "type": "int"}]}))
        output = self.root / "out.csv"
        output.write_text("keep me\n", encoding="utf-8")
        exit_code = merge_files.main(
            ["--output", str(output), "--key", "amount", "--schema", schema, "--on-type-error", "fail", source]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep me\n")
        self.assertEqual(sorted(entry.name for entry in self.root.iterdir()), ["a.csv", "out.csv", "s.json"])


if __name__ == "__main__":
    unittest.main()
