"""Tests for merge_files.py, run with: python -m unittest -v"""

from __future__ import annotations

import csv
import gzip
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import merge_files


class MergeTestCase(unittest.TestCase):
    """Base class giving each test a scratch directory and a runner."""

    def setUp(self) -> None:
        self._workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self._workspace.cleanup)
        self.directory = Path(self._workspace.name)
        self.output = self.directory / "merged.csv"

    def write(self, name: str, text: str) -> str:
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def write_gzip(self, name: str, text: str) -> str:
        path = self.directory / name
        path.write_bytes(gzip.compress(text.encode("utf-8")))
        return str(path)

    def write_jsonl(self, name: str, *objects: dict) -> str:
        return self.write(name, "".join(json.dumps(item) + "\n" for item in objects))

    def write_parquet(self, name: str, table: pa.Table, **options: int) -> str:
        path = self.directory / name
        pq.write_table(table, path, **options)
        return str(path)

    def schema_file(self, *columns: tuple[str, object]) -> str:
        """Write a schema; a type is a name or the object form of a nested type."""
        document = {"columns": [{"name": name, "type": kind} for name, kind in columns]}
        return self.write("schema.json", json.dumps(document))

    def alias_file(self, **aliases: str) -> str:
        return self.write("aliases.json", json.dumps({"aliases": aliases}))

    def run_partitioned(self, *argv: str) -> tuple[int, Path]:
        """Run the tool into a scratch directory and return its code and path."""
        destination = self.directory / "out"
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = merge_files.main(["--output", str(destination), *argv])
        self.stderr = stderr.getvalue()
        return code, destination

    def tree(self, root: Path) -> list[str]:
        """Every file under ``root``, as sorted paths relative to it."""
        return sorted(path.relative_to(root).as_posix() for path in root.rglob("*.csv"))

    def part(self, root: Path, name: str) -> list[list[str]]:
        """The rows, header first, of one part file under ``root``."""
        return list(csv.reader(io.StringIO((root / name).read_text(encoding="utf-8"))))

    def run_merge(self, *argv: str) -> tuple[int, list[list[str]]]:
        """Run the tool into a scratch file and return its exit code and rows.

        The raw output text is kept on ``self.raw`` and stderr on ``self.stderr``.
        """
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = merge_files.main(["--output", str(self.output), *argv])
        self.stderr = stderr.getvalue()
        self.raw = self.output.read_text(encoding="utf-8") if self.output.exists() else ""
        return code, list(csv.reader(io.StringIO(self.raw)))


class SchemaResolutionTests(MergeTestCase):
    def test_explicit_schema_orders_ignores_and_fills_columns(self):
        first = self.write("a.csv", "id,note,dropped\n1,alpha,x\n")
        second = self.write("b.csv", "note,id\nbeta,2\n")
        schema = self.schema_file(("id", "int"), ("note", "string"), ("missing", "string"))
        code, rows = self.run_merge("--key", "id", "--schema", schema, first, second)
        self.assertEqual(code, 0)
        self.assertEqual(rows, [["id", "note", "missing"], ["1", "alpha", ""], ["2", "beta", ""]])

    def test_inferred_columns_are_the_lexicographic_header_union(self):
        first = self.write("a.csv", "b,a\n1,2\n")
        second = self.write("b.csv", "c,a\n3,4\n")
        _code, rows = self.run_merge("--key", "a", first, second)
        self.assertEqual(rows[0], ["a", "b", "c"])

    def test_strict_inference_falls_back_to_string_when_files_disagree(self):
        first = self.write("a.csv", "n\n1\n2\n")
        second = self.write("b.csv", "n\n2.5\n")
        _code, rows = self.run_merge("--key", "n", "--infer", "strict", first, second)
        self.assertEqual([row[0] for row in rows[1:]], ["1", "2", "2.5"])

    def test_loose_inference_pools_values_into_one_numeric_type(self):
        first = self.write("a.csv", "n\n1\n2\n")
        second = self.write("b.csv", "n\n2.5\n")
        _code, rows = self.run_merge("--key", "n", "--infer", "loose", first, second)
        self.assertEqual([row[0] for row in rows[1:]], ["1.0", "2.0", "2.5"])

    def test_a_column_of_nulls_is_a_string_column(self):
        source = self.write("a.csv", "n,empty\n1,\n,\n3,\n")
        _code, rows = self.run_merge("--key", "n", "--infer", "loose", source)
        self.assertEqual(rows[0], ["empty", "n"])
        self.assertEqual([row[1] for row in rows[1:]], ["", "1", "3"])

    def test_unknown_key_column_is_an_error(self):
        source = self.write("a.csv", "id\n1\n")
        code, _rows = self.run_merge("--key", "nope", source)
        self.assertEqual(code, 3)
        self.assertIn("nope", self.stderr)

    def test_unknown_type_in_schema_is_an_error(self):
        source = self.write("a.csv", "id\n1\n")
        schema = self.schema_file(("id", "nope"))
        code, _rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(code, 6)
        self.assertIn("unknown column type", self.stderr)


class CastingTests(MergeTestCase):
    def test_types_are_rendered_canonically(self):
        source = self.write(
            "a.csv",
            "i,f,b,d,t\n"
            "007,2,1,2024-07-01,2024-07-01T12:00:00+02:00\n"
            "-1,3.50,false,2024-01-31,2024-07-01 08:00:00.500\n",
        )
        schema = self.schema_file(
            ("i", "int"), ("f", "float"), ("b", "bool"), ("d", "date"), ("t", "timestamp")
        )
        _code, rows = self.run_merge("--key", "i", "--schema", schema, source)
        self.assertEqual(rows[1], ["-1", "3.5", "false", "2024-01-31", "2024-07-01T08:00:00.500Z"])
        self.assertEqual(rows[2], ["7", "2.0", "true", "2024-07-01", "2024-07-01T10:00:00Z"])

    def test_coerce_null_replaces_unparsable_cells(self):
        source = self.write("a.csv", "id,amount\n1,oops\n")
        schema = self.schema_file(("id", "int"), ("amount", "float"))
        _code, rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1], ["1", ""])

    def test_keep_string_preserves_the_original_text(self):
        source = self.write("a.csv", "id,amount\n1,oops\n")
        schema = self.schema_file(("id", "int"), ("amount", "float"))
        _code, rows = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "keep-string", source
        )
        self.assertEqual(rows[1], ["1", "oops"])

    def test_fail_reports_the_bad_cell_and_exits_non_zero(self):
        source = self.write("a.csv", "id,amount\n1,oops\n")
        schema = self.schema_file(("id", "int"), ("amount", "float"))
        code, _rows = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "fail", source
        )
        self.assertEqual(code, 4)
        self.assertIn("amount", self.stderr)

    def test_null_literal_is_used_for_missing_values(self):
        first = self.write("a.csv", "id,note\n1,\n")
        second = self.write("b.csv", "id\n2\n")
        _code, rows = self.run_merge("--key", "id", "--csv-null-literal", "NULL", first, second)
        self.assertEqual(rows[1:], [["1", "NULL"], ["2", "NULL"]])

    def test_short_rows_are_padded_with_nulls(self):
        source = self.write("a.csv", "id,note\n1\n2,here\n")
        _code, rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows[1:], [["1", ""], ["2", "here"]])


