#!/usr/bin/env python3
"""Specification tests for merge_files.py."""

import csv
import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "merge_files.py")


def run_tool(args, cwd, expect_rc=0):
    proc = subprocess.run(
        [sys.executable, SCRIPT] + args,
        cwd=cwd, capture_output=True, text=True,
    )
    if expect_rc is not None:
        assert proc.returncode == expect_rc, (
            f"rc={proc.returncode} stderr={proc.stderr!r} stdout={proc.stdout!r}"
        )
    return proc


def read_row(line):
    """Parse one output line with the dialect merge_files.py writes."""
    return next(csv.reader([line], escapechar="\\"))


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return path

    def merge(self, args, expect_rc=0):
        return run_tool(args, self.dir, expect_rc)

    def merge_lines(self, args):
        return self.merge(args).stdout.split("\n")[:-1]


class TestInference(ToolTestCase):
    def test_lexicographic_column_order_and_union(self):
        self.write("a.csv", "b,a\n7,2\n")
        self.write("c.csv", "c,a\nx,3\n")
        lines = self.merge_lines(["--output", "-", "--key", "a", "a.csv", "c.csv"])
        self.assertEqual(lines[0], "a,b,c")
        self.assertEqual(lines[1:], ["2,7,", "3,,x"])

    def test_strict_conflicting_types_fall_back_to_string(self):
        self.write("a.csv", "x\n1\n2\n")
        self.write("b.csv", "x\nfoo\n")
        lines = self.merge_lines(["--output", "-", "--key", "x", "a.csv", "b.csv"])
        # string ordering: "1" < "2" < "foo"
        self.assertEqual(lines, ["x", "1", "2", "foo"])

    def test_strict_agreeing_types_kept(self):
        self.write("a.csv", "x\n10\n")
        self.write("b.csv", "x\n9\n")
        lines = self.merge_lines(["--output", "-", "--key", "x", "a.csv", "b.csv"])
        self.assertEqual(lines, ["x", "9", "10"])  # numeric order

    def test_loose_unifies_int_and_float(self):
        self.write("a.csv", "x\n10\n")
        self.write("b.csv", "x\n9.5\n")
        strict = self.merge_lines(
            ["--output", "-", "--key", "x", "a.csv", "b.csv"])
        self.assertEqual(strict, ["x", "10", "9.5"])  # string fallback
        loose = self.merge_lines(
            ["--output", "-", "--key", "x", "--infer", "loose", "a.csv", "b.csv"])
        self.assertEqual(loose, ["x", "9.5", "10.0"])  # numeric

    def test_loose_ignores_empty_strings(self):
        self.write("a.csv", "x\n\n3\n")
        self.write("b.csv", "x\n1\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "x", "--infer", "loose", "a.csv", "b.csv"])
        # a lone empty field is written as "" so the row is not a blank line
        self.assertEqual(lines, ["x", '""', "1", "3"])

    def test_type_priority_bool_over_int(self):
        self.write("a.csv", "flag\n1\n0\n")
        lines = self.merge_lines(["--output", "-", "--key", "flag", "a.csv"])
        self.assertEqual(lines, ["flag", "false", "true"])

    def test_date_not_swallowed_by_timestamp(self):
        self.write("a.csv", "d\n2024-07-02\n2024-01-05\n")
        lines = self.merge_lines(["--output", "-", "--key", "d", "a.csv"])
        self.assertEqual(lines, ["d", "2024-01-05", "2024-07-02"])

    def test_timestamp_inference_and_normalisation(self):
        self.write("a.csv", "t\n2024-07-01T12:00:00+02:00\n2024-07-01T09:00:00\n")
        lines = self.merge_lines(["--output", "-", "--key", "t", "a.csv"])
        self.assertEqual(
            lines, ["t", "2024-07-01T09:00:00Z", "2024-07-01T10:00:00Z"])

    def test_all_null_column_is_string(self):
        self.write("a.csv", "k,x\n5,\n")
        lines = self.merge_lines(["--output", "-", "--key", "k", "a.csv"])
        self.assertEqual(lines, ["k,x", "5,"])


class TestSchemaFile(ToolTestCase):
    SCHEMA = {
        "columns": [
            {"name": "id", "type": "int"},
            {"name": "ts", "type": "timestamp"},
            {"name": "amount", "type": "float"},
            {"name": "note", "type": "string"},
            {"name": "is_active", "type": "bool"},
        ]
    }

    def write_schema(self, schema=None):
        return self.write("schema.json", json.dumps(schema or self.SCHEMA))

    def test_schema_order_extra_and_missing_columns(self):
        self.write("a.csv", "note,id,extra\nhi,2,drop\n")
        self.write_schema()
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema", "schema.json", "a.csv"])
        self.assertEqual(lines[0], "id,ts,amount,note,is_active")
        self.assertEqual(lines[1], "2,,,hi,")

    def test_bool_one_zero(self):
        self.write("a.csv", "id,is_active\n1,1\n2,0\n3,TRUE\n4,False\n")
        self.write_schema()
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema", "schema.json", "a.csv"])
        self.assertEqual([l.split(",")[4] for l in lines[1:]],
                         ["true", "false", "true", "false"])

    def test_timestamp_keeps_fractional_seconds(self):
        self.write("a.csv", "id,ts\n1,2024-07-01T12:00:00.500+02:00\n")
        self.write_schema()
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema", "schema.json", "a.csv"])
        self.assertEqual(lines[1], "1,2024-07-01T10:00:00.500Z,,,")

    def test_missing_key_column_errors(self):
        self.write("a.csv", "id\n1\n")
        self.write_schema()
        proc = self.merge(
            ["--output", "-", "--key", "nope", "--schema", "schema.json", "a.csv"],
            expect_rc=3)
        self.assertIn("nope", proc.stderr)

    def test_missing_inferred_key_column_errors(self):
        self.write("a.csv", "id\n1\n")
        proc = self.merge(["--output", "-", "--key", "zzz", "a.csv"], expect_rc=3)
        self.assertTrue(proc.stderr.strip())


class TestTypeErrors(ToolTestCase):
    SCHEMA = {"columns": [{"name": "id", "type": "int"},
                          {"name": "v", "type": "int"}]}

    def setUp(self):
        super().setUp()
        self.write("schema.json", json.dumps(self.SCHEMA))
        self.write("a.csv", "id,v\n1,oops\n2,5\n")

    def base(self, *extra):
        return ["--output", "-", "--key", "id", "--schema", "schema.json",
                *extra, "a.csv"]

    def test_coerce_null_default(self):
        lines = self.merge_lines(self.base())
        self.assertEqual(lines, ["id,v", "1,", "2,5"])

    def test_keep_string(self):
        lines = self.merge_lines(self.base("--on-type-error", "keep-string"))
        self.assertEqual(lines, ["id,v", "1,oops", "2,5"])

    def test_fail(self):
        proc = self.merge(self.base("--on-type-error", "fail"), expect_rc=4)
        self.assertIn("oops", proc.stderr)
        self.assertEqual(proc.stdout, "")


class TestSorting(ToolTestCase):
    def test_stability_ascending(self):
        self.write("a.csv", "k,src\n11,a1\n11,a2\n")
        self.write("b.csv", "k,src\n11,b1\n10,b0\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "k", "a.csv", "b.csv"])
        self.assertEqual(lines, ["k,src", "10,b0", "11,a1", "11,a2", "11,b1"])

    def test_stability_descending(self):
        self.write("a.csv", "k,src\n11,a1\n11,a2\n")
        self.write("b.csv", "k,src\n11,b1\n12,b2\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "k", "--desc", "a.csv", "b.csv"])
        self.assertEqual(lines, ["k,src", "12,b2", "11,a1", "11,a2", "11,b1"])

    def test_nulls_first_ascending_last_descending(self):
        self.write("a.csv", "k,v\n,x\n2,y\n1,z\n")
        asc = self.merge_lines(["--output", "-", "--key", "k", "a.csv"])
        self.assertEqual(asc, ["k,v", ",x", "1,z", "2,y"])
        desc = self.merge_lines(["--output", "-", "--key", "k", "--desc", "a.csv"])
        self.assertEqual(desc, ["k,v", "2,y", "1,z", ",x"])

    def test_composite_key(self):
        self.write("a.csv", "a,b\n10,2\n10,1\n5,9\n")
        lines = self.merge_lines(["--output", "-", "--key", "a,b", "a.csv"])
        self.assertEqual(lines, ["a,b", "5,9", "10,1", "10,2"])

    def test_composite_key_repeated_flag(self):
        self.write("a.csv", "a,b\n10,2\n10,1\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "a", "--key", "b", "a.csv"])
        self.assertEqual(lines, ["a,b", "10,1", "10,2"])


class TestIoAndDialect(ToolTestCase):
    def test_output_to_file(self):
        self.write("a.csv", "id\n2\n1\n")
        self.merge(["--output", "out.csv", "--key", "id", "a.csv"])
        with open(os.path.join(self.dir, "out.csv"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "id\n1\n2\n")

    def test_quoting_and_doubling(self):
        self.write("a.csv", 'id,note\n1,"a,b"\n2,"say ""hi"""\n')
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.csv"])
        self.assertEqual(lines, ["id,note", '1,"a,b"', '2,"say ""hi"""'])

    def test_backslash_escaped_quote_is_accepted(self):
        self.write("a.csv", 'id,note\n7,"say \\"hi\\""\n')
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.csv"])
        self.assertEqual(lines, ["id,note", '7,"say ""hi"""'])

    def test_custom_quotechar(self):
        self.write("a.csv", "id,note\n7,|a,b|\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--csv-quotechar", "|", "a.csv"])
        # the configured quote character is used for output as well
        self.assertEqual(lines, ["id,note", "7,|a,b|"])

    def test_null_literal(self):
        self.write("a.csv", "id,v\n1,\n2,NULL\n3,7\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.csv"])
        self.assertEqual(lines, ["id,v", "1,NULL", "2,NULL", "3,7"])

    def test_bom_and_crlf_input(self):
        path = os.path.join(self.dir, "a.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write("id,v\r\n2,x\r\n1,y\r\n")
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.csv"])
        self.assertEqual(lines, ["id,v", "1,y", "2,x"])

    def test_ragged_rows(self):
        self.write("a.csv", "a,b,c\n1,2\n2,3,4,5\n")
        lines = self.merge_lines(["--output", "-", "--key", "a", "a.csv"])
        self.assertEqual(lines, ["a,b,c", "1,2,", "2,3,4"])

    def test_header_only_file(self):
        self.write("a.csv", "id,v\n")
        self.write("b.csv", "id,w\n7,x\n")
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.csv", "b.csv"])
        self.assertEqual(lines, ["id,v,w", "7,,x"])

    def test_missing_input_file_errors(self):
        proc = self.merge(["--output", "-", "--key", "id", "nope.csv"], expect_rc=2)
        self.assertTrue(proc.stderr.strip())


class TestExternalSort(ToolTestCase):
    def test_large_input_under_small_memory_limit(self):
        import random
        rows = 60000
        random.seed(7)
        values = [random.randint(0, 10 ** 9) for _ in range(rows)]
        payload = "x" * 120
        with open(os.path.join(self.dir, "big.csv"), "w", encoding="utf-8",
                  newline="") as handle:
            handle.write("id,pad\n")
            for value in values:
                handle.write(f"{value},{payload}\n")
        proc = self.merge(["--output", "out.csv", "--key", "id",
                           "--memory-limit-mb", "1", "--temp-dir", "tmp",
                           "big.csv"])
        self.assertEqual(proc.stderr, "")
        with open(os.path.join(self.dir, "out.csv"), encoding="utf-8") as handle:
            lines = handle.read().split("\n")[:-1]
        self.assertEqual(len(lines), rows + 1)
        got = [int(line.split(",")[0]) for line in lines[1:]]
        self.assertEqual(got, sorted(values))
        # Temporary resources are cleaned up.
        self.assertEqual(os.listdir(os.path.join(self.dir, "tmp")), [])


class TestDifferential(ToolTestCase):
    """Randomised inputs: spilling must match the pure in-memory result."""

    def _build_inputs(self, seed):
        import random
        rng = random.Random(seed)
        columns = ["id", "ts", "d", "amount", "note", "flag"]
        pools = {
            "id": lambda: rng.choice(["", str(rng.randint(-50, 50))]),
            "ts": lambda: rng.choice(
                ["", "2024-07-01T12:00:00Z", "2024-07-01T14:00:00+02:00",
                 "2024-01-05T00:00:00", "2024-07-01T12:00:00.250Z"]),
            "d": lambda: rng.choice(["", "2024-01-05", "2023-12-31"]),
            "amount": lambda: rng.choice(["", "1.5", "-2", "3.25"]),
            "note": lambda: rng.choice(["", "a", "b,c", 'q"q', "zz"]),
            "flag": lambda: rng.choice(["", "true", "false", "1", "0"]),
        }
        names = []
        for index in range(3):
            subset = rng.sample(columns, rng.randint(2, len(columns)))
            if "id" not in subset:
                subset.append("id")
            rng.shuffle(subset)
            rows = [subset]
            for _ in range(rng.randint(0, 40)):
                rows.append([pools[c]() for c in subset])
            import csv as _csv
            name = f"in{index}.csv"
            with open(os.path.join(self.dir, name), "w", encoding="utf-8",
                      newline="") as handle:
                writer = _csv.writer(handle, lineterminator="\n")
                writer.writerows(rows)
            names.append(name)
        return names

    def _data_rows(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as handle:
            return max(0, sum(1 for _ in handle) - 1)

    def test_spilling_matches_in_memory(self):
        for seed in range(12):
            with self.subTest(seed=seed):
                names = self._build_inputs(seed)
                for extra in ([], ["--desc"], ["--infer", "loose"],
                              ["--key", "note,id", "--desc"]):
                    args = ["--output", "-", "--key", "id", "--infer", "strict",
                            *extra, *names]
                    small = self.merge(["--memory-limit-mb", "1"] + args).stdout
                    big = self.merge(["--memory-limit-mb", "512"] + args).stdout
                    self.assertEqual(small, big)
                    # Spot-check global ordering and row preservation.
                    self.assertEqual(small.count("\n") - 1,
                                     sum(self._data_rows(n) for n in names))


class TestReferenceOrder(ToolTestCase):
    """Compare against an independent stable-sort reference implementation."""

    def test_matches_reference(self):
        import csv as _csv
        import random
        rng = random.Random(99)
        rows_a = [[str(rng.choice([1, 5, 9, 12, ""])), f"a{i}"] for i in range(50)]
        rows_b = [[str(rng.choice([1, 5, 9, 12, ""])), f"b{i}"] for i in range(50)]
        for name, rows in (("a.csv", rows_a), ("b.csv", rows_b)):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8",
                      newline="") as handle:
                writer = _csv.writer(handle, lineterminator="\n")
                writer.writerow(["k", "v"])
                writer.writerows(rows)

        combined = [(r[0], r[1]) for r in rows_a + rows_b]

        def reference(desc):
            keyed = [((0,) if k == "" else (1, int(k)), i, (k, v))
                     for i, (k, v) in enumerate(combined)]
            if desc:
                keyed.sort(key=lambda t: t[1])
                keyed.sort(key=lambda t: t[0], reverse=True)
            else:
                keyed.sort(key=lambda t: (t[0], t[1]))
            return [row for _, _, row in keyed]

        for desc in (False, True):
            args = ["--output", "-", "--key", "k", "--memory-limit-mb", "1",
                    "a.csv", "b.csv"]
            if desc:
                args.insert(4, "--desc")
            out = self.merge(args).stdout.split("\n")[:-1]
            self.assertEqual(out[0], "k,v")
            self.assertEqual([tuple(l.split(",")) for l in out[1:]],
                             reference(desc))


# --------------------------------------------------------------------------
# Checkpoint 2: heterogeneous inputs
# --------------------------------------------------------------------------

def write_parquet(path, columns):
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table(columns), path)


class MultiFormatTestCase(ToolTestCase):
    def write_bytes(self, name, payload):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def write_gz(self, name, text):
        path = os.path.join(self.dir, name)
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return path

    def write_jsonl(self, name, records, gz=False):
        text = "".join(
            record if isinstance(record, str) else json.dumps(record) + "\n"
            for record in records
        )
        return self.write_gz(name, text) if gz else self.write(name, text)

    def parquet(self, name, columns):
        path = os.path.join(self.dir, name)
        write_parquet(path, columns)
        return path


class TestFormatDetection(MultiFormatTestCase):
    def test_extensions(self):
        self.write("a.csv", "id,v\n1,x\n")
        self.write("b.tsv", "id\tv\n2\ty\n")
        self.write_jsonl("c.jsonl", [{"id": 3, "v": "z"}])
        self.write_jsonl("d.ndjson", [{"id": 4, "v": "w"}])
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "a.csv", "b.tsv", "c.jsonl",
             "d.ndjson"])
        self.assertEqual(lines, ["id,v", "1,x", "2,y", "3,z", "4,w"])

    def test_gzip_suffix_after_base_extension(self):
        self.write_gz("a.csv.gz", "id,v\n1,x\n")
        self.write_jsonl("b.jsonl.gz", [{"id": 2, "v": "y"}], gz=True)
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "a.csv.gz", "b.jsonl.gz"])
        self.assertEqual(lines, ["id,v", "1,x", "2,y"])

    def test_parquet_magic_bytes_for_ambiguous_extension(self):
        path = os.path.join(self.dir, "mystery.bin")
        write_parquet(path, {"id": [2, 1]})
        lines = self.merge_lines(["--output", "-", "--key", "id", "mystery.bin"])
        self.assertEqual(lines, ["id", "1", "2"])

    def test_ambiguous_extension_without_magic_is_error_2(self):
        self.write("mystery.dat", "id\n1\n")
        proc = self.merge(["--output", "-", "--key", "id", "mystery.dat"],
                          expect_rc=2)
        self.assertIn("mystery.dat", proc.stderr)

    def test_forced_input_format(self):
        self.write("a.data", "id\tv\n7\tx\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--input-format", "tsv", "a.data"])
        self.assertEqual(lines, ["id,v", "7,x"])

    def test_compression_flags_and_mismatch(self):
        self.write_gz("a.bin", "id,v\n7,x\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--input-format", "csv",
             "--compression", "gzip", "a.bin"])
        self.assertEqual(lines, ["id,v", "7,x"])
        # plain data declared as gzip
        self.write("b.csv", "id\n1\n")
        self.merge(["--output", "-", "--key", "id", "--compression", "gzip",
                    "b.csv"], expect_rc=5)
        # gzip data declared as plain
        self.write_gz("c.csv.gz", "id\n1\n")
        self.merge(["--output", "-", "--key", "id", "--compression", "none",
                    "c.csv.gz"], expect_rc=5)


