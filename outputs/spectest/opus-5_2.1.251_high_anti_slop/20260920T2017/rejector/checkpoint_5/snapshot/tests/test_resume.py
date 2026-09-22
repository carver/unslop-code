"""Deciding how many written rows a resumed run may skip."""

import json

from resume import resume_point


def write_output(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return str(path)


def single(passed=True):
    return {"input": {"q": 1}, "output": {"solution": "x"}, "result": {"passed": passed}}


def multi(solutions):
    return {
        "input": {"q": 1},
        "output": [{"solution": "x"} for _ in range(solutions)],
        "result": {"passed": solutions},
    }


def test_a_missing_output_file_starts_from_the_beginning(tmp_path):
    assert resume_point(str(tmp_path / "out.jsonl"), num_solutions=1) == 0


def test_every_written_row_is_skipped(tmp_path):
    path = write_output(tmp_path / "out.jsonl", [single() for _ in range(5)])
    assert resume_point(path, num_solutions=1) == 5


def test_a_row_that_produced_nothing_still_counts_as_done(tmp_path):
    path = write_output(tmp_path / "out.jsonl", [single(), {"input": {}, "output": None, "result": {}}])
    assert resume_point(path, num_solutions=1) == 2


def test_a_row_short_of_its_solutions_is_reprocessed(tmp_path):
    path = write_output(tmp_path / "out.jsonl", [multi(3), multi(3), multi(1)])
    assert resume_point(path, num_solutions=3) == 2


def test_the_rows_after_an_unfinished_one_are_dropped(tmp_path):
    path = write_output(tmp_path / "out.jsonl", [multi(3), multi(1), multi(3)])
    assert resume_point(path, num_solutions=3) == 1
    assert len(open(path).read().splitlines()) == 1


def test_a_half_written_line_is_reprocessed(tmp_path):
    path = tmp_path / "out.jsonl"
    write_output(path, [single(), single()])
    path.write_text(path.read_text()[:-12])
    assert resume_point(str(path), num_solutions=1) == 1
