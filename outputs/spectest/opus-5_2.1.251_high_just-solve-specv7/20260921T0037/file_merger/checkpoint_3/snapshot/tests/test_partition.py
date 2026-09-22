"""Spec conformance tests for partitioned output."""
import os, random, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "merge_files.py")


def run(args, expect_ok=True):
    p = subprocess.run([sys.executable, SCRIPT] + args, capture_output=True, text=True)
    if expect_ok and p.returncode != 0:
        raise AssertionError("exit %d\nSTDERR: %s" % (p.returncode, p.stderr))
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def w(self, name, text):
        p = os.path.join(self.d, name)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return p

    def out(self, name="out"):
        return os.path.join(self.d, name)

    def tree(self, root):
        """Relative paths of every file below ``root``, sorted."""
        found = []
        for base, _dirs, files in os.walk(root):
            for f in files:
                rel = os.path.relpath(os.path.join(base, f), root)
                found.append(rel.replace(os.sep, "/"))
        return sorted(found)

    def read(self, root, rel):
        with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
            return fh.read()

    def strays(self):
        """Anything in the working dir that is not an expected artefact."""
        return sorted(n for n in os.listdir(self.d) if n.startswith("."))


class TestFieldPartitions(Base):
    def test_hive_layout_and_contents(self):
        a = self.w("a.csv", "id,ts,country\n"
                            "3,2024-01-01T10:00:00Z,US\n"
                            "1,2024-01-02T10:00:00Z,FR\n"
                            "2,2024-01-01T09:00:00Z,US\n")
        o = self.out()
        run(["--output", o, "--key", "ts,id", "--partition-by", "country", a])
        self.assertEqual(self.tree(o), ["country=FR/part-00000.csv",
                                        "country=US/part-00000.csv"])
        self.assertEqual(self.read(o, "country=US/part-00000.csv"),
                         "country,id,ts\n"
                         "US,2,2024-01-01T09:00:00Z\n"
                         "US,3,2024-01-01T10:00:00Z\n")
        self.assertEqual(self.read(o, "country=FR/part-00000.csv"),
                         "country,id,ts\nFR,1,2024-01-02T10:00:00Z\n")

    def test_multiple_partition_columns_nest_in_order(self):
        a = self.w("a.csv", "id,c,d\n1,US,x\n2,US,y\n3,FR,x\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "c,d", a])
        self.assertEqual(self.tree(o), ["c=FR/d=x/part-00000.csv",
                                        "c=US/d=x/part-00000.csv",
                                        "c=US/d=y/part-00000.csv"])

    def test_percent_encoding_of_values(self):
        a = self.w("a.csv", "id,v\n1,hello world\n2,a/b\n3,café\n"
                            "4,plain-ok_1.2\n5,\"x,y\"\n6,100%\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "v", a])
        self.assertEqual(self.tree(o), [
            "v=100%25/part-00000.csv",
            "v=a%2Fb/part-00000.csv",
            "v=caf%C3%A9/part-00000.csv",
            "v=hello%20world/part-00000.csv",
            "v=plain-ok_1.2/part-00000.csv",
            "v=x%2Cy/part-00000.csv",
        ])

    def test_null_partition_value(self):
        a = self.w("a.csv", "id,v\n1,\n2,q\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "v", a])
        self.assertIn("v=_null/part-00000.csv", self.tree(o))

    def test_missing_column_is_null_partition(self):
        a = self.w("a.csv", "id,v\n1,q\n")
        b = self.w("b.csv", "id\n2\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "v", a, b])
        self.assertEqual(self.tree(o), ["v=_null/part-00000.csv",
                                        "v=q/part-00000.csv"])

    def test_values_use_cast_types(self):
        a = self.w("a.csv", "id,n\n1,001\n2,1\n3,1.50\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "n",
             "--infer", "loose", a])
        # all three cast to float -> 1.0 / 1.0 / 1.5
        self.assertEqual(self.tree(o), ["n=1.0/part-00000.csv",
                                        "n=1.5/part-00000.csv"])

    def test_sorted_within_partition_desc(self):
        a = self.w("a.csv", "id,c\n1,US\n3,US\n2,US\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--desc", "--partition-by", "c", a])
        self.assertEqual(self.read(o, "c=US/part-00000.csv"),
                         "c,id\nUS,3\nUS,2\nUS,1\n")

    def test_partition_column_may_also_be_a_key(self):
        a = self.w("a.csv", "id,c\n1,b\n2,a\n")
        o = self.out()
        run(["--output", o, "--key", "c,id", "--partition-by", "c", a])
        self.assertEqual(self.tree(o), ["c=a/part-00000.csv",
                                        "c=b/part-00000.csv"])

    def test_no_rows_yields_empty_directory(self):
        a = self.w("a.csv", "id,c\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "c",
             "--schema", '{"columns":[{"name":"id","type":"int"},'
                         '{"name":"c","type":"string"}]}', a])
        self.assertTrue(os.path.isdir(o))
        self.assertEqual(self.tree(o), [])


class TestSharding(Base):
    def rows(self, n):
        return self.w("a.csv", "id,v\n" + "".join(
            "%d,%d\n" % (i, i * 10) for i in range(1, n + 1)))

    def test_max_rows_per_file(self):
        a = self.rows(7)
        o = self.out()
        run(["--output", o, "--key", "id", "--max-rows-per-file", "3", a])
        self.assertEqual(self.tree(o), ["part-00000.csv", "part-00001.csv",
                                        "part-00002.csv"])
        self.assertEqual(self.read(o, "part-00000.csv"),
                         "id,v\n1,10\n2,20\n3,30\n")
        self.assertEqual(self.read(o, "part-00002.csv"), "id,v\n7,70\n")

    def test_exact_multiple_has_no_trailing_empty_file(self):
        a = self.rows(6)
        o = self.out()
        run(["--output", o, "--key", "id", "--max-rows-per-file", "3", a])
        self.assertEqual(self.tree(o), ["part-00000.csv", "part-00001.csv"])

    def test_max_bytes_includes_header_and_newlines(self):
        a = self.rows(7)
        o = self.out()
        run(["--output", o, "--key", "id", "--max-bytes-per-file", "15", a])
        for rel in self.tree(o):
            size = os.path.getsize(os.path.join(o, rel))
            self.assertLessEqual(size, 15)
        self.assertEqual(self.read(o, "part-00000.csv"), "id,v\n1,10\n2,20\n")

    def test_oversized_row_gets_its_own_file(self):
        a = self.rows(3)
        o = self.out()
        run(["--output", o, "--key", "id", "--max-bytes-per-file", "1", a])
        self.assertEqual(self.tree(o), ["part-00000.csv", "part-00001.csv",
                                        "part-00002.csv"])
        self.assertEqual(self.read(o, "part-00001.csv"), "id,v\n2,20\n")

    def test_both_limits_cut_at_earliest_boundary(self):
        a = self.rows(7)
        o = self.out()
        run(["--output", o, "--key", "id", "--max-bytes-per-file", "100",
             "--max-rows-per-file", "2", a])
        self.assertEqual(len(self.tree(o)), 4)
        o2 = self.out("out2")
        run(["--output", o2, "--key", "id", "--max-bytes-per-file", "15",
             "--max-rows-per-file", "100", a])
        self.assertEqual(len(self.tree(o2)), 4)

    def test_global_sort_order_across_shards(self):
        a = self.w("a.csv", "id\n" + "".join("%d\n" % i for i in [5, 1, 4, 2, 3]))
        o = self.out()
        run(["--output", o, "--key", "id", "--max-rows-per-file", "2", a])
        seen = []
        for rel in self.tree(o):
            body = self.read(o, rel).split("\n")
            self.assertEqual(body[0], "id")
            seen.extend(int(x) for x in body[1:] if x)
        self.assertEqual(seen, [1, 2, 3, 4, 5])

    def test_no_rows_still_writes_one_header_file(self):
        a = self.w("a.csv", "id,v\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--max-rows-per-file", "3", a])
        self.assertEqual(self.tree(o), ["part-00000.csv"])
        self.assertEqual(self.read(o, "part-00000.csv"), "id,v\n")

    def test_partition_and_shard_combined(self):
        a = self.w("a.csv", "id,c\n" + "".join(
            "%d,%s\n" % (i, "ab"[i % 2]) for i in range(1, 8)))
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "c",
             "--max-rows-per-file", "2", a])
        self.assertEqual(self.tree(o), [
            "c=a/part-00000.csv", "c=a/part-00001.csv",
            "c=b/part-00000.csv", "c=b/part-00001.csv",
        ])
        self.assertEqual(self.read(o, "c=b/part-00000.csv"), "c,id\nb,1\nb,3\n")
        self.assertEqual(self.read(o, "c=b/part-00001.csv"), "c,id\nb,5\nb,7\n")


