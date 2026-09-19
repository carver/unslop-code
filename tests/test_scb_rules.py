"""report/scb_rules.py: ast-grep flagged lines per rule, on scb-check's own line count."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import scb_rules  # noqa: E402

SOURCE = '''"""Module docstring."""
import os

# a banner


def load(path):
    """Read it.

    Twice.
    """
    try:
        return open(path).read()
    except Exception:
        return None
'''


def hit(rule, file, start, end, kind="ast"):
    return {"kind": kind, "rule": rule, "message": "", "spans": [{"file": file, "start": start, "end": end}]}


def tree(tmp_path, **files):
    for name, text in files.items():
        path = tmp_path / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_code_lines_leave_out_blanks_comments_and_docstrings():
    assert scb_rules.code_lines(SOURCE) == {2, 7, 12, 13, 14, 15}


def test_a_string_that_is_not_a_docstring_is_code():
    assert scb_rules.code_lines('x = """a\nb"""\n') == {1, 2}


def test_a_file_python_cannot_parse_falls_back_to_nonblank_noncomment_lines():
    assert scb_rules.code_lines("def broken(:\n    # why\n\n    pass\n") == {1, 4}


def test_rule_lines_count_code_lines_only_and_each_line_once_per_rule(tmp_path):
    source = tree(tmp_path, **{"app.py": SOURCE})
    hits = [hit("try-soup", "app.py", 7, 15), hit("try-soup", "app.py", 12, 15), hit("broad-except", "app.py", 14, 15),
            hit("section-banner-comment", "app.py", 4, 4)]
    lines = scb_rules.rule_lines(source, hits, "impl")
    assert {rule: len(found) for rule, found in lines.items()} == {"try-soup": 5, "broad-except": 2,
                                                                  "section-banner-comment": 0}


def test_rule_lines_keep_to_the_part_asked_for(tmp_path):
    source = tree(tmp_path, **{"app.py": SOURCE, "tests__test_app.py": SOURCE})
    hits = [hit("broad-except", "app.py", 14, 15), hit("broad-except", "tests/test_app.py", 12, 15)]
    count = {part: len(scb_rules.rule_lines(source, hits, part)["broad-except"]) for part in ("impl", "test", "all")}
    assert count == {"impl": 2, "test": 4, "all": 6}


def test_rule_lines_ignore_hits_that_are_not_ast_grep(tmp_path):
    source = tree(tmp_path, **{"app.py": SOURCE})
    assert scb_rules.rule_lines(source, [hit("erosion", "app.py", 7, 15, kind="erosion")], "impl") == {}


def test_a_hit_in_a_file_the_walker_skips_is_dropped(tmp_path):
    source = tree(tmp_path, **{"app.py": SOURCE, ".venv__lib.py": SOURCE})
    assert scb_rules.rule_lines(source, [hit("broad-except", ".venv/lib.py", 14, 15)], "all") == {"broad-except": set()}


def test_breakdown_reports_the_union_beside_the_checker_s_own_count(tmp_path):
    source = tree(tmp_path, **{"app.py": SOURCE})
    hits = [hit("try-soup", "app.py", 12, 15), hit("broad-except", "app.py", 14, 15)]
    counts = {"impl": {"total_loc": 6, "ast_grep_flagged_loc": 4}}
    assert scb_rules.breakdown(source, "impl", hits, counts) == {
        "loc": 6, "scb_ast_lines": 4, "union": 4, "rules": {"try-soup": 4, "broad-except": 2}}


def column(name, loc, scb, union, **rules):
    return {"name": name, "loc": loc, "scb_ast_lines": scb, "union": union, "rules": rules}


def test_the_table_is_lines_per_thousand_sorted_by_how_far_the_columns_disagree():
    text = scb_rules.table([column("a", 1000, 300, 310, soup=200, guard=50, tiny=2),
                            column("b", 2000, 100, 100, guard=90, tiny=2)], floor=5)
    assert text.splitlines() == [
        "| flagged lines per 1000 LOC | a | b |",
        "|---|---|---|",
        "| LOC | 1000 | 2000 |",
        "| scb-check ast | 300.0 | 50.0 |",
        "| all rules, each line once | 310.0 | 50.0 |",
        "| soup | 200.0 | 0.0 |",
        "| guard | 50.0 | 45.0 |",
        "| 1 rules under 5.0 everywhere, summed | 2.0 | 1.0 |",
    ]


def test_a_column_with_no_code_prints_dashes():
    text = scb_rules.table([column("empty", 0, 0, 0)], floor=5)
    assert text.splitlines()[2:] == ["| LOC | 0 |", "| scb-check ast | - |", "| all rules, each line once | - |"]
