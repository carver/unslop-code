"""report/spec_patches.py: the spec-patches page, built from specs/ with the Risk scores behind a toggle."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import spec_patches as sp  # noqa: E402


def test_changed_words_are_marked_and_the_rest_is_escaped():
    old, new = sp.marked("Any additional `force` <value> is 400.", "Any `force` <value> is HTTP 400.")
    assert old == 'Any<mark class="del"> additional</mark> `force` &lt;value&gt; is 400.'
    assert new == 'Any `force` &lt;value&gt; is<mark class="add"> HTTP</mark> 400.'


def test_an_added_line_is_marked_whole():
    assert sp.marked(None, "- Send requests in input order.") == (
        None, '<mark class="add">- Send requests in input order.</mark>')


def side(scores, runs=None, unasked=0, unscored=0, unconfirmed=0):
    return {"runs": len(scores) + unasked + unscored if runs is None else runs, "scores": scores,
            "unasked": unasked, "unscored": unscored, "unconfirmed": unconfirmed}


def test_risk_sentence_gives_range_and_median_and_accounts_for_every_wrong_run():
    text = sp.risk_sentence(side([35, 35, 45, 35], unasked=2, unscored=1))
    assert text == ("<b>Risk 35–45, median 35</b> in the 4 runs that read this wrong and had asked the question. "
                    "2 more read it wrong without asking it. 1 more kept a registry from before the Risk line.")
    assert sp.risk_sentence(side([40])) == (
        "<b>Risk 40</b> in the 1 run that read this wrong and had asked the question.")
    assert sp.risk_sentence(side([30, 40])).startswith("<b>Risk 30–40, median 35</b> in the 2 runs")
    assert sp.risk_sentence(side([45, 45, 45])).startswith("<b>Risk 45</b> in all 3 runs that read this wrong")


def test_risk_sentence_without_scores_says_why():
    assert sp.risk_sentence(side([])) == "No run that kept a registry read this wrong."
    assert sp.risk_sentence(side([], unasked=3)) == (
        "No score: 3 runs read this wrong and none had asked the question.")
    assert sp.risk_sentence(side([], unasked=1, unscored=2)) == (
        "No score: 3 runs failed the tests. 1 had not asked the question. 2 kept a registry from before the Risk line.")
    slipped = {**side([30], runs=2), "slips": 1}
    assert sp.risk_sentence(slipped, slip_prompts=["min12-ABDJKMN"]).endswith(
        "1 more (prompt min12-ABDJKMN) chose the tests' reading in the registry and failed the tests anyway: "
        "a slip in the code, not a reading.")
    assert sp.prompt_of("opus-5_2.1.251_high_min12-ABDJKMN-specv3/20260910T0934") == "min12-ABDJKMN"


def test_an_unconfirmed_pick_stops_the_build():
    with pytest.raises(SystemExit, match="bin/patch-risk rejector --candidates"):
        sp.risk_sentence(side([40], unconfirmed=1), problem="rejector")


def test_strip_puts_each_score_on_a_0_to_100_scale_and_stacks_repeats():
    svg = sp.strip([(45, "min13 20260919"), (45, "min11 20260908"), (20, "min12 20260914")])
    assert svg.count('class="strip-dot"') == 3
    xs = [float(x) for x in __import__("re").findall(r'<circle class="strip-dot" cx="([\d.]+)"', svg)]
    assert xs[0] < xs[1] == xs[2]  # 20 left of the two 45s, which share an x
    ys = [float(y) for y in __import__("re").findall(r'<circle class="strip-dot" cx="[\d.]+" cy="([\d.]+)"', svg)]
    assert ys[1] != ys[2]  # and are stacked, not overprinted
    assert "<title>Risk 45 · min13 20260919</title>" in svg
    assert 'class="strip-median"' in svg and ">0<" in svg and ">100<" in svg
    assert sp.strip([]) == ""


def test_history_names_the_version_a_patch_entered_and_a_later_rewording(tmp_path):
    body = "\n--- a/p/checkpoint_1.md\n+++ b/p/checkpoint_1.md\n@@ -1 +1 @@\n-old\n+new\n"
    reworded = body.replace("+new", "+newer")
    for version, text in (("v1", "title\n" + body), ("v2", "title\n" + body), ("v3", "title\n" + reworded)):
        (tmp_path / "p" / version).mkdir(parents=True)
        (tmp_path / "p" / version / "01-x.patch").write_text(text)
    (tmp_path / "p" / "v3" / "02-y.patch").write_text("t\n" + body)
    assert sp.history("p", "01-x.patch", tmp_path) == ("v1", "v3")
    assert sp.history("p", "02-y.patch", tmp_path) == ("v3", None)


def test_the_page_lists_every_patch():
    page = sp.build()
    assert page.count('<article class="patch"') == sum(len(p) for p in sp.patch_files().values()) >= 30
    assert 'id="rejector-01"' in page and "JSONL ranks equal to CSV under the authoritative strategy" in page
    assert "entered v1, reworded in v3" in page


CURVE = {
    "runs": 2, "bugs": 2, "bug_instances": 4, "entries": 4,
    "thresholds": [
        {"risk": 45, "addressed": 1, "hits": 1, "found": 1, "remaining": 3},
        {"risk": 35, "addressed": 3, "hits": 2, "found": 2, "remaining": 2},
        {"risk": 0, "addressed": 4, "hits": 2, "found": 2, "remaining": 2},
    ],
    "gain": [(p, 0 if p == 0 else 0.5) for p in range(101)],
}


def test_the_chart_section_stacks_three_bands_per_run_beside_the_gain_curve_with_a_table():
    section = sp.chart_section(CURVE)
    assert section.count("<svg") == 2 and section.count('class="band') == 3 and section.count('class="series') == 1
    # per run (2 runs): at Risk >= 35, 1 bug addressed, 1 remaining, 0.5 changes that fix no known bug
    assert ("Risk ≥ 35, per run: 1.0 bugs addressed, 1.0 still unfound, "
            "0.5 changes that fix no known bug") in section
    assert "Top 50% of a registry by Risk: 50% of its bugs found (25% in random order)" in section
    assert section.count('class="key-swatch') == 3
    assert "<table" in section and "<td>45</td><td>1</td><td>1</td><td>100.0%</td><td>3</td>" in section
    assert "2 of 4 stay unfound at any level" in section


def test_band_path_closes_a_stepped_area_between_two_edges():
    assert sp.band_path([(10, 50), (30, 50), (30, 20)], [(10, 60), (30, 60), (30, 60)]) == "M10,50H30V20V60H10Z"


def test_a_step_path_holds_each_value_until_the_next_level():
    assert sp.step_path([(10, 50), (30, 50), (30, 20), (60, 20)]) == "M10,50H30V20H60"


def test_the_page_has_no_toggle_and_shows_every_risk_block():
    page = sp.build()
    assert "show-risk" not in page and '<div class="risk" hidden>' not in page
    assert page.count('<div class="risk">') == page.count('<div class="hunk">') >= 34
    assert page.index('id="risk-charts"') < page.index('<nav class="toc">')


def test_the_per_problem_section_is_one_card_per_problem_in_order_of_difficulty_on_shared_scales():
    other = {**CURVE, "runs": 1, "thresholds": [
        {"risk": 40, "addressed": 9, "hits": 1, "found": 1, "remaining": 1},
        {"risk": 0, "addressed": 20, "hits": 1, "found": 1, "remaining": 1}]}
    section = sp.problem_section({"rejector": CURVE, "xjq": other}, {"rejector": "Hard", "xjq": "Easy"})
    assert section.index("xjq") < section.index("rejector")  # Easy before Hard
    assert "xjq</span> Easy · 1 run · 2 bugs" in section and "rejector</span> Hard · 2 runs · 2 bugs" in section
    assert section.count('<div class="card">') == 2 and section.count("<svg") == 4
    assert section.count('class="key-swatch') == 3  # one shared legend, not one per chart
    # both stacked charts share the y scale of the tallest: xjq's 20 entries per run
    tops = __import__("re").findall(r'<text class="tick" x="[\d.]+" y="([\d.]+)" text-anchor="end">20</text>', section)
    assert len(tops) == 2 and tops[0] == tops[1]


def test_nice_step_keeps_the_axis_close_to_the_data():
    assert [sp.nice_step(top) for top in (4.7, 20, 76, 108, 260)] == [1, 5, 20, 25, 100]
