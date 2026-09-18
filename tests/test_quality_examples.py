"""report/quality_examples.py: code pairs from run snapshots, annotated with their scb-check hits."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import quality_examples as qe  # noqa: E402

SOURCE = "\n".join(f"line_{n} = {n}" for n in range(1, 21)) + "\n"


def ast_hit(start, end, rule="verbose-or-return", file="app.py"):
    return {"kind": "ast", "rule": rule, "message": "m", "spans": [{"file": file, "start": start, "end": end}]}


def clone_hit(*ranges, file="app.py"):
    return {"kind": "clone", "rule": "duplicate-structure", "message": "m",
            "spans": [{"file": file, "start": a, "end": b} for a, b in ranges]}


def function(name, start, end, complexity, file="app.py"):
    return {"name": name, "type": "function", "file_path": file, "start": start, "end": end, "complexity": complexity}


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / "checkpoint_1" / "snapshot"
    root.mkdir(parents=True)
    (root / "app.py").write_text(SOURCE)
    return root


def side(snapshot, segments, hits=(), functions=()):
    return qe.Side(snapshot=snapshot, segments=segments, hits=list(hits), functions=list(functions))


def test_a_segment_holds_exactly_its_lines(snapshot):
    seg = qe.annotate(side(snapshot, [{"file": "app.py", "start": 3, "end": 5}]), "ast")[0]
    assert [line.number for line in seg.lines] == [3, 4, 5]
    assert "line_3" in seg.lines[0].html


def test_a_range_past_the_end_of_the_file_is_an_error(snapshot):
    with pytest.raises(ValueError, match="app.py"):
        qe.annotate(side(snapshot, [{"file": "app.py", "start": 19, "end": 25}]), "ast")


def test_ast_flags_only_the_overlap_with_the_segment(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 3, "end": 6}], hits=[ast_hit(5, 9), ast_hit(12, 13)])
    seg = qe.annotate(s, "ast")[0]
    assert [line.number for line in seg.lines if line.flagged] == [5, 6]


def test_hits_of_another_category_or_file_do_not_flag(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 1, "end": 9}],
             hits=[clone_hit((2, 4)), ast_hit(5, 6, file="other.py")])
    assert not any(line.flagged for line in qe.annotate(s, "ast")[0].lines)


def test_blowup_examples_flag_clones(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 1, "end": 9}], hits=[clone_hit((2, 4), (30, 32))])
    assert [line.number for line in qe.annotate(s, "blowup")[0].lines if line.flagged] == [2, 3, 4]


def test_erosion_flags_the_def_line_of_functions_over_the_threshold(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 1, "end": 20}],
             functions=[function("big", 2, 9, 17), function("small", 11, 14, 4)])
    assert [line.number for line in qe.annotate(s, "erosion")[0].lines if line.flagged] == [2]


def test_summary_counts_ast_hits_by_rule(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 1, "end": 9}],
             hits=[ast_hit(2, 2), ast_hit(4, 5), ast_hit(7, 7, rule="redundant-return-none"), ast_hit(15, 15)])
    summary = qe.summarize(s, "ast")
    assert summary.count == 3
    assert summary.items == [("verbose-or-return", 2), ("redundant-return-none", 1)]


def test_summary_counts_cloned_lines_inside_the_segments(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 1, "end": 5}, {"file": "app.py", "start": 10, "end": 12}],
             hits=[clone_hit((2, 4), (10, 12), (30, 32)), clone_hit((3, 5), (40, 42))])
    summary = qe.summarize(s, "clone")
    assert summary.count == 7  # lines 2-5 and 10-12; a line in two groups counts once
    assert qe.stat_text(summary, "clone", 8) == "7 of 8 lines cloned"


def test_blowup_stat_names_the_largest_group(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 1, "end": 8}],
             hits=[clone_hit((2, 4), (30, 32)), clone_hit((5, 6), (40, 41), (50, 51), (60, 61))])
    assert qe.stat_text(qe.summarize(s, "blowup"), "blowup", 8) == "5 of 8 lines cloned, largest group has 4 copies"


def test_ast_stat_names_hits_and_flagged_lines(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 1, "end": 9}], hits=[ast_hit(2, 3), ast_hit(3, 5)])
    summary = qe.summarize(s, "ast")
    assert qe.stat_text(summary, "ast", 9) == "2 ast-grep hits on 4 of 9 lines"


def test_summary_lists_function_complexities_for_erosion(snapshot):
    s = side(snapshot, [{"file": "app.py", "start": 1, "end": 20}],
             functions=[function("big", 2, 9, 17), function("small", 11, 14, 4), function("elsewhere", 40, 50, 30)])
    summary = qe.summarize(s, "erosion")
    assert summary.items == [("big", 17), ("small", 4)]
    assert summary.count == 17


@pytest.mark.parametrize("category, before, after, expected", [
    ("ast", 4, 0, "clean"), ("ast", 4, 2, "fewer hits"), ("ast", 4, 4, "no better"), ("ast", 2, 5, "worse"),
    ("clone", 12, 0, "clean"), ("clone", 12, 6, "fewer cloned lines"), ("clone", 6, 6, "no better"),
    ("erosion", 25, 9, "clean"), ("erosion", 25, 14, "lower"), ("erosion", 25, 25, "no better"),
    ("erosion", 12, 20, "worse"),
])
def test_verdict(category, before, after, expected):
    assert qe.verdict(category, before, after) == expected


def manifest(snapshot, **example):
    base = {"id": "A1", "category": "ast", "problem": "xjq", "title": "Parsing <flags>",
            "what_is_wrong": "Wrong.", "what_changed": "Changed.",
            "before": {"run": "js", "segments": [{"file": "app.py", "start": 1, "end": 4}]},
            "after": {"run": "js", "segments": [{"file": "app.py", "start": 6, "end": 8}]}}
    return {"runs": {"js": str(snapshot)}, "examples": [base | example]}


def build(snapshot, hits=(), **example):
    return qe.render_examples(manifest(snapshot, **example), load_hits=lambda _: list(hits))


def test_the_spectest_pane_starts_hidden_behind_a_switch(snapshot):
    html = build(snapshot)
    assert 'role="switch" aria-checked="false"' in html
    assert '<section class="pane min" id="A1-after" hidden>' in html


def test_titles_are_escaped(snapshot):
    assert "Parsing &lt;flags&gt;" in build(snapshot)


def test_a_blowup_has_no_switch(snapshot):
    example = manifest(snapshot, id="B1", category="blowup")["examples"][0]
    del example["after"]
    html = qe.render_examples({"runs": {"js": str(snapshot)}, "examples": [example]}, load_hits=lambda _: [])
    assert 'role="switch"' not in html


def test_the_verdict_comes_from_the_hits_not_the_manifest(snapshot):
    html = build(snapshot, hits=[ast_hit(2, 2)], verdict="worse")
    assert "clean" in html and "worse" not in html


def test_functions_come_from_the_symbols_file_beside_the_snapshot(snapshot):
    symbols = snapshot.parent / "quality_analysis" / "symbols.jsonl"
    symbols.parent.mkdir()
    rows = [function("big", 2, 9, 17), {"name": "X", "type": "variable", "file_path": "app.py", "start": 1, "end": 1}]
    symbols.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert [f["name"] for f in qe.load_functions(snapshot)] == ["big"]
