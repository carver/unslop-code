"""bin/test-failure: the assertion lines pytest printed for one failing test of a run."""
import random
import string
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "test-failure"
mod = types.ModuleType("test_failure")
mod.__file__ = str(SCRIPT)
sys.modules["test_failure"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)

STDOUT = """\
============================= test session starts ==============================
collected 3 items
_____ not a failure, the block has not started _____
=================================== FAILURES ===================================
_____________________ TestErrors.test_missing_vault_route ______________________

self = <test_checkpoint_5.TestErrors object at 0x7f>

>       assert response.status == 302
E       assert 404 == 302
E        +  where 404 = <Response>.status

tests/test_checkpoint_5.py:41: AssertionError
----------------------------- Captured stdout call -----------------------------
GET /vault/nope
_ TestErrors.test_static_routes_block_path_traversal[/vault/v3/media/../../secret.txt] _

>       assert "secret" not in body
E       AssertionError: leaked
=========================== short test summary info ============================
FAILED tests/test_checkpoint_5.py::TestErrors::test_missing_vault_route
_____ not a failure either, the block is over _____
========================= 2 failed, 1 passed in 1.20s ==========================
"""


def make_run(tmp_path, stdout=STDOUT):
    run = tmp_path / "outputs" / "spectest" / "opus-5_high_anti_slop" / "20260921T0531"
    for checkpoint, text in (("checkpoint_4", "== 3 passed in 1s ==\n"), ("checkpoint_5", stdout)):
        evaluation = run / "mvvault" / checkpoint / "evaluation"
        evaluation.mkdir(parents=True)
        (evaluation / "stdout.txt").write_text(text)
    return run


def test_sections_are_the_titled_blocks_between_failures_and_the_next_banner():
    sections = mod.failure_sections(STDOUT)
    assert [title for title, _ in sections] == [
        "TestErrors.test_missing_vault_route",
        "TestErrors.test_static_routes_block_path_traversal[/vault/v3/media/../../secret.txt]",
    ]
    assert sections[0][1][-1] == "GET /vault/nope"
    assert sections[1][1][-1] == "E       AssertionError: leaked"


def test_errors_block_counts_too():
    text = "==== ERRORS ====\n____ ERROR at setup of test_x ____\nE   fixture 'srv' not found\n==== 1 error ====\n"
    assert mod.failure_sections(text) == [("ERROR at setup of test_x", ["E   fixture 'srv' not found"])]


def test_main_prints_each_match_under_its_checkpoint_with_only_the_assertion_lines(tmp_path, capsys):
    mod.main([str(make_run(tmp_path)), "missing_vault"])
    assert capsys.readouterr().out.splitlines() == [
        "mvvault/checkpoint_5 TestErrors.test_missing_vault_route",
        "E       assert 404 == 302",
        "E        +  where 404 = <Response>.status",
    ]


def test_lines_caps_the_assertion_lines_and_width_cuts_them(tmp_path, capsys):
    mod.main([str(make_run(tmp_path)), "missing_vault", "--lines", "1", "--width", "12"])
    assert capsys.readouterr().out.splitlines()[1:] == ["E       asse"]


def test_full_prints_the_whole_section(tmp_path, capsys):
    mod.main([str(make_run(tmp_path)), "path_traversal", "--full"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("mvvault/checkpoint_5 TestErrors.test_static_routes")
    assert out[1:] == ["", '>       assert "secret" not in body', "E       AssertionError: leaked"]


def test_the_problem_folder_works_as_the_run(tmp_path, capsys):
    mod.main([str(make_run(tmp_path) / "mvvault"), "missing_vault", "--lines", "0"])
    assert capsys.readouterr().out.splitlines() == ["mvvault/checkpoint_5 TestErrors.test_missing_vault_route"]


def test_no_match_names_the_failures_that_exist(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        mod.main([str(make_run(tmp_path)), "no_such_test"])
    message = str(exit_info.value)
    assert "no_such_test" in message
    assert "TestErrors.test_missing_vault_route" in message


def test_a_run_without_pytest_output_says_so(tmp_path):
    with pytest.raises(SystemExit, match="no checkpoint_\\*/evaluation/stdout.txt"):
        mod.main([str(tmp_path), "anything"])


def test_undecodable_bytes_do_not_stop_the_read(tmp_path, capsys):
    run = make_run(tmp_path)
    path = run / "mvvault" / "checkpoint_5" / "evaluation" / "stdout.txt"
    path.write_bytes(path.read_bytes().replace(b"GET /vault/nope", b"GET /\xff\xfe"))
    mod.main([str(run), "missing_vault"])
    assert "assert 404 == 302" in capsys.readouterr().out


@pytest.mark.parametrize("seed", range(50))
def test_every_section_written_into_a_failures_block_is_read_back(seed):
    rng = random.Random(seed)
    alphabet = string.ascii_letters + string.digits + " .:[]/<>'-"

    def words(low):
        return "".join(rng.choices(alphabet, k=rng.randint(low, 30))).strip() or "x"

    sections = [(words(1), [words(0) for _ in range(rng.randint(0, 5))]) for _ in range(rng.randint(0, 5))]
    text = "==== FAILURES ====\n"
    for title, body in sections:
        text += f"___ {title} ___\n" + "".join(line + "\n" for line in body)
    text += "==== 1 failed in 1s ====\n"
    assert mod.failure_sections(text) == sections


def test_a_failure_repeated_unchanged_in_later_checkpoints_prints_once(tmp_path, capsys):
    run = make_run(tmp_path)
    for checkpoint in ("checkpoint_6", "checkpoint_7"):
        evaluation = run / "mvvault" / checkpoint / "evaluation"
        evaluation.mkdir(parents=True)
        changed = STDOUT.replace("404 == 302", "500 == 302") if checkpoint == "checkpoint_7" else STDOUT
        (evaluation / "stdout.txt").write_text(changed)
    mod.main([str(run), "missing_vault", "--lines", "1"])
    assert capsys.readouterr().out.splitlines() == [
        "mvvault/checkpoint_5 TestErrors.test_missing_vault_route (the same at checkpoint_6)",
        "E       assert 404 == 302",
        "mvvault/checkpoint_7 TestErrors.test_missing_vault_route",
        "E       assert 500 == 302",
    ]


def test_checkpoint_10_comes_after_checkpoint_9(tmp_path):
    run = tmp_path / "run"
    for n in (10, 9):
        evaluation = run / "mvvault" / f"checkpoint_{n}" / "evaluation"
        evaluation.mkdir(parents=True)
        (evaluation / "stdout.txt").write_text(STDOUT)
    assert [checkpoint for _, checkpoint, _, _ in mod.run_failures(run)][::2] == ["checkpoint_9", "checkpoint_10"]
