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


def test_parse_result_extracts_the_array_keyed_by_label():
    parsed = judge.parse_result('Sure.\n[{"id": "A1", "choice": 2, "rule": "x"}, {"id": "A2", "choice": "other"}]\n')
    assert parsed["A1"] == {"id": "A1", "choice": 2, "rule": "x"}
    assert parsed["A2"]["choice"] == "other"
    assert judge.parse_result("no json here") is None
    assert judge.parse_result('{"choice": 1}') is None


def test_parse_result_accepts_bare_objects_without_an_array():
    parsed = judge.parse_result('{"id":"A1","choice":1,"rule":"x [1] y"}\n{"id":"A2","choice":"other","rule":"z"}\n')
    assert parsed["A1"]["choice"] == 1 and parsed["A2"]["choice"] == "other"


def test_user_prompt_labels_entries_and_numbers_alternatives_in_shuffled_order():
    e1, e2 = judge.parse_registry(SAMPLE)
    text = judge.user_prompt([("A1", e1, [2, 0, 1]), ("A2", e2, [1, 0])])
    assert "### A1: Does `x` count the header?" in text
    assert "1. Something else." in text
    assert "3. `rowid` numbers the data rows." in text
    assert "### A2: Free-form choice" in text and "1. two\n2. one" in text


def test_partition_is_random_per_sample_and_covers_every_entry():
    entries = [judge.Entry(id=f"T{i}", title="", spec_text="", alternatives=["a", "b"], choice=1, checkpoint=3)
               for i in range(25)]
    batches = judge.partition(entries, "choose", 0, 10)
    assert sorted(len(b) for b in batches) == [8, 8, 9]
    assert sorted(e.id for b in batches for e in b) == sorted(e.id for e in entries)
    assert batches == judge.partition(entries, "choose", 0, 10)
    assert batches != judge.partition(entries, "choose", 1, 10)
    assert judge.partition([], "choose", 0, 10) == []


def test_plan_skips_judged_entries_and_groups_by_checkpoint():
    entries = [judge.Entry(id=f"T{i}", title="", spec_text="", alternatives=["a", "b"], choice=1, checkpoint=1 + i % 2)
               for i in range(6)]
    done = {("T0", "choose", 0), ("T2", "choose", 0), ("T4", "choose", 0)}  # all of checkpoint 1, sample 0
    plan = judge.build_plan(entries, ["choose"], 2, 15, done)
    assert [(sorted(e.id for e in b), v, s) for b, v, s in plan] == [
        (["T0", "T2", "T4"], "choose", 1),
        (["T1", "T3", "T5"], "choose", 0),
        (["T1", "T3", "T5"], "choose", 1),
    ]


def test_variants_are_the_eight_combinations():
    assert len(judge.VARIANTS) == 8
    assert judge.VARIANTS["rule+both+impl"] == ("rule", True, True)
    assert judge.VARIANTS["choose"] == ("choose", False, False)
    sp = judge.system_prompt("SPEC", "choose+impl")
    assert judge.IMPL_TEXT in sp and judge.BOTH_TEXT not in sp and sp.endswith("SPEC")


PATCH = """--- a/datagate/checkpoint_2.md
+++ b/datagate/checkpoint_2.md
@@ -30,7 +30,7 @@
 context
-`_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file row number). `rowid` is not in `columns`.
+`_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file row number, starting at the header). `rowid` is not in `columns`.
 context
"""  # noqa: E501  a spec sentence, quoted verbatim


def test_patch_sentences_pairs_removed_and_added_lines():
    pairs = judge.patch_sentences(PATCH)
    assert len(pairs) == 1
    assert pairs[0][0].startswith("`_shape=objects`") and "starting at the header" in pairs[0][1]


def test_rewrite_quotes_replaces_a_wrapped_quoted_sentence():
    e = judge.parse_registry(SAMPLE)[0]
    e.spec_text = "> `_shape=objects`: `rows` is objects and includes `rowid` (1-based\n> source-file row number)."
    untouched = judge.parse_registry(SAMPLE)[1]
    changed = judge.rewrite_quotes([e, untouched], judge.patch_sentences(PATCH))
    assert changed == ["T7"]
    assert e.spec_text == (
        "> `_shape=objects`: `rows` is objects and includes `rowid` "
        "(1-based source-file row number, starting at the header)."
    )
    assert untouched.spec_text == "> text"


def test_infer_problem_finds_the_single_registry_holder(tmp_path):
    (tmp_path / "xjq/checkpoint_1/snapshot").mkdir(parents=True)
    (tmp_path / "xjq/checkpoint_1/snapshot/AMBIGUITIES.md").write_text("")
    (tmp_path / "other/checkpoint_1").mkdir(parents=True)  # no registry, ignored
    assert judge.infer_problem(tmp_path) == "xjq"


HEADING_SAMPLE = """# Ambiguities

## T13. What "direct text extraction" produces per matched element

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements.

> `selector::text` returns direct text;

### Alternatives
1. Every direct child text node is its own result, so `<a>x<b/>z</a>` yields two
   results, `x` and `z`, on two lines.
2. The direct text children of an element are concatenated into a single result
   per element.

### Choice
Alternative 1. The `::text` rule spells the descendant mode as "one text node per
line".

### Risk: 40
Most likely divergence: the author joins the text.

## T14. Whether descendant text includes the matched element's own text

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. All text nodes in the subtree.
2. Strictly below the children.

### Choice
Alternative 2, because of the combinator.
"""


def test_parse_registry_reads_the_heading_layout_too():
    """min9-and-later registries write `## T1. title` and `### Section` headings, not bold labels."""
    entries = judge.parse_registry(HEADING_SAMPLE)
    assert [e.id for e in entries] == ["T13", "T14"]
    t13 = entries[0]
    assert t13.title == 'What "direct text extraction" produces per matched element'
    assert t13.spec_text.startswith("> `-t`, `--text`") and "`selector::text`" in t13.spec_text
    assert "Risk" not in t13.spec_text
    assert len(t13.alternatives) == 2 and t13.alternatives[1].startswith("The direct text children")
    assert t13.choice == 1 and "Risk" not in t13.choice_raw and "Most likely" not in t13.choice_raw
    assert entries[1].choice == 2
