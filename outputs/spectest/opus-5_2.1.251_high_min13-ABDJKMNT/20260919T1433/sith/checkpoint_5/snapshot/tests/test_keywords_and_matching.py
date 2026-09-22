"""Spec: Completion / 3. Keyword Completion, and Prefix Matching."""

import keyword


# Spec: "When in a name-completion context, also include Python keywords as
# completions."
def test_keywords_included_in_name_context(complete):
    names = complete("$\n").names
    assert {"import", "return", "lambda", "while"} <= set(names)


# Spec: "Keywords are filtered by the same prefix rules as names."
def test_keywords_filtered_by_prefix(complete):
    names = complete("wh$\n").names
    assert "while" in names
    assert "import" not in names


# Spec: keyword completions carry the keyword type and description.
def test_keyword_type_and_description(complete):
    item = complete("whil$\n").by_name("while")
    assert item["type"] == "keyword"
    assert item["description"] == "while"
    assert item["complete"] == "e"


# Spec: "also include Python keywords" - the full keyword list is offered.
def test_all_keywords_offered_with_empty_prefix(complete):
    items = complete("$\n").items
    offered = {item["name"] for item in items}
    assert set(keyword.kwlist) <= offered


# Spec: "By default, prefix matching is case-insensitive."
def test_prefix_matching_is_case_insensitive(complete):
    source = "CamelValue = 1\ncamel$\n"
    assert "CamelValue" in complete(source).names


def test_lowercase_name_matches_uppercase_prefix(complete):
    source = "lower_value = 1\nLOWER$\n"
    assert "lower_value" in complete(source).names


# Spec: "the characters of the query must appear in the name in order, but not
# necessarily contiguously."
def test_fuzzy_matching_is_subsequence(complete):
    source = "alphabet = 1\nabt$\n"
    assert "alphabet" in complete(source, fuzzy=True).names
    assert "alphabet" not in complete(source).names


def test_fuzzy_requires_characters_in_order(complete):
    source = "alphabet = 1\ntba$\n"
    assert "alphabet" not in complete(source, fuzzy=True).names


# Spec: "Fuzzy matching is also case-insensitive."
def test_fuzzy_matching_is_case_insensitive(complete):
    source = "AlphaBetaGamma = 1\nabg$\n"
    assert "AlphaBetaGamma" in complete(source, fuzzy=True).names


# Spec: fuzzy matching also applies after a dot.
def test_fuzzy_matching_applies_to_attributes(complete):
    names = complete("'text'.swh$\n", fuzzy=True).names
    assert "startswith" in names


# Spec: "When there is no prefix (cursor is right after `.` ...), all
# applicable names are returned."
def test_empty_prefix_after_dot_returns_all_attributes(complete):
    names = complete("'text'.$\n").names
    assert len(names) == len(dir(str))


# Spec: "... or at a blank position), all applicable names are returned."
def test_empty_prefix_returns_names_and_keywords(complete):
    names = complete("alpha = 1\n$\n").names
    assert "alpha" in names
    assert "print" in names
    assert "lambda" in names


# Spec clarification: "Attribute completion with an empty prefix ... never adds
# keywords."
def test_empty_prefix_after_dot_never_adds_keywords(complete):
    items = complete("'text'.$\n").items
    assert not [item for item in items if item["type"] == "keyword"]
