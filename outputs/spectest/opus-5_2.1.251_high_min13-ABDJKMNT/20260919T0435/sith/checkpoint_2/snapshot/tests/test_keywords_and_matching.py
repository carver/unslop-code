"""Keyword completion, prefix matching, fuzzy matching."""
import keyword


# Spec: "When in a name-completion context, also include Python keywords as completions."
def test_keywords_appear_in_name_context(complete):
    result = complete("|\n")
    keywords = {c["name"] for c in result.completions if c["type"] == "keyword"}
    assert set(keyword.kwlist) <= keywords


# Spec: "Keywords are filtered by the same prefix rules as names."
def test_keywords_are_prefix_filtered(complete):
    result = complete("imp|\n")
    keywords = [c["name"] for c in result.completions if c["type"] == "keyword"]
    assert keywords == ["import"]


# Spec: "For keywords: the keyword itself." (description) and type `keyword`.
def test_keyword_completion_shape(complete):
    completion = [c for c in complete("whil|\n").completions if c["type"] == "keyword"][0]
    assert completion == {
        "name": "while",
        "complete": "e",
        "type": "keyword",
        "description": "while",
    }


# Spec: "Keywords are not included in attribute completion (after `.`)."
def test_keywords_absent_after_dot(complete):
    result = complete("import os\nos.|\n")
    assert all(c["type"] != "keyword" for c in result.completions)


# Spec: "By default, prefix matching is case-insensitive."
def test_prefix_matching_is_case_insensitive(complete):
    source = "AlphaBeta = 1\nalp|\n"
    assert "AlphaBeta" in complete(source).names


def test_uppercase_query_matches_lowercase_name(complete):
    source = "alphabeta = 1\nALP|\n"
    assert "alphabeta" in complete(source).names


# Spec: "the first `len(prefix)` characters of the matched name are stripped regardless of case."
def test_complete_strips_by_character_count(complete):
    source = "AlphaBeta = 1\nalp|\n"
    assert complete(source).by_name("AlphaBeta")["complete"] == "haBeta"


# Spec: "If no prefix, equals `name`."
def test_complete_equals_name_with_no_prefix(complete):
    source = "alpha = 1\n|\n"
    assert complete(source).by_name("alpha")["complete"] == "alpha"


# Spec: "When `--fuzzy` is passed ... the characters of the query must appear in the name in
#        order, but not necessarily contiguously."
def test_fuzzy_matches_subsequence(complete):
    source = "alpha_beta_gamma = 1\nabg|\n"
    assert "alpha_beta_gamma" not in complete(source).names
    assert "alpha_beta_gamma" in complete(source, fuzzy=True).names


def test_fuzzy_requires_characters_in_order(complete):
    # "dg" only matches gamma_delta if the characters may be reordered.
    source = "gamma_delta = 1\ndg|\n"
    assert "gamma_delta" not in complete(source, fuzzy=True).names


# Spec: "Fuzzy matching is also case-insensitive."
def test_fuzzy_is_case_insensitive(complete):
    source = "AlphaBetaGamma = 1\nabg|\n"
    assert "AlphaBetaGamma" in complete(source, fuzzy=True).names


# Spec: fuzzy still strips `len(prefix)` characters from the front of the name.
def test_fuzzy_complete_strips_by_character_count(complete):
    source = "alpha_beta_gamma = 1\nabg|\n"
    assert complete(source, fuzzy=True).by_name("alpha_beta_gamma")["complete"] == "ha_beta_gamma"


# Spec: fuzzy also applies to attribute completion.
def test_fuzzy_applies_after_a_dot(complete):
    result = complete("import os\nos.gtcw|\n", fuzzy=True)
    assert "getcwd" in result.names


# Spec: "When there is no prefix (cursor is right after `.` or at a blank position), all
#        applicable names are returned."
def test_no_prefix_returns_everything_applicable(complete):
    source = "alpha = 1\nbeta = 2\n|\n"
    names = set(complete(source).names)
    assert {"alpha", "beta", "print", "import", "lambda"} <= names


# Spec: "Name completion with an empty prefix returns all currently visible names plus keywords"
def test_empty_prefix_includes_keywords(complete):
    types = {c["type"] for c in complete("alpha = 1\n|\n").completions}
    assert "keyword" in types