class TestOutputMode(Base):
    def test_stdout_rejected_with_partitioning(self):
        a = self.w("a.csv", "id,c\n1,x\n")
        for extra in (["--partition-by", "c"], ["--max-rows-per-file", "1"],
                      ["--max-bytes-per-file", "10"]):
            p = run(["--output", "-", "--key", "id"] + extra + [a], False)
            self.assertEqual(p.returncode, 2, extra)
            self.assertTrue(p.stderr.startswith("merge_files.py: error: "))

    def test_no_partition_flags_writes_single_csv(self):
        a = self.w("a.csv", "id\n2\n1\n")
        o = self.out("merged.csv")
        run(["--output", o, "--key", "id", a])
        self.assertTrue(os.path.isfile(o))

    def test_creates_missing_directories(self):
        a = self.w("a.csv", "id,c\n1,x\n")
        o = os.path.join(self.d, "a", "b", "c")
        run(["--output", o, "--key", "id", "--partition-by", "c", a])
        self.assertEqual(self.tree(o), ["c=x/part-00000.csv"])

    def test_trailing_slash_is_accepted(self):
        a = self.w("a.csv", "id,c\n1,x\n")
        o = self.out() + os.sep
        run(["--output", o, "--key", "id", "--partition-by", "c", a])
        self.assertEqual(self.tree(self.out()), ["c=x/part-00000.csv"])

    def test_rerun_replaces_previous_tree(self):
        a = self.w("a.csv", "id,c\n1,x\n")
        b = self.w("b.csv", "id,c\n2,y\n")
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "c", a])
        run(["--output", o, "--key", "id", "--partition-by", "c", b])
        self.assertEqual(self.tree(o), ["c=y/part-00000.csv"])
        self.assertEqual(self.strays(), [])

    def test_output_path_that_is_a_file_is_an_error(self):
        a = self.w("a.csv", "id,c\n1,x\n")
        o = self.w("taken", "hi")
        p = run(["--output", o, "--key", "id", "--partition-by", "c", a], False)
        self.assertEqual(p.returncode, 4)

    def test_failure_leaves_no_output_and_no_temp_dir(self):
        a = self.w("a.csv", "id,n\n1,x\n")
        o = self.out()
        p = run(["--output", o, "--key", "id", "--max-rows-per-file", "1",
                 "--on-type-error", "fail", "--schema",
                 '{"columns":[{"name":"id","type":"int"},'
                 '{"name":"n","type":"int"}]}', a], False)
        self.assertEqual(p.returncode, 1)
        self.assertFalse(os.path.exists(o))
        self.assertEqual(self.strays(), [])

    def test_bad_partition_column(self):
        a = self.w("a.csv", "id\n1\n")
        p = run(["--output", self.out(), "--key", "id",
                 "--partition-by", "nope", a], False)
        self.assertEqual(p.returncode, 3)
        self.assertTrue(p.stderr.startswith("merge_files.py: error: "))

    def test_non_positive_limits_rejected(self):
        a = self.w("a.csv", "id\n1\n")
        for flag in ("--max-rows-per-file", "--max-bytes-per-file"):
            p = run(["--output", self.out(), "--key", "id", flag, "0", a], False)
            self.assertEqual(p.returncode, 2, flag)

    def test_empty_partition_by_rejected(self):
        a = self.w("a.csv", "id\n1\n")
        p = run(["--output", self.out(), "--key", "id",
                 "--partition-by", "", a], False)
        self.assertEqual(p.returncode, 2)


