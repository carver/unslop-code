"""Resuming a run from an output file an earlier run left behind."""

import json


def resume_config(url, *, scheme="greedy", temperature=0.0, n=1):
    return f"""
task:
  name: "resumable"
  api_url: "{url}"
  model: "mock-model"
  rate_limits:
    rpm: 600
  prompt:
    user: "{{question}}"
  generation:
    scheme: "{scheme}"
    temperature: {temperature}
    max_tokens: 32
    n: {n}
  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
  output_field: "solution"
"""


def rows(count, answer="8"):
    return [{"question": f"question {index}", "answer": answer} for index in range(count)]


def test_resume_appends_only_the_missing_rows(mock_server, workdir):
    server = mock_server()
    workdir.write(resume_config(server.url), rows(3))
    workdir.run()
    first_pass = workdir.output.read_text(encoding="utf-8")

    workdir.write(resume_config(server.url), rows(5))
    completed = workdir.run("--resume")

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["resumed_from"] == 3
    assert summary["total"] == 2
    assert len(workdir.results()) == 5
    assert workdir.output.read_text(encoding="utf-8").startswith(first_pass)
    assert [result["input"]["question"] for result in workdir.results()[3:]] == [
        "question 3",
        "question 4",
    ]


def test_resume_without_an_existing_output_runs_everything(mock_server, workdir):
    server = mock_server()
    workdir.write(resume_config(server.url), rows(2))

    completed = workdir.run("--resume")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["resumed_from"] == 0
    assert len(workdir.results()) == 2


def test_a_failed_greedy_row_counts_as_finished(mock_server, workdir):
    server = mock_server("--answer", "-1")
    workdir.write(resume_config(server.url), rows(2))
    workdir.run()

    completed = workdir.run("--resume")

    summary = json.loads(completed.stdout)
    assert summary["resumed_from"] == 2 and summary["total"] == 0
    assert len(workdir.results()) == 2


def test_an_incomplete_rejection_row_is_produced_again(mock_server, workdir):
    failing = mock_server("--answer", "-1")
    config = resume_config(failing.url, scheme="rejection", temperature=0.7, n=2)
    workdir.write(config, rows(1))
    workdir.run()
    assert workdir.results()[0]["result"]["passed"] is False

    passing = mock_server()
    workdir.write(resume_config(passing.url, scheme="rejection", temperature=0.7, n=2), rows(1))
    completed = workdir.run("--resume")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["resumed_from"] == 0
    assert len(workdir.results()) == 1
    assert workdir.results()[0]["result"]["passed"] is True


def test_an_incomplete_multi_solution_row_is_produced_again(mock_server, workdir):
    server = mock_server("--pass-every", "5")
    config = resume_config(server.url, scheme="rejection", temperature=0.7) + "  num_solutions: 4\n"
    workdir.write(config, rows(2))
    workdir.run()
    finished = [row["result"]["passed"] >= 4 for row in workdir.results()]
    assert finished == [False, False]

    completed = workdir.run("--resume")

    assert json.loads(completed.stdout)["resumed_from"] == 0
    assert json.loads(completed.stdout)["total"] == 2
    assert len(workdir.results()) == 2


def test_a_truncated_last_line_is_produced_again(mock_server, workdir):
    server = mock_server()
    workdir.write(resume_config(server.url), rows(3))
    workdir.run()
    lines = workdir.output.read_text(encoding="utf-8").splitlines()
    workdir.output.write_text("\n".join(lines[:2]) + "\n" + lines[2][:20], encoding="utf-8")

    completed = workdir.run("--resume")

    assert json.loads(completed.stdout)["resumed_from"] == 2
    assert len(workdir.results()) == 3


MULTI_CONFIG = """
defaults:
  api_url: "{url}"
  model: "mock-model"
  output_field: "solution"
  prompt:
    user: "{{question}}"
  rate_limits:
    rpm: 600

tasks:
  first:
    generation:
      scheme: "greedy"
  second:
    generation:
      scheme: "greedy"
"""


def test_resume_is_applied_per_task_output_file(mock_server, tmp_path, run_rejector):
    server = mock_server()
    config = tmp_path / "multi.yaml"
    config.write_text(MULTI_CONFIG.format(url=server.url), encoding="utf-8")
    data, results = tmp_path / "data", tmp_path / "results"
    data.mkdir()
    counts = {"first": 2, "second": 3}
    for name, count in counts.items():
        write_rows(data / f"{name}.jsonl", count)

    def run(*extra):
        return run_rejector(
            "--config", str(config), "--input-dir", str(data), "--output", str(results), *extra
        )

    assert run().returncode == 0
    write_rows(data / "first.jsonl", 5)
    completed = run("--resume")

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["resumed_from"] == 5
    assert summary["tasks"]["first"]["total"] == 3 and summary["tasks"]["second"]["total"] == 0
    assert len(read(results / "first.jsonl")) == 5
    assert len(read(results / "second.jsonl")) == 3


def write_rows(path, count):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows(count)), encoding="utf-8")


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
