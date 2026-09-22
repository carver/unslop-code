"""End-to-end tests driving the CLI exactly as a user would."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import merge_files


class MergeTestCase(unittest.TestCase):
    """Base case providing a scratch directory and a `run` helper."""

    def setUp(self) -> None:
        self._workspace = TemporaryDirectory()
        self.addCleanup(self._workspace.cleanup)
        self.root = Path(self._workspace.name)

    def write(self, name: str, text: str) -> str:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def run_merge(self, *argv: str) -> list[str]:
        """Run the CLI, assert success, and return the output file's lines."""
        output = self.root / "out.csv"
        exit_code = merge_files.main(["--output", str(output), *argv])
        self.assertEqual(exit_code, 0)
        return output.read_text(encoding="utf-8").splitlines()


class SchemaResolutionTests(MergeTestCase):
    def test_explicit_schema_fixes_column_order_and_drops_extras(self) -> None:
        source = self.write("a.csv", "extra,note,id\nx,hello,2\ny,world,1\n")
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "missing", "type": "float"},
            {"name": "note", "type": "string"},
        ]}))
        self.assertEqual(
            self.run_merge("--key", "id", "--schema", schema, source),
            ["id,missing,note", "1,,world", "2,,hello"],
        )

    def test_inferred_schema_is_union_of_headers_in_lexicographic_order(self) -> None:
        first = self.write("a.csv", "b,a\n1,2\n")
        second = self.write("b.csv", "c,a\n3,4\n")
        self.assertEqual(self.run_merge("--key", "a", first, second)[0], "a,b,c")

    def test_strict_falls_back_to_string_when_files_disagree(self) -> None:
        first = self.write("a.csv", "v\n1\n")
        second = self.write("b.csv", "v\n2.5\n")
        self.assertEqual(self.run_merge("--key", "v", first, second), ["v", "1", "2.5"])

    def test_loose_unifies_int_and_float_columns(self) -> None:
        first = self.write("a.csv", "v\n1\n")
        second = self.write("b.csv", "v\n2.5\n")
        rows = self.run_merge("--key", "v", "--infer", "loose", first, second)
        self.assertEqual(rows, ["v", "1.0", "2.5"])

    def test_loose_ignores_blanks_while_strict_treats_them_as_strings(self) -> None:
        source = self.write("a.csv", "v,src\n10,a\n,b\n9,c\n")
        self.assertEqual(self.run_merge("--key", "v", "--infer", "loose", source)[1:], ["b,", "c,9", "a,10"])
        self.assertEqual(self.run_merge("--key", "v", source)[1:], ["b,", "a,10", "c,9"])

    def test_bare_dates_infer_as_date_not_timestamp(self) -> None:
        source = self.write("a.csv", "d\n2024-01-02\n")
        self.assertEqual(self.run_merge("--key", "d", "--infer", "loose", source), ["d", "2024-01-02"])

    def test_inference_keeps_numbers_numeric_but_still_finds_bools(self) -> None:
        source = self.write("a.csv", "flag,n\ntrue,1\nfalse,0\n")
        self.assertEqual(self.run_merge("--key", "n", source)[1:], ["false,0", "true,1"])


class CastingTests(MergeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "ts", "type": "timestamp"},
            {"name": "amount", "type": "float"},
            {"name": "is_active", "type": "bool"},
        ]}))

    def test_timestamps_are_normalised_to_utc(self) -> None:
        source = self.write("a.csv", "id,ts\n1,2024-07-01T08:30:00+02:00\n2,2024-07-01 05:00:00\n")
        rows = self.run_merge("--key", "id", "--schema", self.schema, source)
        self.assertEqual(rows[1:], ["1,2024-07-01T06:30:00Z,,", "2,2024-07-01T05:00:00Z,,"])

    def test_bool_accepts_one_and_zero(self) -> None:
        source = self.write("a.csv", "id,is_active\n1,1\n2,0\n3,TRUE\n")
        rows = self.run_merge("--key", "id", "--schema", self.schema, source)
        self.assertEqual([row.split(",")[3] for row in rows[1:]], ["true", "false", "true"])

    def test_coerce_null_is_the_default_for_bad_casts(self) -> None:
        source = self.write("a.csv", "id,amount\n1,oops\n")
        self.assertEqual(self.run_merge("--key", "id", "--schema", self.schema, source)[1], "1,,,")

    def test_keep_string_preserves_the_original_text(self) -> None:
        source = self.write("a.csv", "id,amount\n1,oops\n")
        rows = self.run_merge("--key", "id", "--schema", self.schema, "--on-type-error", "keep-string", source)
        self.assertEqual(rows[1], "1,,oops,")

    def test_fail_exits_non_zero(self) -> None:
        source = self.write("a.csv", "id,amount\n1,oops\n")
        exit_code = merge_files.main(
            ["--output", "-", "--key", "id", "--schema", self.schema, "--on-type-error", "fail", source]
        )
        self.assertEqual(exit_code, 1)


