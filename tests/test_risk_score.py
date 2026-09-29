"""report/risk_score.py: the charts of what reading a registry from its highest Risk down finds."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import risk_score as rs  # noqa: E402


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
    section = rs.chart_section(CURVE)
    assert section.count("<svg") == 2 and section.count('class="band') == 3 and section.count('class="series') == 1
    # per run (2 runs): at Risk >= 35, 1 bug addressed, 1 remaining, 0.5 changes that fix no known bug
    assert ("Risk ≥ 35, per run: 1.0 bugs addressed, 1.0 still unfound, "
            "0.5 changes that fix no known bug") in section
    assert "Top 50% of a registry by Risk: 50% of its bugs found (25% in random order)" in section
    assert section.count('class="key-swatch') == 3
    assert "<table" in section and "<td>45</td><td>1</td><td>1</td><td>100.0%</td><td>3</td>" in section
    assert "2 of 4 stay unfound at any level" in section


def test_band_path_closes_a_stepped_area_between_two_edges():
    assert rs.band_path([(10, 50), (30, 50), (30, 20)], [(10, 60), (30, 60), (30, 60)]) == "M10,50H30V20V60H10Z"


def test_a_step_path_holds_each_value_until_the_next_level():
    assert rs.step_path([(10, 50), (30, 50), (30, 20), (60, 20)]) == "M10,50H30V20H60"


def test_the_per_problem_section_is_one_card_per_problem_in_order_of_difficulty_on_shared_scales():
    other = {**CURVE, "runs": 1, "thresholds": [
        {"risk": 40, "addressed": 9, "hits": 1, "found": 1, "remaining": 1},
        {"risk": 0, "addressed": 20, "hits": 1, "found": 1, "remaining": 1}]}
    section = rs.problem_section({"rejector": CURVE, "xjq": other}, {"rejector": "Hard", "xjq": "Easy"})
    assert section.index("xjq") < section.index("rejector")  # Easy before Hard
    assert "xjq</span> Easy · 1 run · 2 bugs" in section and "rejector</span> Hard · 2 runs · 2 bugs" in section
    assert section.count('<div class="card">') == 2 and section.count("<svg") == 4
    assert section.count('class="key-swatch') == 3  # one shared legend, not one per chart
    # both stacked charts share the y scale of the tallest: xjq's 20 entries per run
    tops = re.findall(r'<text class="tick" x="[\d.]+" y="([\d.]+)" text-anchor="end">20</text>', section)
    assert len(tops) == 2 and tops[0] == tops[1]


def test_highlights_quote_the_figures_of_the_curves_they_talk_about():
    def curve(top20, ceiling, unfound, instances):
        gain = [(p, ceiling if p == 100 else top20 if p == 20 else 0) for p in range(101)]
        return {**CURVE, "bug_instances": instances, "gain": gain,
                "thresholds": [{"risk": 0, "addressed": 10, "hits": 1, "found": 1, "remaining": unfound}]}
    curves = {"rejector": curve(0.48, 0.58, 20, 48), "datagate": curve(0.38, 0.85, 9, 62),
              "xjq": curve(0.15, 0.71, 13, 45), "mvvault": curve(0.13, 0.40, 18, 30)}
    text = " ".join(rs.problem_highlights(curves).split())  # the prose wraps in the source
    assert "finds 38% of its bugs (17% in random order), and on xjq 15% (14%)" in text
    assert "finds 48% of its bugs, against 12% in random order" in text
    assert "60% of mvvault's bug instances" in text
    assert rs.problem_highlights({"rejector": curves["rejector"]}) == ""  # nothing to compare


def test_the_stacked_chart_uses_a_log_axis_so_a_few_bugs_are_readable_under_many_changes():
    levels = [(45, [0.0, 5.0, 1.0]), (0, [3.0, 2.0, 80.0])]
    svg = rs.stacked_chart("t", levels, (50, 0), [50, 0], "x", ["a", "b"])
    ticks = re.findall(r'<text class="tick" x="[\d.]+" y="[\d.]+" text-anchor="end">([^<]+)</text>', svg)[:-1]
    assert ticks == ["0", "1", "2", "5", "10", "20", "50", "100"]
    at = [float(y) for y in re.findall(r'<text class="tick" x="[\d.]+" y="([\d.]+)" text-anchor="end">', svg)][:-1]
    ys = dict(zip(ticks, at, strict=True))
    assert ys["1"] - ys["10"] == ys["10"] - ys["100"]  # a decade is a decade, wherever it sits
    assert ys["0"] > ys["1"]  # zero has a place below the first decade, so an empty band still draws
    assert "log scale" in svg


def test_the_page_charts_the_pooled_runs_then_each_problem_and_links_the_patches():
    page = rs.build()
    assert page.index('id="risk-charts"') < page.index('id="risk-by-problem"')
    assert 'href="spec-patches.html"' in page and '<article class="patch"' not in page