class TestTsvSource(MultiFormatTestCase):
    def test_crlf_and_missing_trailing_fields(self):
        self.write("a.tsv", "id\tv\tw\r\n2\tb\r\n1\ta\tc\r\n")
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.tsv"])
        self.assertEqual(lines, ["id,v,w", "1,a,c", "2,b,"])

    def test_quotes_are_literal(self):
        self.write("a.tsv", 'id\tv\n7\t"x"\n')
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.tsv"])
        self.assertEqual(lines, ["id,v", '7,"""x"""'])

    def test_extra_tab_is_error_5(self):
        self.write("a.tsv", "id\tv\n1\tx\ty\n")
        proc = self.merge(["--output", "-", "--key", "id", "a.tsv"], expect_rc=5)
        self.assertIn("tab", proc.stderr)

    def test_header_required(self):
        self.write("a.tsv", "")
        self.merge(["--output", "-", "--key", "id", "a.tsv"], expect_rc=5)


class TestJsonlSource(MultiFormatTestCase):
    def test_blank_lines_nulls_and_case_sensitive_keys(self):
        self.write_jsonl("a.jsonl", [
            {"id": 2, "V": "upper"},
            "\n",
            "   \n",
            {"id": 1, "v": None},
        ])
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.jsonl"])
        self.assertEqual(lines, ["V,id,v", ",1,", "upper,2,"])

    def test_null_literal_for_json_null(self):
        self.write_jsonl("a.jsonl", [{"id": 7, "v": None}])
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--csv-null-literal", "NULL",
             "a.jsonl"])
        self.assertEqual(lines, ["id,v", "7,NULL"])

    def test_numbers_prefer_int_when_integral(self):
        self.write_jsonl("a.jsonl", [{"id": 1, "v": 3.0}, {"id": 2, "v": 2}])
        lines = self.merge_lines(["--output", "-", "--key", "v", "a.jsonl"])
        self.assertEqual(lines, ["id,v", "2,2", "1,3"])

    def test_numbers_fall_back_to_float(self):
        self.write_jsonl("a.jsonl", [{"id": 1, "v": 3.5}, {"id": 2, "v": 2}])
        lines = self.merge_lines(["--output", "-", "--key", "v", "a.jsonl"])
        self.assertEqual(lines, ["id,v", "2,2.0", "1,3.5"])

    def test_nested_object_is_error_6(self):
        self.write_jsonl("a.jsonl", [{"id": 1, "v": {"n": 1}}])
        proc = self.merge(["--output", "-", "--key", "id", "a.jsonl"], expect_rc=6)
        self.assertIn("nested", proc.stderr)

    def test_nested_array_value_is_error_6(self):
        self.write_jsonl("a.jsonl", [{"id": 1, "v": [1, 2]}])
        self.merge(["--output", "-", "--key", "id", "a.jsonl"], expect_rc=6)

    def test_array_line_is_error_6(self):
        self.write_jsonl("a.jsonl", ["[1, 2]\n"])
        self.merge(["--output", "-", "--key", "id", "a.jsonl"], expect_rc=6)

    def test_malformed_json_is_error_5(self):
        self.write_jsonl("a.jsonl", ['{"id": 1\n'])
        self.merge(["--output", "-", "--key", "id", "a.jsonl"], expect_rc=5)

    def test_booleans_and_strings(self):
        self.write_jsonl("a.jsonl", [{"id": 1, "flag": True},
                                     {"id": 2, "flag": False}])
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.jsonl"])
        self.assertEqual(lines, ["flag,id", "true,1", "false,2"])


