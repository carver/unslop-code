"""Make the tool's modules importable from the tests directory, and share the CLI harness."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mock_server import start_mock_server  # noqa: E402
import rejector  # noqa: E402


@dataclass(frozen=True)
class Run:
    """What one CLI invocation produced."""

    code: int
    records: list[dict]
    summary: dict | None
    stderr: str


@pytest.fixture
def api():
    """Start a mock server whose responder the test installs afterwards."""
    servers = []

    def start(responder, delay=0.0, capacity=8):
        url, state, shutdown = start_mock_server(responder, delay=delay, capacity=capacity)
        servers.append(shutdown)
        return url, state

    yield start
    for shutdown in servers:
        shutdown()


@pytest.fixture
def cli(tmp_path, capsys):
    """Run the CLI over a task config and its rows, reading back what it wrote.

    Multi task configs pass the whole document as `task`, an `--output`
    directory then holding one file per task.
    """

    def run(task: dict, rows, *flags: str, multi: bool = False) -> Run:
        document = task if multi else {"task": task}
        (tmp_path / "task.yaml").write_text(yaml.safe_dump(document))
        inputs = _write_inputs(tmp_path, rows)
        output = tmp_path / ("results" if multi else "out.jsonl")
        code = rejector.main(
            ["run", "--config", str(tmp_path / "task.yaml"), *inputs,
             "--output", str(output), *flags]
        )
        streams = capsys.readouterr()
        return Run(code, read_records(output), _json(streams.out), streams.err)

    return run


def _write_inputs(tmp_path, rows) -> list[str]:
    """One `--input` flag per task; a plain list of rows is a single task's input."""
    if isinstance(rows, dict):
        flags = []
        for name, task_rows in rows.items():
            write_rows(tmp_path / f"{name}.jsonl", task_rows)
            flags.extend(["--input", f"{name}={tmp_path / f'{name}.jsonl'}"])
        return flags
    write_rows(tmp_path / "in.jsonl", rows)
    return ["--input", str(tmp_path / "in.jsonl")]


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def read_records(path: Path) -> list[dict]:
    """The records of an output file, or of every file in an output directory."""
    if path.is_dir():
        return [record for child in sorted(path.iterdir()) for record in read_records(child)]
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _json(text: str) -> dict | None:
    return json.loads(text) if text.strip() else None
