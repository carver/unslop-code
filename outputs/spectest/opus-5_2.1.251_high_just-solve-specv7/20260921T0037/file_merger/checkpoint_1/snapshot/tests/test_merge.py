"""Spec conformance tests for merge_files.py."""
import json, os, random, shutil, subprocess, sys, tempfile, unittest

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

    def schema(self, cols):
        return self.w("schema.json", json.dumps({"columns": cols}))

    def lines(self, out):
        return out.rstrip("\n").split("\n") if out.strip() else []


class TestBasics(Base):
    def test_single_file_sorted_by_int_key(self):
        a = self.w("a.csv", "id,name\n3,c\n1,a\n2,b\n")
        out = run(["--output", "-", "--key", "id", a]).stdout
        self.assertEqual(out, "id,name\n1,a\n2,b\n3,c\n")

    def test_numeric_not_lexicographic(self):
        a = self.w("a.csv", "id\n10\n9\n100\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id\n9\n10\n100\n")

    def test_union_of_headers_lexicographic_order(self):
        a = self.w("a.csv", "b,a\n1,x\n")
        b = self.w("b.csv", "c,a\n2,y\n")
        out = run(["--output", "-", "--key", "a", a, b]).stdout
        self.assertEqual(self.lines(out)[0], "a,b,c")

    def test_missing_columns_filled_with_null(self):
        a = self.w("a.csv", "a,b\n7,x\n")
        b = self.w("b.csv", "a\n2\n")
        out = run(["--output", "-", "--key", "a", a, b]).stdout
        self.assertEqual(out, "a,b\n2,\n7,x\n")

    def test_output_to_file(self):
        a = self.w("a.csv", "id\n2\n7\n")
        dest = os.path.join(self.d, "out", "merged.csv")
        run(["--output", dest, "--key", "id", a])
        with open(dest, encoding="utf-8", newline="") as fh:
            self.assertEqual(fh.read(), "id\n2\n7\n")

    def test_line_endings_are_lf(self):
        a = self.w("a.csv", "id\n4\n")
        dest = os.path.join(self.d, "m.csv")
        run(["--output", dest, "--key", "id", a])
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"id\n4\n")

    def test_desc_order(self):
        a = self.w("a.csv", "id\n1\n3\n2\n")
        self.assertEqual(run(["--output", "-", "--key", "id", "--desc", a]).stdout,
                         "id\n3\n2\n1\n")

    def test_empty_and_header_only_inputs(self):
        a = self.w("a.csv", "id\n4\n")
        b = self.w("b.csv", "id\n")
        c = self.w("c.csv", "")
        self.assertEqual(run(["--output", "-", "--key", "id", a, b, c]).stdout,
                         "id\n4\n")

    def test_blank_lines_skipped(self):
        a = self.w("a.csv", "id\n4\n\n2\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout, "id\n2\n4\n")

    def test_crlf_tolerated(self):
        a = self.w("a.csv", "id,n\r\n2,b\r\n7,a\r\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id,n\n2,b\n7,a\n")

    def test_bom_stripped(self):
        p = os.path.join(self.d, "bom.csv")
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("id,n\n5,a\n")
        self.assertEqual(run(["--output", "-", "--key", "id", p]).stdout, "id,n\n5,a\n")

    def test_unicode_roundtrip(self):
        a = self.w("a.csv", "id,n\n5,héllo ✓\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id,n\n5,héllo ✓\n")


class TestStability(Base):
    def test_stable_across_files_ascending(self):
        a = self.w("a.csv", "k,v\nx,a1\nx,a2\n")
        b = self.w("b.csv", "k,v\nx,b1\n")
        out = run(["--output", "-", "--key", "k", a, b]).stdout
        self.assertEqual(out, "k,v\nx,a1\nx,a2\nx,b1\n")

    def test_stable_descending(self):
        a = self.w("a.csv", "k,v\nx,a1\nx,a2\n")
        b = self.w("b.csv", "k,v\nx,b1\n")
        out = run(["--output", "-", "--key", "k", "--desc", a, b]).stdout
        self.assertEqual(out, "k,v\nx,a1\nx,a2\nx,b1\n")

    def test_stability_survives_spilling(self):
        rows = "".join("5,%d\n" % i for i in range(3000))
        a = self.w("a.csv", "k,v\n" + rows)
        out = run(["--output", "-", "--key", "k", "--memory-limit-mb", "1", a]).stdout
        vals = [l.split(",")[1] for l in self.lines(out)[1:]]
        self.assertEqual(vals, [str(i) for i in range(3000)])


class TestNulls(Base):
    def test_nulls_first_ascending(self):
        a = self.w("a.csv", "k,v\nb,1\n,2\na,3\n")
        out = run(["--output", "-", "--key", "k", a]).stdout
        self.assertEqual([l.split(",")[0] for l in self.lines(out)[1:]], ["", "a", "b"])

    def test_nulls_last_descending(self):
        a = self.w("a.csv", "k,v\nb,1\n,2\na,3\n")
        out = run(["--output", "-", "--key", "k", "--desc", a]).stdout
        self.assertEqual([l.split(",")[0] for l in self.lines(out)[1:]], ["b", "a", ""])

    def test_null_literal_output(self):
        a = self.w("a.csv", "a,b\n7,\n")
        out = run(["--output", "-", "--key", "a", "--csv-null-literal", "NULL", a]).stdout
        self.assertEqual(out, "a,b\n7,NULL\n")

    def test_null_literal_recognised_on_input(self):
        a = self.w("a.csv", "a,b\n1,NULL\n2,5\n")
        s = self.schema([{"name": "a", "type": "int"}, {"name": "b", "type": "int"}])
        out = run(["--output", "-", "--key", "a", "--schema", s,
                   "--csv-null-literal", "NULL", "--on-type-error", "fail", a]).stdout
        self.assertEqual(out, "a,b\n1,NULL\n2,5\n")

    def test_composite_key_null_in_second_position(self):
        a = self.w("a.csv", "x,y\n1,b\n1,\n0,z\n")
        out = run(["--output", "-", "--key", "x,y", a]).stdout
        # x holds only 0/1 -> bool (priority bool > int); false < true
        self.assertEqual(self.lines(out)[1:], ["false,z", "true,", "true,b"])
        out = run(["--output", "-", "--key", "x,y", "--desc", a]).stdout
        self.assertEqual(self.lines(out)[1:], ["true,b", "true,", "false,z"])


class TestCsvDialect(Base):
    def test_quoted_comma_and_doubled_quotes(self):
        a = self.w("a.csv", 'id,n\n7,"a,b"\n2,"say ""hi"""\n')
        out = run(["--output", "-", "--key", "id", a]).stdout
        self.assertEqual(out, 'id,n\n2,"say ""hi"""\n7,"a,b"\n')

    def test_backslash_escape_accepted_by_default(self):
        a = self.w("a.csv", 'id,n\n5,"a\\"b"\n')
        out = run(["--output", "-", "--key", "id", a]).stdout
        self.assertEqual(out, 'id,n\n5,"a""b"\n')

    def test_plain_backslash_preserved(self):
        a = self.w("a.csv", 'id,n\n5,C:\\temp\n')
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id,n\n5,C:\\temp\n")

    def test_custom_quotechar(self):
        a = self.w("a.csv", "id,n\n5,|a,b|\n")
        out = run(["--output", "-", "--key", "id", "--csv-quotechar", "|", a]).stdout
        self.assertEqual(out, 'id,n\n5,"a,b"\n')

    def test_custom_escapechar(self):
        a = self.w("a.csv", "id,n\n5,~,x\n")
        out = run(["--output", "-", "--key", "id", "--csv-escapechar", "~", a]).stdout
        self.assertEqual(out, 'id,n\n5,",x"\n')

    def test_output_quotes_only_when_needed(self):
        a = self.w("a.csv", 'id,n\n5,"plain"\n')
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id,n\n5,plain\n")

    def test_extra_and_short_rows(self):
        a = self.w("a.csv", "a,b\n7,x,ignored\n2\n")
        self.assertEqual(run(["--output", "-", "--key", "a", a]).stdout,
                         "a,b\n2,\n7,x\n")


class TestInference(Base):
    def _types(self, *files, **kw):
        # round-trip check helper: returns the header + rows
        args = ["--output", "-", "--key", kw.get("key", "v")]
        if "infer" in kw:
            args += ["--infer", kw["infer"]]
        return run(args + list(files)).stdout

    def test_int_column(self):
        a = self.w("a.csv", "v\n2\n10\n")
        self.assertEqual(self._types(a), "v\n2\n10\n")

    def test_float_column(self):
        a = self.w("a.csv", "v\n2.50\n10\n")
        self.assertEqual(self._types(a), "v\n2.5\n10.0\n")

    def test_bool_column(self):
        a = self.w("a.csv", "v\ntrue\n0\n")
        self.assertEqual(self._types(a), "v\nfalse\ntrue\n")

    def test_date_column(self):
        a = self.w("a.csv", "v\n2024-03-02\n2023-01-01\n")
        self.assertEqual(self._types(a), "v\n2023-01-01\n2024-03-02\n")

    def test_timestamp_column_normalised(self):
        a = self.w("a.csv", "v\n2024-07-01T12:00:00+02:00\n2024-07-01T09:00:00Z\n")
        self.assertEqual(self._types(a), "v\n2024-07-01T09:00:00Z\n2024-07-01T10:00:00Z\n")

    def test_string_fallback(self):
        a = self.w("a.csv", "v\n1\nabc\n")
        self.assertEqual(self._types(a), "v\n1\nabc\n")

    def test_strict_conflict_across_files_falls_back_to_string(self):
        a = self.w("a.csv", "v\n1\n")
        b = self.w("b.csv", "v\n1.5\n")
        # strict: int vs float -> string, so lexicographic ordering
        self.assertEqual(self._types(a, b, infer="strict"), "v\n1\n1.5\n")

    def test_loose_unifies_numeric_across_files(self):
        a = self.w("a.csv", "v\n10\n")
        b = self.w("b.csv", "v\n1.5\n")
        self.assertEqual(self._types(a, b, infer="loose"), "v\n1.5\n10.0\n")

    def test_loose_ignores_empty_strings(self):
        a = self.w("a.csv", "k,v\nr1,10\nr2,\nr3,2\n")
        out = run(["--output", "-", "--key", "v", "--infer", "loose", a]).stdout
        self.assertEqual(self.lines(out)[1:], ["r2,", "r3,2", "r1,10"])

    def test_loose_string_fallback_on_unparsable(self):
        a = self.w("a.csv", "v\n10\nxyz\n")
        self.assertEqual(self._types(a, infer="loose"), "v\n10\nxyz\n")

    def test_zero_one_column_is_bool_by_priority(self):
        # Type priority puts bool above int, and bool accepts 1/0.
        a = self.w("a.csv", "k,v\nr1,1\nr2,0\n")
        out = run(["--output", "-", "--key", "k", a]).stdout
        self.assertEqual(out, "k,v\nr1,true\nr2,false\n")

    def test_int_wins_when_not_only_zero_one(self):
        a = self.w("a.csv", "k,v\nr1,1\nr2,2\n")
        self.assertEqual(run(["--output", "-", "--key", "k", a]).stdout,
                         "k,v\nr1,1\nr2,2\n")

    def test_date_not_swallowed_by_timestamp(self):
        a = self.w("a.csv", "k,v\nr1,2024-01-02\n")
        self.assertEqual(run(["--output", "-", "--key", "k", a]).stdout,
                         "k,v\nr1,2024-01-02\n")

    def test_strict_empty_value_forces_string(self):
        a = self.w("a.csv", "k,v\nr1,10\nr2,\nr3,2\n")
        out = run(["--output", "-", "--key", "v", a]).stdout
        # strict counts the empty cell as an observed value -> string column,
        # so ordering is lexicographic with the null first.
        self.assertEqual(self.lines(out)[1:], ["r2,", "r1,10", "r3,2"])

    def test_all_null_column_is_string(self):
        a = self.w("a.csv", "k,v\n7,\n")
        self.assertEqual(run(["--output", "-", "--key", "k", a]).stdout, "k,v\n7,\n")


class TestSchema(Base):
    def test_schema_column_order_and_projection(self):
        a = self.w("a.csv", "note,id,extra\nx,2,drop\ny,1,drop\n")
        s = self.schema([{"name": "id", "type": "int"},
                         {"name": "missing", "type": "string"},
                         {"name": "note", "type": "string"}])
        out = run(["--output", "-", "--key", "id", "--schema", s, a]).stdout
        self.assertEqual(out, "id,missing,note\n1,,y\n2,,x\n")

    def test_inline_schema_json(self):
        a = self.w("a.csv", "id\n2\n1\n")
        s = json.dumps({"columns": [{"name": "id", "type": "int"}]})
        self.assertEqual(run(["--output", "-", "--key", "id", "--schema", s, a]).stdout,
                         "id\n1\n2\n")

    def test_all_types_cast(self):
        a = self.w("a.csv", "i,f,b,d,t,s\n7,1.50,1,2024-01-02,2024-07-01T12:00:00+02:00,hey\n")
        s = self.schema([{"name": "i", "type": "int"}, {"name": "f", "type": "float"},
                         {"name": "b", "type": "bool"}, {"name": "d", "type": "date"},
                         {"name": "t", "type": "timestamp"}, {"name": "s", "type": "string"}])
        out = run(["--output", "-", "--key", "i", "--schema", s, a]).stdout
        self.assertEqual(out.split("\n")[1], "7,1.5,true,2024-01-02,2024-07-01T10:00:00Z,hey")

    def test_timestamp_without_zone_is_utc(self):
        a = self.w("a.csv", "t\n2024-07-01T12:00:00\n")
        s = self.schema([{"name": "t", "type": "timestamp"}])
        self.assertEqual(run(["--output", "-", "--key", "t", "--schema", s, a]).stdout,
                         "t\n2024-07-01T12:00:00Z\n")

    def test_fractional_seconds_kept(self):
        a = self.w("a.csv", "t\n2024-07-01T12:00:00.123456-05:30\n")
        s = self.schema([{"name": "t", "type": "timestamp"}])
        self.assertEqual(run(["--output", "-", "--key", "t", "--schema", s, a]).stdout,
                         "t\n2024-07-01T17:30:00.123456Z\n")

    def test_fractional_seconds_sort_correctly(self):
        a = self.w("a.csv", "t\n2024-07-01T12:00:00.5Z\n2024-07-01T12:00:00Z\n"
                            "2024-07-01T12:00:00.25Z\n")
        s = self.schema([{"name": "t", "type": "timestamp"}])
        out = run(["--output", "-", "--key", "t", "--schema", s, a]).stdout
        self.assertEqual(self.lines(out)[1:], ["2024-07-01T12:00:00Z",
                                               "2024-07-01T12:00:00.25Z",
                                               "2024-07-01T12:00:00.5Z"])

    def test_bad_type_rejected(self):
        a = self.w("a.csv", "id\n1\n")
        s = self.schema([{"name": "id", "type": "integer"}])
        p = run(["--output", "-", "--key", "id", "--schema", s, a], expect_ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("integer", p.stderr)

    def test_key_not_in_schema_is_error(self):
        a = self.w("a.csv", "id\n1\n")
        s = self.schema([{"name": "id", "type": "int"}])
        p = run(["--output", "-", "--key", "nope", "--schema", s, a], expect_ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(p.stderr.strip())

    def test_key_not_in_inferred_schema_is_error(self):
        a = self.w("a.csv", "id\n1\n")
        p = run(["--output", "-", "--key", "zz", a], expect_ok=False)
        self.assertNotEqual(p.returncode, 0)


class TestTypeErrors(Base):
    def setUp(self):
        super().setUp()
        self.a = self.w("a.csv", "id,n\n1,oops\n2,5\n")
        self.s = self.schema([{"name": "id", "type": "int"},
                              {"name": "n", "type": "int"}])

    def test_coerce_null_is_default(self):
        self.assertEqual(run(["--output", "-", "--key", "id", "--schema", self.s,
                              self.a]).stdout, "id,n\n1,\n2,5\n")

    def test_keep_string(self):
        self.assertEqual(run(["--output", "-", "--key", "id", "--schema", self.s,
                              "--on-type-error", "keep-string", self.a]).stdout,
                         "id,n\n1,oops\n2,5\n")

    def test_fail(self):
        p = run(["--output", "-", "--key", "id", "--schema", self.s,
                 "--on-type-error", "fail", self.a], expect_ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("oops", p.stderr)

    def test_keep_string_key_column_sorts(self):
        a = self.w("k.csv", "k\n5\nzz\n1\n")
        s = self.schema([{"name": "k", "type": "int"}])
        out = run(["--output", "-", "--key", "k", "--schema", s,
                   "--on-type-error", "keep-string", a]).stdout
        self.assertEqual(self.lines(out)[1:], ["1", "5", "zz"])

    def test_fail_cleans_up_temp_dir(self):
        td = os.path.join(self.d, "tmp")
        os.makedirs(td)
        run(["--output", "-", "--key", "id", "--schema", self.s, "--temp-dir", td,
             "--on-type-error", "fail", self.a], expect_ok=False)
        self.assertEqual(os.listdir(td), [])


class TestExternalSort(Base):
    def test_many_runs_multi_pass_merge(self):
        random.seed(11)
        n = 20000
        rows = [(random.randint(0, 500), i) for i in range(n)]
        self.w("a.csv", "k,v\n" + "".join("%d,%d\n" % r for r in rows))
        td = os.path.join(self.d, "spill")
        out = run(["--output", "-", "--key", "k", "--memory-limit-mb", "1",
                   "--temp-dir", td, os.path.join(self.d, "a.csv")]).stdout
        got = [tuple(map(int, l.split(","))) for l in self.lines(out)[1:]]
        exp = sorted(rows, key=lambda r: (r[0], r[1]))
        self.assertEqual(got, exp)
        self.assertEqual(os.listdir(td), [])

    def test_temp_dir_created_if_absent(self):
        a = self.w("a.csv", "id\n1\n")
        td = os.path.join(self.d, "new", "spill")
        run(["--output", "-", "--key", "id", "--temp-dir", td, a])
        self.assertTrue(os.path.isdir(td))
        self.assertEqual(os.listdir(td), [])

    def test_randomised_against_reference(self):
        random.seed(5)
        vals = ["", "3", "1", "20", "b", "a", "", "10"]
        files, rows = [], []
        for fi in range(3):
            body = []
            for _ in range(400):
                k1 = random.choice(vals)
                k2 = random.choice(["x", "y", ""])
                body.append((k1, k2))
            rows.extend(body)
            files.append(self.w("f%d.csv" % fi, "k1,k2\n" +
                                "".join("%s,%s\n" % r for r in body)))
        for desc in (False, True):
            args = ["--output", "-", "--key", "k1,k2", "--memory-limit-mb", "1"]
            if desc:
                args.append("--desc")
            out = run(args + files).stdout
            got = [tuple(l.split(",")) for l in self.lines(out)[1:]]
            # k1 mixes ints and strings -> string type; nulls first/last
            def sk(item):
                r, i = item
                parts = []
                for v in r:
                    parts.append((0, "") if v == "" else (1, v))
                return parts
            idx = list(range(len(rows)))
            keyed = sorted(zip(rows, idx),
                           key=lambda p: (sk(p), -p[1] if desc else p[1]),
                           reverse=desc)
            exp = [r for r, _ in keyed]
            self.assertEqual(got, exp, "desc=%s" % desc)


class TestMisc(Base):
    def test_missing_input_file(self):
        p = run(["--output", "-", "--key", "id", os.path.join(self.d, "nope.csv")],
                expect_ok=False)
        self.assertNotEqual(p.returncode, 0)

    def test_composite_key_desc(self):
        a = self.w("a.csv", "ts,id\n2024-01-01,2\n2024-01-01,5\n2023-01-01,9\n")
        # inferred header order is lexicographic: id,ts
        out = run(["--output", "-", "--key", "ts,id", "--desc", a]).stdout
        self.assertEqual(self.lines(out)[1:],
                         ["5,2024-01-01", "2,2024-01-01", "9,2023-01-01"])

    def test_duplicate_header_column_uses_first(self):
        a = self.w("a.csv", "id,id\n7,2\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout, "id\n7\n")

    def test_negative_and_exponent_numbers(self):
        a = self.w("a.csv", "v\n-5\n3\n-10\n")
        self.assertEqual(run(["--output", "-", "--key", "v", a]).stdout,
                         "v\n-10\n-5\n3\n")

    def test_help(self):
        p = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True,
                           text=True)
        self.assertEqual(p.returncode, 0)
        for flag in ("--output", "--key", "--desc", "--schema", "--infer",
                     "--on-type-error", "--memory-limit-mb", "--temp-dir",
                     "--csv-quotechar", "--csv-escapechar", "--csv-null-literal"):
            self.assertIn(flag, p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