class TestParquetSource(MultiFormatTestCase):
    def test_typed_values_and_nulls(self):
        import datetime
        import pyarrow as pa

        path = os.path.join(self.dir, "a.parquet")
        import pyarrow.parquet as pq
        pq.write_table(pa.table({
            "id": pa.array([2, 1], pa.int64()),
            "d": pa.array([datetime.date(2024, 1, 5), None], pa.date32()),
            "t": pa.array([datetime.datetime(2024, 1, 5, 10, 30), None],
                          pa.timestamp("us")),
            "f": pa.array([1.5, None], pa.float64()),
            "b": pa.array([True, None], pa.bool_()),
            "s": pa.array(["x", None], pa.string()),
        }), path)
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.parquet"])
        self.assertEqual(lines[0], "b,d,f,id,s,t")
        self.assertEqual(lines[1], ",,,1,,")
        self.assertEqual(lines[2], "true,2024-01-05,1.5,2,x,2024-01-05T10:30:00Z")

    def test_nested_column_is_error_6(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        path = os.path.join(self.dir, "a.parquet")
        pq.write_table(pa.table({"id": pa.array([1]),
                                 "tags": pa.array([["a", "b"]])}), path)
        proc = self.merge(["--output", "-", "--key", "id", "a.parquet"],
                          expect_rc=6)
        self.assertIn("nested", proc.stderr)

    def test_gzipped_parquet(self):
        path = self.parquet("a.parquet", {"id": [2, 1]})
        with open(path, "rb") as raw, gzip.open(path + ".gz", "wb") as out:
            out.write(raw.read())
        os.remove(path)
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.parquet.gz"])
        self.assertEqual(lines, ["id", "1", "2"])

    def test_row_group_streaming_flag(self):
        self.parquet("a.parquet", {"id": list(range(2000, 0, -1))})
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--parquet-row-group-bytes", "4096",
             "--memory-limit-mb", "64", "a.parquet"])
        self.assertEqual(lines[0], "id")
        self.assertEqual([int(v) for v in lines[1:]], list(range(1, 2001)))

    def test_file_without_matching_columns_still_contributes_rows(self):
        self.parquet("a.parquet", {"other": [1, 2]})
        self.write("b.csv", "id\n7\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "b.csv", "a.parquet"])
        self.assertEqual(lines, ["id,other", ",1", ",2", "7,"])


class TestSchemaStrategies(MultiFormatTestCase):
    def setUp(self):
        super().setUp()
        # CSV says v is an int, Parquet declares it a float, TSV says string.
        self.write("a.csv", "id,v\n11,3\n")
        self.parquet("b.parquet", {"id": [12], "v": [2.5]})
        self.write("c.tsv", "id\tv\n13\tzz\n")

    def test_authoritative_prefers_parquet(self):
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "a.csv", "b.parquet"])
        self.assertEqual(lines, ["id,v", "11,3.0", "12,2.5"])

    def test_authoritative_ignores_lower_ranked_tsv(self):
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "a.csv", "c.tsv"])
        # CSV outranks TSV, so `v` stays an int and "zz" coerces to null.
        self.assertEqual(lines, ["id,v", "11,3", "13,"])

    def test_jsonl_ranks_equal_to_csv(self):
        self.write_jsonl("d.jsonl", [{"id": 14, "v": "text"}])
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "a.csv", "d.jsonl"])
        # equal rank + disagreement => string
        self.assertEqual(lines, ["id,v", "11,3", "14,text"])

    def test_consensus_majority_wins(self):
        self.write("e.csv", "id,v\n15,7\n")
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema-strategy", "consensus",
             "a.csv", "e.csv", "b.parquet"])
        # two int votes vs one float vote => int, and 2.5 cannot be cast
        self.assertEqual(lines, ["id,v", "11,3", "12,", "15,7"])

    def test_union_widens_to_common_type(self):
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema-strategy", "union",
             "a.csv", "b.parquet"])
        self.assertEqual(lines, ["id,v", "11,3.0", "12,2.5"])

    def test_union_falls_back_to_string(self):
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema-strategy", "union",
             "a.csv", "c.tsv"])
        self.assertEqual(lines, ["id,v", "11,3", "13,zz"])


