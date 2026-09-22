from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
REJECTOR = ROOT / "rejector.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))


class RunResult:
    def __init__(self, proc, output_path):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr
        self._output_path = Path(output_path)

    @property
    def rows(self):
        """Parsed JSONL output rows."""
        text = self._output_path.read_text()
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    @property
    def output_exists(self):
        return self._output_path.exists()

    @property
    def summary(self):
        """The single JSON summary object printed to stdout."""
        lines = [l for l in self.stdout.splitlines() if l.strip()]
        assert lines, f"no stdout summary; stderr={self.stderr}"
        return json.loads(lines[-1])

    def __repr__(self):
        return (f"RunResult(rc={self.returncode}, stdout={self.stdout!r}, "
                f"stderr={self.stderr!r})")


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.fixture
def write_config(workdir):
    def _write(cfg, name="task.yaml"):
        path = workdir / name
        path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        return str(path)
    return _write


@pytest.fixture
def write_input(workdir):
    def _write(rows, name="data.jsonl"):
        path = workdir / name
        if isinstance(rows, str):
            path.write_text(rows)
        else:
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return str(path)
    return _write


@pytest.fixture
def run_tool(workdir):
    """Invoke `python rejector.py run ...` as a subprocess."""
    def _run(config=None, input=None, output=None, extra=(), timeout=120,
             subcommand="run"):
        out = output or str(workdir / "results.jsonl")
        argv = [sys.executable, str(REJECTOR)]
        if subcommand:
            argv.append(subcommand)
        if config is not None:
            argv += ["--config", str(config)]
        if input is not None:
            argv += ["--input", str(input)]
        if output is not False:
            argv += ["--output", out]
        argv += [str(a) for a in extra]
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, cwd=str(ROOT), env=env)
        return RunResult(proc, out)
    return _run


def base_config(api_url, **overrides):
    """The spec's canonical config, with per-test overrides merged in."""
    cfg = {
        "task": {
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
    }
    task = cfg["task"]
    for key, value in overrides.items():
        if value is None:
            task.pop(key, None)
        elif isinstance(value, dict) and isinstance(task.get(key), dict):
            merged = dict(task[key])
            for k, v in value.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
            task[key] = merged
        else:
            task[key] = value
    return cfg


@pytest.fixture
def cfg_builder():
    return base_config
