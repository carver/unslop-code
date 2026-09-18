"""report/scb_hits.py: per-hit locations parsed from scb-check's human report."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import scb_hits  # noqa: E402

SNAPSHOT = "outputs/run/xjq/checkpoint_5/snapshot"
REPORT = """
warning[redundant-return-none]: `return None` at end of function - drop it
    ┌─ xjq.py:103:5
    │
102 │         return DIRECT
103 │     return None
104 │
    │

erosion: function `extract_text` exceeds complexity threshold
    ┌─ pkg/render.py:624
    │
623 │
624 │ def extract_text(result, mode, first=False):
625 │     \"\"\"Render a query result.
    │
    = complexity: 17, sloc: 30 (threshold: complexity > 10)
trivial-wrapper[single-return-function]: `is_int` adds no behavior
    ┌─ conftest.py:143:1
    │
142 │
143 │ def is_int(v):
144 │     return isinstance(v, int)
145 │
    │
    = resolved usages: 4

duplicate-structure: duplicated block (4 lines, 2 instances)
    ┌─ tests/test_cli.py:643
    │
643 │             for chunk in chunks:
644 │                 text = normalize(chunk)
645 │                 if text:
646 │                     lines.append(text)
    │
    ┆
    ┌─ test_more.py:684
    │
684 │         for chunk in chunks:
685 │             text = normalize(chunk)
686 │             if text:
687 │                 lines.append(text)
    │
"""


def parsed():
    return scb_hits.parse_report(REPORT)


def test_one_hit_per_header_with_kind_and_rule():
    assert [(h["kind"], h["rule"]) for h in parsed()] == [
        ("ast", "redundant-return-none"), ("erosion", "erosion"), ("wrapper", "single-return-function"),
        ("clone", "duplicate-structure")]


def test_ast_span_is_the_match_without_the_context_lines():
    assert parsed()[0]["spans"] == [{"file": "xjq.py", "start": 103, "end": 103}]


def test_paths_keep_their_directories():
    assert parsed()[1]["spans"][0]["file"] == "pkg/render.py"


def test_erosion_carries_its_complexity():
    assert parsed()[1]["complexity"] == 17


def test_a_wrapper_hit_does_not_leak_into_the_erosion_hit_before_it():
    assert parsed()[1]["spans"] == [{"file": "pkg/render.py", "start": 624, "end": 625}]


def test_clone_has_one_span_per_instance():
    assert parsed()[3]["spans"] == [
        {"file": "tests/test_cli.py", "start": 643, "end": 646},
        {"file": "test_more.py", "start": 684, "end": 687}]


def test_a_hit_is_test_code_only_when_every_span_is():
    assert [h["test"] for h in parsed()] == [False, False, True, True]


def test_is_test_file_by_name():
    assert scb_hits.is_test_file("tests/helpers.py")
    assert scb_hits.is_test_file("conftest.py")
    assert scb_hits.is_test_file("pkg/testing/plugin.py")
    assert scb_hits.is_test_file("pkg/cli_test.py")
    assert not scb_hits.is_test_file("pkg/testing_tools/latest.py")
    assert not scb_hits.is_test_file("contest.py")


def test_load_runs_the_checker_once_and_caches(tmp_path):
    calls = []

    def fake_check(snapshot):
        calls.append(snapshot)
        return REPORT

    cache = tmp_path / "cache"
    first = scb_hits.load(SNAPSHOT, cache, check=fake_check)
    second = scb_hits.load(SNAPSHOT, cache, check=fake_check)
    assert first == second == parsed()
    assert calls == [SNAPSHOT]
