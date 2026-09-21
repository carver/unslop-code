"""bin/patch-risk: the Risk scores runs gave a patched sentence while it was still unpatched."""
import json
import re
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "patch-risk"
pr = types.ModuleType("patch_risk")
pr.__file__ = str(SCRIPT)
sys.modules["patch_risk"] = pr
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), pr.__dict__)

RETRY_PATCH = """rejector: a failing request gets three HTTP calls in all (checkpoint 1)

Sentence: "retry it up to 3 times". test_api_failure_after_max_retries wants three calls.

--- a/rejector/checkpoint_1.md
+++ b/rejector/checkpoint_1.md
@@ -142,5 +142,5 @@
 ```

-If a request receives an HTTP `5xx`, retry it up to 3 times. After the
+If a request receives an HTTP `5xx`, retry it up to 3 total requests. After the
 third failure, treat that row as failed, emit `null` output for it.
"""

ORDER_PATCH = """rejector: requests go out in input order (checkpoint 1)

--- a/rejector/checkpoint_1.md
+++ b/rejector/checkpoint_1.md
@@ -90,3 +90,4 @@
 Requests may run concurrently up to `max_concurrent`.
+Send requests in input order.
 Write one output line per row.
@@ -200,3 +200,3 @@
-The summary prints a `tasks` object.
+The summary prints a `tasks` object when there is more than one task.
 It ends with a newline.
"""


def entry(number, heading, quote, risk):
    return f"## T{number}. {heading}\n### Spec Text\n> {quote}\n### Choice\nOption 1.\n### Risk: {risk}\nMaybe.\n\n"


RETRY_LINE = "If a request receives an HTTP `5xx`, retry it up to 3 times."
WRONG_REGISTRY = (
    entry(1, "How many HTTP calls a failing request gets", RETRY_LINE, 45)
    + entry(2, "A permanent failure part-way through rejection sampling", f"{RETRY_LINE} After the third failure", 35)
    + entry(3, "Rounding of money", '"total": 12.45', 10)
)
RIGHT_REGISTRY = entry(4, "How many HTTP requests one call makes before giving up", "retry it up to 3 times.", 35)
UNASKED_REGISTRY = entry(1, "Rounding of money", '"total": 12.45', 10)


def make_tree(tmp_path):
    specs = tmp_path / "specs"
    for version, patches in (("v1", {"01-three.patch": RETRY_PATCH}),
                             ("v2", {"01-three.patch": RETRY_PATCH, "02-order.patch": ORDER_PATCH})):
        folder = specs / "rejector" / version
        folder.mkdir(parents=True)
        for name, text in patches.items():
            (folder / name).write_text(text)
    (specs / "patch-tests.json").write_text(json.dumps({"rejector": {
        "01-three.patch": ["test_api_failure_after_max_retries"],
        "02-order.patch": {"1": ["test_first_number_extract"], "2": ["test_backward_compat"]},
    }}))
    return specs


def make_run(tmp_path, family, stamp, registry, passed, failed, version=None):
    run = tmp_path / "outputs" / "spectest" / family / stamp
    checkpoint = run / "rejector" / "checkpoint_1"
    (checkpoint / "snapshot").mkdir(parents=True)
    if registry:
        (checkpoint / "snapshot" / "AMBIGUITIES.md").write_text(registry)
    evaluation = {"tests": {"checkpoint_1-Core": {"passed": passed, "failed": failed}}}
    (checkpoint / "evaluation.json").write_text(json.dumps(evaluation))
    record = {"version": "abc"}
    if version:
        record = {"version": "env-override", "commit": f"/x/specs/rejector/{version}/problems"}
    (run / "problem_catalog.json").write_text(json.dumps(record))
    return run


def test_sentences_are_the_hunks_of_the_latest_version_with_their_tests(tmp_path):
    got = pr.sentences("rejector", make_tree(tmp_path))
    assert [(s["patch"], s["hunk"], s["checkpoint"], s["tests"]) for s in got] == [
        ("01-three.patch", 1, 1, ["test_api_failure_after_max_retries"]),
        ("02-order.patch", 1, 1, ["test_first_number_extract"]),
        ("02-order.patch", 2, 1, ["test_backward_compat"]),
    ]
    assert got[0]["title"] == "rejector: a failing request gets three HTTP calls in all (checkpoint 1)"
    assert got[0]["removed"] == ["If a request receives an HTTP `5xx`, retry it up to 3 times. After the"]
    assert got[1]["removed"] == [] and got[1]["added"] == ["Send requests in input order."]
    assert got[1]["context"] == [
        "Requests may run concurrently up to `max_concurrent`.", "Write one output line per row."]


