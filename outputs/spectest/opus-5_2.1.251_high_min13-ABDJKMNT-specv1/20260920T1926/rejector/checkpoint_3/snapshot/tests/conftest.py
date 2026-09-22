"""Shared fixtures: config/input file builders and a CLI subprocess runner."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO_ROOT / "rejector.py"

sys.path.insert(0, str(REPO_ROOT))


def base_task(api_url: str, **overrides) -> dict:
    """The spec's example config, as a mutable dict."""
    task = {
        "name": "gsm8k_solve",
        "api_url": api_url,
        "model": "gpt-4",
        "rpm": 600,
        "prompt": {
            "system": "Solve the math problem. Put your final answer after ####.",
            "user": "{question}",
        },
        "generation": {
            "scheme": "greedy",
            "temperature": 0.0,
            "max_tokens": 512,
            "n": 1,
        },
        "evaluation": {
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "last_number",
        },
        "output_field": "solution",
    }
    task.update(overrides)
    return task


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    output_path: Path

    @property
    def summary(self) -> dict:
        return json.loads(self.stdout.strip().splitlines()[-1])

    @property
    def rows(self) -> list[dict]:
        text = self.output_path.read_text()
        return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def write_config(workdir: Path):
    def _write(task: dict, name: str = "task.yaml") -> Path:
        path = workdir / name
        path.write_text(yaml.safe_dump({"task": task}))
        return path

    return _write


@pytest.fixture
def write_input(workdir: Path):
    def _write(rows: list[dict], name: str = "input.jsonl") -> Path:
        path = workdir / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    return _write


@pytest.fixture
def run_cli(workdir: Path):
    def _run(config: Path, input_path: Path, *extra: str, output: str = "out.jsonl") -> CliResult:
        output_path = workdir / output
        proc = subprocess.run(
            [
                sys.executable,
                str(ENTRYPOINT),
                "run",
                "--config",
                str(config),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return CliResult(proc.returncode, proc.stdout, proc.stderr, output_path)

    return _run


def base_defaults(api_url: str, **overrides) -> dict:
    """Shared `defaults` block for multi-task configs."""
    defaults = {"api_url": api_url, "model": "gpt-4", "rpm": 600, "generation": {"max_tokens": 512}}
    defaults.update(overrides)
    return defaults


def math_task(**overrides) -> dict:
    """The spec's `gsm8k` task body, as a mutable dict."""
    task = {
        "prompt": {"system": "Solve the math problem.", "user": "{question}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    }
    task.update(overrides)
    return task


def choice_task(**overrides) -> dict:
    """The spec's `mmlu` task body, as a mutable dict."""
    task = {
        "prompt": {
            "system": "Answer the multiple choice question with a single letter.",
            "user": "{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}",
        },
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "letter"},
        "output_field": "choice",
    }
    task.update(overrides)
    return task


def judge_task(**overrides) -> dict:
    """The spec's `review` task body, as a mutable dict."""
    task = {
        "prompt": {"system": "You are a writing assistant.", "user": "{prompt_text}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "llm_judge",
            "judge_prompt": {
                "system": "You are a quality evaluator.",
                "user": "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:",
            },
            "threshold": 7,
            "extract": "first_number",
        },
        "output_field": "response",
    }
    task.update(overrides)
    return task


def script_task(**overrides) -> dict:
    """The spec's `code_gen` task body, as a mutable dict."""
    task = {
        "prompt": {"system": "Write a Python function.", "user": "{problem}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "script",
            "command_template": 'bash -c "{test_code}"',
            "success_exit_code": 0,
        },
        "output_field": "code",
    }
    task.update(overrides)
    return task


@pytest.fixture
def write_yaml(workdir: Path):
    """Write an arbitrary config document, for the multi-task `defaults`/`tasks` shape."""

    def _write(document: dict, name: str = "multi.yaml") -> Path:
        path = workdir / name
        path.write_text(yaml.safe_dump(document))
        return path

    return _write


@pytest.fixture
def write_inputs(workdir: Path):
    """Write one `<name>.jsonl` per task into a directory and return that directory."""

    def _write(per_task: dict[str, list[dict]], directory: str = "data") -> Path:
        target = workdir / directory
        target.mkdir(exist_ok=True)
        for task, rows in per_task.items():
            body = "".join(json.dumps(row) + "\n" for row in rows)
            (target / f"{task}.jsonl").write_text(body)
        return target

    return _write


@pytest.fixture
def run_args(workdir: Path):
    """Run the CLI with an arbitrary argument list."""

    def _run(*argv: str, output: str = "results") -> CliResult:
        proc = subprocess.run(
            [sys.executable, str(ENTRYPOINT), *argv],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return CliResult(proc.returncode, proc.stdout, proc.stderr, workdir / output)

    return _run


def task_rows(result: CliResult, task: str) -> list[dict]:
    """Rows written to `<output_dir>/<task>.jsonl` by a multi-task run."""
    text = (result.output_path / f"{task}.jsonl").read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def inline_setup(name: str, *outputs: str) -> dict:
    """A setup whose examples answer `{question}` with the given outputs."""
    return {
        "name": name,
        "examples": [
            {"input": {"question": f"{name} q{index}"}, "output": output}
            for index, output in enumerate(outputs)
        ],
    }


def icl_block(setups: list[dict], **settings) -> dict:
    """An `icl` section: its setups plus optional `k` and `strategy`."""
    return {"setups": setups, **settings}


def used_setup(body: dict) -> str | None:
    """The ICL setup a request used, read back from its first demonstration."""
    if not any(message["role"] == "assistant" for message in body["messages"]):
        return None
    first_user = next(m for m in body["messages"] if m["role"] == "user")
    return first_user["content"].rsplit(" ", 1)[0]
