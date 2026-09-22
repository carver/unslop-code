"""Exit codes and error reporting for bad configuration or input."""

import json

import yaml

import rejector

TASK = {
    "name": "math_solve",
    "api_url": "http://127.0.0.1:1",
    "model": "gpt-4",
    "prompt": {"user": "{question}"},
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
}


def invoke(tmp_path, capsys, rows, extra=(), **task):
    (tmp_path / "task.yaml").write_text(yaml.safe_dump({"task": {**TASK, **task}}))
    (tmp_path / "in.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    code = rejector.main(
        [
            "run",
            "--config", str(tmp_path / "task.yaml"),
            "--input", str(tmp_path / "in.jsonl"),
            "--output", str(tmp_path / "out.jsonl"),
            *extra,
        ]
    )
    return code, capsys.readouterr()


def test_missing_template_field_names_the_row(tmp_path, capsys):
    code, streams = invoke(tmp_path, capsys, [{"question": "q", "answer": "1"}, {"text": "hello"}])

    assert code == 1
    assert "row 1" in streams.err and "missing field 'question'" in streams.err
    assert not (tmp_path / "out.jsonl").exists()


def test_missing_answer_field_names_the_row(tmp_path, capsys):
    code, streams = invoke(tmp_path, capsys, [{"question": "q"}])

    assert code == 1
    assert "row 0: missing evaluation field 'answer'" in streams.err


def test_invalid_input_json_is_reported(tmp_path, capsys):
    (tmp_path / "task.yaml").write_text(yaml.safe_dump({"task": TASK}))
    (tmp_path / "in.jsonl").write_text('{"question": "q"}\nnot json\n')
    code = rejector.main(
        [
            "run",
            "--config", str(tmp_path / "task.yaml"),
            "--input", str(tmp_path / "in.jsonl"),
            "--output", str(tmp_path / "out.jsonl"),
        ]
    )
    assert code == 1
    assert "line 2: invalid JSON" in capsys.readouterr().err


def test_missing_input_file_is_reported(tmp_path, capsys):
    (tmp_path / "task.yaml").write_text(yaml.safe_dump({"task": TASK}))
    code = rejector.main(
        [
            "run",
            "--config", str(tmp_path / "task.yaml"),
            "--input", str(tmp_path / "absent.jsonl"),
            "--output", str(tmp_path / "out.jsonl"),
        ]
    )
    assert code == 1
    assert "cannot read input" in capsys.readouterr().err


def test_scheme_override_is_validated(tmp_path, capsys):
    code, streams = invoke(
        tmp_path, capsys, [{"question": "q", "answer": "1"}], extra=["--scheme", "sample"]
    )
    assert code == 1
    assert "temperature must be > 0 for the 'sample' scheme" in streams.err


MULTI = {
    "defaults": {"api_url": "http://127.0.0.1:1", "model": "gpt-4"},
    "tasks": {
        "gsm8k": {
            "prompt": {"user": "{question}"},
            "generation": {"scheme": "greedy"},
            "output_field": "solution",
        },
        "mmlu": {
            "prompt": {"user": "{question}"},
            "generation": {"scheme": "greedy"},
            "output_field": "choice",
        },
    },
}


def invoke_multi(tmp_path, capsys, *argv):
    (tmp_path / "multi.yaml").write_text(yaml.safe_dump(MULTI))
    (tmp_path / "in.jsonl").write_text('{"question": "q"}\n')
    code = rejector.main(["run", "--config", str(tmp_path / "multi.yaml"), *argv])
    return code, capsys.readouterr()


def test_input_and_input_dir_cannot_be_combined(tmp_path, capsys):
    code, streams = invoke_multi(
        tmp_path, capsys,
        "--input", f"gsm8k={tmp_path / 'in.jsonl'}",
        "--input-dir", str(tmp_path),
        "--output", str(tmp_path / "results"),
    )
    assert code == 1
    assert "--input and --input-dir cannot be combined" in streams.err


def test_multi_task_input_needs_a_task_name(tmp_path, capsys):
    code, streams = invoke_multi(
        tmp_path, capsys,
        "--input", str(tmp_path / "in.jsonl"),
        "--output", str(tmp_path / "results"),
    )
    assert code == 1
    assert "needs --input <task>=<path>" in streams.err


def test_a_task_without_an_input_is_reported(tmp_path, capsys):
    code, streams = invoke_multi(
        tmp_path, capsys,
        "--input", f"gsm8k={tmp_path / 'in.jsonl'}",
        "--output", str(tmp_path / "results"),
    )
    assert code == 1
    assert "no input for task 'mmlu'" in streams.err


def test_unselected_tasks_need_no_input(tmp_path, capsys):
    code, streams = invoke_multi(
        tmp_path, capsys,
        "--input", f"gsm8k={tmp_path / 'in.jsonl'}",
        "--output", str(tmp_path / "results"),
        "--task", "gsm8k",
    )
    # The unreachable API fails the row, but planning got past input validation.
    assert code == 0 and not streams.err
    assert not (tmp_path / "results" / "mmlu.jsonl").exists()


def test_multi_task_output_must_be_a_directory(tmp_path, capsys):
    (tmp_path / "results").write_text("")
    code, streams = invoke_multi(
        tmp_path, capsys,
        "--input-dir", str(tmp_path),
        "--output", str(tmp_path / "results"),
    )
    assert code == 1
    assert "must be a directory" in streams.err


def test_input_dir_needs_a_multi_task_config(tmp_path, capsys):
    code, streams = invoke(
        tmp_path, capsys, [{"question": "q", "answer": "1"}],
        extra=["--input-dir", str(tmp_path)],
    )
    assert code == 1
    assert "--input-dir needs a multi task config" in streams.err