class SortingTests(MergeTestCase):
    def test_composite_key_and_descending_order(self):
        source = self.write("a.csv", "a,b\n1,2\n1,1\n2,1\n")
        schema = self.schema_file(("a", "int"), ("b", "int"))
        _code, rows = self.run_merge("--key", "a,b", "--desc", "--schema", schema, source)
        self.assertEqual(rows[1:], [["2", "1"], ["1", "2"], ["1", "1"]])

    def test_nulls_sort_first_ascending_and_last_descending(self):
        source = self.write("a.csv", "id,k\n1,5\n2,\n3,1\n")
        schema = self.schema_file(("id", "int"), ("k", "int"))
        _code, ascending = self.run_merge("--key", "k", "--schema", schema, source)
        self.assertEqual([row[0] for row in ascending[1:]], ["2", "3", "1"])
        _code, descending = self.run_merge("--key", "k", "--desc", "--schema", schema, source)
        self.assertEqual([row[0] for row in descending[1:]], ["1", "3", "2"])

    def test_sort_is_stable_across_files_in_both_directions(self):
        first = self.write("a.csv", "k,v\n1,a1\n1,a2\n")
        second = self.write("b.csv", "k,v\n1,b1\n1,b2\n")
        schema = self.schema_file(("k", "int"), ("v", "string"))
        for extra in ([], ["--desc"]):
            with self.subTest(order=extra):
                _code, rows = self.run_merge("--key", "k", "--schema", schema, *extra, first, second)
                self.assertEqual([row[1] for row in rows[1:]], ["a1", "a2", "b1", "b2"])

    def test_spilled_runs_sort_like_an_in_memory_sort(self):
        values = [(index * 7919) % 1000 for index in range(1000)]
        source = self.write("a.csv", "k\n" + "".join(f"{value}\n" for value in values))
        schema = self.schema_file(("k", "int"))
        _code, buffered = self.run_merge("--key", "k", "--schema", schema, source)
        self.assertEqual([int(row[0]) for row in buffered[1:]], sorted(values))
        _code, spilled = self.run_merge(
            "--key", "k", "--schema", schema, "--memory-limit-mb", "0", source
        )
        self.assertEqual(spilled, buffered)

    def test_timestamps_sort_by_instant_not_by_text(self):
        source = self.write(
            "a.csv",
            "id,t\n1,2024-07-01T12:00:00Z\n2,2024-07-01T09:00:00-05:00\n3,2024-07-01T12:00:00.5Z\n",
        )
        schema = self.schema_file(("id", "int"), ("t", "timestamp"))
        _code, rows = self.run_merge(
            "--key", "t", "--schema", schema, "--memory-limit-mb", "0", source
        )
        self.assertEqual([row[0] for row in rows[1:]], ["1", "3", "2"])

    def test_kept_strings_sort_after_the_values_of_their_column(self):
        source = self.write("a.csv", "id,k\n1,oops\n2,10\n3,\n")
        schema = self.schema_file(("id", "int"), ("k", "int"))
        _code, rows = self.run_merge(
            "--key", "k", "--schema", schema, "--on-type-error", "keep-string", source
        )
        self.assertEqual([row[0] for row in rows[1:]], ["3", "2", "1"])


class DialectTests(MergeTestCase):
    def test_both_escape_styles_are_read_and_quotes_are_doubled_on_output(self):
        source = self.write("a.csv", 'id,note\n1,"a\\"b"\n2,"c""d"\n3,"e,f"\n')
        _code, rows = self.run_merge("--key", "id", source)
        self.assertEqual([row[1] for row in rows[1:]], ['a"b', 'c"d', "e,f"])
        self.assertIn('"a""b"', self.raw)

    def test_custom_quote_character_is_read_and_written(self):
        source = self.write("a.csv", "id,note\n7,'c,d'\n")
        code, _rows = self.run_merge("--key", "id", "--csv-quotechar", "'", source)
        self.assertEqual(code, 0)
        self.assertEqual(self.raw, "id,note\n7,'c,d'\n")

    def test_output_uses_newline_line_endings(self):
        source = self.write("a.csv", "id\n2\n1\n")
        code, _rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 0)
        self.assertEqual(self.output.read_bytes(), b"id\n1\n2\n")

    def test_dash_writes_the_merged_csv_to_stdout(self):
        source = self.write("a.csv", "id\n2\n1\n")
        finished = subprocess.run(
            [sys.executable, str(Path(merge_files.__file__)), "--output", "-", "--key", "id", source],
            capture_output=True,
            check=True,
        )
        self.assertEqual(finished.stdout, b"id\n1\n2\n")

    def test_temporary_runs_are_removed(self):
        temp_dir = self.directory / "spill"
        temp_dir.mkdir()
        source = self.write("a.csv", "id\n" + "".join(f"{value}\n" for value in range(500)))
        code, _rows = self.run_merge(
            "--key", "id", "--memory-limit-mb", "0", "--temp-dir", str(temp_dir), source
        )
        self.assertEqual(code, 0)
        self.assertEqual(list(temp_dir.iterdir()), [])


class FormatDetectionTests(MergeTestCase):
    def test_extensions_name_the_format(self):
        csv_input = self.write("a.csv", "id\n1\n")
        tsv_input = self.write("b.tsv", "id\n2\n")
        jsonl_input = self.write_jsonl("c.jsonl", {"id": 3})
        ndjson_input = self.write_jsonl("d.ndjson", {"id": 4})
        parquet_input = self.write_parquet("e.parquet", pa.table({"id": [5]}))
        code, rows = self.run_merge(
            "--key", "id", csv_input, tsv_input, jsonl_input, ndjson_input, parquet_input
        )
        self.assertEqual(code, 0)
        self.assertEqual([row[0] for row in rows[1:]], ["1", "2", "3", "4", "5"])

    def test_gzip_suffix_follows_the_base_extension(self):
        csv_input = self.write_gzip("a.csv.gz", "id\n1\n")
        jsonl_input = self.write_gzip("b.jsonl.gz", '{"id": 2}\n')
        _code, rows = self.run_merge("--key", "id", csv_input, jsonl_input)
        self.assertEqual([row[0] for row in rows[1:]], ["1", "2"])

    def test_parquet_magic_bytes_settle_an_unknown_extension(self):
        mystery = self.write_parquet("data.bin", pa.table({"id": [7]}))
        _code, rows = self.run_merge("--key", "id", mystery)
        self.assertEqual(rows[1:], [["7"]])

    def test_an_undetectable_extension_is_a_usage_error(self):
        mystery = self.write("data.txt", "id\n1\n")
        code, _rows = self.run_merge("--key", "id", mystery)
        self.assertEqual(code, 2)
        self.assertIn("--input-format", self.stderr)

    def test_input_format_overrides_the_extension(self):
        mystery = self.write("data.txt", "id\tnote\n41\tx\n")
        _code, rows = self.run_merge("--key", "id", "--input-format", "tsv", mystery)
        self.assertEqual(rows, [["id", "note"], ["41", "x"]])

    def test_forced_gzip_on_plain_data_is_a_compression_error(self):
        source = self.write("a.csv", "id\n1\n")
        code, _rows = self.run_merge("--key", "id", "--compression", "gzip", source)
        self.assertEqual(code, 5)
        self.assertIn("compression", self.stderr)

    def test_forced_none_on_gzip_data_is_a_compression_error(self):
        source = self.write_gzip("a.csv.gz", "id\n1\n")
        code, _rows = self.run_merge("--key", "id", "--compression", "none", source)
        self.assertEqual(code, 5)

    def test_a_gz_name_without_gzip_content_is_a_compression_error(self):
        source = self.write("a.csv.gz", "id\n1\n")
        code, _rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 5)

    def test_a_truncated_gzip_stream_is_a_data_error(self):
        whole = gzip.compress(b"id\n1\n")
        source = self.directory / "a.csv.gz"
        source.write_bytes(whole[: len(whole) - 4])
        code, _rows = self.run_merge("--key", "id", str(source))
        self.assertEqual(code, 5)

    def test_a_file_that_only_looks_like_parquet_is_a_data_error(self):
        source = self.write("a.parquet", "PAR1 and nothing else")
        code, _rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 5)

    def test_a_missing_input_is_reported_without_a_traceback(self):
        code, _rows = self.run_merge("--key", "id", str(self.directory / "absent.csv"))
        self.assertEqual(code, 1)
        self.assertIn("absent.csv", self.stderr)