def test_a_patch_is_absent_from_v0_and_from_versions_before_it_entered(tmp_path):
    specs = make_tree(tmp_path)
    assert pr.absent_at("rejector", "02-order.patch", "v0", specs)
    assert pr.absent_at("rejector", "02-order.patch", "v1", specs)
    assert not pr.absent_at("rejector", "02-order.patch", "v2", specs)
    assert not pr.absent_at("rejector", "01-three.patch", "v1", specs)


def test_candidates_put_the_entries_quoting_the_line_first_then_the_nearest_wording(tmp_path):
    sentence = pr.sentences("rejector", make_tree(tmp_path))[0]
    rows = pr.registry_scores.entries(WRONG_REGISTRY)
    assert [r["id"] for r in pr.candidates(rows, sentence)][:2] == ["T1", "T2"]  # both quote it; T1 asks it


def test_an_added_sentence_gets_its_candidates_by_wording_alone(tmp_path):
    added = pr.sentences("rejector", make_tree(tmp_path))[1]
    nearby = entry(7, "How many requests run at once", "Requests may run concurrently up to `max_concurrent`.", 20)
    asks = entry(8, "Whether requests go out in input order", "Responses are matched to rows by position.", 30)
    assert [r["id"] for r in pr.candidates(pr.registry_scores.entries(nearby + asks), added)][0] == "T8"


def test_outcome_is_wrong_when_any_of_the_tests_failed_and_none_when_none_was_reached(tmp_path):
    failed = ["TestX::test_api_failure_after_max_retries[3]"]
    run = make_run(tmp_path, "opus-5_high_min13", "a", None, ["test_ok"], failed)
    assert pr.outcome(run / "rejector", ["test_api_failure_after_max_retries"]) == "wrong"
    assert pr.outcome(run / "rejector", ["test_ok"]) == "right"
    assert pr.outcome(run / "rejector", ["test_never_ran"]) is None


def make_runs(tmp_path):
    fail, ok = ["test_api_failure_after_max_retries"], ["test_api_failure_after_max_retries"]
    make_run(tmp_path, "opus-5_high_min13", "20260901T0000", WRONG_REGISTRY, [], fail)
    make_run(tmp_path, "opus-5_high_min12", "20260902T0000", RIGHT_REGISTRY, ok, [])
    make_run(tmp_path, "opus-5_high_min11", "20260903T0000", UNASKED_REGISTRY, [], fail)
    unscored = re.sub(r"### Risk: \d+", "### Notes", WRONG_REGISTRY)
    make_run(tmp_path, "opus-5_high_v7", "20260903T1200", unscored, [], fail)
    make_run(tmp_path, "opus-5_high_just-solve", "20260904T0000", None, [], fail)  # no registry: not a test writer
    make_run(tmp_path, "opus-5_high_min13-specv1", "20260905T0000", WRONG_REGISTRY, [], fail, version="v1")  # patched


def test_collect_counts_only_confirmed_picks_and_says_what_is_left(tmp_path):
    specs = make_tree(tmp_path)
    make_runs(tmp_path)
    got = pr.collect("rejector", specs, tmp_path / "outputs")[0]
    assert got["wrong"] == {"runs": 3, "scores": [], "unasked": 0, "unscored": 1, "unconfirmed": 2, "slips": 0}
    assert [r["id"] for r in got["detail"][0]["candidates"]][0] == "T1"
    (specs / "patch-entries.json").write_text(json.dumps({"rejector": {"01-three.patch#1": {
        "opus-5_high_min13/20260901T0000": "T1", "opus-5_high_min12/20260902T0000": "T4",
        "opus-5_high_min11/20260903T0000": None}}}))
    got = pr.collect("rejector", specs, tmp_path / "outputs")[0]
    assert got["wrong"] == {"runs": 3, "scores": [45], "unasked": 1, "unscored": 1, "unconfirmed": 0, "slips": 0}
    assert got["right"] == {"runs": 1, "scores": [35], "unasked": 0, "unscored": 0, "unconfirmed": 0, "slips": 0}
    assert pr.spread([45]) == {"n": 1, "min": 45, "median": 45, "max": 45}
    assert pr.spread([10, 40, 30, 20]) == {"n": 4, "min": 10, "median": 25, "max": 40}
    assert pr.spread([]) is None


def test_an_entry_that_chose_the_tests_reading_in_a_failing_run_is_a_slip_without_a_score(tmp_path):
    specs = make_tree(tmp_path)
    make_runs(tmp_path)
    (specs / "patch-entries.json").write_text(json.dumps({"rejector": {"01-three.patch#1": {
        "opus-5_high_min13/20260901T0000": {"entry": "T1", "slip": True}, "opus-5_high_min11/20260903T0000": None}}}))
    got = pr.collect("rejector", specs, tmp_path / "outputs")[0]
    assert got["wrong"] == {"runs": 3, "scores": [], "unasked": 1, "unscored": 1, "unconfirmed": 0, "slips": 1}


