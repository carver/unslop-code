"""End-to-end tests of Hive-style field partitioning and size/row based sharding."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

# ``support`` puts the repository root on sys.path, so it is imported first.
from support import MergeTestCase, merge_files

from csvmerge.shards import atomic_directory

ROWS = "country,dt,id,note\nUS,2024-07-01,3,c\nCA,2024-07-01,1,a\nUS,2024-07-01,2,b\nUS,2024-07-02,4,d\n"


class LayoutTests(MergeTestCase):
    def test_hive_directories_hold_their_rows_sorted_by_key(self) -> None:
        source = self.write("a.csv", ROWS)
        tree = self.run_tree("--key", "id", "--partition-by", "country,dt", source)
        self.assertEqual(
            tree,
            {
                "country=CA/dt=2024-07-01/part-00000.csv": ["country,dt,id,note", "CA,2024-07-01,1,a"],
                "country=US/dt=2024-07-01/part-00000.csv": [
                    "country,dt,id,note",
                    "US,2024-07-01,2,b",
                    "US,2024-07-01,3,c",
                ],
                "country=US/dt=2024-07-02/part-00000.csv": ["country,dt,id,note", "US,2024-07-02,4,d"],
            },
        )

    def test_descending_applies_within_each_partition(self) -> None:
        source = self.write("a.csv", ROWS)
        tree = self.run_tree("--key", "id", "--desc", "--partition-by", "country", source)
        self.assertEqual(
            tree["country=US/part-00000.csv"][1:], ["US,2024-07-02,4,d", "US,2024-07-01,3,c", "US,2024-07-01,2,b"]
        )

    def test_values_are_percent_encoded_and_nulls_become_the_null_segment(self) -> None:
        source = self.write("a.csv", "g,id\nCA/QC,1\na b,2\nnaïve,3\n,4\n")
        self.assertEqual(
            sorted(self.run_tree("--key", "id", "--partition-by", "g", source)),
            [
                "g=CA%2FQC/part-00000.csv",
                "g=_null/part-00000.csv",
                "g=a%20b/part-00000.csv",
                "g=na%C3%AFve/part-00000.csv",
            ],
        )

    def test_segments_spell_the_value_as_the_resolved_type_renders_it(self) -> None:
        source = self.write("a.csv", "when,n,id\n2024-07-01T08:30:00+02:00,007,1\n")
        schema = self.write("s.json", json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "n", "type": "int"},
            {"name": "when", "type": "timestamp"},
        ]}))
        tree = self.run_tree("--key", "id", "--schema", schema, "--partition-by", "when,n", source)
        self.assertEqual(list(tree), ["when=2024-07-01T06%3A30%3A00Z/n=7/part-00000.csv"])

    def test_partition_column_missing_from_the_schema_exits_with_the_schema_code(self) -> None:
        source = self.write("a.csv", "id\n1\n")
        exit_code = merge_files.main(
            ["--output", str(self.root / "out"), "--key", "id", "--partition-by", "nope", source]
        )
        self.assertEqual(exit_code, 3)


class ShardingTests(MergeTestCase):
    def test_row_limit_cuts_files_in_emitted_order_each_with_a_header(self) -> None:
        source = self.write("a.csv", "id\n" + "".join(f"{index}\n" for index in range(5)))
        tree = self.run_tree("--key", "id", "--max-rows-per-file", "2", source)
        self.assertEqual(
            tree,
            {
                "part-00000.csv": ["id", "0", "1"],
                "part-00001.csv": ["id", "2", "3"],
                "part-00002.csv": ["id", "4"],
            },
        )

    def test_byte_limit_keeps_every_file_within_the_budget(self) -> None:
        source = self.write("a.csv", "id,pad\n" + "".join(f"{index},{'x' * 20}\n" for index in range(40)))
        self.run_tree("--key", "id", "--max-bytes-per-file", "128", source)
        parts = sorted((self.root / "out").iterdir())
        self.assertGreater(len(parts), 5)
        self.assertTrue(all(part.stat().st_size <= 128 for part in parts))
        self.assertEqual(sum(len(part.read_text().splitlines()) - 1 for part in parts), 40)

    def test_a_row_larger_than_the_budget_gets_a_file_of_its_own(self) -> None:
        source = self.write("a.csv", f"id,pad\n1,{'x' * 200}\n2,y\n3,z\n")
        tree = self.run_tree("--key", "id", "--max-bytes-per-file", "32", source)
        self.assertEqual(tree["part-00000.csv"], ["id,pad", "1," + "x" * 200])
        self.assertEqual(tree["part-00001.csv"], ["id,pad", "2,y", "3,z"])

    def test_multibyte_rows_are_measured_in_bytes_not_characters(self) -> None:
        source = self.write("a.csv", "id,note\n1,ü\n2,ü\n")
        header, row = len("id,note\n"), len("1,ü\n".encode("utf-8"))
        tree = self.run_tree("--key", "id", "--max-bytes-per-file", str(header + row), source)
        self.assertEqual(list(tree), ["part-00000.csv", "part-00001.csv"])

    def test_both_limits_cut_at_whichever_boundary_comes_first(self) -> None:
        source = self.write("a.csv", "id,pad\n" + "".join(f"{index},{'x' * 10}\n" for index in range(6)))
        by_rows = self.run_tree("--key", "id", "--max-rows-per-file", "2", "--max-bytes-per-file", "10000", source)
        both = self.run_tree("--key", "id", "--max-rows-per-file", "2", "--max-bytes-per-file", "25", source)
        self.assertEqual(len(by_rows), 3)
        self.assertEqual([len(lines) - 1 for lines in both.values()], [1, 1, 1, 1, 1, 1])

    def test_sharding_and_field_partitioning_combine(self) -> None:
        source = self.write("a.csv", ROWS)
        tree = self.run_tree("--key", "id", "--partition-by", "country", "--max-rows-per-file", "1", source)
        self.assertEqual(
            sorted(tree),
            [
                "country=CA/part-00000.csv",
                "country=US/part-00000.csv",
                "country=US/part-00001.csv",
                "country=US/part-00002.csv",
            ],
        )
        self.assertEqual(tree["country=US/part-00001.csv"], ["country,dt,id,note", "US,2024-07-01,3,c"])

    def test_spilling_to_disk_produces_the_same_tree(self) -> None:
        rows = [f"{(index * 7919) % 500},g{index % 7}" for index in range(4000)]
        source = self.write("a.csv", "k,g\n" + "\n".join(rows) + "\n")
        arguments = ("--key", "k", "--partition-by", "g", "--max-rows-per-file", "200", source)
        spilled = self.run_tree(*arguments, "--memory-limit-mb", "1", output="spilled")
        in_memory = self.run_tree(*arguments, "--memory-limit-mb", "512", output="memory")
        self.assertEqual(spilled, in_memory)
        self.assertEqual(sum(len(lines) - 1 for lines in spilled.values()), 4000)


class OutputLocationTests(MergeTestCase):
    def test_missing_directories_are_created(self) -> None:
        source = self.write("a.csv", "id\n1\n")
        tree = self.run_tree("--key", "id", "--max-rows-per-file", "1", source, output="nested/deep/out")
        self.assertEqual(list(tree), ["part-00000.csv"])

    def test_stdout_is_rejected_when_partitioning(self) -> None:
        source = self.write("a.csv", "id\n1\n")
        with self.assertRaises(SystemExit) as raised:
            merge_files.main(["--output", "-", "--key", "id", "--partition-by", "id", source])
        self.assertEqual(raised.exception.code, 2)

    def test_an_existing_file_is_rejected_as_a_partitioned_output(self) -> None:
        source = self.write("a.csv", "id\n1\n")
        with self.assertRaises(SystemExit) as raised:
            merge_files.main(["--output", source, "--key", "id", "--max-rows-per-file", "1", source])
        self.assertEqual(raised.exception.code, 2)

    def test_a_rerun_replaces_the_previous_tree(self) -> None:
        first = self.write("a.csv", "id\n1\n2\n3\n")
        self.run_tree("--key", "id", "--max-rows-per-file", "1", first)
        second = self.write("b.csv", "id\n9\n")
        self.assertEqual(self.run_tree("--key", "id", "--max-rows-per-file", "1", second), {"part-00000.csv": ["id", "9"]})

    def test_a_failed_run_leaves_no_temporary_directory_behind(self) -> None:
        destination = self.root / "out"
        with self.assertRaises(RuntimeError):
            with atomic_directory(str(destination)) as pending:
                Path(pending, "part-00000.csv").write_text("id\n")
                raise RuntimeError("boom")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_no_partitioning_flags_still_writes_one_csv(self) -> None:
        source = self.write("a.csv", "id\n2\n1\n")
        self.assertEqual(self.run_merge("--key", "id", source), ["id", "1", "2"])


if __name__ == "__main__":
    unittest.main()