class TsvTests(MergeTestCase):
    def test_tabs_separate_fields_and_crlf_endings_are_accepted(self):
        source = self.write("a.tsv", "id\tnote\r\n2\tb\r\n1\ta\r\n")
        _code, rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows, [["id", "note"], ["1", "a"], ["2", "b"]])

    def test_quotes_are_data_rather_than_quoting(self):
        source = self.write("a.tsv", 'id\tnote\n41\t"a,b"\n')
        _code, rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows[1], ["41", '"a,b"'])

    def test_a_literal_tab_inside_a_field_is_a_data_error(self):
        source = self.write("a.tsv", "id\tnote\n1\ta\tb\n")
        code, _rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 5)
        self.assertIn("tab", self.stderr)


class JsonlTests(MergeTestCase):
    def test_values_arrive_typed_and_blank_lines_are_ignored(self):
        source = self.write("a.jsonl", '{"id": 1, "ok": true}\n\n   \n{"id": 2, "ok": false}\n')
        _code, rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows, [["id", "ok"], ["1", "true"], ["2", "false"]])

    def test_the_column_set_is_the_union_of_the_object_keys(self):
        source = self.write_jsonl("a.jsonl", {"b": 1}, {"a": 2})
        _code, rows = self.run_merge("--key", "a", source)
        self.assertEqual(rows, [["a", "b"], ["", "1"], ["2", ""]])

    def test_keys_are_case_sensitive(self):
        source = self.write_jsonl("a.jsonl", {"id": 1, "ID": 2})
        _code, rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows, [["ID", "id"], ["2", "1"]])

    def test_a_whole_number_stays_an_integer_and_a_fraction_becomes_a_float(self):
        source = self.write_jsonl("a.jsonl", {"n": 1.0}, {"n": 2.5})
        _code, rows = self.run_merge("--key", "n", "--infer", "loose", source)
        self.assertEqual([row[0] for row in rows[1:]], ["1.0", "2.5"])

    def test_the_number_one_is_not_a_boolean(self):
        source = self.write_jsonl("a.jsonl", {"n": 1}, {"n": 0})
        _code, rows = self.run_merge("--key", "n", source)
        self.assertEqual([row[0] for row in rows[1:]], ["0", "1"])

    def test_null_becomes_the_null_literal(self):
        source = self.write_jsonl("a.jsonl", {"id": 1, "note": None})
        _code, rows = self.run_merge("--key", "id", "--csv-null-literal", "NULL", source)
        self.assertEqual(rows[1], ["1", "NULL"])

    def test_a_nested_value_is_a_schema_error(self):
        source = self.write("a.jsonl", '{"id": 1, "tags": ["x"], "meta": {"k": 1}}\n')
        code, _rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 6)
        self.assertIn("meta, tags", self.stderr)

    def test_a_broken_line_is_a_data_error(self):
        source = self.write("a.jsonl", '{"id": 1}\n{"id":\n')
        code, _rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 5)
        self.assertIn("line 2", self.stderr)

    def test_a_line_that_is_not_an_object_is_a_data_error(self):
        source = self.write("a.jsonl", "[1, 2]\n")
        code, _rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 5)


class ParquetTests(MergeTestCase):
    def test_declared_types_are_used_and_rendered_canonically(self):
        table = pa.table(
            {
                "id": pa.array([2, 1], pa.int32()),
                "amount": pa.array([1.5, None], pa.float64()),
                "day": pa.array([date(2024, 3, 1), date(2024, 2, 1)]),
                "seen": pa.array([datetime(2024, 3, 1, 12, 30), None], pa.timestamp("ms")),
                "ok": pa.array([True, False]),
                "tag": pa.array(["b", "a"]),
            }
        )
        source = self.write_parquet("a.parquet", table)
        _code, rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows[0], ["amount", "day", "id", "ok", "seen", "tag"])
        self.assertEqual(rows[1], ["", "2024-02-01", "1", "false", "", "a"])
        self.assertEqual(rows[2], ["1.5", "2024-03-01", "2", "true", "2024-03-01T12:30:00Z", "b"])

    def test_a_nested_column_is_a_schema_error(self):
        table = pa.table({"id": [1], "tags": [["x", "y"]]})
        source = self.write_parquet("a.parquet", table)
        code, _rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 6)
        self.assertIn("tags", self.stderr)

    def test_every_row_group_is_read_with_a_small_batch_budget(self):
        table = pa.table({"id": list(range(500, 0, -1))})
        source = self.write_parquet("a.parquet", table, row_group_size=50)
        code, rows = self.run_merge(
            "--key", "id", "--parquet-row-group-bytes", "64", "--memory-limit-mb", "64", source
        )
        self.assertEqual(code, 0)
        self.assertEqual([int(row[0]) for row in rows[1:]], list(range(1, 501)))

    def test_a_gzipped_parquet_file_is_read(self):
        plain = Path(self.write_parquet("a.parquet", pa.table({"id": [4, 3]})))
        source = self.directory / "a.parquet.gz"
        source.write_bytes(gzip.compress(plain.read_bytes()))
        _code, rows = self.run_merge("--key", "id", str(source))
        self.assertEqual([row[0] for row in rows[1:]], ["3", "4"])


class SchemaStrategyTests(MergeTestCase):
    def test_authoritative_prefers_the_parquet_type(self):
        typed = self.write_parquet("a.parquet", pa.table({"n": pa.array([1.5], pa.float64())}))
        text = self.write("b.csv", "n\n2\n")
        _code, rows = self.run_merge("--key", "n", typed, text)
        self.assertEqual([row[0] for row in rows[1:]], ["1.5", "2.0"])

    def test_authoritative_lets_csv_outrank_tsv(self):
        text = self.write("a.csv", "n\n5\n")
        weak = self.write("b.tsv", "n\nnot-a-number\n")
        _code, rows = self.run_merge("--key", "n", text, weak)
        self.assertEqual([row[0] for row in rows[1:]], ["", "5"])

    def test_authoritative_ranks_jsonl_with_csv_so_they_disagree(self):
        text = self.write("a.csv", "n\n5\n")
        objects = self.write_jsonl("b.jsonl", {"n": 2.5})
        _code, rows = self.run_merge("--key", "n", text, objects)
        self.assertEqual([row[0] for row in rows[1:]], ["2.5", "5"])

    def test_consensus_follows_the_majority_of_files(self):
        first = self.write("a.csv", "n\n5\n")
        second = self.write("b.csv", "n\n7\n")
        third = self.write("c.csv", "n\n2.5\n")
        _code, rows = self.run_merge(
            "--key", "n", "--schema-strategy", "consensus", first, second, third
        )
        self.assertEqual([row[0] for row in rows[1:]], ["", "5", "7"])

    def test_consensus_reconciles_a_tie_the_way_infer_asks(self):
        first = self.write("a.csv", "n\n5\n")
        second = self.write("b.csv", "n\n2.5\n")
        _code, strict = self.run_merge(
            "--key", "n", "--schema-strategy", "consensus", first, second
        )
        self.assertEqual([row[0] for row in strict[1:]], ["2.5", "5"])
        _code, loose = self.run_merge(
            "--key", "n", "--schema-strategy", "consensus", "--infer", "loose", first, second
        )
        self.assertEqual([row[0] for row in loose[1:]], ["2.5", "5.0"])

    def test_union_widens_to_hold_every_value(self):
        typed = self.write_parquet("a.parquet", pa.table({"n": pa.array([5], pa.int64())}))
        objects = self.write_jsonl("b.jsonl", {"n": 2.5})
        _code, rows = self.run_merge("--key", "n", "--schema-strategy", "union", typed, objects)
        self.assertEqual([row[0] for row in rows[1:]], ["2.5", "5.0"])

    def test_a_provided_schema_ignores_the_strategies(self):
        objects = self.write_jsonl("a.jsonl", {"id": 1, "extra": "dropped"})
        typed = self.write_parquet("b.parquet", pa.table({"id": pa.array([2], pa.int64())}))
        schema = self.schema_file(("id", "string"), ("missing", "int"))
        _code, rows = self.run_merge("--key", "id", "--schema", schema, objects, typed)
        self.assertEqual(rows, [["id", "missing"], ["1", ""], ["2", ""]])

    def test_a_key_outside_the_resolved_schema_is_an_error(self):
        objects = self.write_jsonl("a.jsonl", {"id": 1})
        code, _rows = self.run_merge("--key", "id,when", objects)
        self.assertEqual(code, 3)
        self.assertIn("when", self.stderr)


