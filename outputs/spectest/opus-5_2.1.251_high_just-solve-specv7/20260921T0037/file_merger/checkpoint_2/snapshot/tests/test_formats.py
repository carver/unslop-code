"""Conformance tests for the multi-format (checkpoint 2) behaviour."""
import datetime, decimal, gzip, json, os, shutil, subprocess, sys, tempfile, unittest

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "merge_files.py")

EXIT_TYPE, EXIT_USAGE, EXIT_KEY, EXIT_IO, EXIT_DIALECT, EXIT_NESTED = 1, 2, 3, 4, 5, 6


def run(args, expect=0):
    p = subprocess.run([sys.executable, SCRIPT] + args, capture_output=True, text=True)
    if expect is not None and p.returncode != expect:
        raise AssertionError("exit %d (wanted %d)\nSTDERR: %s"
                             % (p.returncode, expect, p.stderr))
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def p(self, name):
        return os.path.join(self.d, name)

    def w(self, name, text):
        with open(self.p(name), "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return self.p(name)

    def wgz(self, name, text):
        with gzip.open(self.p(name), "wt", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return self.p(name)

    def wraw(self, name, data):
        with open(self.p(name), "wb") as fh:
            fh.write(data)
        return self.p(name)

    def wpq(self, name, table, **kw):
        pq.write_table(table, self.p(name), **kw)
        return self.p(name)

    def jsonl(self, name, objs):
        return self.w(name, "".join(json.dumps(o) + "\n" for o in objs))

    def lines(self, out):
        return out.rstrip("\n").split("\n") if out.strip() else []


# ---------------------------------------------------------------- detection

class TestDetection(Base):
    def test_extension_dispatch(self):
        c = self.w("a.csv", "id,src\n1,csv\n")
        t = self.w("b.tsv", "id\tsrc\n2\ttsv\n")
        j = self.jsonl("c.jsonl", [{"id": 3, "src": "jsonl"}])
        n = self.jsonl("d.ndjson", [{"id": 4, "src": "ndjson"}])
        q = self.wpq("e.parquet", pa.table({"id": pa.array([5]),
                                            "src": pa.array(["parquet"])}))
        out = run(["--output", "-", "--key", "id", c, t, j, n, q]).stdout
        self.assertEqual(self.lines(out),
                         ["id,src", "1,csv", "2,tsv", "3,jsonl", "4,ndjson",
                          "5,parquet"])

    def test_gz_suffix_after_base_extension(self):
        a = self.wgz("a.csv.gz", "id\n2\n")
        b = self.wgz("b.jsonl.gz", '{"id": 1}\n')
        c = self.wgz("c.tsv.gz", "id\n3\n")
        out = run(["--output", "-", "--key", "id", a, b, c]).stdout
        self.assertEqual(out, "id\n1\n2\n3\n")

    def test_gzipped_parquet(self):
        raw = self.wpq("x.parquet", pa.table({"id": pa.array([2, 1])}))
        with open(raw, "rb") as fh:
            data = fh.read()
        self.wraw("x.parquet.gz", gzip.compress(data))
        self.assertEqual(run(["--output", "-", "--key", "id",
                              self.p("x.parquet.gz")]).stdout, "id\n1\n2\n")

    def test_ambiguous_extension_with_parquet_magic(self):
        tbl = pa.table({"id": pa.array([9, 8])})
        pq.write_table(tbl, self.p("anon"))
        self.assertEqual(run(["--output", "-", "--key", "id", self.p("anon")]).stdout,
                         "id\n8\n9\n")

    def test_ambiguous_extension_without_magic_is_error_2(self):
        a = self.w("a.dat", "id\n1\n")
        p = run(["--output", "-", "--key", "id", a], expect=EXIT_USAGE)
        self.assertTrue(p.stderr.startswith("merge_files.py: error: "))

    def test_no_extension_text_is_error_2(self):
        a = self.w("plainfile", "id\n1\n")
        run(["--output", "-", "--key", "id", a], expect=EXIT_USAGE)

    def test_forced_input_format_overrides_extension(self):
        a = self.w("rows.txt", '{"id": 2}\n{"id": 1}\n')
        self.assertEqual(run(["--output", "-", "--key", "id",
                              "--input-format", "jsonl", a]).stdout, "id\n1\n2\n")

    def test_forced_format_applies_to_every_input(self):
        a = self.w("a.dat", "id\tn\n2\tb\n")
        b = self.w("b.dat", "id\tn\n1\ta\n")
        self.assertEqual(run(["--output", "-", "--key", "id",
                              "--input-format", "tsv", a, b]).stdout,
                         "id,n\n1,a\n2,b\n")


class TestCompression(Base):
    def test_auto_detects_gzip(self):
        a = self.wgz("a.csv.gz", "id\n5\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout, "id\n5\n")

    def test_forced_gzip(self):
        a = self.wgz("a.csv.gz", "id\n5\n")
        self.assertEqual(run(["--output", "-", "--key", "id",
                              "--compression", "gzip", a]).stdout, "id\n5\n")

    def test_forced_none_on_plain_file_named_gz(self):
        a = self.w("a.csv.gz", "id\n5\n")
        self.assertEqual(run(["--output", "-", "--key", "id",
                              "--compression", "none", a]).stdout, "id\n5\n")

    def test_gz_extension_but_not_gzipped_is_error_5(self):
        a = self.w("a.csv.gz", "id\n5\n")
        run(["--output", "-", "--key", "id", a], expect=EXIT_DIALECT)

    def test_forced_gzip_on_plain_file_is_error_5(self):
        a = self.w("a.csv", "id\n5\n")
        run(["--output", "-", "--key", "id", "--compression", "gzip", a],
            expect=EXIT_DIALECT)

    def test_forced_none_on_gzip_file_is_error_5(self):
        a = self.wgz("a.csv.gz", "id\n5\n")
        run(["--output", "-", "--key", "id", "--compression", "none", a],
            expect=EXIT_DIALECT)


# --------------------------------------------------------------------- tsv

class TestTsv(Base):
    def test_basic(self):
        a = self.w("a.tsv", "id\tname\n3\tc\n1\ta\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id,name\n1,a\n3,c\n")

    def test_crlf(self):
        self.wraw("a.tsv", b"id\tn\r\n2\tb\r\n1\ta\r\n")
        self.assertEqual(run(["--output", "-", "--key", "id", self.p("a.tsv")]).stdout,
                         "id,n\n1,a\n2,b\n")

    def test_no_quoting_quotes_are_literal(self):
        a = self.w("a.tsv", 'id\tn\n4\t"x y"\n')
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         'id,n\n4,"""x y"""\n')

    def test_comma_in_field_is_quoted_on_output(self):
        a = self.w("a.tsv", "id\tn\n4\ta,b\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         'id,n\n4,"a,b"\n')

    def test_extra_tab_is_error_5(self):
        a = self.w("a.tsv", "a\tb\n1\t2\t3\n")
        p = run(["--output", "-", "--key", "a", a], expect=EXIT_DIALECT)
        self.assertIn("a.tsv", p.stderr)

    def test_missing_header_is_error_5(self):
        a = self.w("a.tsv", "")
        run(["--output", "-", "--key", "a", a], expect=EXIT_DIALECT)

    def test_short_row_padded_with_nulls(self):
        a = self.w("a.tsv", "id\tn\tz\n5\tq\n")
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id,n,z\n5,q,\n")

    def test_empty_field_is_null(self):
        a = self.w("a.tsv", "id\tn\n5\t\n")
        self.assertEqual(run(["--output", "-", "--key", "id",
                              "--csv-null-literal", "NULL", a]).stdout,
                         "id,n\n5,NULL\n")


# ------------------------------------------------------------------- jsonl

class TestJsonl(Base):
    def test_typed_values(self):
        a = self.jsonl("a.jsonl", [{"id": 2, "ok": True, "x": 1.5},
                                   {"id": 1, "ok": False, "x": 2.25}])
        self.assertEqual(self.lines(run(["--output", "-", "--key", "id", a]).stdout),
                         ["id,ok,x", "1,false,2.25", "2,true,1.5"])

    def test_blank_lines_ignored(self):
        a = self.w("a.jsonl", '{"id": 2}\n\n   \n{"id": 1}\n')
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout, "id\n1\n2\n")

    def test_null_is_missing(self):
        a = self.jsonl("a.jsonl", [{"id": 7, "v": None}])
        self.assertEqual(run(["--output", "-", "--key", "id",
                              "--csv-null-literal", "NULL", a]).stdout,
                         "id,v\n7,NULL\n")

    def test_missing_key_filled_with_null(self):
        a = self.jsonl("a.jsonl", [{"id": 1}, {"id": 2, "v": "x"}])
        self.assertEqual(self.lines(run(["--output", "-", "--key", "id", a]).stdout),
                         ["id,v", "1,", "2,x"])

    def test_union_of_keys_lexicographic(self):
        a = self.jsonl("a.jsonl", [{"b": 1, "a": 2}])
        b = self.jsonl("b.jsonl", [{"c": 3, "a": 4}])
        out = run(["--output", "-", "--key", "a", a, b]).stdout
        self.assertEqual(self.lines(out)[0], "a,b,c")

    def test_keys_are_case_sensitive(self):
        a = self.jsonl("a.jsonl", [{"Id": 4, "id": 2}])
        out = run(["--output", "-", "--key", "id", a]).stdout
        self.assertEqual(self.lines(out), ["Id,id", "4,2"])

    def test_integer_preferred_for_integral_numbers(self):
        a = self.jsonl("a.jsonl", [{"k": 1, "v": 8.0}, {"k": 2, "v": 3}])
        self.assertEqual(self.lines(run(["--output", "-", "--key", "k", a]).stdout),
                         ["k,v", "1,8", "2,3"])

    def test_float_when_not_integral(self):
        a = self.jsonl("a.jsonl", [{"k": 1, "v": 8.0}, {"k": 2, "v": 3.5}])
        self.assertEqual(self.lines(run(["--output", "-", "--key", "k", a]).stdout),
                         ["k,v", "1,8.0", "2,3.5"])

    def test_nested_object_value_is_error_6(self):
        a = self.w("a.jsonl", '{"a": 1, "b": {"c": 2}}\n')
        p = run(["--output", "-", "--key", "a", a], expect=EXIT_NESTED)
        self.assertIn("a.jsonl", p.stderr)

    def test_nested_array_value_is_error_6(self):
        a = self.w("a.jsonl", '{"a": 1, "b": [1, 2]}\n')
        run(["--output", "-", "--key", "a", a], expect=EXIT_NESTED)

    def test_top_level_array_is_error_6(self):
        a = self.w("a.jsonl", "[1, 2]\n")
        run(["--output", "-", "--key", "a", a], expect=EXIT_NESTED)

    def test_invalid_json_is_error_5(self):
        a = self.w("a.jsonl", '{"a": \n')
        run(["--output", "-", "--key", "a", a], expect=EXIT_DIALECT)

    def test_scalar_record_is_error_5(self):
        a = self.w("a.jsonl", "42\n")
        run(["--output", "-", "--key", "a", a], expect=EXIT_DIALECT)

    def test_gzipped(self):
        a = self.wgz("a.jsonl.gz", '{"id": 2}\n{"id": 1}\n')
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id\n1\n2\n")

    def test_unicode(self):
        a = self.jsonl("a.jsonl", [{"id": 5, "n": "héllo ✓"}])
        self.assertEqual(run(["--output", "-", "--key", "id", a]).stdout,
                         "id,n\n5,héllo ✓\n")


# ----------------------------------------------------------------- parquet

class TestParquet(Base):
    def test_typed_columns_render(self):
        tbl = pa.table({
            "i": pa.array([7, 8], pa.int32()),
            "f": pa.array([1.5, 2.0], pa.float64()),
            "b": pa.array([True, False]),
            "s": pa.array(["hi", None]),
            "d": pa.array([datetime.date(2024, 5, 1), None], pa.date32()),
            "t": pa.array([datetime.datetime(2024, 5, 1, 12, 30, 0, 500000),
                           datetime.datetime(2024, 1, 1)],
                          pa.timestamp("us", tz="UTC")),
        })
        a = self.wpq("a.parquet", tbl)
        out = run(["--output", "-", "--key", "i", a]).stdout
        self.assertEqual(self.lines(out), [
            "b,d,f,i,s,t",
            "true,2024-05-01,1.5,7,hi,2024-05-01T12:30:00.5Z",
            "false,,2.0,8,,2024-01-01T00:00:00Z",
        ])

    def test_timezone_normalised_to_utc(self):
        tz = datetime.timezone(datetime.timedelta(hours=2))
        tbl = pa.table({"t": pa.array(
            [datetime.datetime(2024, 7, 1, 12, 0, 0, tzinfo=tz)],
            pa.timestamp("s", tz="+02:00"))})
        a = self.wpq("a.parquet", tbl)
        self.assertEqual(run(["--output", "-", "--key", "t", a]).stdout,
                         "t\n2024-07-01T10:00:00Z\n")

    def test_decimal_column(self):
        tbl = pa.table({"d": pa.array([decimal.Decimal("1.50")],
                                      pa.decimal128(9, 2))})
        a = self.wpq("a.parquet", tbl)
        self.assertEqual(run(["--output", "-", "--key", "d", a]).stdout, "d\n1.5\n")

    def test_null_becomes_null_literal(self):
        tbl = pa.table({"i": pa.array([1]), "v": pa.array([None], pa.int64())})
        a = self.wpq("a.parquet", tbl)
        self.assertEqual(run(["--output", "-", "--key", "i",
                              "--csv-null-literal", "NULL", a]).stdout,
                         "i,v\n1,NULL\n")

    def test_list_column_is_error_6(self):
        tbl = pa.table({"id": pa.array([1]), "xs": pa.array([[1, 2]])})
        a = self.wpq("a.parquet", tbl)
        p = run(["--output", "-", "--key", "id", a], expect=EXIT_NESTED)
        self.assertIn("xs", p.stderr)

    def test_struct_column_is_error_6(self):
        tbl = pa.table({"id": pa.array([1]), "s": pa.array([{"x": 1}])})
        a = self.wpq("a.parquet", tbl)
        run(["--output", "-", "--key", "id", a], expect=EXIT_NESTED)

    def test_map_column_is_error_6(self):
        tbl = pa.table({"id": pa.array([1]),
                        "m": pa.array([[("k", 1)]], pa.map_(pa.string(), pa.int64()))})
        a = self.wpq("a.parquet", tbl)
        run(["--output", "-", "--key", "id", a], expect=EXIT_NESTED)

    def test_dictionary_column_is_flat(self):
        tbl = pa.table({"id": pa.array([2, 1]),
                        "c": pa.array(["x", "y"]).dictionary_encode()})
        a = self.wpq("a.parquet", tbl)
        self.assertEqual(self.lines(run(["--output", "-", "--key", "id", a]).stdout),
                         ["c,id", "y,1", "x,2"])

    def test_row_group_streaming_preserves_order(self):
        n = 5000
        tbl = pa.table({"id": pa.array(list(range(n))),
                        "v": pa.array([str(i) for i in range(n)])})
        a = self.wpq("a.parquet", tbl, row_group_size=137)
        out = run(["--output", "-", "--key", "id", "--desc",
                   "--parquet-row-group-bytes", "4096",
                   "--memory-limit-mb", "64", a]).stdout
        rows = self.lines(out)[1:]
        self.assertEqual(len(rows), n)
        self.assertEqual(rows[0], "%d,%d" % (n - 1, n - 1))
        self.assertEqual(rows[-1], "0,0")

    def test_not_a_parquet_file_is_error_5(self):
        a = self.w("a.parquet", "not parquet at all\n")
        run(["--output", "-", "--key", "id", a], expect=EXIT_DIALECT)


# ------------------------------------------------------- schema strategies

class TestSchemaStrategies(Base):
    def _mixed(self):
        # two CSVs say int, one Parquet says double
        a = self.w("a.csv", "k,v\n1,10\n")
        b = self.w("b.csv", "k,v\n2,20\n")
        c = self.wpq("c.parquet", pa.table({"k": pa.array([3]),
                                            "v": pa.array([1.5], pa.float64())}))
        return [a, b, c]

    def test_authoritative_prefers_parquet(self):
        out = run(["--output", "-", "--key", "k"] + self._mixed()).stdout
        self.assertEqual(self.lines(out), ["k,v", "1,10.0", "2,20.0", "3,1.5"])

    def test_consensus_follows_the_majority(self):
        out = run(["--output", "-", "--key", "k", "--schema-strategy", "consensus"]
                  + self._mixed()).stdout
        # int wins 2-1; the double that will not fit is coerced to null
        self.assertEqual(self.lines(out), ["k,v", "1,10", "2,20", "3,"])

    def test_union_picks_simplest_common_type(self):
        out = run(["--output", "-", "--key", "k", "--schema-strategy", "union"]
                  + self._mixed()).stdout
        self.assertEqual(self.lines(out), ["k,v", "1,10.0", "2,20.0", "3,1.5"])

    def test_jsonl_ranks_equal_to_csv(self):
        # JSONL says int, CSV says float; equal rank + strict disagreement
        # collapses to string, so both texts pass through unchanged.
        a = self.jsonl("a.jsonl", [{"k": 1, "v": 3}])
        b = self.w("b.csv", "k,v\n2,4.5\n")
        out = run(["--output", "-", "--key", "k", a, b]).stdout
        self.assertEqual(self.lines(out), ["k,v", "1,3", "2,4.5"])

    def test_authoritative_parquet_string_beats_csv_number(self):
        a = self.wpq("a.parquet", pa.table({"k": pa.array([1]),
                                            "v": pa.array(["7"])}))
        b = self.w("b.csv", "k,v\n2,9\n")
        out = run(["--output", "-", "--key", "v", a, b]).stdout
        # v is a declared Parquet string -> lexicographic, not numeric
        self.assertEqual(self.lines(out), ["k,v", "1,7", "2,9"])

    def test_union_across_three_formats(self):
        a = self.w("a.csv", "k,v\n1,1\n")
        b = self.w("b.tsv", "k\tv\n2\t2.5\n")
        c = self.jsonl("c.jsonl", [{"k": 3, "v": 4}])
        out = run(["--output", "-", "--key", "k", "--schema-strategy", "union",
                   a, b, c]).stdout
        self.assertEqual(self.lines(out), ["k,v", "1,1.0", "2,2.5", "3,4.0"])

    def test_consensus_with_loose_inference(self):
        a = self.w("a.csv", "k,v\n1,10\n")
        b = self.w("b.csv", "k,v\n2,\n")
        out = run(["--output", "-", "--key", "k", "--infer", "loose",
                   "--schema-strategy", "consensus", a, b]).stdout
        self.assertEqual(self.lines(out), ["k,v", "1,10", "2,"])


# ------------------------------------------------------------- mixed input

class TestMixedInputs(Base):
    def _three(self):
        c = self.w("users.csv", "id,ts,name\n2,2024-01-02T00:00:00Z,bob\n")
        j = self.wgz("events.jsonl.gz",
                     '{"id": 3, "ts": "2024-01-03T00:00:00Z", "kind": "click"}\n')
        q = self.wpq("metrics.parquet",
                     pa.table({"id": pa.array([1]),
                               "ts": pa.array(["2024-01-01T00:00:00Z"]),
                               "score": pa.array([1.5])}))
        return c, j, q

    def test_composite_key_across_formats(self):
        out = run(["--output", "-", "--key", "ts,id",
                   "--schema-strategy", "consensus"] + list(self._three())).stdout
        self.assertEqual(self.lines(out), [
            "id,kind,name,score,ts",
            "1,,,1.5,2024-01-01T00:00:00Z",
            "2,,bob,,2024-01-02T00:00:00Z",
            "3,click,,,2024-01-03T00:00:00Z",
        ])

    def test_every_row_appears_exactly_once(self):
        a = self.w("a.csv", "k\nx\nx\n")
        b = self.jsonl("b.jsonl", [{"k": "x"}, {"k": "x"}])
        c = self.wpq("c.parquet", pa.table({"k": pa.array(["x", "x"])}))
        out = run(["--output", "-", "--key", "k", a, b, c]).stdout
        self.assertEqual(len(self.lines(out)) - 1, 6)

    def test_stability_across_formats(self):
        a = self.w("a.csv", "k,v\n1,csv1\n1,csv2\n")
        b = self.jsonl("b.jsonl", [{"k": 1, "v": "json1"}])
        c = self.wpq("c.parquet", pa.table({"k": pa.array([1]),
                                            "v": pa.array(["pq1"])}))
        for extra in ([], ["--desc"]):
            out = run(["--output", "-", "--key", "k"] + extra + [a, b, c]).stdout
            self.assertEqual([l.split(",")[1] for l in self.lines(out)[1:]],
                             ["csv1", "csv2", "json1", "pq1"])

    def test_provided_schema_projects_every_format(self):
        c, j, q = self._three()
        schema = json.dumps({"columns": [{"name": "ts", "type": "timestamp"},
                                         {"name": "id", "type": "int"},
                                         {"name": "absent", "type": "string"}]})
        out = run(["--output", "-", "--key", "ts,id", "--desc",
                   "--schema", schema, c, j, q]).stdout
        self.assertEqual(self.lines(out), [
            "ts,id,absent",
            "2024-01-03T00:00:00Z,3,",
            "2024-01-02T00:00:00Z,2,",
            "2024-01-01T00:00:00Z,1,",
        ])

    def test_key_absent_from_resolved_schema_is_error_3(self):
        c, j, q = self._three()
        run(["--output", "-", "--key", "nope", c, j, q], expect=EXIT_KEY)

    def test_spilling_with_mixed_sources(self):
        n = 2000
        self.w("a.csv", "k,v\n" + "".join("%d,a%d\n" % (i % 7, i) for i in range(n)))
        self.jsonl("b.jsonl", [{"k": i % 7, "v": "b%d" % i} for i in range(n)])
        self.wpq("c.parquet", pa.table({"k": pa.array([i % 7 for i in range(n)]),
                                        "v": pa.array(["c%d" % i for i in range(n)])}),
                 row_group_size=97)
        td = self.p("spill")
        out = run(["--output", "-", "--key", "k", "--memory-limit-mb", "1",
                   "--temp-dir", td, self.p("a.csv"), self.p("b.jsonl"),
                   self.p("c.parquet")]).stdout
        rows = [l.split(",") for l in self.lines(out)[1:]]
        self.assertEqual(len(rows), 3 * n)
        self.assertEqual([r[0] for r in rows], sorted(r[0] for r in rows))
        expected = ([("a%d" % i) for i in range(n)] + ["b%d" % i for i in range(n)]
                    + ["c%d" % i for i in range(n)])
        for bucket in range(7):
            got = [r[1] for r in rows if r[0] == str(bucket)]
            want = [v for v in expected if int(v[1:]) % 7 == bucket]
            self.assertEqual(got, want)
        self.assertEqual(os.listdir(td), [])


class TestOutput(Base):
    def test_atomic_write_leaves_no_partial_file(self):
        a = self.w("a.csv", "id,n\n1,oops\n")
        schema = json.dumps({"columns": [{"name": "id", "type": "int"},
                                         {"name": "n", "type": "int"}]})
        dest = self.p("out.csv")
        run(["--output", dest, "--key", "id", "--schema", schema,
             "--on-type-error", "fail", a], expect=EXIT_TYPE)
        self.assertFalse(os.path.exists(dest))
        self.assertEqual([f for f in os.listdir(self.d) if f.startswith(".merge")], [])

    def test_atomic_replace_of_existing_output(self):
        a = self.w("a.csv", "id\n6\n")
        dest = self.w("out.csv", "stale\n")
        run(["--output", dest, "--key", "id", a])
        with open(dest, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "id\n6\n")

    def test_null_literal_used_for_every_source(self):
        a = self.w("a.csv", "id,v\n1,\n")
        b = self.jsonl("b.jsonl", [{"id": 2, "v": None}])
        c = self.wpq("c.parquet", pa.table({"id": pa.array([3]),
                                            "v": pa.array([None], pa.string())}))
        out = run(["--output", "-", "--key", "id", "--csv-null-literal", "NA",
                   a, b, c]).stdout
        self.assertEqual(self.lines(out), ["id,v", "1,NA", "2,NA", "3,NA"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
