"""Spec section: Output Format / Ordering."""
from conftest import CURSOR, complete_at, names

C = CURSOR


def rank(name, typ):
    if typ == "keyword":
        return 3
    if name.startswith("__") and name.endswith("__"):
        return 2
    if name.startswith("_"):
        return 1
    return 0


# --- Phrase: "1. Public names (do not start with `_`) — sorted alphabetically,
#              case-insensitive."
#     Context: several public globals.
def test_public_names_sorted_case_insensitively(tmp_path):
    code = (
        "zebra = 1\n"
        "Apple = 2\n"
        "mango = 3\n"
        "Banana = 4\n"
        + C + "\n"
    )
    data = complete_at(tmp_path, code)
    ns = names(data)
    picked = [n for n in ns if n in {"zebra", "Apple", "mango", "Banana"}]
    assert picked == ["Apple", "Banana", "mango", "zebra"]


# --- Phrase: "2. Private names (start with `_` but not `__`)"
#     Context: private names come after all public names.
def test_private_names_after_public(tmp_path):
    code = (
        "class Holder:\n"
        "    _private_b = 1\n"
        "    zzz_public = 2\n"
        "    _private_a = 3\n"
        "\n"
        "Holder." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    ns = names(data)
    assert ns.index("zzz_public") < ns.index("_private_a") < ns.index("_private_b")


# --- Phrase: "3. Dunder names (start with `__` and end with `__`)"
#     Context: dunders come after private names.
def test_dunder_names_last_among_names(tmp_path):
    code = (
        "class Holder:\n"
        "    def __repr__(self):\n"
        "        pass\n"
        "    _private = 1\n"
        "    zzz_public = 2\n"
        "\n"
        "Holder." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    ns = names(data)
    assert ns.index("zzz_public") < ns.index("_private") < ns.index("__repr__")


# --- Phrase: "4. Keywords — sorted alphabetically after all names."
#     Context: keywords occupy the tail of the list.
def test_keywords_last(tmp_path):
    data = complete_at(tmp_path, C + "\n")
    comps = data["completions"]
    first_kw = next(i for i, c in enumerate(comps) if c["type"] == "keyword")
    assert all(c["type"] == "keyword" for c in comps[first_kw:])


# --- Phrase: "Keywords — sorted alphabetically after all names."
#     Context: keyword block itself is case-insensitively alphabetical.
def test_keywords_sorted(tmp_path):
    data = complete_at(tmp_path, C + "\n")
    kws = [c["name"] for c in data["completions"] if c["type"] == "keyword"]
    assert kws == sorted(kws, key=str.lower)


# --- Phrase: "Completions are sorted in this order: 1..4"
#     Context: the whole list is non-decreasing in (rank, lowercased name).
def test_global_ordering_invariant(tmp_path):
    code = (
        "import os\n"
        "_hidden = 1\n"
        "Visible = 2\n"
        + C + "\n"
    )
    data = complete_at(tmp_path, code)
    keys = [(rank(c["name"], c["type"]), c["name"].lower())
            for c in data["completions"]]
    assert keys == sorted(keys)


# --- Phrase: "Within each group, break ties by case-insensitive alphabetical order."
#     Context: names differing only by case sit adjacently, deterministically.
def test_case_variant_tie(tmp_path):
    code = "abc = 1\nABC_z = 2\n" + C + "\n"
    data = complete_at(tmp_path, code)
    ns = names(data)
    assert ns.index("abc") < ns.index("ABC_z")


# --- Phrase: "Ordering" applied to attribute completion.
#     Context: module attributes are alphabetical too.
def test_attribute_ordering(tmp_path):
    data = complete_at(tmp_path, "import os\nos." + C + "\n")
    ns = names(data)
    assert ns == sorted(ns, key=str.lower)


# --- Phrase: "Dunder names (start with `__` and end with `__`)" (T11)
#     Context: a name starting with `__` but not ending with `__` is not a dunder.
def test_double_underscore_non_dunder_sorts_as_private(tmp_path):
    code = (
        "class Holder:\n"
        "    __mangled = 1\n"
        "    def __repr__(self):\n"
        "        pass\n"
        "    zzz = 2\n"
        "\n"
        "Holder." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    ns = names(data)
    assert ns.index("zzz") < ns.index("__mangled") < ns.index("__repr__")