class TestHeterogeneousMerge(MultiFormatTestCase):
    def build(self):
        self.write("users.csv", "id,ts,name\n"
                                "3,2024-07-01T12:00:00Z,carol\n"
                                "1,2024-07-01T08:00:00Z,alice\n")
        self.write_jsonl("events.jsonl.gz", [
            {"id": 2, "ts": "2024-07-01T09:30:00Z", "name": "bob"},
            {"id": 4, "ts": "2024-07-01T11:00:00Z", "name": None},
        ], gz=True)
        self.parquet("metrics.parquet", {"id": [5], "ts": ["2024-07-01T07:00:00Z"]})

    def test_composite_key_across_sources(self):
        self.build()
        lines = self.merge_lines(
            ["--output", "-", "--key", "ts,id", "--schema-strategy", "consensus",
             "users.csv", "events.jsonl.gz", "metrics.parquet"])
        self.assertEqual(lines[0], "id,name,ts")
        self.assertEqual([line.split(",")[0] for line in lines[1:]],
                         ["5", "1", "2", "4", "3"])

    def test_no_deduplication_and_stability(self):
        self.write("a.csv", "id,src\n9,a1\n9,a2\n")
        self.write_jsonl("b.jsonl", [{"id": 9, "src": "b1"},
                                     {"id": 9, "src": "b2"}])
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "a.csv", "b.jsonl"])
        self.assertEqual(lines, ["id,src", "9,a1", "9,a2", "9,b1", "9,b2"])

    def test_provided_schema_across_sources(self):
        self.build()
        self.write("schema.json", json.dumps({"columns": [
            {"name": "ts", "type": "timestamp"},
            {"name": "id", "type": "int"},
            {"name": "missing", "type": "string"},
        ]}))
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--desc", "--schema", "schema.json",
             "users.csv", "events.jsonl.gz", "metrics.parquet"])
        self.assertEqual(lines[0], "ts,id,missing")
        self.assertEqual([line.split(",")[1] for line in lines[1:]],
                         ["5", "4", "3", "2", "1"])

    def test_missing_key_column_is_error_3(self):
        self.build()
        self.merge(["--output", "-", "--key", "nope", "users.csv",
                    "metrics.parquet"], expect_rc=3)

    def test_atomic_output_file(self):
        self.build()
        self.merge(["--output", "out.csv", "--key", "id", "users.csv",
                    "events.jsonl.gz", "metrics.parquet"])
        with open(os.path.join(self.dir, "out.csv"), encoding="utf-8") as handle:
            rows = handle.read().splitlines()
        self.assertEqual(len(rows), 6)
        leftovers = [n for n in os.listdir(self.dir) if n.startswith(".merge_files-")]
        self.assertEqual(leftovers, [])

    def test_spilling_matches_in_memory(self):
        self.build()
        args = ["--output", "-", "--key", "ts,id", "users.csv",
                "events.jsonl.gz", "metrics.parquet"]
        small = self.merge(["--memory-limit-mb", "1"] + args).stdout
        big = self.merge(["--memory-limit-mb", "256"] + args).stdout
        self.assertEqual(small, big)


class TestCastingAcrossSources(MultiFormatTestCase):
    INT_SCHEMA = json.dumps({"columns": [{"name": "id", "type": "int"},
                                         {"name": "v", "type": "int"}]})

    def test_boolean_does_not_cast_to_a_number(self):
        self.write("a.csv", "id,v\n7,true\n")
        self.write_jsonl("b.jsonl", [{"id": 8, "v": True}])
        for name in ("a.csv", "b.jsonl"):
            lines = self.merge_lines(
                ["--output", "-", "--key", "id", "--schema", self.INT_SCHEMA, name])
            self.assertEqual(lines[1].split(",")[1], "")

    def test_fail_mode_on_typed_value(self):
        self.write_jsonl("b.jsonl", [{"id": 8, "v": True}])
        proc = self.merge(
            ["--output", "-", "--key", "id", "--schema", self.INT_SCHEMA,
             "--on-type-error", "fail", "b.jsonl"], expect_rc=4)
        self.assertIn("true", proc.stderr)

    def test_integral_typed_floats_cast_to_int(self):
        self.parquet("a.parquet", {"id": [9], "v": [10.0]})
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema", self.INT_SCHEMA,
             "a.parquet"])
        self.assertEqual(lines, ["id,v", "9,10"])

    def test_numbers_cast_to_bool_like_csv(self):
        schema = json.dumps({"columns": [{"name": "id", "type": "int"},
                                         {"name": "v", "type": "bool"}]})
        self.write_jsonl("a.jsonl", [{"id": 7, "v": 1}, {"id": 8, "v": 0}])
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema", schema, "a.jsonl"])
        self.assertEqual(lines, ["id,v", "7,true", "8,false"])

    def test_typed_values_cast_to_string(self):
        schema = json.dumps({"columns": [{"name": "id", "type": "int"},
                                         {"name": "v", "type": "string"}]})
        self.write_jsonl("a.jsonl", [{"id": 7, "v": True}, {"id": 8, "v": 2.5}])
        lines = self.merge_lines(
            ["--output", "-", "--key", "id", "--schema", schema, "a.jsonl"])
        self.assertEqual(lines, ["id,v", "7,true", "8,2.5"])


class PartitionTestCase(ToolTestCase):
    """Helpers for inspecting a partitioned output tree."""

    def tree(self, name="out"):
        """Every output file, as paths relative to the output directory."""
        root = os.path.join(self.dir, name)
        found = []
        for base, _dirs, files in os.walk(root):
            for entry in files:
                path = os.path.join(base, entry)
                found.append(os.path.relpath(path, root).replace(os.sep, "/"))
        return sorted(found)

    def read(self, relative, name="out"):
        path = os.path.join(self.dir, name, *relative.split("/"))
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()

    def lines(self, relative, name="out"):
        return self.read(relative, name).split("\n")[:-1]

    def size(self, relative, name="out"):
        return len(self.read(relative, name).encode("utf-8"))

    def strays(self):
        return [e for e in os.listdir(self.dir) if e.startswith(".merge_files-")]