class SortingTests(MergeTestCase):
    def test_composite_key_and_descending_order(self) -> None:
        source = self.write("a.csv", "g,id\nb,1\na,2\nb,2\na,1\n")
        rows = self.run_merge("--key", "g,id", "--desc", source)
        self.assertEqual(rows[1:], ["b,2", "b,1", "a,2", "a,1"])

    def test_nulls_sort_below_values_in_both_directions(self) -> None:
        source = self.write("a.csv", "v,src\n2,a\n,b\n1,c\n")
        self.assertEqual(self.run_merge("--key", "v", "--infer", "loose", source)[1:], ["b,", "c,1", "a,2"])
        self.assertEqual(
            self.run_merge("--key", "v", "--infer", "loose", "--desc", source)[1:], ["a,2", "c,1", "b,"]
        )

    def test_equal_keys_keep_input_order_across_files(self) -> None:
        first = self.write("a.csv", "k,src\n1,a1\n1,a2\n")
        second = self.write("b.csv", "k,src\n1,b1\n1,b2\n")
        expected = ["1,a1", "1,a2", "1,b1", "1,b2"]
        self.assertEqual(self.run_merge("--key", "k", first, second)[1:], expected)
        self.assertEqual(self.run_merge("--key", "k", "--desc", first, second)[1:], expected)

    def test_spilling_to_disk_matches_an_in_memory_sort(self) -> None:
        rows = [f"{(index * 7919) % 1000},row-{index}" for index in range(5000)]
        source = self.write("a.csv", "k,src\n" + "\n".join(rows) + "\n")
        spilled = self.run_merge("--key", "k", "--memory-limit-mb", "1", "--temp-dir", str(self.root), source)
        in_memory = self.run_merge("--key", "k", "--memory-limit-mb", "512", source)
        self.assertEqual(spilled, in_memory)
        self.assertEqual(len(spilled), 5001)
        self.assertEqual([entry.name for entry in self.root.iterdir() if entry.is_dir()], [])

    def test_unknown_key_column_is_an_error(self) -> None:
        source = self.write("a.csv", "id\n1\n")
        self.assertEqual(merge_files.main(["--output", "-", "--key", "nope", source]), 1)


class DialectTests(MergeTestCase):
    def test_quotes_and_embedded_delimiters_round_trip(self) -> None:
        source = self.write("a.csv", 'id,note\n1,"a,b"\n2,"say ""hi"""\n')
        rows = self.run_merge("--key", "id", source)
        self.assertEqual(rows[1:], ['1,"a,b"', '2,"say ""hi"""'])

    def test_custom_quote_and_escape_characters(self) -> None:
        source = self.write("a.csv", "id,note\n1,'a,b'\n")
        self.assertEqual(self.run_merge("--key", "id", "--csv-quotechar", "'", source)[1:], ["1,'a,b'"])
        escaped = self.write("b.csv", 'id,note\n1,"a\\"b"\n')
        rows = self.run_merge("--key", "id", "--csv-escapechar", "\\", escaped)
        self.assertEqual(rows[1:], ['1,a\\"b'])

    def test_null_literal_is_written_and_read_back(self) -> None:
        source = self.write("a.csv", "id,note\n1,\n")
        self.assertEqual(self.run_merge("--key", "id", "--csv-null-literal", "NULL", source)[1:], ["1,NULL"])
        round_trip = self.write("b.csv", "id,note\n1,NULL\n")
        self.assertEqual(self.run_merge("--key", "id", "--csv-null-literal", "-", round_trip)[1:], ["1,NULL"])


if __name__ == "__main__":
    unittest.main()
