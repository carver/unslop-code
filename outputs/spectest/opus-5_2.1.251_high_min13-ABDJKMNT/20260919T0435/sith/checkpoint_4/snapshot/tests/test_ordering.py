"""Result ordering rules."""


def _group_of(name):
    if name.startswith("__") and name.endswith("__"):
        return 2
    if name.startswith("_"):
        return 1
    return 0


# Spec: "1. Public names (do not start with `_`) - sorted alphabetically, case-insensitive."
def test_public_names_sorted_case_insensitively(complete):
    source = "Zeta = 1\nalpha = 2\nBeta = 3\ndelta = 4\n|\n"
    names = complete(source).names
    ours = [n for n in names if n in {"Zeta", "alpha", "Beta", "delta"}]
    assert ours == sorted(ours, key=str.lower)


# Spec: "2. Private names (start with `_` but not `__`)" come after public names.
def test_private_names_follow_public_names(complete):
    source = "_private = 1\nzpublic = 2\n|\n"
    names = complete(source).names
    assert names.index("zpublic") < names.index("_private")


# Spec: "3. Dunder names (start with `__` and end with `__`)" come after private names.
def test_dunder_names_follow_private_names(complete):
    source = "_private = 1\n__dunder__ = 2\n|\n"
    names = complete(source).names
    assert names.index("_private") < names.index("__dunder__")


# Spec: groups are contiguous - public, then private, then dunder.
def test_name_groups_are_contiguous_and_ordered(complete):
    source = "_p = 1\n__d__ = 2\npub = 3\n|\n"
    names = [c["name"] for c in complete(source).completions if c["type"] != "keyword"]
    groups = [_group_of(n) for n in names]
    assert groups == sorted(groups)


# Spec: "4. Keywords - sorted alphabetically after all names."
def test_keywords_come_after_all_names(complete):
    completions = complete("alpha = 1\n_p = 2\n__d__ = 3\n|\n").completions
    kinds = [c["type"] == "keyword" for c in completions]
    assert kinds == sorted(kinds)


def test_keywords_are_sorted_alphabetically(complete):
    keywords = [c["name"] for c in complete("|\n").completions if c["type"] == "keyword"]
    assert keywords == sorted(keywords, key=str.lower)


# Spec: "Within each group, break ties by case-insensitive alphabetical order."
def test_full_ordering_within_each_group(complete):
    source = "_b = 1\n_A = 2\n|\n"
    names = complete(source).names
    assert names.index("_A") < names.index("_b")


# Spec: attribute completions obey the same grouping.
def test_attribute_ordering_groups(complete):
    source = "'abc'.|\n"
    names = complete(source).names
    groups = [_group_of(n) for n in names]
    assert groups == sorted(groups)
    public = [n for n in names if _group_of(n) == 0]
    assert public == sorted(public, key=str.lower)
