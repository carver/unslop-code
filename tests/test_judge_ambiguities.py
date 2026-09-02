"""Parser and answer-mapping tests for bin/judge-ambiguities."""
import sys
import types
from pathlib import Path

# The script has no .py suffix, so it is loaded by hand; dataclasses need the
# module registered in sys.modules while the class bodies run.
SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "judge-ambiguities"
judge = types.ModuleType("judge")
judge.__file__ = str(SCRIPT)
sys.modules["judge"] = judge
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), judge.__dict__)

SAMPLE = """# Ambiguities

---

## T7 — Does `x` count the header?

**Spec Text**
> `rowid` (1-based source-file row number).

**Alternatives**
1. The header is line 1, so the first data row is
   `rowid` 2.
2. `rowid` numbers the data rows.
3. Something else.

**Choice** — (2). Because reasons, with a mention of (1) and (3).
*Tests:* `t.py::a`.

---

## I1 — Free-form choice

**Spec Text**
> text

**Alternatives**
1. one
2. two

**Choice** — Both satisfy SPEC, so the test only checks status.
"""


def test_parse_registry_splits_sections_and_alternatives():
    entries = judge.parse_registry(SAMPLE)
    assert [e.id for e in entries] == ["T7", "I1"]
    t7 = entries[0]
    assert t7.title == "Does `x` count the header?"
    assert t7.spec_text == "> `rowid` (1-based source-file row number)."
    assert t7.alternatives == [
        "The header is line 1, so the first data row is `rowid` 2.",
        "`rowid` numbers the data rows.",
        "Something else.",
    ]
    assert t7.choice == 2
    assert "Tests" not in t7.spec_text


def test_choice_without_a_number_is_none():
    assert judge.parse_registry(SAMPLE)[1].choice is None


def test_shuffle_is_deterministic_and_maps_back():
    e = judge.parse_registry(SAMPLE)[0]
    order = judge.shuffled_order(e, "choose", 0)
    assert sorted(order) == [0, 1, 2]
    assert order == judge.shuffled_order(e, "choose", 0)
    assert order != judge.shuffled_order(e, "choose", 1) or order != judge.shuffled_order(e, "rule", 0)
    # the judge answers in shuffled numbering; position k holds original alternative order[k-1]
    for k in (1, 2, 3):
        assert judge.normalize_choice(k, order) == order[k - 1] + 1
    assert judge.normalize_choice("2", order) == order[1] + 1


def test_normalize_choice_handles_other_and_both():
    order = [1, 0]
    assert judge.normalize_choice("other", order) == "other"
    assert judge.normalize_choice("both", order) == "both"
    assert judge.normalize_choice("1 and 2", order) == "both"
    assert judge.normalize_choice(7, order) == "other"
    assert judge.normalize_choice(True, order) == "other"


def test_parse_result_extracts_json_from_prose():
    assert judge.parse_result('Sure.\n{"choice": 2, "rule": "x"}\n') == {"choice": 2, "rule": "x"}
    assert judge.parse_result("no json here") is None


def test_user_prompt_numbers_alternatives_in_shuffled_order():
    e = judge.parse_registry(SAMPLE)[0]
    text = judge.user_prompt(e, [2, 0, 1])
    assert "1. Something else." in text
    assert "3. `rowid` numbers the data rows." in text


def test_variants_are_the_eight_combinations():
    assert len(judge.VARIANTS) == 8
    assert judge.VARIANTS["rule+both+impl"] == ("rule", True, True)
    assert judge.VARIANTS["choose"] == ("choose", False, False)
    sp = judge.system_prompt("SPEC", "choose+impl")
    assert judge.IMPL_TEXT in sp and judge.BOTH_TEXT not in sp and sp.endswith("SPEC")
