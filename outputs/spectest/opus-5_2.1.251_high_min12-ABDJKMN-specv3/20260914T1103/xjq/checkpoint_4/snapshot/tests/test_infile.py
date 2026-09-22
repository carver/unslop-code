"""Spec section: Input Source (from "File Input, First-Result, and Compact
Output").

Each test section quotes the minimal spec phrase it covers.
"""
import json

import pytest


def write(tmp_path, name, data, encoding="utf-8"):
    """Write a fixture file and return its path as a string."""
    path = tmp_path / name
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_bytes(data.encode(encoding))
    return str(path)


# --- Phrase: "`INFILE` takes precedence over stdin when both are present."
# Context: a path is supplied AND stdin has content; the file wins.

def test_infile_is_used_when_stdin_is_also_present(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", "<a><b>from-file</b></a>")
    r = xjq("//b/text()", path, stdin="<a><b>from-stdin</b></a>")
    assert r.returncode == 0
    assert r.stdout == "from-file"


def test_infile_is_used_when_stdin_is_empty(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", "<a><b>from-file</b></a>")
    r = xjq("//b/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "from-file"


def test_stdin_is_not_even_consulted_when_infile_given(xjq, tmp_path):
    # Broken stdin must not matter: it is never parsed.
    path = write(tmp_path, "doc.xml", "<a><b>ok</b></a>")
    r = xjq("//b/text()", path, stdin="<<<not xml at all")
    assert r.returncode == 0
    assert r.stdout == "ok"


def test_stdin_still_used_when_no_infile(xjq, books):
    r = xjq("//title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines()[0] == "Dune"


def test_infile_works_with_flags(xjq, tmp_path, books):
    path = write(tmp_path, "books.xml", books)
    r = xjq("--text", "//title", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_infile_works_with_css_mode(xjq, tmp_path, books):
    path = write(tmp_path, "books.xml", books)
    r = xjq("--css", "title", path, stdin="")
    assert r.returncode == 0
    assert r.stdout.strip() == "<title>Dune</title>"


# --- Phrase: "Additional positional args after `QUERY [INFILE]` are ignored."
# Context: a third (and further) positional is accepted and discarded.

def test_extra_positional_is_ignored(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", "<a><b>ok</b></a>")
    r = xjq("//b/text()", path, "extra", stdin="")
    assert r.returncode == 0
    assert r.stdout == "ok"


def test_many_extra_positionals_are_ignored(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", "<a><b>ok</b></a>")
    r = xjq("//b/text()", path, "one", "two", "three", stdin="")
    assert r.returncode == 0
    assert r.stdout == "ok"


def test_extra_positional_that_looks_like_a_path_is_not_read(xjq, tmp_path):
    first = write(tmp_path, "first.xml", "<a><b>first</b></a>")
    second = write(tmp_path, "second.xml", "<a><b>second</b></a>")
    r = xjq("//b/text()", first, second, stdin="")
    assert r.returncode == 0
    assert r.stdout == "first"


def test_extra_positional_that_does_not_exist_is_not_an_error(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", "<a><b>ok</b></a>")
    r = xjq("//b/text()", path, str(tmp_path / "nope.xml"), stdin="")
    assert r.returncode == 0
    assert r.stdout == "ok"


# T36: flags may still appear after the extra positionals.
def test_flag_after_extra_positionals_still_parsed(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", "<a><b>x</b><b>y</b></a>")
    r = xjq("//b/text()", path, "junk", "--first", stdin="")
    assert r.returncode == 0
    assert r.stdout == "x"


# --- Phrase: "Decode `INFILE` as UTF-8 text" ------------------------------
# Context: non-ASCII content in the file round-trips.

def test_infile_decoded_as_utf8(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", "<a><b>café über 日本</b></a>")
    r = xjq("//b/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "café über 日本"


def test_infile_utf8_attribute_value(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", '<a><b v="été"/></a>')
    r = xjq("//b/@v", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "été"


# --- Phrase: "a UTF-8 BOM is allowed" -------------------------------------
# Context: a leading EF BB BF must not break XML, JSON, or detection.

def test_bom_before_xml_is_allowed(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", b"\xef\xbb\xbf<a><b>ok</b></a>")
    r = xjq("//b/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "ok"


def test_bom_before_xml_declaration_is_allowed(xjq, tmp_path):
    doc = b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?><a><b>ok</b></a>'
    path = write(tmp_path, "doc.xml", doc)
    r = xjq("//b/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "ok"


def test_bom_before_json_object_is_allowed(xjq, tmp_path):
    path = write(tmp_path, "doc.json", b'\xef\xbb\xbf{"a": "x"}')
    r = xjq("/root/a/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "x"


def test_bom_before_json_array_is_allowed(xjq, tmp_path):
    path = write(tmp_path, "doc.json", b"\xef\xbb\xbf[1, 2]")
    r = xjq("/root/item/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1", "2"]


def test_bom_is_not_part_of_the_output(xjq, tmp_path):
    path = write(tmp_path, "doc.xml", b"\xef\xbb\xbf<a><b>ok</b></a>")
    r = xjq("//b/text()", path, stdin="")
    assert "﻿" not in r.stdout


# T33: bytes that are not UTF-8 are treated as an unreadable file.
def test_non_utf8_infile_exits_one(xjq, tmp_path):
    path = write(tmp_path, "latin.xml", b"<a><b>caf\xe9</b></a>")
    r = xjq("//b/text()", path, stdin="")
    assert r.returncode == 1
    assert r.stderr.strip() != ""
    assert r.stdout == ""


# --- Phrase: "Apply JSON auto-detection to file input: treat as JSON
#             object/array when detected" ---------------------------------
# Context: the same detection rule as stdin, now keyed on the file's bytes.

def test_json_object_file_is_converted(xjq, tmp_path):
    path = write(tmp_path, "d.json", '{"name": "ada", "age": 36}')
    r = xjq("/root/name/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "ada"


def test_json_array_file_becomes_items(xjq, tmp_path):
    path = write(tmp_path, "d.json", "[10, 20, 30]")
    r = xjq("/root/item/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["10", "20", "30"]


def test_json_file_keeps_type_attributes(xjq, tmp_path):
    path = write(tmp_path, "d.json", '{"a": 1, "b": "s", "c": true}')
    r = xjq("/root/a/@type", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "int"


def test_json_detection_ignores_the_file_extension(xjq, tmp_path):
    path = write(tmp_path, "looks_like.xml", '{"a": "x"}')
    r = xjq("/root/a/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "x"


def test_leading_whitespace_before_json_in_file(xjq, tmp_path):
    path = write(tmp_path, "d.json", '\n\n  {"a": "x"}\n')
    r = xjq("/root/a/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "x"


# --- Phrase: "otherwise parse as XML/HTML" --------------------------------
# Context: anything the JSON detector rejects goes down the XML/HTML path.

def test_xml_file_is_parsed_as_xml(xjq, tmp_path, books):
    path = write(tmp_path, "books.xml", books)
    r = xjq("//book[@id='b2']/title/text()", path, stdin="")
    assert r.returncode == 0
    assert r.stdout == "Le Petit Prince"


def test_html_file_is_parsed_as_html(xjq, tmp_path):
    doc = "<!DOCTYPE html><html><body><p>hi<br>there</p></body></html>"
    path = write(tmp_path, "page.html", doc)
    r = xjq("//p", path, stdin="")
    assert r.returncode == 0
    assert "<p>" in r.stdout


def test_json_primitive_file_is_not_json_input(xjq, tmp_path):
    # A top-level primitive is not an object/array, so it goes to the XML
    # parser and fails there.
    path = write(tmp_path, "d.json", '"just a string"')
    r = xjq("//a", path, stdin="")
    assert r.returncode == 1


def test_malformed_xml_file_exits_one(xjq, tmp_path):
    path = write(tmp_path, "bad.xml", "<a><b></a>")
    r = xjq("//b", path, stdin="")
    assert r.returncode == 1
    assert r.stderr.strip() != ""


# T35: an empty file is the empty-input error, not a fallback to stdin.
def test_empty_file_is_an_error_not_a_stdin_fallback(xjq, tmp_path):
    path = write(tmp_path, "empty.xml", "")
    r = xjq("//b/text()", path, stdin="<a><b>from-stdin</b></a>")
    assert r.returncode == 1
    assert r.stdout == ""


# --- Phrase: "Missing/unreadable file: stderr message, exit code `1`." ----
# Context: the path does not exist, or cannot be opened.

def test_missing_file_exits_one(xjq, tmp_path):
    r = xjq("//b", str(tmp_path / "nope.xml"), stdin="")
    assert r.returncode == 1


def test_missing_file_writes_to_stderr_and_not_stdout(xjq, tmp_path):
    r = xjq("//b", str(tmp_path / "nope.xml"), stdin="")
    assert r.stdout == ""
    assert r.stderr.strip() != ""


def test_missing_file_message_names_the_path(xjq, tmp_path):
    missing = str(tmp_path / "nope.xml")
    r = xjq("//b", missing, stdin="")
    assert "nope.xml" in r.stderr


def test_missing_file_does_not_fall_back_to_stdin(xjq, tmp_path):
    r = xjq("//b/text()", str(tmp_path / "nope.xml"), stdin="<a><b>x</b></a>")
    assert r.returncode == 1
    assert r.stdout == ""


def test_directory_as_infile_exits_one(xjq, tmp_path):
    r = xjq("//b", str(tmp_path), stdin="")
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_unreadable_file_exits_one(xjq, tmp_path):
    import os
    path = tmp_path / "secret.xml"
    path.write_text("<a><b>x</b></a>")
    os.chmod(path, 0o000)
    try:
        r = xjq("//b", str(path), stdin="")
    finally:
        os.chmod(path, 0o600)
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits are not enforced")
    assert r.returncode == 1
    assert r.stderr.strip() != ""


# T34: `-` is an ordinary (missing) filename, not a stdin placeholder.
def test_dash_infile_is_a_literal_filename(xjq):
    r = xjq("//b/text()", "-", stdin="<a><b>x</b></a>")
    assert r.returncode == 1
    assert r.stdout == ""
