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


ROWS = [
    row("xjq", "just-solve", part(10, 9, 0.9, 0.9), part(10, 9, 0.9, 0.9), part(20, 18, 0.9, 0.9)),
    row("ALL", "just-solve", part(1000, 400, 0.6, 0.05), part(500, 50, 0.7, 0.06), part(1500, 450, 0.64, 0.053)),
    row("ALL", "min12-ABDJKMN", part(800, 240, 0.45, 0.03), part(2000, 40, 0.02, 0.2), part(2800, 280, 0.16, 0.15)),
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
    assert "share falls 67%" in html  # 0.30 to 0.10 over the whole snapshot
    assert "it falls 25%" in html  # 0.40 to 0.30 in implementation files
    assert "implementation lines falls 40%</b> (400 to 240)" in html
    assert "4.0 times the test code" in html


def test_the_human_row_is_the_mean_of_the_repositories():
    human = uplift_grid.human_mean(REPOS)
    assert round(human["impl"]["ast"], 3) == 0.15
    assert human["test_share"] == 0.625
    html = uplift_grid.split_section(ROWS, REPOS)
    assert "<td>human, 2 repositories</td>" in html
    assert "2.0 times the human one" in html  # 0.30 against 0.15