class TestLargeInputs(Base):
    def test_low_memory_partitioned_run_is_complete_and_sorted(self):
        random.seed(11)
        ids = [random.randrange(10 ** 6) for _ in range(20000)]
        a = self.w("a.csv", "id,g,pad\n" + "".join(
            "%d,%s,%s\n" % (v, "abcd"[i % 4], "p" * 20)
            for i, v in enumerate(ids)))
        o = self.out()
        run(["--output", o, "--key", "id", "--partition-by", "g",
             "--max-rows-per-file", "1000", "--memory-limit-mb", "1", a])
        total = 0
        for g in "abcd":
            files = sorted(os.listdir(os.path.join(o, "g=" + g)))
            self.assertEqual(files,
                             ["part-%05d.csv" % i for i in range(len(files))])
            prev = None
            for fn in files:
                body = self.read(o, "g=%s/%s" % (g, fn)).split("\n")
                self.assertEqual(body[0], "g,id,pad")
                data = [r for r in body[1:] if r]
                self.assertTrue(0 < len(data) <= 1000)
                for r in data:
                    cols = r.split(",")
                    self.assertEqual(cols[0], g)
                    v = int(cols[1])
                    if prev is not None:
                        self.assertGreaterEqual(v, prev)
                    prev = v
                    total += 1
        self.assertEqual(total, len(ids))


if __name__ == "__main__":
    unittest.main()
