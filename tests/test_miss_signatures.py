"""report/miss_signatures.py: hidden-test misses bucketed by how they failed, and matched across runs."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import miss_signatures as ms  # noqa: E402

DNS = ("AssertionError: Expected exit 0 but got 1.\n  stderr:\n  mvault: error: source metadata fetch failed for "
       "https://media.example.com/channel/{id}: HTTPSConnectionPool(host='media.example.com', port=443): Max retries "
       "exceeded (Caused by NameResolutionError(\"Failed to resolve 'media.example.com'\"))\nassert 1 == 0")


def test_a_signature_is_the_first_line_and_the_exceptions_named_further_down():
    assert ms.signature(DNS.format(id="abc")) == "AssertionError: Expected exit N but got N. [NameResolutionError]"


def test_tests_that_fail_the_same_way_on_different_data_share_a_signature():
    assert ms.signature(DNS.format(id="abc")) == ms.signature(DNS.format(id="legacychan"))


def test_the_first_line_loses_numbers_addresses_and_temporary_paths():
    assert ms.signature("assert 0.011 <= 0.01") == "assert N <= N"
    assert ms.signature("assert 'http://127.0.0.1:60837/?missing=missing' == 'http://127.0.0.1:60837'") \
        == "assert 'http://N:N/?missing=missing' == 'http://N:N'"
    assert ms.signature("assert <Row object at 0x7f6164ce8760> is None") == "assert <Row object at <addr>> is None"
    assert ms.signature("subprocess.TimeoutExpired: Command '['uv', 'run', '--config', "
                        "'/tmp/pytest-of-agent/pytest-0/test_tpm_gate0/config.yaml']' timed out after 10") \
        == "subprocess.TimeoutExpired: Command '['uv', 'run', '--config', '<tmp>/config.yaml']' timed out after N"


def test_the_exception_on_the_first_line_is_not_repeated():
    assert ms.signature("ValueError: bad\n  raised ValueError again, then KeyError") == "ValueError: bad [KeyError]"


def report(path, *tests):
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"tests": [
        {"nodeid": f".evaluation_tests/{name}", "outcome": outcome, stage: {"crash": {"message": message}}}
        for name, outcome, stage, message in tests]}))


def test_run_misses_take_every_checkpoint_and_keep_the_latest_failure_of_a_test(tmp_path):
    report(tmp_path / "checkpoint_1" / "evaluation" / "report.json",
           ("test_checkpoint_1.py::test_a", "failed", "call", "assert 1 == 2"),
           ("test_checkpoint_1.py::test_ok", "passed", "call", ""))
    report(tmp_path / "checkpoint_2" / "evaluation" / "report.json",
           ("test_checkpoint_1.py::test_a", "failed", "call", "ValueError: late"),
           ("test_checkpoint_2.py::test_b", "error", "setup", "OSError: port in use"))
    (tmp_path / "checkpoint_3").mkdir()
    assert ms.run_misses(tmp_path) == {"test_checkpoint_1.py::test_a": "ValueError: late",
                                       "test_checkpoint_2.py::test_b": "OSError: port in use"}


def test_buckets_put_the_largest_first():
    misses = {"t1": "X", "t2": "Y", "t3": "Y"}
    assert ms.buckets(misses) == [("Y", ["t2", "t3"]), ("X", ["t1"])]


def test_shared_counts_the_same_test_failing_the_same_way_in_another_run():
    mine = {"t1": "DNS", "t2": "DNS", "t3": "rounding"}
    others = {"just-solve 0915": {"t1": "DNS", "t2": "DNS", "t3": "timeout"}, "min12 0914": {"t9": "DNS"},
              "sonnet 0829": {"t2": "DNS"}}
    assert ms.shared(mine, others) == {"DNS": [("just-solve 0915", 2), ("sonnet 0829", 1)]}


def test_render_lists_each_bucket_with_the_runs_that_share_it():
    mine = {"t1": "DNS", "t2": "DNS", "t3": "rounding"}
    text = ms.render(mine, {"just-solve 0915": {"t1": "DNS", "t2": "DNS"}})
    assert text.splitlines() == [
        "2 tests: DNS",
        "    t1",
        "    t2",
        "    same tests, same failure in: just-solve 0915 (2 of 2)",
        "1 test: rounding",
        "    t3",
    ]


def test_render_says_so_when_nothing_was_missed():
    assert ms.render({}, {}) == "No misses."


def test_a_long_first_line_is_cut():
    sig = ms.signature("AssertionError: assert 'x' in '" + "page text " * 40 + "'")
    assert len(sig) == ms.FIRST_LINE_LIMIT + 1 and sig.endswith("…")


def test_render_names_the_first_few_sharing_runs_and_counts_the_rest():
    others = {f"run {n}": {"t1": "DNS"} for n in range(1, 8)}
    assert ms.render({"t1": "DNS"}, others).splitlines()[-1] == (
        "    same tests, same failure in: run 1 (1 of 1), run 2 (1 of 1), run 3 (1 of 1), run 4 (1 of 1) and 3 more")
