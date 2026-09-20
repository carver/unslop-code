"""report/uplift_grid.py: the implementation-against-tests section."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import uplift_grid  # noqa: E402


def part(loc, ast_lines, erosion, cloned):
    return {"loc": loc, "ast_lines": ast_lines, "ast": ast_lines / loc, "erosion": erosion, "cloned": cloned}


def row(name, prompt, impl, test, whole, runs=2):
    return {"name": name, "prompt": prompt, "runs": runs, "impl": impl, "test": test, "all": whole,
            "test_share": test["loc"] / (impl["loc"] + test["loc"])}


# Scores are means over the problems, each problem counting once; the ALL rows only lend their line counts.
ROWS = [
    row("xjq", "just-solve", part(100, 50, 0.8, 0.04), part(100, 5, 0.9, 0.06), part(200, 40, 0.34, 0.05)),
    row("sith", "just-solve", part(900, 270, 0.4, 0.06), part(400, 20, 0.5, 0.06), part(1300, 338, 0.26, 0.06)),
    row("ALL", "just-solve", part(1000, 400, 0.44, 0.058), part(500, 50, 0.6, 0.06), part(1500, 450, 0.27, 0.059)),
    row("xjq", "min12-ABDJKMN", part(80, 16, 0.2, 0.02), part(500, 5, 0.0, 0.3), part(580, 29, 0.05, 0.26)),
    row("sith", "min12-ABDJKMN", part(720, 288, 0.7, 0.04), part(1500, 15, 0.04, 0.1), part(2220, 333, 0.15, 0.08)),
    row("ALL", "min12-ABDJKMN", part(800, 240, 0.65, 0.038), part(2000, 40, 0.03, 0.15), part(2800, 280, 0.14, 0.12)),
]


REPOS = [
    row("flask", None, part(100, 10, 0.4, 0.08), part(100, 2, 0.2, 0.1), part(200, 12, 0.3, 0.09)),
    row("django", None, part(100, 20, 0.5, 0.04), part(300, 6, 0.1, 0.1), part(400, 26, 0.2, 0.07)),
]


def test_the_table_has_one_row_per_prompt_under_the_page_names():
    html = uplift_grid.split_section(ROWS, REPOS)
    assert html.count("<tr><td>") == 3
    assert "<td>spectest</td>" in html and "min12" not in html


def test_the_note_gives_the_drops_in_share_and_in_absolute_flagged_lines():
    html = uplift_grid.split_section(ROWS, REPOS)
    assert "share falls 57%" in html  # whole snapshot, problem means: (0.20 + 0.26) / 2 to (0.05 + 0.15) / 2
    assert "it falls 25%" in html  # implementation files: (0.50 + 0.30) / 2 to (0.20 + 0.40) / 2
    assert "implementation lines per run falls 40%</b> (200 to 120)" in html
    assert "4.0 times the test code" in html


def test_the_human_row_is_the_mean_of_the_repositories():
    human = uplift_grid.human_mean(REPOS)
    assert round(human["impl"]["ast"], 3) == 0.15
    assert human["test_share"] == 0.625
    html = uplift_grid.split_section(ROWS, REPOS)
    assert "<td>human, 2 repositories</td>" in html
    assert "2.0 times the human one" in html  # 0.30 against 0.15
    assert "0.45 against 0.45" in html  # erosion: the mean of 0.2 and 0.7, not sith's weight in the pooled 0.65


def test_line_counts_are_per_run_so_a_prompt_with_fewer_runs_compares():
    once = [r | {"prompt": "anti_slop"} for r in ROWS[:2]]
    once.append(row("ALL", "anti_slop", part(500, 200, 0.44, 0.058), part(250, 25, 0.6, 0.06),
                    part(750, 225, 0.27, 0.059), runs=1))
    html = uplift_grid.split_section(ROWS + once, REPOS)
    just_solve, anti_slop = (uplift_grid.prompt_row(ROWS + once, p) for p in ("just-solve", "anti_slop"))
    assert (just_solve["runs"], anti_slop["runs"]) == (2, 1)
    assert just_solve["impl"]["loc"] == anti_slop["impl"]["loc"] == 500
    assert "anti-slop writes 1.0 times the test code" in html


def test_a_prompts_test_share_is_the_mean_of_its_problems_as_the_human_one_is_of_repositories():
    assert uplift_grid.prompt_row(ROWS, "just-solve")["test_share"] == (100 / 200 + 400 / 1300) / 2


def test_the_test_share_panel_names_each_prompts_problems_and_the_human_spread():
    panel = uplift_grid.test_share_panel(ROWS, REPOS)
    assert list(panel["prompts"]) == ["just-solve", "min12-ABDJKMN"]
    spectest = panel["prompts"]["min12-ABDJKMN"]
    assert spectest["problems"] == {"xjq": 500 / 580, "sith": 1500 / 2220}
    assert spectest["mean"] == (500 / 580 + 1500 / 2220) / 2
    assert panel["human"] == {"n": 2, "mean": 0.625, "min": {"repo": "flask", "value": 0.5},
                              "max": {"repo": "django", "value": 0.75}}


def test_the_cloned_sentence_blames_the_tests_only_for_a_rise_the_implementation_does_not_share():
    base = {"all": {"cloned": 0.04}, "impl": {"cloned": 0.04}}
    rise = uplift_grid.cloned_sentence(base, {"all": {"cloned": 0.17}, "impl": {"cloned": 0.03}})
    fall = uplift_grid.cloned_sentence(base, {"all": {"cloned": 0.03}, "impl": {"cloned": 0.006}})
    assert rise == "The rise in cloned lines is all in the tests; implementation clones go from 0.040 to 0.030."
    assert fall.startswith("Cloned lines go from 0.040 to 0.030 over the whole snapshot;")
