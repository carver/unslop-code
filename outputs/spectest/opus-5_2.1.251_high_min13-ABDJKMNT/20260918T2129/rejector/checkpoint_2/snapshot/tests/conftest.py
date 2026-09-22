"""Shared fixtures: config/input builders and a CLI invoker."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = REPO_ROOT / "rejector.py"


def base_config(api_url: str, **task_overrides) -> dict:
    """A valid greedy exact_match config, used as the starting point."""
    task = {
        "name": "gsm8k_solve",
        "api_url": api_url,
        "model": "gpt-4",
        "rpm": 600,
        "prompt": {
            "system": "Solve the math problem. Put your final answer after ####.",
            "user": "{question}",
        },
        "generation": {"scheme": "greedy", "temperature": 0.0, "max_tokens": 512, "n": 1},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    }
    task.update(task_overrides)
    return {"task": task}


GSM8K_TASK = {
    "prompt": {
        "system": "Solve the math problem step by step. Put your final answer after ####.",
        "user": "{question}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
}

MMLU_TASK = {
    "prompt": {
        "system": "Answer the multiple choice question with a single letter.",
        "user": "{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "letter"},
    "output_field": "choice",
}


def multi_config(api_url: str, tasks: dict, **defaults) -> dict:
    """A `defaults` + `tasks` config; `tasks` maps task name to its section."""
    shared = {"api_url": api_url, "model": "gpt-4", "rpm": 600, "generation": {"max_tokens": 512}}
    shared.update(defaults)
    return {"defaults": shared, "tasks": tasks}


@dataclass
class CLIResult:
    """The outcome of one `rejector.py run` invocation."""

    returncode: int
    stdout: str
    stderr: str
    output_path: Path
    payloads: list | None = None

    @property
    def summary(self) -> dict:
        return json.loads(self.stdout)

    @property
    def rows(self) -> list:
        return self.rows_of(self.output_path)

    def task_rows(self, task_name: str) -> list:
        """Rows from `<output_dir>/<task_name>.jsonl` of a multi-task run."""
        return self.rows_of(self.output_path / f"{task_name}.jsonl")

    @staticmethod
    def rows_of(path: Path) -> list:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def write_config(workdir: Path):
    """Write a config mapping to YAML and return its path."""

    def _write(config: dict, name: str = "task.yaml") -> Path:
        path = workdir / name
        path.write_text(yaml.safe_dump(config))
        return path

    return _write


@pytest.fixture
def write_input(workdir: Path):
    """Write rows (dicts or raw strings) as a JSONL file and return its path."""

    def _write(rows: list, name: str = "input.jsonl") -> Path:
        path = workdir / name
        lines = [row if isinstance(row, str) else json.dumps(row) for row in rows]
        path.write_text("\n".join(lines) + "\n" if lines else "")
        return path

    return _write


@pytest.fixture
def run_cli(workdir: Path):
    """Invoke `python rejector.py run ...` as a subprocess."""

    def _run(config_path: Path, input_path: Path, *extra, output_name: str = "results.jsonl") -> CLIResult:
        output_path = workdir / output_name
        argv = [
            sys.executable,
            str(ENTRY_POINT),
            "run",
            "--config",
            str(config_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            *extra,
        ]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
        return CLIResult(proc.returncode, proc.stdout, proc.stderr, output_path)

    return _run


@pytest.fixture
def run_argv(workdir: Path):
    """Invoke `python rejector.py run ...` with an explicit flag list.

    Unlike `run_cli`, nothing is supplied implicitly, so multi-task input
    modes and task selection can be exercised directly.  `output` names the
    path passed to `--output`, which is a directory for multi-task runs.
    """

    def _run(*argv: str, output: str | Path = "results") -> CLIResult:
        output_path = workdir / output
        command = [sys.executable, str(ENTRY_POINT), "run", *[str(arg) for arg in argv]]
        command += ["--output", str(output_path)]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=180)
        return CLIResult(proc.returncode, proc.stdout, proc.stderr, output_path)

    return _run