class MixedSourceTests(MergeTestCase):
    def build_inputs(self) -> list[str]:
        """One row per format, each with the same three columns."""
        return [
            self.write("a.csv", "ts,id,src\n2024-01-02T00:00:00Z,2,csv\n"),
            self.write_gzip(
                "b.jsonl.gz", '{"ts": "2024-01-01T00:00:00Z", "id": 3, "src": "jsonl"}\n'
            ),
            self.write_parquet(
                "c.parquet",
                pa.table(
                    {
                        "ts": pa.array([datetime(2024, 1, 1)], pa.timestamp("ms")),
                        "id": pa.array([1], pa.int64()),
                        "src": ["parquet"],
                    }
                ),
            ),
        ]

    def test_composite_key_sorts_across_formats(self):
        code, rows = self.run_merge(
            "--key", "ts,id", "--schema-strategy", "consensus", *self.build_inputs()
        )
        self.assertEqual(code, 0)
        self.assertEqual(rows[0], ["id", "src", "ts"])
        self.assertEqual([row[1] for row in rows[1:]], ["parquet", "jsonl", "csv"])

    def test_descending_order_reverses_the_mixed_result(self):
        _code, rows = self.run_merge(
            "--key", "ts,id", "--desc", "--schema-strategy", "consensus", *self.build_inputs()
        )
        self.assertEqual([row[1] for row in rows[1:]], ["csv", "jsonl", "parquet"])

    def test_equal_keys_keep_the_order_of_the_sources(self):
        first = self.write("a.csv", "k,v\n1,csv\n")
        second = self.write_jsonl("b.jsonl", {"k": 1, "v": "jsonl"})
        third = self.write_parquet(
            "c.parquet", pa.table({"k": pa.array([1], pa.int64()), "v": ["parquet"]})
        )
        for extra in ([], ["--desc"]):
            with self.subTest(order=extra):
                _code, rows = self.run_merge("--key", "k", *extra, first, second, third)
                self.assertEqual([row[1] for row in rows[1:]], ["csv", "jsonl", "parquet"])

    def test_every_row_appears_once_when_the_sort_spills(self):
        rows_per_source = 300
        csv_input = self.write(
            "a.csv", "k\n" + "".join(f"{value}\n" for value in range(rows_per_source))
        )
        jsonl_input = self.write_jsonl(
            "b.jsonl", *({"k": value} for value in range(rows_per_source))
        )
        parquet_input = self.write_parquet(
            "c.parquet",
            pa.table({"k": pa.array(list(range(rows_per_source)), pa.int64())}),
            row_group_size=64,
        )
        _code, rows = self.run_merge(
            "--key", "k", "--memory-limit-mb", "0", csv_input, jsonl_input, parquet_input
        )
        keys = [int(row[0]) for row in rows[1:]]
        self.assertEqual(len(keys), 3 * rows_per_source)
        self.assertEqual(keys, sorted(keys))


class OutputTests(MergeTestCase):
    def test_a_failed_run_leaves_neither_output_nor_partial_file(self):
        source = self.write("a.csv", "id,amount\n1,oops\n")
        schema = self.schema_file(("id", "int"), ("amount", "float"))
        code, _rows = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "fail", source
        )
        self.assertEqual(code, 4)
        self.assertFalse(self.output.exists())
        self.assertEqual(sorted(path.name for path in self.directory.glob("*.part")), [])

    def test_an_existing_output_is_replaced_in_one_step(self):
        source = self.write("a.csv", "id\n41\n")
        self.output.write_text("stale\n", encoding="utf-8")
        code, rows = self.run_merge("--key", "id", source)
        self.assertEqual(code, 0)
        self.assertEqual(rows, [["id"], ["41"]])


class FieldPartitionTests(MergeTestCase):
    def test_each_value_combination_gets_a_hive_directory(self):
        source = self.write(
            "a.csv",
            "country,dt,id\nUS,2024-01-01,2\nFR,2024-01-02,1\nUS,2024-01-01,3\n",
        )
        code, root = self.run_partitioned("--key", "id", "--partition-by", "country,dt", source)
        self.assertEqual(code, 0)
        self.assertEqual(
            self.tree(root),
            [
                "country=FR/dt=2024-01-02/part-00000.csv",
                "country=US/dt=2024-01-01/part-00000.csv",
            ],
        )
        self.assertEqual(
            self.part(root, "country=US/dt=2024-01-01/part-00000.csv"),
            [["country", "dt", "id"], ["US", "2024-01-01", "2"], ["US", "2024-01-01", "3"]],
        )

    def test_partition_directories_follow_the_order_of_the_flag(self):
        source = self.write("a.csv", "a,b,id\nx,y,1\n")
        _code, root = self.run_partitioned("--key", "id", "--partition-by", "b,a", source)
        self.assertEqual(self.tree(root), ["b=y/a=x/part-00000.csv"])

    def test_values_are_percent_encoded_by_their_utf8_bytes(self):
        source = self.write(
            "a.csv", "name,id\nFr an/ce,1\n\u65e5\u672c,2\na~b,3\nplain._-,4\n"
        )
        _code, root = self.run_partitioned("--key", "id", "--partition-by", "name", source)
        self.assertEqual(
            self.tree(root),
            [
                "name=%E6%97%A5%E6%9C%AC/part-00000.csv",
                "name=Fr%20an%2Fce/part-00000.csv",
                "name=a%7Eb/part-00000.csv",
                "name=plain._-/part-00000.csv",
            ],
        )

    def test_a_missing_value_partitions_as_null(self):
        first = self.write("a.csv", "country,id\nUS,1\n,2\n")
        second = self.write_jsonl("b.jsonl", {"id": 3}, {"id": 4, "country": None})
        _code, root = self.run_partitioned(
            "--key", "id", "--partition-by", "country", first, second
        )
        self.assertEqual(
            self.tree(root), ["country=US/part-00000.csv", "country=_null/part-00000.csv"]
        )
        self.assertEqual(
            [row[1] for row in self.part(root, "country=_null/part-00000.csv")[1:]],
            ["2", "3", "4"],
        )

    def test_a_value_is_partitioned_after_it_is_cast(self):
        source = self.write("a.csv", "id,n\n1,007\n2,7\n")
        schema = self.schema_file(("id", "int"), ("n", "int"))
        _code, root = self.run_partitioned(
            "--key", "id", "--schema", schema, "--partition-by", "n", source
        )
        self.assertEqual(self.tree(root), ["n=7/part-00000.csv"])

    def test_rows_are_sorted_inside_every_partition(self):
        source = self.write(
            "a.csv", "g,ts\nb,3\na,2\nb,1\na,4\nb,2\n"
        )
        _code, root = self.run_partitioned("--key", "ts", "--partition-by", "g", source)
        self.assertEqual(
            [row[1] for row in self.part(root, "g=a/part-00000.csv")[1:]], ["2", "4"]
        )
        self.assertEqual(
            [row[1] for row in self.part(root, "g=b/part-00000.csv")[1:]], ["1", "2", "3"]
        )

    def test_desc_reverses_the_order_inside_every_partition(self):
        source = self.write("a.csv", "g,ts\na,1\nb,1\na,2\nb,2\n")
        _code, root = self.run_partitioned("--key", "ts", "--desc", "--partition-by", "g", source)
        for partition in ("g=a", "g=b"):
            self.assertEqual(
                [row[1] for row in self.part(root, f"{partition}/part-00000.csv")[1:]], ["2", "1"]
            )

    def test_partition_columns_stay_in_the_output_rows(self):
        source = self.write("a.csv", "g,id\na,7\n")
        _code, root = self.run_partitioned("--key", "id", "--partition-by", "g", source)
        self.assertEqual(self.part(root, "g=a/part-00000.csv"), [["g", "id"], ["a", "7"]])

    def test_partitions_survive_a_spilled_sort(self):
        values = [(index * 7919) % 500 for index in range(1000)]
        source = self.write(
            "a.csv", "g,k\n" + "".join(f"g{value % 4},{value}\n" for value in values)
        )
        schema = self.schema_file(("g", "string"), ("k", "int"))
        code, root = self.run_partitioned(
            "--key", "k", "--schema", schema, "--partition-by", "g",
            "--memory-limit-mb", "0", source,
        )
        self.assertEqual(code, 0)
        merged = []
        for group in range(4):
            rows = self.part(root, f"g=g{group}/part-00000.csv")[1:]
            keys = [int(row[1]) for row in rows]
            self.assertEqual(keys, sorted(keys))
            self.assertEqual({row[0] for row in rows}, {f"g{group}"})
            merged += keys
        self.assertEqual(sorted(merged), sorted(values))

    def test_an_unknown_partition_column_is_a_usage_error(self):
        source = self.write("a.csv", "id\n1\n")
        code, root = self.run_partitioned("--key", "id", "--partition-by", "id,nope", source)
        self.assertEqual(code, 2)
        self.assertIn("partition column(s) not in the resolved schema: nope", self.stderr)
        self.assertFalse(root.exists())

    def test_an_empty_partition_list_is_a_usage_error(self):
        source = self.write("a.csv", "id\n1\n")
        code, _root = self.run_partitioned("--key", "id", "--partition-by", " ,", source)
        self.assertEqual(code, 2)
        self.assertIn("--partition-by needs at least one column name", self.stderr)


