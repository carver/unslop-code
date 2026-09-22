"""Tests for merge_files.py, run with: python -m unittest -v"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

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

    def schema_file(self, *columns: tuple[str, str]) -> str:
        document = {"columns": [{"name": name, "type": kind} for name, kind in columns]}
        return self.write("schema.json", json.dumps(document))

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
        self.assertEqual(code, 1)
        self.assertIn("nope", self.stderr)

    def test_unknown_type_in_schema_is_an_error(self):
        source = self.write("a.csv", "id\n1\n")
        schema = self.schema_file(("id", "integer"))
        code, _rows = self.run_merge("--key", "id", "--schema", schema, source)
        self.assertEqual(code, 1)
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
        self.assertEqual(code, 1)
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

    def test_custom_quote_character(self):
        source = self.write("a.csv", "id,note\n7,'c,d'\n")
        _code, rows = self.run_merge("--key", "id", "--csv-quotechar", "'", source)
        self.assertEqual(rows[1], ["7", "c,d"])

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


if __name__ == "__main__":
    unittest.main()
