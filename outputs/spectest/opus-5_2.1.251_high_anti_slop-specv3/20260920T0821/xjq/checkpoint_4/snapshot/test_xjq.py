"""End-to-end tests for the xjq.py CLI, driven through a subprocess."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("xjq.py")

CATALOG = (
    '<catalog><book id="1"><title>  The   Great\n Book </title>tail</book>'
    '<book id="2"><title>Second</title></book></catalog>'
)


def run_xjq(query: str, document: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), query, *extra],
        input=document,
        capture_output=True,
        text=True,
    )


class TextResultTests(unittest.TestCase):
    def test_text_nodes_are_normalized_and_newline_joined(self):
        result = run_xjq("//title/text()", CATALOG)
        self.assertEqual(result.stdout, "The Great Book\nSecond")
        self.assertEqual(result.returncode, 0)

    def test_attributes_are_listed(self):
        self.assertEqual(run_xjq("//book/@id", CATALOG).stdout, "1\n2")

    def test_scalar_results(self):
        self.assertEqual(run_xjq("count(//book)", CATALOG).stdout, "2")
        self.assertEqual(run_xjq("boolean(//book)", CATALOG).stdout, "true")
        self.assertEqual(run_xjq("string(//title)", CATALOG).stdout, "The Great Book")

    def test_element_matching_is_case_sensitive(self):
        self.assertEqual(run_xjq("//TITLE/text()", CATALOG).stdout, "")
        self.assertEqual(run_xjq("//Body/text()", "<Html><Body>hi</Body></Html>").stdout, "hi")


class NodeResultTests(unittest.TestCase):
    def test_matched_element_is_pretty_printed(self):
        result = run_xjq('//book[@id="2"]', CATALOG)
        self.assertEqual(result.stdout, '<book id="2">\n  <title>Second</title>\n</book>')

    def test_only_the_first_element_is_printed(self):
        self.assertEqual(run_xjq("//book", CATALOG).stdout.count("<book"), 1)


class NoMatchTests(unittest.TestCase):
    def test_no_match_is_silent_and_successful(self):
        result = run_xjq("//missing", CATALOG)
        self.assertEqual((result.stdout, result.stderr, result.returncode), ("", "", 0))


class ErrorTests(unittest.TestCase):
    def test_invalid_xpath_reports_xpath_and_fails(self):
        result = run_xjq("//[nope", CATALOG)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("xpath", result.stderr.lower())

    def test_malformed_xml_reports_parse_failure(self):
        result = run_xjq("//a", "<a><b></a>")
        self.assertEqual(result.returncode, 1)
        self.assertIn("xml", result.stderr.lower())

    def test_empty_input_reports_parse_failure(self):
        result = run_xjq("//a", "")
        self.assertEqual(result.returncode, 1)
        self.assertIn("parse", result.stderr.lower())


class InfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def write(self, name: str, contents: bytes) -> str:
        path = Path(self.directory.name, name)
        path.write_bytes(contents)
        return str(path)

    def test_infile_is_queried_instead_of_stdin(self):
        path = self.write("catalog.xml", CATALOG.encode())
        result = run_xjq("//book/@id", "<other><book id=\"9\"/></other>", path)
        self.assertEqual(result.stdout, "1\n2")

    def test_extra_positional_arguments_are_ignored(self):
        path = self.write("catalog.xml", CATALOG.encode())
        result = run_xjq("//book/@id", "", path, "leftover", "--", "more")
        self.assertEqual(result.stdout, "1\n2")

    def test_utf8_file_with_a_byte_order_mark_is_accepted(self):
        path = self.write("bom.xml", b"\xef\xbb\xbf<a><b>caf\xc3\xa9</b></a>")
        self.assertEqual(run_xjq("//b/text()", "", path).stdout, "café")

    def test_json_detection_applies_to_file_input(self):
        path = self.write("doc.json", b'\xef\xbb\xbf{"name": "Ada"}')
        self.assertEqual(run_xjq("/root/name/text()", "", path).stdout, "Ada")

    def test_json_array_file_is_converted(self):
        path = self.write("doc.json", b'[1, "two"]')
        self.assertEqual(run_xjq("/root/item/text()", "", path).stdout, "1\ntwo")

    def test_missing_file_reports_an_error(self):
        result = run_xjq("//a", "", str(Path(self.directory.name, "absent.xml")))
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("absent.xml", result.stderr)

    def test_file_that_is_not_utf8_reports_an_error(self):
        path = self.write("bad.bin", b"\xff\xfe<a/>")
        result = run_xjq("//a", "", path)
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("utf-8", result.stderr.lower())


class FirstFlagTests(unittest.TestCase):
    def test_first_text_result(self):
        self.assertEqual(run_xjq("//title/text()", CATALOG, "--first").stdout, "The Great Book")
        self.assertEqual(run_xjq("//book", CATALOG, "-f", "--text-all").stdout,
                         "The Great Book tail")

    def test_first_attribute_result(self):
        self.assertEqual(run_xjq("//book/@id", CATALOG, "-f").stdout, "1")

    def test_first_xml_node_result(self):
        result = run_xjq("//book", CATALOG, "-f")
        self.assertEqual(result.stdout.count("<book"), 1)
        self.assertIn('<book id="1">', result.stdout)

    def test_first_without_matches_is_silent(self):
        result = run_xjq("//missing", CATALOG, "-f")
        self.assertEqual((result.stdout, result.stderr, result.returncode), ("", "", 0))

    def test_first_leaves_scalar_results_alone(self):
        self.assertEqual(run_xjq("count(//book)", CATALOG, "-f").stdout, "2")


class CompactFlagTests(unittest.TestCase):
    def test_compact_xml_has_no_added_formatting(self):
        result = run_xjq('//book[@id="2"]', CATALOG, "--compact")
        self.assertEqual(result.stdout, '<book id="2"><title>Second</title></book>')

    def test_compact_applies_to_json_derived_xml(self):
        self.assertEqual(run_xjq("/root", '{"b": 1, "a": 2}', "-c").stdout,
                         '<root><b type="int">1</b><a type="int">2</a></root>')

    def test_compact_leaves_text_results_unchanged(self):
        self.assertEqual(run_xjq("//title/text()", CATALOG, "-c").stdout,
                         "The Great Book\nSecond")

    def test_compact_and_first_combine(self):
        self.assertEqual(run_xjq('//book[@id="2"]/title', CATALOG, "-c", "-f").stdout,
                         "<title>Second</title>")


class CssNodeTests(unittest.TestCase):
    def test_css_selector_pretty_prints_the_matched_element(self):
        result = run_xjq('book[id="2"]', CATALOG, "--css")
        self.assertEqual(result.stdout, '<book id="2">\n  <title>Second</title>\n</book>')

    def test_descendant_and_attribute_selectors(self):
        self.assertEqual(run_xjq("catalog > book title", CATALOG, "--css").stdout.count("<title"), 1)
        self.assertEqual(run_xjq('book[id="1"] title::text', CATALOG, "--css").stdout, "The Great Book")

    def test_invalid_css_selector_fails(self):
        result = run_xjq("book[", CATALOG, "--css")
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("css", result.stderr.lower())


class CssTextTests(unittest.TestCase):
    def test_direct_text_pseudo_element(self):
        self.assertEqual(run_xjq("title::text", CATALOG, "--css").stdout, "The Great Book\nSecond")
        self.assertEqual(run_xjq("book::text", CATALOG, "--css").stdout, "tail")

    def test_descendant_text_pseudo_element_lists_each_text_node(self):
        result = run_xjq("book ::text", CATALOG, "--css")
        self.assertEqual(result.stdout, "The Great Book\ntail\nSecond")

    def test_comma_separated_selectors_share_a_text_mode(self):
        self.assertEqual(run_xjq("title::text, book::text", CATALOG, "--css").stdout,
                         "The Great Book\ntail\nSecond")

    def test_mixing_text_modes_is_rejected(self):
        result = run_xjq("title::text, book ::text", CATALOG, "--css")
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("::text", result.stderr)

    def test_mixing_text_and_element_selectors_is_rejected(self):
        self.assertEqual(run_xjq("title::text, book", CATALOG, "--css").returncode, 1)


class TextFlagTests(unittest.TestCase):
    def test_text_flag_takes_the_direct_text_of_each_match(self):
        self.assertEqual(run_xjq("//title", CATALOG, "--text").stdout, "The Great Book\nSecond")
        self.assertEqual(run_xjq("//book", CATALOG, "-t").stdout, "tail\n")

    def test_text_all_flag_takes_the_descendant_text_of_each_match(self):
        self.assertEqual(run_xjq("//book", CATALOG, "--text-all").stdout,
                         "The Great Book tail\nSecond")

    def test_text_all_wins_over_text(self):
        with_both = run_xjq("//book", CATALOG, "-t", "--text-all").stdout
        self.assertEqual(with_both, run_xjq("//book", CATALOG, "--text-all").stdout)

    def test_flags_are_a_no_op_for_queries_that_already_extract_text(self):
        self.assertEqual(run_xjq("//title/text()", CATALOG, "--text-all").stdout,
                         "The Great Book\nSecond")
        self.assertEqual(run_xjq("title::text", CATALOG, "--css", "--text-all").stdout,
                         "The Great Book\nSecond")

    def test_flags_apply_to_css_matches(self):
        self.assertEqual(run_xjq("book", CATALOG, "--css", "--text-all").stdout,
                         "The Great Book tail\nSecond")


JSON_DOC = (
    '{"name": "Ada", "Count": 2, "ratio": 1.50, "ok": true, "gap": null,'
    ' "tags": ["x", {"deep": 1}]}'
)


class JsonDetectionTests(unittest.TestCase):
    def test_object_input_is_converted_and_queryable(self):
        self.assertEqual(run_xjq("/root/name/text()", JSON_DOC).stdout, "Ada")

    def test_array_input_wraps_each_entry_in_an_item(self):
        self.assertEqual(run_xjq("/root/item/text()", '[1, "two"]').stdout, "1\ntwo")

    def test_top_level_primitives_are_not_json_input(self):
        for document in ('42', '"hi"', 'true', 'null'):
            result = run_xjq("/root", document)
            self.assertEqual(result.returncode, 1, document)
            self.assertIn("xml", result.stderr.lower())

    def test_markup_is_still_parsed_as_xml(self):
        self.assertEqual(run_xjq("//b/text()", "<a><b>hi</b></a>").stdout, "hi")


class JsonConversionTests(unittest.TestCase):
    def test_root_has_no_type_and_keys_become_children_in_order(self):
        result = run_xjq("/root", '{"b": 1, "a": 2}')
        self.assertEqual(
            result.stdout,
            '<root>\n  <b type="int">1</b>\n  <a type="int">2</a>\n</root>',
        )

    def test_key_case_is_preserved(self):
        self.assertEqual(run_xjq("/root/Count/text()", JSON_DOC).stdout, "2")
        self.assertEqual(run_xjq("/root/count", JSON_DOC).stdout, "")

    def test_types_are_recorded_on_every_converted_element(self):
        self.assertEqual(
            run_xjq("//*/@type", JSON_DOC).stdout,
            "str\nint\nfloat\nbool\nnull\nlist\nstr\ndict\nint",
        )

    def test_booleans_and_null_render_as_text(self):
        self.assertEqual(run_xjq("/root/ok/text()", JSON_DOC).stdout, "true")
        self.assertEqual(run_xjq("/root/gap", JSON_DOC).stdout, '<gap type="null"></gap>')

    def test_numbers_take_their_shortest_form(self):
        document = '{"a": 1, "b": 1.0, "c": 1.50, "d": 0.00012}'
        self.assertEqual(run_xjq("/root/*/text()", document).stdout, "1\n1\n1.5\n0.00012")

    def test_nested_containers_keep_their_shape(self):
        self.assertEqual(run_xjq("//deep/text()", JSON_DOC).stdout, "1")
        self.assertEqual(run_xjq("count(/root/tags/item)", JSON_DOC).stdout, "2")

    def test_css_and_text_flags_work_on_converted_documents(self):
        self.assertEqual(run_xjq("name::text", JSON_DOC, "--css").stdout, "Ada")
        self.assertEqual(run_xjq("/root/tags", JSON_DOC, "--text-all").stdout, "x1")


class JsonKeyTests(unittest.TestCase):
    def test_keys_that_are_not_xml_names_are_rejected(self):
        for document in ('{"a b": 1}', '{"1st": 1}', '{"": 1}', '{"ok": {"a<b>": 1}}'):
            result = run_xjq("/root", document)
            self.assertEqual((result.returncode, result.stdout), (1, ""), document)
            self.assertIn("json", result.stderr.lower())
            self.assertIn("key", result.stderr.lower())
            self.assertIn("invalid", result.stderr.lower())

    def test_dots_dashes_and_underscores_are_valid_keys(self):
        self.assertEqual(run_xjq("//*/text()", '{"a-b.c_d": 1}').stdout, "1")


if __name__ == "__main__":
    unittest.main()
