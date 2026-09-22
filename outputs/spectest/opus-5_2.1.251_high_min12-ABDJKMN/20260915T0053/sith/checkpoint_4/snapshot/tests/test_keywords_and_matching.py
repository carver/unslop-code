"""Spec sections: 3. Keyword Completion, Prefix Matching, Clarifications."""
import keyword

from conftest import CURSOR, complete_at, entry, has, names

C = CURSOR


# --- Phrase: "When in a name-completion context, also include Python keywords as completions."
#     Context: empty prefix at module level.
def test_keywords_included_in_name_context(tmp_path):
    data = complete_at(tmp_path, C + "\n")
    for kw in ("for", "while", "import", "lambda", "None", "True"):
        assert has(data, kw), kw


# --- Phrase: "Keywords are filtered by the same prefix rules as names."
#     Context: prefix "de" matches the keyword "def" and "del".
def test_keywords_filtered_by_prefix(tmp_path):
    data = complete_at(tmp_path, "de" + C + "\n")
    assert has(data, "def") and has(data, "del")
    assert not has(data, "for")


# --- Phrase: "Keywords are filtered by the same prefix rules as names."
#     Context: case-insensitive prefix matching also applies to keywords.
def test_keywords_case_insensitive(tmp_path):
    data = complete_at(tmp_path, "NON" + C + "\n")
    assert has(data, "None")
    assert entry(data, "None")["complete"] == "e"


# --- Phrase: "For keywords: the keyword itself." (description)
#     Context: description field of a keyword entry.
def test_keyword_type_and_description(tmp_path):
    data = complete_at(tmp_path, "whi" + C + "\n")
    assert entry(data, "while") == {
        "name": "while", "complete": "le", "type": "keyword",
        "description": "while",
    }


# --- Phrase: "also include Python keywords" (T9)
#     Context: the keyword set is keyword.kwlist.
def test_keyword_set_is_kwlist(tmp_path):
    data = complete_at(tmp_path, C + "\n")
    kws = {c["name"] for c in data["completions"] if c["type"] == "keyword"}
    assert kws == set(keyword.kwlist)


# --- Phrase: "Keywords are not included in attribute completion (after `.`)."
#     Context: after a dot, no keyword entries.
def test_no_keywords_after_dot(tmp_path):
    data = complete_at(tmp_path, "import os\nos.i" + C + "\n")
    assert all(c["type"] != "keyword" for c in data["completions"])
    assert not has(data, "if")
    assert not has(data, "import")


# --- Phrase: "Keywords are not included in attribute completion (after `.`)."
#     Context: even with an empty prefix after the dot.
def test_no_keywords_after_dot_empty_prefix(tmp_path):
    code = "class Widget:\n    pass\n\nWidget." + C + "\n"
    data = complete_at(tmp_path, code)
    assert all(c["type"] != "keyword" for c in data["completions"])


# --- Phrase: "By default, prefix matching is case-insensitive."
#     Context: lowercase query matching a capitalised name.
def test_case_insensitive_prefix(tmp_path):
    data = complete_at(tmp_path, "valu" + C + "\nValueError\n")
    assert has(data, "ValueError")


# --- Phrase: "By default, prefix matching is case-insensitive."
#     Context: uppercase query matching a lowercase name.
def test_case_insensitive_prefix_reverse(tmp_path):
    code = "widget = 1\nWID" + C + "\n"
    data = complete_at(tmp_path, code)
    assert has(data, "widget")
    assert entry(data, "widget")["complete"] == "get"


# --- Phrase: "By default, prefix matching is case-insensitive."
#     Context: a non-fuzzy run does NOT match non-contiguous subsequences.
def test_default_is_not_fuzzy(tmp_path):
    code = "alphabet = 1\naph" + C + "\n"
    data = complete_at(tmp_path, code)
    assert not has(data, "alphabet")


# --- Phrase: "When `--fuzzy` is passed, matching is relaxed: the characters of the query must
#              appear in the name in order, but not necessarily contiguously."
#     Context: query "aph" against "alphabet".
def test_fuzzy_subsequence_match(tmp_path):
    code = "alphabet = 1\naph" + C + "\n"
    data = complete_at(tmp_path, code, fuzzy=True)
    assert has(data, "alphabet")


# --- Phrase: "the characters of the query must appear in the name in order"
#     Context: out-of-order query does not match under fuzzy.
def test_fuzzy_requires_order(tmp_path):
    code = "alphabet = 1\nhpa" + C + "\n"
    data = complete_at(tmp_path, code, fuzzy=True)
    assert not has(data, "alphabet")


# --- Phrase: "Fuzzy matching is also case-insensitive."
#     Context: mixed-case fuzzy query.
def test_fuzzy_case_insensitive(tmp_path):
    code = "alphabet = 1\nAPH" + C + "\n"
    data = complete_at(tmp_path, code, fuzzy=True)
    assert has(data, "alphabet")


# --- Phrase: "--fuzzy ... complete" (T12)
#     Context: fuzzy still strips len(prefix) characters.
def test_fuzzy_complete_field_strips_by_count(tmp_path):
    code = "alphabet = 1\naph" + C + "\n"
    data = complete_at(tmp_path, code, fuzzy=True)
    assert entry(data, "alphabet")["complete"] == "habet"


# --- Phrase: "When `--fuzzy` is passed ..."
#     Context: fuzzy applies to attribute completion as well.
def test_fuzzy_on_attributes(tmp_path):
    data = complete_at(tmp_path, "import os\nos.gtcw" + C + "\n", fuzzy=True)
    assert has(data, "getcwd")


# --- Phrase: "When there is no prefix (cursor is right after `.` ...), all applicable names are
#              returned."
#     Context: right after a dot.
def test_no_prefix_after_dot_returns_all(tmp_path):
    import os as _os
    data = complete_at(tmp_path, "import os\nos." + C + "\n")
    assert len(names(data)) == len([n for n in dir(_os) if not n.startswith("_")])


# --- Phrase: "When there is no prefix (... or at a blank position), all applicable names are
#              returned."
#     Context: blank position at module level.
def test_no_prefix_blank_position(tmp_path):
    data = complete_at(tmp_path, "widget = 1\n" + C + "\n")
    assert has(data, "widget") and has(data, "print") and has(data, "if")


# --- Phrase: "Name completion with an empty prefix returns all currently visible names plus
#              keywords, then applies the ordering rules in this spec."
#     Context: clarifications section; builtins + globals + keywords all present.
def test_empty_prefix_name_completion_contents(tmp_path):
    import builtins
    code = "widget = 1\n" + C + "\n"
    data = complete_at(tmp_path, code)
    expected = set(dir(builtins)) | {"widget"} | set(keyword.kwlist)
    assert set(names(data)) == expected