class ShardingTests(MergeTestCase):
    def source_of(self, rows: int) -> str:
        return self.write("a.csv", "id\n" + "".join(f"{value}\n" for value in range(rows)))

    def test_max_rows_per_file_cuts_every_file_at_the_limit(self):
        source = self.source_of(7)
        code, root = self.run_partitioned("--key", "id", "--max-rows-per-file", "3", source)
        self.assertEqual(code, 0)
        self.assertEqual(
            self.tree(root),
            ["part-00000.csv", "part-00001.csv", "part-00002.csv"],
        )
        self.assertEqual(self.part(root, "part-00000.csv"), [["id"], ["0"], ["1"], ["2"]])
        self.assertEqual(self.part(root, "part-00002.csv"), [["id"], ["6"]])

    def test_every_part_repeats_the_header(self):
        source = self.source_of(4)
        _code, root = self.run_partitioned("--key", "id", "--max-rows-per-file", "1", source)
        for name in self.tree(root):
            self.assertEqual(self.part(root, name)[0], ["id"])

    def test_max_bytes_per_file_counts_the_header_and_the_line_endings(self):
        source = self.source_of(10)
        # The 3 byte header leaves room for four of the 2 byte rows.
        _code, root = self.run_partitioned("--key", "id", "--max-bytes-per-file", "12", source)
        sizes = [(root / name).stat().st_size for name in self.tree(root)]
        self.assertEqual(sizes, [11, 11, 7])
        self.assertEqual(self.part(root, "part-00000.csv"), [["id"], ["0"], ["1"], ["2"], ["3"]])

    def test_a_row_too_large_for_the_limit_gets_a_file_of_its_own(self):
        source = self.write("a.csv", "id,note\n1,short\n2," + "x" * 100 + "\n3,short\n")
        _code, root = self.run_partitioned("--key", "id", "--max-bytes-per-file", "20", source)
        self.assertEqual(
            self.tree(root), ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
        )
        self.assertGreater((root / "part-00001.csv").stat().st_size, 20)
        self.assertEqual(len(self.part(root, "part-00001.csv")), 2)

    def test_both_limits_cut_at_the_earliest_boundary(self):
        source = self.source_of(10)
        _code, root = self.run_partitioned(
            "--key", "id", "--max-rows-per-file", "4", "--max-bytes-per-file", "9", source
        )
        written = [len(self.part(root, name)) - 1 for name in self.tree(root)]
        self.assertEqual(written, [3, 3, 3, 1])

    def test_each_partition_is_sharded_on_its_own(self):
        source = self.write(
            "a.csv", "g,id\n" + "".join(f"g{value % 2},{value}\n" for value in range(10))
        )
        _code, root = self.run_partitioned(
            "--key", "id", "--partition-by", "g", "--max-rows-per-file", "2", source
        )
        self.assertEqual(
            self.tree(root),
            [f"g=g{group}/part-{index:05d}.csv" for group in (0, 1) for index in range(3)],
        )
        self.assertEqual(
            [row[1] for row in self.part(root, "g=g1/part-00000.csv")[1:]], ["1", "3"]
        )

    def test_the_stream_is_globally_sorted_across_the_parts(self):
        values = [(index * 7919) % 1000 for index in range(1000)]
        source = self.write("a.csv", "k\n" + "".join(f"{value}\n" for value in values))
        schema = self.schema_file(("k", "int"),)
        _code, root = self.run_partitioned(
            "--key", "k", "--schema", schema, "--max-rows-per-file", "64", source
        )
        emitted = [int(row[0]) for name in self.tree(root) for row in self.part(root, name)[1:]]
        self.assertEqual(emitted, sorted(values))

    def test_an_empty_result_still_writes_a_header_only_part(self):
        source = self.write("a.csv", "id\n")
        _code, root = self.run_partitioned("--key", "id", "--max-rows-per-file", "5", source)
        self.assertEqual(self.tree(root), ["part-00000.csv"])
        self.assertEqual(self.part(root, "part-00000.csv"), [["id"]])

    def test_a_limit_below_one_is_a_usage_error(self):
        source = self.write("a.csv", "id\n1\n")
        code, root = self.run_partitioned("--key", "id", "--max-bytes-per-file", "0", source)
        self.assertEqual(code, 2)
        self.assertIn("--max-bytes-per-file must be at least 1", self.stderr)
        self.assertFalse(root.exists())

    def test_stdout_cannot_hold_a_partitioned_output(self):
        source = self.write("a.csv", "id\n1\n")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = merge_files.main(
                ["--output", "-", "--key", "id", "--max-rows-per-file", "5", source]
            )
        self.assertEqual(code, 2)
        self.assertIn("--output must be a directory", stderr.getvalue())