def test_a_pick_the_registry_does_not_have_is_an_error(tmp_path):
    import pytest
    specs = make_tree(tmp_path)
    make_runs(tmp_path)
    (specs / "patch-entries.json").write_text(json.dumps({"rejector": {"01-three.patch#1": {
        "opus-5_high_min13/20260901T0000": "T99"}}}))
    with pytest.raises(SystemExit, match="T99"):
        pr.collect("rejector", specs, tmp_path / "outputs")


def test_candidates_mode_lists_the_unconfirmed_pairs_with_the_patch_and_the_choices(tmp_path, capsys):
    specs = make_tree(tmp_path)
    make_runs(tmp_path)
    pr.main(["rejector", "--candidates", "--specs", str(specs), "--outputs", str(tmp_path / "outputs")])
    out = capsys.readouterr().out
    assert "=== 01-three.patch#1  rejector: a failing request gets three HTTP calls in all" in out
    assert "  + If a request receives an HTTP `5xx`, retry it up to 3 total requests. After the" in out
    assert "opus-5_high_min13/20260901T0000  (read it wrong;" in out
    assert "    risk  45  T1. How many HTTP calls a failing request gets" in out
    assert "opus-5_high_min12/20260902T0000" not in out  # the right side is not asked for by default
    (specs / "patch-entries.json").write_text(json.dumps({"rejector": {"01-three.patch#1": {
        "opus-5_high_min13/20260901T0000": "T1"}}}))
    where = ["--specs", str(specs), "--outputs", str(tmp_path / "outputs")]
    pr.main(["rejector", "--candidates", "--side", "both", *where])
    assert "  confirmed in another run: T1. How many HTTP calls a failing request gets" in capsys.readouterr().out


def curve_tree(tmp_path):
    """Two scored runs of one problem with two bugs: 01 (both runs asked, Risk 45 and 35) and the second
    hunk of 02, which no run asked. The first hunk of 02 is declared the same reading as 01."""
    specs = make_tree(tmp_path)
    tests = json.loads((specs / "patch-tests.json").read_text())
    tests["rejector"]["02-order.patch"] = {"1": ["test_api_failure_after_max_retries"], "2": ["test_backward_compat"]}
    tests["rejector"]["_same"] = {"02-order.patch#1": "01-three.patch#1"}
    (specs / "patch-tests.json").write_text(json.dumps(tests))
    retry = ["test_api_failure_after_max_retries"]
    make_run(tmp_path, "opus-5_high_min13", "20260901T0000", WRONG_REGISTRY, ["test_backward_compat"], retry)
    make_run(tmp_path, "opus-5_high_min12", "20260902T0000", RIGHT_REGISTRY, [*retry, "test_backward_compat"], [])
    unscored = re.sub(r"### Risk: \d+", "### Notes", WRONG_REGISTRY)
    make_run(tmp_path, "opus-5_high_v7", "20260903T0000", unscored, [], retry)
    a, b = "opus-5_high_min13/20260901T0000", "opus-5_high_min12/20260902T0000"
    (specs / "patch-entries.json").write_text(json.dumps({"rejector": {
        "01-three.patch#1": {a: "T1", b: "T4"}, "02-order.patch#1": {a: "T1", b: "T4"},
        "02-order.patch#2": {a: None, b: None}}}))
    return specs


def test_curve_counts_one_bug_per_reading_and_only_runs_with_scores(tmp_path):
    got = pr.curve(["rejector"], curve_tree(tmp_path), tmp_path / "outputs")
    assert (got["runs"], got["bugs"], got["bug_instances"], got["entries"]) == (2, 2, 4, 4)
    by_t = {row["risk"]: row for row in got["thresholds"]}
    assert by_t[45] == {"risk": 45, "addressed": 1, "hits": 1, "found": 1, "remaining": 3}
    assert by_t[35] == {"risk": 35, "addressed": 3, "hits": 2, "found": 2, "remaining": 2}
    assert by_t[0]["remaining"] == 2 and by_t[0]["addressed"] == 4  # the bug no run asked is never found


def test_curve_gain_is_the_share_of_bugs_found_reading_a_registry_from_the_top(tmp_path):
    got = pr.curve(["rejector"], curve_tree(tmp_path), tmp_path / "outputs")
    gain = dict(got["gain"])
    assert gain[0] == 0 and gain[100] == 0.5  # each run finds one of its two bugs, the other is never asked
    assert gain[50] == 0.5  # min13 finds its bug with its first entry of three, min12 with its only entry


def test_curve_refuses_unconfirmed_pairs(tmp_path):
    import pytest
    specs = curve_tree(tmp_path)
    (specs / "patch-entries.json").write_text("{}")
    with pytest.raises(SystemExit, match="unconfirmed"):
        pr.curve(["rejector"], specs, tmp_path / "outputs")