class TestFieldPartitioning(PartitionTestCase):
    def test_hive_layout_and_per_partition_sorting(self):
        self.write("a.csv", "country,dt,ts,id\n"
                            "US,2024-01-01,3,a\n"
                            "DE,2024-01-02,1,b\n"
                            "US,2024-01-01,2,c\n")
        self.merge(["--output", "out", "--key", "ts,id",
                    "--partition-by", "country,dt", "a.csv"])
        self.assertEqual(self.tree(), [
            "country=DE/dt=2024-01-02/part-00000.csv",
            "country=US/dt=2024-01-01/part-00000.csv",
        ])
        self.assertEqual(
            self.lines("country=US/dt=2024-01-01/part-00000.csv"),
            ["country,dt,id,ts", "US,2024-01-01,c,2", "US,2024-01-01,a,3"],
        )
        self.assertEqual(
            self.lines("country=DE/dt=2024-01-02/part-00000.csv"),
            ["country,dt,id,ts", "DE,2024-01-02,b,1"],
        )

    def test_one_file_per_partition_without_limits(self):
        rows = "".join(f"A,{i}\n" for i in range(50))
        self.write("a.csv", "p,id\n" + rows + "".join(f"B,{i}\n" for i in range(50)))
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p", "a.csv"])
        self.assertEqual(self.tree(),
                         ["p=A/part-00000.csv", "p=B/part-00000.csv"])

    def test_partition_columns_stay_in_the_output_rows(self):
        self.write("a.csv", "p,id\nx,7\n")
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p", "a.csv"])
        self.assertEqual(self.lines("p=x/part-00000.csv"), ["id,p", "7,x"])

    def test_percent_encoding_of_values(self):
        self.write("a.csv", "id,p\n"
                            "1,New York\n"
                            "2,a/b\n"
                            "3,ümlaut\n"
                            "4,~tilde+x\n"
                            "5,a.b-c_d\n")
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p", "a.csv"])
        self.assertEqual(self.tree(), sorted([
            "p=New%20York/part-00000.csv",
            "p=a%2Fb/part-00000.csv",
            "p=%C3%BCmlaut/part-00000.csv",
            "p=%7Etilde%2Bx/part-00000.csv",
            "p=a.b-c_d/part-00000.csv",
        ]))

    def test_null_partition_values(self):
        self.write("a.csv", "id,p\n1,x\n2,\n")
        self.write("b.jsonl", '{"id": 3}\n{"id": 4, "p": null}\n')
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p",
                    "a.csv", "b.jsonl"])
        self.assertEqual(self.tree(),
                         ["p=_null/part-00000.csv", "p=x/part-00000.csv"])
        self.assertEqual(self.lines("p=_null/part-00000.csv"),
                         ["id,p", "2,", "3,", "4,"])

    def test_values_use_the_casted_representation(self):
        self.write("a.csv", "id,flag,when\n"
                            "1,1,2024-03-05T10:00:00+02:00\n"
                            "2,0,2024-03-05T08:00:00Z\n")
        self.merge(["--output", "out", "--key", "id",
                    "--partition-by", "flag,when", "a.csv"])
        self.assertEqual(self.tree(), sorted([
            "flag=true/when=2024-03-05T08%3A00%3A00Z/part-00000.csv",
            "flag=false/when=2024-03-05T08%3A00%3A00Z/part-00000.csv",
        ]))

    def test_descending_order_inside_each_partition(self):
        self.write("a.csv", "p,id\nA,1\nB,2\nA,3\nB,4\n")
        self.merge(["--output", "out", "--key", "id", "--desc",
                    "--partition-by", "p", "a.csv"])
        self.assertEqual(self.lines("p=A/part-00000.csv"), ["id,p", "3,A", "1,A"])
        self.assertEqual(self.lines("p=B/part-00000.csv"), ["id,p", "4,B", "2,B"])

    def test_quoting_rules_apply_inside_partitions(self):
        self.write("a.csv", 'p,id,note\nx,1,"a,b"\nx,2,"say ""hi"""\n')
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p", "a.csv"])
        self.assertEqual(self.lines("p=x/part-00000.csv"),
                         ["id,note,p", '1,"a,b",x', '2,"say ""hi""",x'])

    def test_null_literal_applies_to_partitioned_files(self):
        self.write("a.csv", "p,id,v\nx,7,\n")
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p",
                    "--csv-null-literal", "NULL", "a.csv"])
        self.assertEqual(self.lines("p=x/part-00000.csv"), ["id,p,v", "7,x,NULL"])

    def test_missing_partition_column_is_error_3(self):
        self.write("a.csv", "id\n1\n")
        proc = self.merge(["--output", "out", "--key", "id",
                           "--partition-by", "nope", "a.csv"], expect_rc=3)
        self.assertIn("partition column(s) not present in resolved schema: nope",
                      proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "out")))

    def test_empty_partition_by_is_error_2(self):
        self.write("a.csv", "id\n1\n")
        self.merge(["--output", "out", "--key", "id",
                    "--partition-by", "", "a.csv"], expect_rc=2)


class TestShardedOutput(PartitionTestCase):
    def test_max_rows_per_file(self):
        rows = "".join(f"{i},v{i:03d}\n" for i in range(23))
        self.write("a.csv", "id,v\n" + rows)
        self.merge(["--output", "out", "--key", "id",
                    "--max-rows-per-file", "10", "a.csv"])
        self.assertEqual(self.tree(), ["part-00000.csv", "part-00001.csv",
                                       "part-00002.csv"])
        for name, count in (("part-00000.csv", 10), ("part-00001.csv", 10),
                            ("part-00002.csv", 3)):
            lines = self.lines(name)
            self.assertEqual(lines[0], "id,v")
            self.assertEqual(len(lines) - 1, count)

    def test_shards_follow_the_global_sort_order(self):
        rows = "".join(f"{i},v\n" for i in (5, 1, 4, 2, 3))
        self.write("a.csv", "id,v\n" + rows)
        self.merge(["--output", "out", "--key", "id",
                    "--max-rows-per-file", "2", "a.csv"])
        self.assertEqual(self.lines("part-00000.csv"), ["id,v", "1,v", "2,v"])
        self.assertEqual(self.lines("part-00001.csv"), ["id,v", "3,v", "4,v"])
        self.assertEqual(self.lines("part-00002.csv"), ["id,v", "5,v"])

    def test_max_bytes_per_file_counts_header_and_newlines(self):
        rows = "".join(f"{i},v{i:03d}\n" for i in range(23))
        self.write("a.csv", "id,v\n" + rows)
        self.merge(["--output", "out", "--key", "id",
                    "--max-bytes-per-file", "40", "a.csv"])
        names = self.tree()
        self.assertGreater(len(names), 1)
        emitted = []
        for name in names:
            self.assertLessEqual(self.size(name), 40)
            lines = self.lines(name)
            self.assertEqual(lines[0], "id,v")
            emitted.extend(lines[1:])
        self.assertEqual(emitted, [f"{i},v{i:03d}" for i in range(23)])

    def test_oversized_row_gets_a_file_of_its_own(self):
        self.write("a.csv", "id,v\n1,short\n2," + "x" * 200 + "\n3,short\n")
        self.merge(["--output", "out", "--key", "id",
                    "--max-bytes-per-file", "30", "a.csv"])
        self.assertEqual(self.tree(), ["part-00000.csv", "part-00001.csv",
                                       "part-00002.csv"])
        self.assertEqual(self.lines("part-00001.csv"), ["id,v", "2," + "x" * 200])
        self.assertGreater(self.size("part-00001.csv"), 30)

    def test_both_limits_cut_at_the_earliest_boundary(self):
        rows = "".join(f"{i},v{i:03d}\n" for i in range(12))
        self.write("a.csv", "id,v\n" + rows)
        self.merge(["--output", "out", "--key", "id",
                    "--max-rows-per-file", "4", "--max-bytes-per-file", "32",
                    "a.csv"])
        for name in self.tree():
            self.assertLessEqual(self.size(name), 32)
            self.assertLessEqual(len(self.lines(name)) - 1, 4)
        self.assertEqual(self.lines("part-00000.csv")[1:],
                         ["0,v000", "1,v001", "2,v002"])

    def test_row_limit_wins_when_it_is_the_tighter_one(self):
        rows = "".join(f"{i},v\n" for i in range(6))
        self.write("a.csv", "id,v\n" + rows)
        self.merge(["--output", "out", "--key", "id",
                    "--max-rows-per-file", "2", "--max-bytes-per-file", "1000",
                    "a.csv"])
        self.assertEqual(self.tree(), ["part-00000.csv", "part-00001.csv",
                                       "part-00002.csv"])

    def test_sharding_inside_field_partitions_restarts_numbering(self):
        rows = "".join(f"{'AB'[i % 2]},{i}\n" for i in range(12))
        self.write("a.csv", "p,id\n" + rows)
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p",
                    "--max-rows-per-file", "2", "a.csv"])
        self.assertEqual(self.tree(), sorted(
            [f"p={letter}/part-{i:05d}.csv"
             for letter in "AB" for i in range(3)]))
        self.assertEqual(self.lines("p=A/part-00000.csv"),
                         ["id,p", "0,A", "2,A"])

    def test_non_positive_limits_are_error_2(self):
        self.write("a.csv", "id\n1\n")
        self.merge(["--output", "out", "--key", "id",
                    "--max-rows-per-file", "0", "a.csv"], expect_rc=2)
        self.merge(["--output", "out", "--key", "id",
                    "--max-bytes-per-file", "-3", "a.csv"], expect_rc=2)