class PartitionedOutputTests(MergeTestCase):
    def test_the_output_directory_is_created_with_its_parents(self):
        source = self.write("a.csv", "id\n1\n")
        destination = self.directory / "nested" / "out"
        code = merge_files.main(
            ["--output", str(destination), "--key", "id", "--max-rows-per-file", "5", source]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.tree(destination), ["part-00000.csv"])

    def test_an_existing_directory_is_replaced_whole(self):
        source = self.write("a.csv", "id\n1\n")
        destination = self.directory / "out"
        (destination / "g=stale").mkdir(parents=True)
        (destination / "g=stale" / "part-00000.csv").write_text("stale\n", encoding="utf-8")
        code, root = self.run_partitioned("--key", "id", "--max-rows-per-file", "5", source)
        self.assertEqual(code, 0)
        self.assertEqual(self.tree(root), ["part-00000.csv"])
        self.assertEqual(sorted(path.name for path in self.directory.iterdir()), ["a.csv", "out"])

    def test_a_failed_run_keeps_the_previous_directory_and_leaves_no_temp_files(self):
        good = self.write("a.csv", "amount,id\n1.5,7\n")
        code, root = self.run_partitioned("--key", "id", "--max-rows-per-file", "5", good)
        self.assertEqual(code, 0)

        bad = self.write("b.csv", "amount,id\noops,8\n")
        schema = self.schema_file(("amount", "float"), ("id", "int"))
        code, _root = self.run_partitioned(
            "--key", "id", "--schema", schema, "--on-type-error", "fail",
            "--max-rows-per-file", "5", good, bad,
        )
        self.assertEqual(code, 4)
        self.assertEqual(self.part(root, "part-00000.csv"), [["amount", "id"], ["1.5", "7"]])
        self.assertEqual(
            sorted(path.name for path in self.directory.iterdir()),
            ["a.csv", "b.csv", "out", "schema.json"],
        )

    def test_a_file_where_the_directory_should_go_is_a_usage_error(self):
        source = self.write("a.csv", "id\n1\n")
        (self.directory / "out").write_text("in the way\n", encoding="utf-8")
        code, _root = self.run_partitioned("--key", "id", "--max-rows-per-file", "5", source)
        self.assertEqual(code, 2)
        self.assertIn("--output must be a directory", self.stderr)

    def test_the_output_dialect_carries_into_the_parts(self):
        source = self.write("a.csv", 'id,note\n7,"a,b"\n8,\n')
        _code, root = self.run_partitioned(
            "--key", "id", "--csv-null-literal", "NULL", "--max-rows-per-file", "5", source
        )
        self.assertEqual(
            (root / "part-00000.csv").read_text(encoding="utf-8"),
            'id,note\n7,"a,b"\n8,NULL\n',
        )


# The struct, array and map used by most of the nested tests, matching the
# schema of the task description.
USER_TYPE = {
    "struct": {
        "fields": [
            {"name": "id", "type": "int"},
            {"name": "name", "type": "string"},
            {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}},
        ]
    }
}
ITEMS_TYPE = {
    "array": {
        "element": {
            "struct": {
                "fields": [{"name": "sku", "type": "string"}, {"name": "qty", "type": "int"}]
            }
        }
    }
}
ATTRS_TYPE = {"map": {"key": "string", "value": "string"}}


class NestedTypeTests(MergeTestCase):
    def nested_schema(self) -> str:
        return self.schema_file(
            ("id", "int"), ("user", USER_TYPE), ("items", ITEMS_TYPE), ("attrs", ATTRS_TYPE)
        )

    def test_a_nested_column_is_written_as_canonical_json(self):
        source = self.write_jsonl(
            "a.jsonl",
            {
                "id": 1,
                "user": {"prefs": {"z": "1", "a": "2"}, "name": "ada", "id": "7"},
                "items": [{"sku": "x", "qty": "3"}, {"sku": "y", "qty": 4}],
                "attrs": {"b": "2", "a": "1"},
            },
        )
        _code, rows = self.run_merge("--key", "id", "--schema", self.nested_schema(), source)
        self.assertEqual(
            rows[1][1:],
            [
                '{"id":7,"name":"ada","prefs":{"a":"2","z":"1"}}',
                '[{"sku":"x","qty":3},{"sku":"y","qty":4}]',
                '{"a":"1","b":"2"}',
            ],
        )

    def test_missing_struct_fields_are_written_as_explicit_nulls(self):
        source = self.write_jsonl("a.jsonl", {"id": 1, "user": {"name": "ada"}})
        _code, rows = self.run_merge("--key", "id", "--schema", self.nested_schema(), source)
        self.assertEqual(rows[1][1], '{"id":null,"name":"ada","prefs":null}')

    def test_only_a_wholly_null_column_becomes_the_null_literal(self):
        source = self.write_jsonl(
            "a.jsonl", {"id": 1, "user": None, "items": [], "attrs": {}}
        )
        _code, rows = self.run_merge(
            "--key", "id", "--csv-null-literal", "NULL", "--schema", self.nested_schema(), source
        )
        self.assertEqual(rows[1], ["1", "NULL", "[]", "{}"])

    def test_temporal_values_inside_a_nested_column_are_normalised(self):
        schema = self.schema_file(
            ("id", "int"),
            (
                "when",
                {
                    "struct": {
                        "fields": [
                            {"name": "day", "type": "date"},
                            {"name": "at", "type": "timestamp"},
                        ]
                    }
                },
            ),
        )
        source = self.write_jsonl(
            "a.jsonl", {"id": 1, "when": {"day": "2024-07-01", "at": "2024-07-01 12:00:00+02:00"}}
        )
        _code, rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1][1], '{"day":"2024-07-01","at":"2024-07-01T10:00:00Z"}')

    def test_a_csv_cell_holds_one_json_literal_and_an_empty_cell_is_null(self):
        source = self.write("a.csv", 'id,attrs\n1,"{""country"": ""US""}"\n2,\n')
        schema = self.schema_file(("id", "int"), ("attrs", ATTRS_TYPE))
        _code, rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual([row[1] for row in rows[1:]], ['{"country":"US"}', ""])

    def test_a_cell_that_is_not_json_follows_on_type_error(self):
        source = self.write("a.csv", "id,attrs\n1,{oops\n")
        schema = self.schema_file(("id", "int"), ("attrs", ATTRS_TYPE))
        _code, coerced = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(coerced[1], ["1", ""])
        _code, kept = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "keep-string", source
        )
        self.assertEqual(kept[1], ["1", "{oops"])
        code, _rows = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "fail", source
        )
        self.assertEqual(code, 4)
        self.assertIn('cannot cast "{oops" to map<string,string> in field "attrs"', self.stderr)

    def test_a_leaf_that_does_not_cast_follows_on_type_error(self):
        source = self.write_jsonl("a.jsonl", {"id": 1, "items": [{"sku": "x", "qty": "oops"}]})
        schema = self.schema_file(("id", "int"), ("items", ITEMS_TYPE))
        _code, coerced = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(coerced[1][1], '[{"sku":"x","qty":null}]')
        _code, kept = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "keep-string", source
        )
        self.assertEqual(kept[1][1], '[{"sku":"x","qty":"oops"}]')
        code, _rows = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "fail", source
        )
        self.assertEqual(code, 4)
        self.assertIn('to int in field "items.0.qty"', self.stderr)
        self.assertIn("a.jsonl, line=1", self.stderr)

    def test_a_value_of_the_wrong_shape_follows_on_type_error(self):
        source = self.write_jsonl("a.jsonl", {"id": 1, "items": {"sku": "x"}})
        schema = self.schema_file(("id", "int"), ("items", ITEMS_TYPE))
        _code, rows = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "keep-string", source
        )
        self.assertEqual(rows[1][1], '{"sku":"x"}')

    def test_a_nested_value_in_a_flat_column_follows_on_type_error(self):
        source = self.write_jsonl("a.jsonl", {"id": 1, "user": {"name": "ada"}})
        schema = self.schema_file(("id", "int"), ("user", "string"))
        _code, rows = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "keep-string", source
        )
        self.assertEqual(rows[1][1], '{"name":"ada"}')
        code, _rows = self.run_merge(
            "--key", "id", "--schema", schema, "--on-type-error", "fail", source
        )
        self.assertEqual(code, 4)

    def test_a_json_column_takes_any_value_and_is_only_normalised(self):
        schema = self.schema_file(("id", "int"), ("blob", "json"))
        source = self.write(
            "a.tsv",
            "id\tblob\n"
            '1\t{"b": 1, "a": [1, "two", null]}\n'
            "2\t[1, 2]\n"
            '3\t"text"\n'
            "4\t\n",
        )
        _code, rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(
            [row[1] for row in rows[1:]], ['{"a":[1,"two",null],"b":1}', "[1,2]", '"text"', ""]
        )

    def test_nested_parquet_columns_are_cast_against_the_schema(self):
        table = pa.table(
            {
                "id": pa.array([1], pa.int64()),
                "user": pa.array(
                    [{"id": 7, "name": "ada", "prefs": {"k": "v"}}],
                    pa.struct(
                        [
                            ("id", pa.int32()),
                            ("name", pa.string()),
                            ("prefs", pa.map_(pa.string(), pa.string())),
                        ]
                    ),
                ),
                "items": pa.array(
                    [[{"sku": "x", "qty": 2}]],
                    pa.list_(pa.struct([("sku", pa.string()), ("qty", pa.int64())])),
                ),
            }
        )
        source = self.write_parquet("a.parquet", table)
        schema = self.schema_file(("id", "int"), ("user", USER_TYPE), ("items", ITEMS_TYPE))
        code, rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(code, 0)
        self.assertEqual(
            rows[1][1:], ['{"id":7,"name":"ada","prefs":{"k":"v"}}', '[{"sku":"x","qty":2}]']
        )

    def test_nested_inputs_without_a_schema_are_rejected(self):
        jsonl = self.write_jsonl("a.jsonl", {"id": 1, "user": {"name": "ada"}})
        parquet = self.write_parquet("b.parquet", pa.table({"id": [1], "tags": [["x"]]}))
        for source in (jsonl, parquet):
            with self.subTest(source=source):
                code, _rows = self.run_merge("--key", "id", source)
                self.assertEqual(code, 6)
                self.assertIn("nested structure requires provided --schema", self.stderr)

    def test_a_csv_cell_holding_json_stays_a_string_without_a_schema(self):
        source = self.write("a.csv", 'id,attrs\n1,"{""a"": 1}"\n')
        _code, rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows[1][0], '{"a": 1}')

    def test_a_struct_needs_unique_field_names(self):
        schema = self.schema_file(
            ("id", "int"),
            ("user", {"struct": {"fields": [{"name": "a", "type": "int"}] * 2}}),
        )
        source = self.write("a.csv", "id\n1\n")
        code, _rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(code, 6)
        self.assertIn("duplicate field names", self.stderr)

    def test_a_map_must_have_string_keys(self):
        schema = self.schema_file(("id", "int"), ("m", {"map": {"key": "int", "value": "int"}}))
        source = self.write("a.csv", "id\n1\n")
        code, _rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(code, 6)
        self.assertIn("string keys", self.stderr)


