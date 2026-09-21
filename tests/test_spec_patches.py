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


def test_the_page_lists_every_patch_with_the_risk_blocks_hidden_until_the_toggle():
    page = sp.build()
    assert page.count('<article class="patch"') == sum(len(p) for p in sp.patch_files().values()) >= 30
    assert '<input type="checkbox" id="show-risk">' in page
    assert page.count('<div class="risk" hidden>') == page.count('<div class="hunk">') >= 34
    assert 'id="rejector-01"' in page and "JSONL ranks equal to CSV under the authoritative strategy" in page
    assert "entered v1, reworded in v3" in page