class TestPartitionedOutputLocation(PartitionTestCase):
    def test_stdout_is_rejected_when_partitioning(self):
        self.write("a.csv", "p,id\nx,1\n")
        for extra in (["--partition-by", "p"], ["--max-rows-per-file", "5"],
                      ["--max-bytes-per-file", "500"]):
            proc = self.merge(["--output", "-", "--key", "id"] + extra + ["a.csv"],
                              expect_rc=2)
            self.assertIn("--output", proc.stderr)

    def test_single_csv_when_no_partitioning_flag_is_given(self):
        self.write("a.csv", "id\n2\n1\n")
        self.merge(["--output", "merged.csv", "--key", "id", "a.csv"])
        with open(os.path.join(self.dir, "merged.csv"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "id\n1\n2\n")

    def test_missing_directories_are_created(self):
        self.write("a.csv", "id\n1\n")
        self.merge(["--output", "deep/nest/out", "--key", "id",
                    "--max-rows-per-file", "5", "a.csv"])
        self.assertTrue(os.path.isfile(
            os.path.join(self.dir, "deep", "nest", "out", "part-00000.csv")))

    def test_existing_directory_is_replaced_and_no_temp_is_left(self):
        self.write("a.csv", "id\n1\n")
        os.mkdir(os.path.join(self.dir, "out"))
        with open(os.path.join(self.dir, "out", "stale.csv"), "w") as handle:
            handle.write("stale\n")
        self.merge(["--output", "out", "--key", "id",
                    "--max-rows-per-file", "5", "a.csv"])
        self.assertEqual(self.tree(), ["part-00000.csv"])
        self.assertEqual(self.strays(), [])

    def test_existing_file_as_output_is_error_2(self):
        self.write("a.csv", "id\n1\n")
        self.write("out", "not a directory\n")
        self.merge(["--output", "out", "--key", "id",
                    "--max-rows-per-file", "5", "a.csv"], expect_rc=2)

    def test_failure_keeps_the_previous_directory_and_cleans_up(self):
        schema = json.dumps({"columns": [{"name": "id", "type": "int"}]})
        self.write("a.csv", "id\n1\nzz\n")
        os.mkdir(os.path.join(self.dir, "out"))
        with open(os.path.join(self.dir, "out", "previous.csv"), "w") as handle:
            handle.write("previous\n")
        self.merge(["--output", "out", "--key", "id", "--schema", schema,
                    "--on-type-error", "fail", "--max-rows-per-file", "1",
                    "a.csv"], expect_rc=4)
        self.assertEqual(self.tree(), ["previous.csv"])
        self.assertEqual(self.strays(), [])

    def test_trailing_slash_is_accepted(self):
        self.write("a.csv", "id\n1\n")
        self.merge(["--output", "out/", "--key", "id",
                    "--max-rows-per-file", "5", "a.csv"])
        self.assertEqual(self.tree(), ["part-00000.csv"])

    def test_empty_input_sharded_writes_one_header_only_file(self):
        self.write("a.csv", "id,v\n")
        self.merge(["--output", "out", "--key", "id",
                    "--max-rows-per-file", "5", "a.csv"])
        self.assertEqual(self.tree(), ["part-00000.csv"])
        self.assertEqual(self.read("part-00000.csv"), "id,v\n")

    def test_empty_input_field_partitioned_writes_no_partitions(self):
        self.write("a.csv", "p,id\n")
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p",
                    "a.csv"])
        self.assertEqual(self.tree(), [])
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "out")))


class TestPartitionedScale(PartitionTestCase):
    def _source(self, rows=4000):
        body = "".join(
            f"{'ABC'[i % 3]},{(i * 7919) % rows},{'p' * 20}\n" for i in range(rows)
        )
        self.write("a.csv", "p,id,v\n" + body)

    def test_spilling_matches_the_in_memory_result(self):
        self._source()
        args = ["--key", "id", "--partition-by", "p",
                "--max-rows-per-file", "700", "a.csv"]
        self.merge(["--output", "big"] + args + ["--memory-limit-mb", "512"])
        self.merge(["--output", "small"] + args + ["--memory-limit-mb", "1"])
        self.assertEqual(self.tree("big"), self.tree("small"))
        for name in self.tree("big"):
            self.assertEqual(self.read(name, "big"), self.read(name, "small"))

    def test_every_row_survives_and_stays_sorted(self):
        self._source()
        self.merge(["--output", "out", "--key", "id", "--partition-by", "p",
                    "--max-bytes-per-file", "2000", "--memory-limit-mb", "1",
                    "a.csv"])
        seen = 0
        for partition in ("A", "B", "C"):
            names = [n for n in self.tree() if n.startswith(f"p={partition}/")]
            previous = None
            for name in sorted(names):
                self.assertLessEqual(self.size(name), 2000)
                lines = self.lines(name)
                self.assertEqual(lines[0], "id,p,v")
                for line in lines[1:]:
                    identifier, letter, _ = line.split(",")
                    self.assertEqual(letter, partition)
                    current = int(identifier)
                    if previous is not None:
                        self.assertLessEqual(previous, current)
                    previous = current
                    seen += 1
        self.assertEqual(seen, 4000)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# --------------------------------------------------------------------------
# Checkpoint 4: nested types
# --------------------------------------------------------------------------

NESTED_SCHEMA = {
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
        {"name": "attrs", "type": {"map": {"key": "string", "value": "string"}}},
        {"name": "event_time", "type": "timestamp"},
    ]
}


class NestedTestCase(MultiFormatTestCase):
    def setUp(self):
        super().setUp()
        self.write("nested.json", json.dumps(NESTED_SCHEMA))

    def events(self, name="events.jsonl"):
        return self.write_jsonl(name, [
            {"id": 2,
             "user": {"name": "bo", "age": "41", "prefs": {"z": "1", "a": "2"}},
             "items": [{"sku": "s2", "qty": 1}],
             "attrs": {"country": "US"},
             "event_time": "2024-01-02 10:00:00+02:00"},
            {"id": 1,
             "user": {"name": "ann", "prefs": {}},
             "items": [],
             "attrs": {"country": "de"},
             "event_time": "2024-01-01T00:00:00Z"},
            {"id": 3, "user": None,
             "items": [{"sku": "s3", "qty": "x"}, None],
             "attrs": None, "event_time": None},
        ])

    def base(self, *extra):
        return ["--output", "-", "--schema", "nested.json", *extra,
                "events.jsonl"]


