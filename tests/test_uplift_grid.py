"""report/uplift_grid.py: the implementation-against-tests section."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import uplift_grid  # noqa: E402


def part(loc, ast_lines, erosion, cloned):
    return {"loc": loc, "ast_lines": ast_lines, "ast": ast_lines / loc, "erosion": erosion, "cloned": cloned}


def row(name, prompt, impl, test, whole):
    return {"name": name, "prompt": prompt, "runs": 2, "impl": impl, "test": test, "all": whole,
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
    assert "implementation lines falls 40%</b> (400 to 240)" in html
    assert "4.0 times the test code" in html


def test_the_human_row_is_the_mean_of_the_repositories():
    human = uplift_grid.human_mean(REPOS)
    assert round(human["impl"]["ast"], 3) == 0.15
    assert human["test_share"] == 0.625
    html = uplift_grid.split_section(ROWS, REPOS)
    assert "<td>human, 2 repositories</td>" in html
    assert "2.0 times the human one" in html  # 0.30 against 0.15
    assert "0.45 against 0.45" in html  # erosion: the mean of 0.2 and 0.7, not sith's weight in the pooled 0.65
