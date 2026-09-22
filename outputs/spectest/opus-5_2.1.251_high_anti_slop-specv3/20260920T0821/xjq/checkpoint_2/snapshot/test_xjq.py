"""End-to-end tests for the xjq.py CLI, driven through a subprocess."""

import subprocess
import sys
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


class ArgumentTests(unittest.TestCase):
    def test_infile_argument_is_accepted_and_input_still_comes_from_stdin(self):
        result = run_xjq("//book/@id", CATALOG, "ignored.xml")
        self.assertEqual(result.stdout, "1\n2")


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


if __name__ == "__main__":
    unittest.main()