class TestNestedOutput(NestedTestCase):
    def test_canonical_json_encoding(self):
        self.events()
        lines = self.merge_lines(self.base("--key", "id"))
        self.assertEqual(lines[0], "id,user,items,attrs,event_time")
        rows = [read_row(line) for line in lines[1:]]
        # struct fields keep the declared order, map keys are sorted, every
        # declared field is present even when null
        self.assertEqual(rows[0][1], '{"name":"ann","age":null,"prefs":{}}')
        self.assertEqual(rows[1][1],
                         '{"name":"bo","age":41,"prefs":{"a":"2","z":"1"}}')
        self.assertEqual(rows[0][2], "[]")
        self.assertEqual(rows[1][2], '[{"sku":"s2","qty":1}]')
        # a null column value is the CSV null literal, not JSON null
        self.assertEqual(rows[2][1], "")
        self.assertEqual(rows[2][3], "")
        # nested cast failures follow --on-type-error inside the structure
        self.assertEqual(rows[2][2], '[{"sku":"s3","qty":null},null]')
        # timestamps inside and outside nested values normalise to UTC
        self.assertEqual(rows[1][4], "2024-01-02T08:00:00Z")

    def test_minified_and_utf8(self):
        self.write("a.tsv", 'id\tv\n1\t{"k": "a,b\\"c\\u00fc"}\n')
        lines = self.merge_lines([
            "--output", "-", "--key", "id", "--schema",
            json.dumps({"columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": "map<string,string>"}]}),
            "a.tsv"])
        row = read_row(lines[1])
        self.assertEqual(row[1], '{"k":"a,b\\"cü"}')

    def test_keep_string_and_coerce_null_inside_nested(self):
        self.write("a.tsv", 'id\ts\n1\t{"a":"oops","b":{"x":1}}\n')
        schema = json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "s", "type": "struct<a:int,b:string>"}]})
        args = ["--output", "-", "--key", "id", "--schema", schema, "a.tsv"]
        row = read_row(self.merge_lines(args)[1])
        self.assertEqual(row[1], '{"a":null,"b":null}')
        row = read_row(
            self.merge_lines(args + ["--on-type-error", "keep-string"])[1])
        self.assertEqual(row[1], '{"a":"oops","b":"{\\"x\\":1}"}')

    def test_fail_inside_nested_is_error_4(self):
        self.write("a.tsv", 'id\ts\n1\t{"a":"oops"}\n')
        schema = json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "s", "type": "struct<a:int>"}]})
        proc = self.merge(["--output", "-", "--key", "id", "--schema", schema,
                           "--on-type-error", "fail", "a.tsv"], expect_rc=4)
        self.assertIn('ERR 4 cannot cast "oops" to int in field "s.a"',
                      proc.stderr)
        self.assertIn("file=a.tsv", proc.stderr)
        self.assertIn("line=2", proc.stderr)


