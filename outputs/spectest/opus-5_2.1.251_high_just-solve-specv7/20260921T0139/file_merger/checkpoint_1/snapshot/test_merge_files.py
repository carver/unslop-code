#!/usr/bin/env python3
"""Specification tests for merge_files.py."""

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
            expect_rc=1)
        self.assertIn("nope", proc.stderr)

    def test_missing_inferred_key_column_errors(self):
        self.write("a.csv", "id\n1\n")
        proc = self.merge(["--output", "-", "--key", "zzz", "a.csv"], expect_rc=1)
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
        proc = self.merge(self.base("--on-type-error", "fail"), expect_rc=1)
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
        self.assertEqual(lines, ["id,note", '7,"a,b"'])

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
        proc = self.merge(["--output", "-", "--key", "id", "nope.csv"], expect_rc=1)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)


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
