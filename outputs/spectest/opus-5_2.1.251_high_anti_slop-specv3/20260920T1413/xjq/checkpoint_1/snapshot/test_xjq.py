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
