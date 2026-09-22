"""Counting the rows an earlier run already wrote, and appending after them."""

import json
import pathlib
from dataclasses import replace

from config import GenerationConfig, PromptConfig, TaskConfig
from dataset import write_results
from resume import completed_rows

TASK = TaskConfig(
    name="demo",
    api_url="http://localhost:8000",
    model="gpt-4",
    prompt=PromptConfig(system="", user="{question}"),
    generation=GenerationConfig(scheme="greedy", temperature=0.0, max_tokens=64, n=1),
    evaluation=None,
    output_field="solution",
)

REJECTION = replace(TASK, generation=GenerationConfig("rejection", 0.7, 64, n=3))


def row(output):
    return {"input": {}, "output": output, "result": {"passed": True}, "meta": None}


def write(tmp_path, *rows):
    path = tmp_path / "out.jsonl"
    path.write_text("".join(json.dumps(entry) + "\n" for entry in rows))
    return str(path)


def test_a_missing_output_file_starts_from_the_beginning(tmp_path):
    assert completed_rows(str(tmp_path / "absent.jsonl"), TASK) == 0


def test_every_written_row_of_a_greedy_task_counts_as_done(tmp_path):
    path = write(tmp_path, row({"solution": "a"}), row(None), row({"solution": "c"}))
    assert completed_rows(path, TASK) == 3


def test_a_rejection_row_without_a_solution_is_redone(tmp_path):
    path = write(tmp_path, row({"solution": "a"}), row(None), row({"solution": "c"}))
    assert completed_rows(path, REJECTION) == 1


def test_a_multi_solution_row_short_of_its_target_is_redone(tmp_path):
    task = replace(TASK, num_solutions=3)
    path = write(tmp_path, row([{"solution": "a"}] * 3), row([{"solution": "a"}] * 2))
    assert completed_rows(path, task) == 1


def test_a_half_written_last_line_is_redone(tmp_path):
    path = tmp_path / "out.jsonl"
    path.write_text(json.dumps(row({"solution": "a"})) + "\n" + '{"input": {}, "outp')
    assert completed_rows(str(path), TASK) == 1


def test_writing_appends_after_the_rows_that_were_kept(tmp_path):
    path = write(tmp_path, row({"solution": "a"}), row({"solution": "b"}), row(None))
    write_results(path, [row({"solution": "c"})], resume_from=2)

    written = [json.loads(line) for line in pathlib.Path(path).read_text().splitlines()]
    assert [entry["output"] for entry in written] == [{"solution": "a"}, {"solution": "b"}, {"solution": "c"}]