class TypeAliasTests(MergeTestCase):
    def test_built_in_aliases_are_case_insensitive(self):
        source = self.write("a.csv", "n,t,s\n007,2024-07-01 00:00:00,x\n")
        schema = self.schema_file(("n", "Integer"), ("t", "DATETIME"), ("s", "varchar"))
        _code, rows = self.run_merge("--key", "n", "--schema", schema, source)
        self.assertEqual(rows[1], ["7", "2024-07-01T00:00:00Z", "x"])

    def test_an_alias_file_adds_names_and_resolves_them_transitively(self):
        source = self.write("a.csv", "id,amount,when\n1,2,2024-07-01T00:00:00Z\n")
        schema = self.schema_file(("id", "smallint"), ("amount", "decimal"), ("when", "myts"))
        aliases = self.alias_file(smallint="int", decimal="double", myts="datetime")
        _code, rows = self.run_merge(
            "--key", "id", "--schema", schema, "--type-alias-file", aliases, source
        )
        self.assertEqual(rows[1], ["1", "2.0", "2024-07-01T00:00:00Z"])

    def test_list_is_an_alias_of_array_in_both_forms(self):
        source = self.write_jsonl("a.jsonl", {"id": 1, "xs": [1, "2"], "ys": ["3"]})
        schema = self.schema_file(
            ("id", "int"), ("xs", {"list": {"element": "long"}}), ("ys", "LIST<int>")
        )
        _code, rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1][1:], ["[1,2]", "[3]"])

    def test_a_generic_type_can_be_written_in_one_string(self):
        source = self.write_jsonl("a.jsonl", {"id": 1, "m": {"b": [2.5], "a": [1]}})
        schema = self.schema_file(("id", "int"), ("m", "map<string,array<number>>"))
        _code, rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(rows[1][1], '{"a":[1.0],"b":[2.5]}')

    def test_an_alias_cycle_is_a_usage_error(self):
        source = self.write("a.csv", "id\n1\n")
        schema = self.schema_file(("id", "int"))
        aliases = self.alias_file(one="two", two="one")
        code, _rows = self.run_merge(
            "--key", "id", "--schema", schema, "--type-alias-file", aliases, source
        )
        self.assertEqual(code, 2)
        self.assertIn("type alias cycle", self.stderr)

    def test_an_unknown_type_name_is_still_a_schema_error(self):
        source = self.write("a.csv", "id\n1\n")
        schema = self.schema_file(("id", "smallint"))
        code, _rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(code, 6)
        self.assertIn("unknown column type", self.stderr)