class TestNestedInputs(NestedTestCase):
    def test_csv_cell_holds_one_json_literal(self):
        self.write("a.csv", 'id,v\n1,"{""a"":1}"\n2,\n3,notjson\n')
        schema = json.dumps({"columns": [{"name": "id", "type": "int"},
                                         {"name": "v", "type": "json"}]})
        args = ["--output", "-", "--key", "id", "--schema", schema, "a.csv"]
        lines = self.merge_lines(args)
        self.assertEqual([read_row(l)[1] for l in lines[1:]],
                         ['{"a":1}', "", ""])
        lines = self.merge_lines(args + ["--on-type-error", "keep-string"])
        self.assertEqual(read_row(lines[3])[1], "notjson")
        proc = self.merge(args + ["--on-type-error", "fail"], expect_rc=4)
        self.assertIn("notjson", proc.stderr)

    def test_json_type_accepts_any_json_value(self):
        self.write("a.tsv", 'id\tv\n1\t5\n2\t"txt"\n3\tnull\n4\t[1,{"b":2}]\n')
        schema = json.dumps({"columns": [{"name": "id", "type": "int"},
                                         {"name": "v", "type": "json"}]})
        lines = self.merge_lines(["--output", "-", "--key", "id",
                                  "--schema", schema, "a.tsv"])
        self.assertEqual([read_row(l)[1] for l in lines[1:]],
                         ["5", '"txt"', "", '[1,{"b":2}]'])

    def test_flat_declared_column_with_nested_input(self):
        self.write_jsonl("a.jsonl", [{"id": 1, "v": {"a": 1}}, {"id": 2, "v": 3}])
        schema = json.dumps({"columns": [{"name": "id", "type": "int"},
                                         {"name": "v", "type": "int"}]})
        args = ["--output", "-", "--key", "id", "--schema", schema, "a.jsonl"]
        self.assertEqual(self.merge_lines(args), ["id,v", "1,", "2,3"])
        lines = self.merge_lines(args + ["--on-type-error", "keep-string"])
        self.assertEqual(read_row(lines[1])[1], '{"a":1}')
        self.merge(args + ["--on-type-error", "fail"], expect_rc=4)

    def test_parquet_nested_structs_lists_and_maps(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        path = os.path.join(self.dir, "u.parquet")
        pq.write_table(pa.table({
            "id": pa.array([10, 11], pa.int64()),
            "user": pa.array(
                [{"name": "pq", "age": 7, "prefs": [("b", "2"), ("a", "1")]},
                 None],
                pa.struct([("name", pa.string()), ("age", pa.int64()),
                           ("prefs", pa.map_(pa.string(), pa.string()))])),
            "items": pa.array(
                [[{"sku": "k", "qty": 3}], []],
                pa.list_(pa.struct([("sku", pa.string()),
                                    ("qty", pa.int64())]))),
            "attrs": pa.array([[("country", "FR")], None],
                              pa.map_(pa.string(), pa.string())),
        }), path)
        lines = self.merge_lines(["--output", "-", "--key", "id",
                                  "--schema", "nested.json", "u.parquet"])
        rows = [read_row(line) for line in lines[1:]]
        self.assertEqual(rows[0][1],
                         '{"name":"pq","age":7,"prefs":{"a":"1","b":"2"}}')
        self.assertEqual(rows[0][2], '[{"sku":"k","qty":3}]')
        self.assertEqual(rows[0][3], '{"country":"FR"}')
        self.assertEqual(rows[1][1], "")
        self.assertEqual(rows[1][2], "[]")

    def test_merging_nested_jsonl_and_parquet(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        self.events()
        pq.write_table(pa.table({
            "id": pa.array([4], pa.int64()),
            "attrs": pa.array([[("country", "US")]],
                              pa.map_(pa.string(), pa.string())),
        }), os.path.join(self.dir, "u.parquet"))
        lines = self.merge_lines(["--output", "-", "--key", "id",
                                  "--schema", "nested.json",
                                  "events.jsonl", "u.parquet"])
        self.assertEqual(len(lines), 5)
        self.assertEqual(read_row(lines[4])[3], '{"country":"US"}')


class TestNestedWithoutSchema(MultiFormatTestCase):
    def test_jsonl_nested_requires_schema(self):
        self.write_jsonl("a.jsonl", [{"id": 1, "v": {"n": 1}}])
        proc = self.merge(["--output", "-", "--key", "id", "a.jsonl"],
                          expect_rc=6)
        self.assertIn("ERR 6 nested structure requires provided --schema",
                      proc.stderr)

    def test_parquet_nested_requires_schema(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        pq.write_table(pa.table({"id": pa.array([1]),
                                 "tags": pa.array([["a", "b"]])}),
                       os.path.join(self.dir, "a.parquet"))
        proc = self.merge(["--output", "-", "--key", "id", "a.parquet"],
                          expect_rc=6)
        self.assertIn("ERR 6 nested structure requires provided --schema",
                      proc.stderr)

    def test_csv_json_cell_stays_a_string(self):
        self.write("a.csv", 'id,v\n1,"{""a"":1}"\n')
        lines = self.merge_lines(["--output", "-", "--key", "id", "a.csv"])
        self.assertEqual(read_row(lines[1])[1], '{"a":1}')


class TestFieldPaths(NestedTestCase):
    def ids(self, *extra):
        lines = self.merge_lines(self.base(*extra))
        return [read_row(line)[0] for line in lines[1:]]

    def test_struct_leaf_key(self):
        self.events()
        self.assertEqual(self.ids("--key", "user.name"), ["3", "1", "2"])
        self.assertEqual(self.ids("--key", "user.name", "--desc"),
                         ["2", "1", "3"])

    def test_array_index_key(self):
        self.events()
        self.assertEqual(self.ids("--key", "items.0.qty,id"), ["1", "3", "2"])

    def test_map_lookup_key(self):
        self.events()
        self.assertEqual(self.ids("--key", 'attrs["country"],id'),
                         ["3", "2", "1"])

    def test_out_of_range_and_missing_keys_are_null(self):
        self.events()
        self.assertEqual(self.ids("--key", "items.5.qty,id"), ["1", "2", "3"])
        self.assertEqual(self.ids("--key", 'attrs["nope"],id'),
                         ["1", "2", "3"])

    def test_non_primitive_key_is_error_3(self):
        self.events()
        for path in ("user", "items", "attrs", "items.0"):
            proc = self.merge(self.base("--key", path), expect_rc=3)
            self.assertIn(
                f'ERR 3 key column "{path}" does not resolve to a primitive',
                proc.stderr)

    def test_unknown_leaf_is_error_3(self):
        self.events()
        self.merge(self.base("--key", "user.nope"), expect_rc=3)
        self.merge(self.base("--key", "items.x.sku"), expect_rc=3)

    def test_unknown_column_is_error_3(self):
        self.events()
        proc = self.merge(self.base("--key", "nope.x"), expect_rc=3)
        self.assertIn("not present in resolved schema: nope.x", proc.stderr)

    def test_map_keys_must_be_quoted(self):
        self.events()
        self.merge(self.base("--key", 'attrs[country]'), expect_rc=3)
        self.merge(self.base("--key", "user..name"), expect_rc=3)

    def test_partition_by_nested_paths(self):
        self.events()
        self.merge(["--output", "out", "--key", "id", "--schema", "nested.json",
                    "--partition-by", 'attrs["country"]', "events.jsonl"])
        parts = sorted(
            os.path.relpath(os.path.join(root, name), os.path.join(self.dir, "out"))
            for root, _dirs, files in os.walk(os.path.join(self.dir, "out"))
            for name in files
        )
        self.assertEqual(parts, [
            'attrs["country"]=US/part-00000.csv',
            'attrs["country"]=_null/part-00000.csv',
            'attrs["country"]=de/part-00000.csv',
        ])

    def test_partition_by_non_primitive_is_error_3(self):
        self.events()
        proc = self.merge(["--output", "out", "--key", "id", "--schema",
                           "nested.json", "--partition-by", "user",
                           "events.jsonl"], expect_rc=3)
        self.assertIn(
            'ERR 3 partition column "user" does not resolve to a primitive',
            proc.stderr)

    def test_column_name_with_a_dot_wins_over_a_path(self):
        self.write("a.csv", "a.b,c\n2,x\n1,y\n")
        lines = self.merge_lines(["--output", "-", "--key", "a.b", "a.csv"])
        self.assertEqual(lines, ["a.b,c", "1,y", "2,x"])

    def test_spilling_matches_in_memory_with_nested_keys(self):
        records = []
        for i in range(400):
            records.append({
                "id": i,
                "user": {"name": f"n{i % 17}", "age": i % 13,
                         "prefs": {"k": str(i)}},
                "items": [{"sku": f"s{i % 7}", "qty": i % 5}],
                "attrs": {"country": ["US", "de", "fr"][i % 3]},
                "event_time": f"2024-01-{1 + i % 28:02d}T00:00:00Z",
            })
        self.write_jsonl("events.jsonl", records)
        args = self.base("--key", 'user.age,items.0.sku,attrs["country"],id')
        small = self.merge(["--memory-limit-mb", "1"] + args).stdout
        big = self.merge(["--memory-limit-mb", "256"] + args).stdout
        self.assertEqual(small, big)
        self.assertEqual(len(small.splitlines()), 401)


class TestTypeAliases(ToolTestCase):
    def schema(self, type_spec):
        return json.dumps({"columns": [{"name": "v", "type": type_spec}]})

    def test_builtin_aliases_are_case_insensitive(self):
        self.write("a.csv", "v\n7\n")
        for alias in ("INTEGER", "Long", "int"):
            lines = self.merge_lines(["--output", "-", "--key", "v",
                                      "--schema", self.schema(alias), "a.csv"])
            self.assertEqual(lines, ["v", "7"])

    def test_builtin_alias_table(self):
        cases = {
            "double": ("1.5", "1.5"), "number": ("1.5", "1.5"),
            "boolean": ("1", "true"), "text": ("x", "x"),
            "varchar": ("x", "x"),
            "datetime": ("2024-01-02T03:04:05+01:00", "2024-01-02T02:04:05Z"),
            "timestamptz": ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        }
        for alias, (raw, expected) in cases.items():
            self.write("a.csv", f"v\n{raw}\n")
            lines = self.merge_lines(["--output", "-", "--key", "v", "--schema",
                                      self.schema(alias), "a.csv"])
            self.assertEqual(lines, ["v", expected], alias)

    def test_list_alias_maps_onto_array(self):
        self.write("a.csv", 'v\n"[1,2]"\n')
        lines = self.merge_lines(["--output", "-", "--key", "v.0", "--schema",
                                  self.schema("LIST<integer>"), "a.csv"])
        self.assertEqual(read_row(lines[1])[0], "[1,2]")

    def test_alias_file_is_transitive(self):
        self.write("aliases.json", json.dumps({"aliases": {
            "smallint": "int", "decimal": "float", "uuid": "string",
            "myts": "mydate", "mydate": "timestamp"}}))
        self.write("a.csv", "v\n2024-01-02 03:04:05\n")
        lines = self.merge_lines([
            "--output", "-", "--key", "v", "--schema", self.schema("MyTs"),
            "--type-alias-file", "aliases.json", "a.csv"])
        self.assertEqual(lines, ["v", "2024-01-02T03:04:05Z"])

    def test_alias_file_applies_inside_nested_types(self):
        self.write("aliases.json", json.dumps({"aliases": {"smallint": "int"}}))
        self.write("a.csv", 'v\n"{""a"":""3""}"\n')
        lines = self.merge_lines([
            "--output", "-", "--key", "v.a", "--schema",
            self.schema({"struct": {"fields": [{"name": "a",
                                                "type": "SMALLINT"}]}}),
            "--type-alias-file", "aliases.json", "a.csv"])
        self.assertEqual(read_row(lines[1])[0], '{"a":3}')

    def test_alias_cycle_is_error_2(self):
        self.write("aliases.json",
                   json.dumps({"aliases": {"a": "b", "b": "c", "c": "a"}}))
        self.write("x.csv", "v\n1\n")
        proc = self.merge(["--output", "-", "--key", "v", "--schema",
                           self.schema("int"), "--type-alias-file",
                           "aliases.json", "x.csv"], expect_rc=2)
        self.assertIn("cycle", proc.stderr)

    def test_missing_alias_file_is_error_2(self):
        self.write("x.csv", "v\n1\n")
        self.merge(["--output", "-", "--key", "v", "--type-alias-file",
                    "nope.json", "x.csv"], expect_rc=2)

    def test_unknown_type_is_error_3(self):
        self.write("x.csv", "v\n1\n")
        proc = self.merge(["--output", "-", "--key", "v", "--schema",
                           self.schema("widget"), "x.csv"], expect_rc=3)
        self.assertIn("widget", proc.stderr)

    def test_invalid_nested_declarations_are_error_3(self):
        self.write("x.csv", "v\n1\n")
        for spec in (
            {"struct": {"fields": [{"name": "a", "type": "int"},
                                   {"name": "a", "type": "int"}]}},
            {"map": {"key": "int", "value": "int"}},
            {"array": {}},
        ):
            self.merge(["--output", "-", "--key", "v", "--schema",
                        self.schema(spec), "x.csv"], expect_rc=3)
