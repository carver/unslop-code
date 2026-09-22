#!/usr/bin/env python3
"""Specification tests for merge_files.py."""

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