class FieldPathTests(MergeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.schema = self.schema_file(
            ("id", "int"), ("user", USER_TYPE), ("items", ITEMS_TYPE), ("attrs", ATTRS_TYPE)
        )
        self.source = self.write_jsonl(
            "a.jsonl",
            {"id": 1, "user": {"id": 9}, "items": [{"sku": "x", "qty": 2}], "attrs": {"c": "US"}},
            {"id": 2, "user": {"id": 3}, "items": [], "attrs": {}},
            {"id": 3, "user": None, "items": [{"sku": "y", "qty": 1}], "attrs": {"c": "FR"}},
        )

    def test_a_struct_field_sorts_the_rows(self):
        _code, rows = self.run_merge("--key", "user.id", "--schema", self.schema, self.source)
        self.assertEqual([row[0] for row in rows[1:]], ["3", "2", "1"])

    def test_an_array_index_reads_null_when_the_element_is_missing(self):
        _code, rows = self.run_merge("--key", "items.0.qty", "--schema", self.schema, self.source)
        self.assertEqual([row[0] for row in rows[1:]], ["2", "3", "1"])

    def test_a_map_lookup_partitions_the_output(self):
        _code, root = self.run_partitioned(
            "--key", "id", "--partition-by", 'attrs["c"]', "--schema", self.schema, self.source
        )
        self.assertEqual(
            self.tree(root),
            [
                "attrs%5B%22c%22%5D=FR/part-00000.csv",
                "attrs%5B%22c%22%5D=US/part-00000.csv",
                "attrs%5B%22c%22%5D=_null/part-00000.csv",
            ],
        )

    def test_a_path_that_stops_at_a_nested_type_is_a_key_column_error(self):
        code, _rows = self.run_merge("--key", "user", "--schema", self.schema, self.source)
        self.assertEqual(code, 3)
        self.assertIn('key column "user" does not resolve to a primitive', self.stderr)

    def test_a_partition_path_that_stops_at_a_nested_type_is_an_error(self):
        code, _root = self.run_partitioned(
            "--key", "id", "--partition-by", "items", "--schema", self.schema, self.source
        )
        self.assertEqual(code, 3)
        self.assertIn("does not resolve to a primitive", self.stderr)

    def test_a_path_that_leaves_the_schema_is_a_key_column_error(self):
        for key in ("user.nope", "attrs.c", "items.x.sku", "user.id.deeper"):
            with self.subTest(key=key):
                code, _rows = self.run_merge("--key", key, "--schema", self.schema, self.source)
                self.assertEqual(code, 3)


class DocumentedExampleTests(MergeTestCase):
    def test_mixed_sources_with_consensus_inference(self):
        users = self.write("users.csv", "ts,id,name\n2024-01-03T00:00:00Z,7,ada\n")
        events = self.write_gzip(
            "events.jsonl.gz", '{"ts": "2024-01-01T00:00:00Z", "id": 9, "event": "login"}\n'
        )
        metrics = self.write_parquet(
            "metrics.parquet",
            pa.table(
                {
                    "ts": pa.array([datetime(2024, 1, 2)], pa.timestamp("us")),
                    "id": pa.array([8], pa.int64()),
                    "value": pa.array([1.25], pa.float64()),
                }
            ),
        )
        code, rows = self.run_merge(
            "--key", "ts,id", "--schema-strategy", "consensus", users, events, metrics
        )
        self.assertEqual(code, 0)
        self.assertEqual(rows[0], ["event", "id", "name", "ts", "value"])
        self.assertEqual(
            rows[1:],
            [
                ["login", "9", "", "2024-01-01T00:00:00Z", ""],
                ["", "8", "", "2024-01-02T00:00:00Z", "1.25"],
                ["", "7", "ada", "2024-01-03T00:00:00Z", ""],
            ],
        )

    def test_nested_schema_keyed_on_a_leaf_and_partitioned_by_a_map_value(self):
        events = self.write_jsonl(
            "events.jsonl",
            {
                "user": {"id": 9, "name": "ada"},
                "event_time": "2024-07-01 08:00:00",
                "attrs": {"country": "US"},
            },
            {
                "user": {"id": 3, "name": "bo"},
                "event_time": "2024-07-01T12:00:00+02:00",
                "attrs": {"country": "FR"},
            },
        )
        users = self.write_parquet(
            "users.parquet",
            pa.table(
                {
                    "user": pa.array(
                        [{"id": 9, "name": "zed"}],
                        pa.struct([("id", pa.int32()), ("name", pa.string())]),
                    ),
                    "event_time": pa.array([datetime(2024, 7, 1, 6)], pa.timestamp("s")),
                    "attrs": pa.array([[("country", "US")]], pa.map_(pa.string(), pa.string())),
                }
            ),
        )
        schema = self.schema_file(
            (
                "user",
                {
                    "struct": {
                        "fields": [
                            {"name": "id", "type": "int"},
                            {"name": "name", "type": "string"},
                        ]
                    }
                },
            ),
            ("event_time", "timestamp"),
            ("attrs", {"map": {"key": "string", "value": "string"}}),
        )
        code, root = self.run_partitioned(
            "--key", "user.id,event_time",
            "--partition-by", 'attrs["country"]',
            "--schema", schema,
            "--on-type-error", "coerce-null",
            events, users,
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            self.tree(root),
            [
                "attrs%5B%22country%22%5D=FR/part-00000.csv",
                "attrs%5B%22country%22%5D=US/part-00000.csv",
            ],
        )
        self.assertEqual(
            self.part(root, "attrs%5B%22country%22%5D=US/part-00000.csv"),
            [
                ["user", "event_time", "attrs"],
                ['{"id":9,"name":"zed"}', "2024-07-01T06:00:00Z", '{"country":"US"}'],
                ['{"id":9,"name":"ada"}', "2024-07-01T08:00:00Z", '{"country":"US"}'],
            ],
        )

    def test_arbitrary_json_in_a_column_sorted_by_a_primitive(self):
        self.write("a.tsv", 'id\tblob\n2\t{"b": 1, "a": 2}\n')
        self.write("b.tsv", 'id\tblob\n1\t[1, "two", null]\n')
        schema = self.schema_file(("id", "int"), ("blob", "json"))
        code, rows = self.run_merge(
            "--key", "id",
            "--schema", schema,
            *sorted(str(path) for path in self.directory.glob("*.tsv")),
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            rows, [["id", "blob"], ["1", '[1,"two",null]'], ["2", '{"a":2,"b":1}']]
        )

    def test_provided_schema_over_gzipped_tsv_to_stdout_descending(self):
        self.write_gzip(
            "data-1.tsv.gz", "created_at\tid\tnote\n2024-05-01T10:00:00Z\t1\tfirst\n"
        )
        self.write_gzip(
            "data-2.tsv.gz", "created_at\tid\tnote\n2024-05-02T10:00:00Z\t2\tsecond\n"
        )
        schema = self.schema_file(("created_at", "timestamp"), ("id", "int"), ("note", "string"))
        finished = subprocess.run(
            [
                sys.executable,
                str(Path(merge_files.__file__)),
                "--output",
                "-",
                "--key",
                "created_at,id",
                "--desc",
                "--schema",
                schema,
                "--input-format",
                "tsv",
                "--compression",
                "gzip",
                *sorted(str(path) for path in self.directory.glob("*.tsv.gz")),
            ],
            capture_output=True,
            check=True,
        )
        self.assertEqual(
            finished.stdout.decode(),
            "created_at,id,note\n"
            "2024-05-02T10:00:00Z,2,second\n"
            "2024-05-01T10:00:00Z,1,first\n",
        )

    def test_field_partitions_sharded_by_byte_size(self):
        self.write(
            "a.csv",
            "country,dt,id,ts\n"
            "US,2024-01-01,2,2024-01-01T02:00:00Z\n"
            "FR,2024-01-02,1,2024-01-01T01:00:00Z\n",
        )
        self.write("b.csv", "country,dt,id,ts\nUS,2024-01-01,3,2024-01-01T00:30:00Z\n")
        destination = self.directory / "out"
        code = merge_files.main(
            [
                "--output", f"{destination}/",
                "--key", "ts,id",
                "--partition-by", "country,dt",
                "--max-bytes-per-file", "52428800",
                *sorted(str(path) for path in self.directory.glob("*.csv")),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            self.tree(destination),
            [
                "country=FR/dt=2024-01-02/part-00000.csv",
                "country=US/dt=2024-01-01/part-00000.csv",
            ],
        )
        us_rows = self.part(destination, "country=US/dt=2024-01-01/part-00000.csv")
        self.assertEqual([row[2] for row in us_rows[1:]], ["3", "2"])

    def test_a_globally_sorted_stream_sharded_by_row_count(self):
        csv_input = self.write("users.csv", "user_id,ts\n2,2024-01-01T00:00:00Z\n")
        jsonl_input = self.write_gzip(
            "events.jsonl.gz", json.dumps({"user_id": 1, "ts": "2024-01-02T00:00:00Z"}) + "\n"
        )
        parquet_input = self.write_parquet(
            "metrics.parquet",
            pa.table(
                {
                    "user_id": pa.array([2], pa.int64()),
                    "ts": pa.array([datetime(2023, 12, 31)], pa.timestamp("us")),
                }
            ),
        )
        destination = self.directory / "out"
        code = merge_files.main(
            [
                "--output", f"{destination}/",
                "--key", "user_id,ts",
                "--max-rows-per-file", "1000000",
                csv_input, jsonl_input, parquet_input,
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.tree(destination), ["part-00000.csv"])
        self.assertEqual(
            self.part(destination, "part-00000.csv"),
            [
                ["ts", "user_id"],
                ["2024-01-02T00:00:00Z", "1"],
                ["2023-12-31T00:00:00Z", "2"],
                ["2024-01-01T00:00:00Z", "2"],
            ],
        )

    def test_one_file_per_field_partition_in_descending_order(self):
        self.write_gzip(
            "a.tsv.gz",
            "account_id\tcreated_at\tid\n"
            "7\t2024-05-01T10:00:00Z\t1\n"
            "9\t2024-05-03T10:00:00Z\t3\n",
        )
        self.write_gzip("b.tsv.gz", "account_id\tcreated_at\tid\n7\t2024-05-02T10:00:00Z\t2\n")
        destination = self.directory / "out"
        code = merge_files.main(
            [
                "--output", f"{destination}/",
                "--key", "created_at,id",
                "--desc",
                "--partition-by", "account_id",
                *sorted(str(path) for path in self.directory.glob("*.tsv.gz")),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            self.tree(destination),
            ["account_id=7/part-00000.csv", "account_id=9/part-00000.csv"],
        )
        self.assertEqual(
            self.part(destination, "account_id=7/part-00000.csv"),
            [
                ["account_id", "created_at", "id"],
                ["7", "2024-05-02T10:00:00Z", "2"],
                ["7", "2024-05-01T10:00:00Z", "1"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
