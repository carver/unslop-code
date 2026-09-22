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


@dataclass
class CLIResult:
    """The outcome of one `rejector.py run` invocation."""

    returncode: int
    stdout: str
    stderr: str
    output_path: Path

    @property
    def summary(self) -> dict:
        return json.loads(self.stdout)

    @property
    def rows(self) -> list:
        text = self.output_path.read_text()
        return [json.loads(line) for line in text.splitlines() if line.strip()]


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
