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


def write(tmp_path, data, name="doc.xml"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


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


def test_infile_takes_precedence_over_stdin(tmp_path):
    other = write(tmp_path, b"<Catalog><Title>From file</Title></Catalog>")
    assert run("//Title/text()", CATALOG, other).stdout == b"From file"


def test_stdin_is_read_when_no_infile_is_given():
    assert run("//Title/text()", CATALOG).stdout.startswith(b"Dune")


def test_positional_arguments_after_infile_are_ignored(tmp_path):
    infile = write(tmp_path, CATALOG)
    done = run("//book/@id", b"", infile, "extra", "more")
    assert done.returncode == 0
    assert done.stdout == b"lowercase"


def test_infile_may_start_with_a_utf8_bom(tmp_path):
    infile = write(tmp_path, b"\xef\xbb\xbf<Catalog><Title>Caf\xc3\xa9</Title></Catalog>")
    assert run("//Title/text()", b"", infile).stdout.decode() == "Caf\u00e9"


def test_json_detection_applies_to_file_input(tmp_path):
    infile = write(tmp_path, JSON_OBJECT, "doc.json")
    assert run("/root/Name/text()", b"", infile).stdout == b"Ada"


def test_missing_file_reports_an_error(tmp_path):
    done = run("//Title", b"", str(tmp_path / "absent.xml"))
    assert done.returncode == 1
    assert done.stdout == b""
    assert b"absent.xml" in done.stderr


def test_unreadable_file_reports_an_error(tmp_path):
    infile = write(tmp_path, b"\xff\xfe<Catalog/>")
    done = run("//Title", b"", infile)
    assert done.returncode == 1
    assert done.stdout == b""
    assert done.stderr != b""


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


JSON_OBJECT = (
    b'{"Name": "Ada", "age": 36, "score": 1.50, "ok": true, "none": null,'
    b' "tags": ["sf", "classic"], "meta": {"Id": 7, "empty": {}}}'
)


def test_json_object_becomes_root_with_one_child_per_key():
    assert run("/root", JSON_OBJECT).stdout == (
        b'<root>\n'
        b'  <Name type="str">Ada</Name>\n'
        b'  <age type="int">36</age>\n'
        b'  <score type="float">1.5</score>\n'
        b'  <ok type="bool">true</ok>\n'
        b'  <none type="null"></none>\n'
        b'  <tags type="list">\n'
        b'    <item type="str">sf</item>\n'
        b'    <item type="str">classic</item>\n'
        b'  </tags>\n'
        b'  <meta type="dict">\n'
        b'    <Id type="int">7</Id>\n'
        b'    <empty type="dict"></empty>\n'
        b'  </meta>\n'
        b'</root>'
    )


def test_json_array_becomes_item_children_of_root():
    assert run("/root", b'[1, {"a": "b"}]').stdout == (
        b'<root>\n'
        b'  <item type="int">1</item>\n'
        b'  <item type="dict">\n'
        b'    <a type="str">b</a>\n'
        b'  </item>\n'
        b'</root>'
    )


def test_json_keys_keep_their_case_and_order():
    assert run("/root", b'{"b": 1, "A": 2, "a": 3}').stdout == (
        b'<root>\n'
        b'  <b type="int">1</b>\n'
        b'  <A type="int">2</A>\n'
        b'  <a type="int">3</a>\n'
        b'</root>'
    )


@pytest.mark.parametrize(
    ("number", "expected"),
    [(b"1", b"1"), (b"1.0", b"1"), (b"1.50", b"1.5"), (b"0.00012", b"0.00012")],
)
def test_numbers_use_their_minimal_string_form(number, expected):
    assert run("/root/n/text()", b'{"n": ' + number + b"}").stdout == expected


def test_json_types_are_recorded_on_every_element_but_root():
    types = run("/root//@type", JSON_OBJECT).stdout.split(b"\n")
    assert types == [
        b"str", b"int", b"float", b"bool", b"null",
        b"list", b"str", b"str", b"dict", b"int", b"dict",
    ]
    assert run("count(/root/@type)", JSON_OBJECT).stdout == b"0"


def test_json_queries_support_css_and_text_flags():
    assert run("tags ::text", JSON_OBJECT, "--css").stdout == b"sf\nclassic"
    assert run("/root/meta", JSON_OBJECT, "--text-all").stdout == b"7"


@pytest.mark.parametrize("payload", [b"42", b'"text"', b"true", b"null"])
def test_top_level_json_primitives_are_parsed_as_xml(payload):
    done = run("//a", payload)
    assert done.returncode == 1
    assert b"xml" in done.stderr.lower() and b"parse" in done.stderr.lower()


def test_json_like_input_that_is_not_json_falls_back_to_xml():
    assert run("//item/text()", b"<item>{not json}</item>").stdout == b"{not json}"


@pytest.mark.parametrize("key", [b'"bad key"', b'"1st"', b'""', b'"a<b"'])
def test_invalid_json_keys_report_an_error(key):
    done = run("/root", b"{" + key + b": 1}")
    assert done.returncode == 1
    assert done.stdout == b""
    message = done.stderr.lower()
    assert b"json" in message and b"key" in message and b"invalid" in message


@pytest.mark.parametrize(
    ("query", "args", "expected"),
    [
        ("//Title/text()", (), b"Dune and sequels"),
        ("//Book/@id", (), b"b1"),
        ("//Title", ("--text",), b"Dune and sequels"),
        ("Title::text", ("--css",), b"Dune and sequels"),
        ("//Tag", ("--compact",), b"<Tag>sf</Tag>"),
    ],
)
def test_first_flag_keeps_only_the_first_result(query, args, expected):
    assert run(query, CATALOG, "--first", *args).stdout == expected


def test_first_flag_without_a_match_stays_silent():
    done = run("//Missing", CATALOG, "-f")
    assert done.returncode == 0
    assert done.stdout == b""
    assert done.stderr == b""


def test_first_flag_leaves_scalar_results_alone():
    assert run("count(//Book)", CATALOG, "-f").stdout == b"2"


def test_compact_flag_drops_added_xml_formatting():
    assert run("//Tags", CATALOG, "--compact").stdout == (
        b"<Tags><Tag>sf</Tag><Tag>classic</Tag></Tags>"
    )


def test_compact_flag_keeps_the_formatting_of_the_document_itself():
    assert run("//Book[@id='b2']", CATALOG, "-c").stdout == (
        b"<Book id=\"b2\" lang=\"fr\">\n    <Title>Ubik</Title>\n    <Tags><Tag>sf</Tag></Tags>\n  </Book>"
    )


def test_compact_flag_does_not_affect_text_results():
    assert run("//Title/text()", CATALOG, "-c").stdout == b"Dune and sequels\nUbik"


def test_compact_flag_applies_to_json_derived_output():
    assert run("/root", b'{"a": 1, "b": {"c": []}}', "-c").stdout == (
        b'<root><a type="int">1</a><b type="dict"><c type="list"></c></b></root>'
    )


JSON_EXPORT_OF_TITLES = (
    b'[\n'
    b'  {\n'
    b'    "Title": "Dune and sequels"\n'
    b'  },\n'
    b'  {\n'
    b'    "Title": "Ubik"\n'
    b'  }\n'
    b']'
)


def test_json_flag_exports_matched_elements_as_an_array_of_objects():
    assert run("//Title", CATALOG, "--json").stdout == JSON_EXPORT_OF_TITLES


def test_json_export_uses_immediate_text_only():
    assert run("//Book/Tags", CATALOG, "-j").stdout == (
        b'[\n  {\n    "Tags": ""\n  },\n  {\n    "Tags": ""\n  }\n]'
    )


def test_compact_json_export_has_no_leading_whitespace():
    assert run("//Title", CATALOG, "-j", "--compact").stdout == (
        b'[\n{\n"Title": "Dune and sequels"\n},\n{\n"Title": "Ubik"\n}\n]'
    )


def test_json_export_with_first_keeps_the_array():
    assert run("//Title", CATALOG, "-j", "-f").stdout == (
        b'[\n  {\n    "Title": "Dune and sequels"\n  }\n]'
    )


def test_json_export_covers_every_match_of_a_union():
    assert run("//book | //Title", CATALOG, "-j").stdout == (
        b'[\n'
        b'  {\n    "Title": "Dune and sequels"\n  },\n'
        b'  {\n    "Title": "Ubik"\n  },\n'
        b'  {\n    "book": ""\n  }\n'
        b']'
    )


def test_json_export_applies_to_json_derived_documents():
    assert run("/root/Name", JSON_OBJECT, "-j").stdout == (
        b'[\n  {\n    "Name": "Ada"\n  }\n]'
    )


@pytest.mark.parametrize("query", ["//Title/text()", "//Book/@id", "count(//Book)"])
def test_json_flag_is_a_no_op_for_results_that_are_already_text(query):
    assert run(query, CATALOG, "-j").stdout == run(query, CATALOG).stdout


def test_json_flag_is_a_no_op_in_css_mode():
    assert run("Book > Tags", CATALOG, "--css", "-j").stdout == (
        b"<Tags>\n  <Tag>sf</Tag>\n  <Tag>classic</Tag>\n</Tags>"
    )


def test_json_flag_without_a_match_writes_nothing():
    done = run("//Missing", CATALOG, "-j")
    assert done.returncode == 0
    assert done.stdout == b""


@pytest.mark.parametrize("flag", ["--text", "--text-all"])
def test_text_flags_win_over_the_json_flag(flag):
    assert run("//Title", CATALOG, "-j", flag).stdout == b"Dune and sequels\nUbik"


def test_union_of_elements_renders_the_first_match_as_xml():
    assert run("//Tags | //Title", CATALOG).stdout == (
        b"<Title>  Dune    and   sequels </Title>"
    )


def test_union_with_text_flag_reports_the_text_of_each_match():
    assert run("//Title | //Tag", CATALOG, "--text").stdout == (
        b"Dune and sequels\nsf\nclassic\nUbik\nsf"
    )


def test_union_with_text_all_concatenates_the_text_of_every_match():
    assert run("//Title | //Tag", CATALOG, "--text-all").stdout == (
        b"Dune and sequels sfclassicUbiksf"
    )


def test_union_with_text_all_and_first_uses_only_the_first_match():
    assert run("//Title | //Tag", CATALOG, "--text-all", "-f").stdout == b"Dune and sequels"


@pytest.mark.parametrize("args", [(), ("--text",), ("--text-all",)])
def test_union_that_extracts_text_itself_is_written_as_text_results(args):
    assert run("//Title/text() | //Tag", CATALOG, *args).stdout == (
        b"Dune and sequels\nsf\nclassic\nUbik\nsf"
    )


def test_union_mixing_attributes_and_elements_is_written_as_text_results():
    assert run("//Book/@id | //Tag", CATALOG, "--text-all").stdout == (
        b"b1\nsf\nclassic\nb2\nsf"
    )


def test_a_pipe_inside_a_predicate_does_not_make_a_union():
    assert run("//Book[Title|Tags]", CATALOG, "--text-all").stdout == (
        b"Dune and sequels sfclassic\nUbik sf"
    )


def test_union_in_css_mode_is_read_as_a_css_selector():
    done = run("Book | Tags", CATALOG, "--css")
    assert done.returncode == 1
    assert done.stdout == b""
    assert b"css" in done.stderr.lower()


def test_css_namespace_separator_without_a_namespace_reports_a_css_error():
    done = run("Book|Tags", CATALOG, "--css")
    assert done.returncode == 1
    assert done.stdout == b""
    assert b"css" in done.stderr.lower()
