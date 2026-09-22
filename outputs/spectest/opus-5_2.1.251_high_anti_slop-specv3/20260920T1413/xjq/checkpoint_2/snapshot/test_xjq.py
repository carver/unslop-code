"""End-to-end tests driving xjq.py as a subprocess."""

import subprocess
import sys
from pathlib import Path

import pytest

XJQ = str(Path(__file__).with_name("xjq.py"))

CATALOG = b"""<?xml version="1.0"?>
<Catalog>
  <Book id="b1" lang="en">
    <Title>  Dune    and   sequels </Title>
    <Tags><Tag>sf</Tag><Tag>classic</Tag></Tags>
  </Book>
  <Book id="b2" lang="fr">
    <Title>Ubik</Title>
    <Tags><Tag>sf</Tag></Tags>
  </Book>
  <book id="lowercase"/>
</Catalog>
"""


def run(query, stdin=CATALOG, *args):
    return subprocess.run(
        [sys.executable, XJQ, query, *args], input=stdin, capture_output=True
    )


def test_text_results_are_normalized_and_newline_joined():
    done = run("//Title/text()")
    assert done.returncode == 0
    assert done.stdout == b"Dune and sequels\nUbik"


def test_attribute_results():
    assert run("//Book/@id").stdout == b"b1\nb2"


def test_element_matching_is_case_sensitive():
    assert run("//book/@id").stdout == b"lowercase"


def test_first_matching_node_is_pretty_printed():
    assert run("//Tags").stdout == (
        b"<Tags>\n  <Tag>sf</Tag>\n  <Tag>classic</Tag>\n</Tags>"
    )


def test_no_match_writes_nothing_and_succeeds():
    done = run("//Missing")
    assert done.returncode == 0
    assert done.stdout == b""
    assert done.stderr == b""


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("count(//Book)", b"2"),
        ("boolean(//Book)", b"true"),
        ("boolean(//Missing)", b"false"),
        ("string(//Title)", b"Dune and sequels"),
    ],
)
def test_scalar_results(query, expected):
    assert run(query).stdout == expected


def test_infile_argument_is_ignored():
    assert run("//Title/text()", CATALOG, "ignored.xml").stdout.startswith(b"Dune")


def test_invalid_xpath_reports_error():
    done = run("//[unclosed")
    assert done.returncode == 1
    assert done.stdout == b""
    assert b"xpath" in done.stderr.lower()


@pytest.mark.parametrize("payload", [b"", b"   ", b"<a><b></a>"])
def test_bad_xml_input_reports_error(payload):
    done = run("//a", payload)
    assert done.returncode == 1
    assert done.stdout == b""
    assert b"xml" in done.stderr.lower() and b"parse" in done.stderr.lower()


def test_html_document_is_parsed():
    html = b"<!DOCTYPE html><html><body><p>one<p>two</body></html>"
    assert run("//p/text()", html).stdout == b"one\ntwo"


def test_css_query_returns_pretty_printed_node():
    assert run("Book > Tags", CATALOG, "--css").stdout == (
        b"<Tags>\n  <Tag>sf</Tag>\n  <Tag>classic</Tag>\n</Tags>"
    )


def test_css_attribute_selector_is_supported():
    assert run("Book[lang=fr] Title::text", CATALOG, "--css").stdout == b"Ubik"


def test_css_text_pseudo_element_selects_direct_text():
    assert run("Title::text", CATALOG, "--css").stdout == b"Dune and sequels\nUbik"


def test_css_descendant_text_yields_one_line_per_text_node():
    assert run("Tags ::text", CATALOG, "--css").stdout == b"sf\nclassic\nsf"


def test_css_comma_separated_text_selectors_share_a_mode():
    assert run("Title::text, Tag::text", CATALOG, "--css").stdout == (
        b"Dune and sequels\nsf\nclassic\nUbik\nsf"
    )


@pytest.mark.parametrize(
    "query", ["Book ::text, Title::text", "Title::text, Book", "Title::first-line"]
)
def test_unusable_css_text_queries_report_an_error(query):
    done = run(query, CATALOG, "--css")
    assert done.returncode == 1
    assert done.stdout == b""
    assert b"css" in done.stderr.lower()


def test_invalid_css_selector_reports_error():
    done = run("Book[", CATALOG, "--css")
    assert done.returncode == 1
    assert done.stdout == b""
    assert b"css" in done.stderr.lower()


def test_text_flag_extracts_direct_text_of_each_match():
    assert run("//Title", CATALOG, "--text").stdout == b"Dune and sequels\nUbik"


def test_text_all_flag_extracts_descendant_text_of_each_match():
    assert run("//Book/Tags", CATALOG, "--text-all").stdout == b"sfclassic\nsf"


def test_text_all_wins_over_text():
    both = run("//Book/Tags", CATALOG, "-t", "--text-all")
    assert both.stdout == run("//Book/Tags", CATALOG, "--text-all").stdout
    assert both.stdout == b"sfclassic\nsf"


@pytest.mark.parametrize("flag", ["-t", "--text-all"])
def test_text_flags_are_no_ops_for_queries_that_extract_text(flag):
    assert run("//Title/text()", CATALOG, flag).stdout == b"Dune and sequels\nUbik"
    assert run("Title::text", CATALOG, "--css", flag).stdout == b"Dune and sequels\nUbik"


def test_text_flag_applies_to_css_matches():
    assert run("Book > Title", CATALOG, "--css", "-t").stdout == b"Dune and sequels\nUbik"


def test_css_query_without_match_writes_nothing_and_succeeds():
    done = run("Missing", CATALOG, "--css")
    assert done.returncode == 0
    assert done.stdout == b""
    assert done.stderr == b""


def test_css_query_against_html_document():
    page = b"<!DOCTYPE html><html><body><p class='a'>one <b>two</b></p></body></html>"
    assert run("p.a ::text", page, "--css").stdout == b"one\ntwo"
