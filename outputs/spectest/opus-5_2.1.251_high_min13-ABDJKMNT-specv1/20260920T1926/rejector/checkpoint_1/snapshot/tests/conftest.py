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
