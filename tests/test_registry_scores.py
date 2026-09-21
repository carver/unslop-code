"""bin/registry-scores: every Differs (v9) and Risk (v10) spelling the agents have used parses to the same score."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "registry-scores"
rs = types.ModuleType("registry_scores")
rs.__file__ = str(SCRIPT)
sys.modules["registry_scores"] = rs
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), rs.__dict__)

SECTION_STYLE = """## T1. Heading one
### Choice
Option (1), because the table lists no error.
### Differs
20 — the author might have wanted a 400.
"""
DASH_STYLE = """## T2. Heading two
**Choice** — Option (1).
**Differs** — 30 — the carve-out hints otherwise.
"""
BARE_STYLE = """## T3. Heading three
**Choice** Option (1).
**Differs** 10 — the exact id string is unlikely to be asserted.
"""
RISK_HEADING_STYLE = """## T4. Heading four
### Choice
Option (2).
### Risk: 25
the author's fixture probably has a trailing newline.
"""
RISK_BOLD_STYLE = """## T5. Heading five
**Choice** — Option (1).
**Risk** 5 — nothing tested turns on it.
"""
ALL = SECTION_STYLE + DASH_STYLE + BARE_STYLE + RISK_HEADING_STYLE + RISK_BOLD_STYLE


def test_every_differs_spelling_scores():
    got = {e["id"]: e["score"] for e in rs.entries(ALL)}
    assert got == {"T1": 20, "T2": 30, "T3": 10, "T4": 25, "T5": 5}


def test_choice_and_differs_text_survive_each_style():
    by_id = {e["id"]: e for e in rs.entries(ALL)}
    assert by_id["T1"]["choice"].startswith("Option (1), because")
    assert by_id["T3"]["choice"] == "Option (1)."
    assert by_id["T3"]["differs"].startswith("10 — the exact id")
    assert by_id["T4"]["choice"] == "Option (2)."
    assert by_id["T4"]["differs"].startswith("25 the author's fixture")


FULL = """# Registry

## T1. How many calls a failing request gets

### Spec Text
> retry it up to 3 times

### Choice
Four calls.

### Risk: 45
Three in all.

## T2. Rounding of money

### Spec Text
> "total": 12.45

### Choice
Two decimals.

### Risk: 40
The raw float.
"""


def test_an_entry_keeps_its_whole_text_and_matches_on_the_spec_quote_too():
    rows = rs.entries(FULL)
    assert rows[0]["text"].startswith("## T1. How many calls") and rows[0]["text"].rstrip().endswith("Three in all.")
    assert [r["id"] for r in rs.matching(rows, "retry it up to")] == ["T1"]  # only in the quoted spec text
    assert [r["id"] for r in rs.matching(rows, "money")] == ["T2"]
    assert [r["id"] for r in rs.matching(rows, "^T2$")] == ["T2"]  # an id selects its entry


def test_a_run_that_kept_no_registry_is_said_plainly(tmp_path, capsys):
    (tmp_path / "xjq" / "checkpoint_1" / "snapshot").mkdir(parents=True)
    import pytest
    with pytest.raises(SystemExit) as stop:
        rs.registry_text(tmp_path)
    assert "no AMBIGUITIES.md" in str(stop.value)


NEAR = """## T1. User aliases that shadow built-in type names
### Choice
Reject them.
### Risk: 25
The tests may allow it.

## T2. Mapping Parquet types onto the schema types
### Choice
Widen.
### Risk: 30
Narrowing.

## T3. Trailing newline in the type report
### Choice
One newline.
### Risk: 5
None.
"""


def test_words_of_a_test_id_drop_digits_and_the_words_every_test_id_has():
    assert rs.words("test_core_cases[correct_aliases/case12]") == {"aliases"}
    assert rs.words("TestErrors.test_tpm_gate") == {"tpm", "gate"}


def test_near_ranks_entries_by_how_rare_the_shared_words_are_and_names_them():
    rows = rs.entries(NEAR)
    got = rs.near(rows, rs.words("test_hidden_cases[hidden/type_alias_with_parquet]"))
    # "type" is in every entry, so it ranks nothing and T3 drops out; the tie goes to the higher Risk
    assert [(r["id"], hit) for r, hit in got] == [("T2", ["parquet", "type"]), ("T1", ["alias", "type"])]


def test_near_matches_a_plural_to_its_singular_but_not_a_short_prefix():
    rows = rs.entries(NEAR)
    assert [r["id"] for r, _ in rs.near(rows, rs.words("test_core_cases[correct_aliases/case1]"))] == ["T1"]
    # "new" is too short to match "newline" as its prefix
    assert [r["id"] for r, _ in rs.near(rows, rs.words("test_new_entries"))] == []
    assert rs.near(rows, rs.words("test_no_such_word")) == []
    assert rs.near([], {"alias"}) == []


def test_near_lets_the_tests_own_name_outweigh_the_words_around_it_and_lists_its_words_first():
    rows = rs.entries(NEAR)
    got = rs.near(rows, {"parquet", "schema"}, named={"alias"})
    assert [(r["id"], hit) for r, hit in got] == [("T1", ["alias"]), ("T2", ["parquet", "schema"])]
    assert [r["id"] for r, _ in rs.near(rows, {"parquet", "schema", "alias"})] == ["T2", "T1"]


def test_near_marks_a_long_entry_down():
    filler = " ".join(f"filler{chr(97 + i)}word" for i in range(26))
    long_entry = f"## T9. Aliases\n### Choice\n{filler}\n### Risk: 50\nx\n"
    rows = rs.entries(NEAR + "\n" + long_entry)
    assert [r["id"] for r, _ in rs.near(rows, {"alias"})] == ["T1", "T9"]
