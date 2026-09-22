"""End-to-end tests for the xjq.py CLI, driven through a subprocess."""

import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("xjq.py")

CATALOG = (
    '<catalog><book id="1"><title>  The   Great\n Book </title></book>'
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


if __name__ == "__main__":
    unittest.main()
