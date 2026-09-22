"""Shared fixtures: config/input writers and a subprocess runner for the CLI."""

import json
import os
import subprocess
import sys

import pytest
import yaml

from fake_api import FakeAPI  # noqa: F401  (re-exported for tests)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REJECTOR = os.path.join(REPO, "rejector.py")


class RunResult:
    """Outcome of one `python rejector.py run ...` invocation."""

    def __init__(self, proc, output_path):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr
        self._output_path = output_path

    @property
    def summary(self):
        """The JSON summary object printed on stdout."""
        text = self.stdout.strip()
        assert text, "expected a JSON summary on stdout, got nothing"
        # Tolerate other stdout lines; the summary is the last JSON object.
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise AssertionError("no JSON object on stdout: %r" % text)

    @property
    def rows(self):
        """Parsed JSONL output rows."""
        with open(self._output_path) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    @property
    def output_exists(self):
        return os.path.exists(self._output_path)

    def task_rows(self, task):
        """Parsed rows of <output_dir>/<task>.jsonl for a multi-task run."""
        with open(os.path.join(self._output_path, task + ".jsonl")) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def task_output_exists(self, task):
        return os.path.exists(os.path.join(self._output_path,
                                           task + ".jsonl"))

    @property
    def output_listing(self):
        """Names of the files written into the --output directory."""
        if not os.path.isdir(self._output_path):
            return []
        return sorted(os.listdir(self._output_path))


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.fixture
def write_config(workdir):
    """Write a task config; returns the path.

    `task` is merged over a working default so tests only state what matters.
    """
    def _write(task=None, name="task.yaml", raw=None):
        path = workdir / name
        if raw is not None:
            path.write_text(raw)
            return str(path)
        base = {
            "name": "gsm8k_solve",
            "api_url": "http://localhost:1",
            "model": "gpt-4",
            "rpm": 60,
            "prompt": {
                "system": "Solve the math problem. Put your final answer after ####.",
                "user": "{question}",
            },
            "generation": {"scheme": "greedy", "temperature": 0.0,
                           "max_tokens": 512, "n": 1},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "solution",
        }
        merged = dict(base)
        for k, v in (task or {}).items():
            if v is None:
                merged.pop(k, None)
            elif isinstance(v, dict) and isinstance(merged.get(k), dict):
                sub = dict(merged[k])
                for sk, sv in v.items():
                    if sv is None:
                        sub.pop(sk, None)
                    else:
                        sub[sk] = sv
                merged[k] = sub
            else:
                merged[k] = v
        path.write_text(yaml.safe_dump({"task": merged}, sort_keys=False))
        return str(path)
    return _write


@pytest.fixture
def write_input(workdir):
    """Write a JSONL input file; returns the path."""
    def _write(rows, name="data.jsonl", raw=None):
        path = workdir / name
        if raw is not None:
            path.write_text(raw)
            return str(path)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return str(path)
    return _write


@pytest.fixture
def write_file(workdir):
    """Write an arbitrary file under the workdir, creating parent dirs.

    `content` is either raw text or a list of objects written as JSONL.
    Returns the path relative to the workdir (configs reference ICL files
    relative to the config file's directory).
    """
    def _write(relpath, content):
        path = workdir / relpath
        os.makedirs(str(path.parent), exist_ok=True)
        if not isinstance(content, str):
            content = "".join(json.dumps(item) + "\n" for item in content)
        path.write_text(content)
        return relpath
    return _write


@pytest.fixture
def run_cli(workdir):
    """Invoke the CLI as a subprocess and return a RunResult."""
    def _run(*args, output=None, timeout=120, check=None):
        out = output or str(workdir / "results.jsonl")
        argv = [sys.executable, REJECTOR] + [str(a) for a in args]
        if "--output" not in argv:
            argv += ["--output", out]
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, cwd=str(workdir))
        res = RunResult(proc, out)
        if check is not None:
            assert res.returncode == check, (
                "exit %d (expected %d)\nstdout: %s\nstderr: %s"
                % (res.returncode, check, res.stdout, res.stderr))
        return res
    return _run


@pytest.fixture
def run_task(run_cli, write_config, write_input):
    """Config + input + server -> RunResult, the common end-to-end path."""
    def _run(server=None, task=None, rows=None, extra=(), check=None,
             api_url=None, config_raw=None, input_raw=None, timeout=120):
        task = dict(task or {})
        if server is not None and "api_url" not in task:
            task["api_url"] = server.url
        if api_url is not None:
            task["api_url"] = api_url
        cfg = write_config(task, raw=config_raw)
        if rows is None and input_raw is None:
            rows = [{"question": "What is 2 + 3?", "answer": "5"}]
        inp = write_input(rows, raw=input_raw)
        return run_cli("run", "--config", cfg, "--input", inp,
                       *extra, check=check, timeout=timeout)
    return _run


# ---------------------------------------------------------------------------
# Part 2: multi-task configs
# ---------------------------------------------------------------------------

MULTI_DEFAULTS = {
    "api_url": "http://localhost:1",
    "model": "gpt-4",
    "rpm": 60,
    "generation": {"max_tokens": 512},
}

MULTI_TASKS = {
    "gsm8k": {
        "prompt": {"system": "Solve the math problem.", "user": "{question}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "exact_match", "answer_field": "answer",
                       "extract": "last_number"},
        "output_field": "solution",
    },
    "mmlu": {
        "prompt": {"system": "Answer with a single letter.",
                   "user": "{question}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "exact_match", "answer_field": "answer",
                       "extract": "letter"},
        "output_field": "choice",
    },
}


@pytest.fixture
def write_multi_config(workdir):
    """Write a `defaults` + `tasks` config; returns the path.

    `defaults`/`tasks` are merged over a working pair of tasks so a test only
    states what it cares about.  A value of None removes a key.
    """
    def _merge(base, over):
        out = dict(base)
        for k, v in (over or {}).items():
            if v is None:
                out.pop(k, None)
            elif isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = _merge(out[k], v)
            else:
                out[k] = v
        return out

    def _write(defaults=None, tasks=None, name="multi.yaml", raw=None,
               replace_tasks=False):
        path = workdir / name
        if raw is not None:
            path.write_text(raw)
            return str(path)
        doc = {"defaults": _merge(MULTI_DEFAULTS, defaults)}
        if replace_tasks:
            doc["tasks"] = tasks or {}
        else:
            doc["tasks"] = _merge(MULTI_TASKS, tasks)
        path.write_text(yaml.safe_dump(doc, sort_keys=False))
        return str(path)
    return _write


@pytest.fixture
def write_inputs(workdir):
    """Write several JSONL inputs at once; returns {task: path}."""
    def _write(mapping, subdir=None):
        base = workdir if subdir is None else workdir / subdir
        os.makedirs(str(base), exist_ok=True)
        paths = {}
        for task, rows in mapping.items():
            p = base / (task + ".jsonl")
            p.write_text("".join(json.dumps(r) + "\n" for r in rows))
            paths[task] = str(p)
        return paths
    return _write


@pytest.fixture
def run_multi(run_cli, write_multi_config, write_inputs, workdir):
    """Multi-task config + per-task inputs + server -> RunResult."""
    def _run(server=None, defaults=None, tasks=None, inputs=None, extra=(),
             check=None, config_raw=None, out_dir="results",
             replace_tasks=False):
        defaults = dict(defaults or {})
        if server is not None and "api_url" not in defaults:
            defaults["api_url"] = server.url
        cfg = write_multi_config(defaults, tasks, raw=config_raw,
                                 replace_tasks=replace_tasks)
        inputs = inputs if inputs is not None else {
            "gsm8k": [{"question": "2+3?", "answer": "5"}],
            "mmlu": [{"question": "capital?", "answer": "B"}],
        }
        paths = write_inputs(inputs)
        args = ["run", "--config", cfg]
        for task, path in paths.items():
            args += ["--input", "%s=%s" % (task, path)]
        out = str(workdir / out_dir)
        return run_cli(*args, "--output", out, *extra, output=out, check=check)
    return _run


# ---------------------------------------------------------------------------
# Checkpoint 4: agentic tasks and completions mode
# ---------------------------------------------------------------------------

LOOKUP_TOOL = {
    "name": "lookup",
    "description": "Look up a value in the database by key",
    "parameters": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "The database key to look up"},
        },
        "required": ["key"],
    },
    "handler": {
        "type": "static_map",
        "mapping": {"revenue_q1": "1250000", "revenue_q2": "1480000",
                    "employees": "142"},
        "default": "KEY_NOT_FOUND",
    },
}

CALCULATE_TOOL = {
    "name": "calculate",
    "description": "Evaluate a mathematical expression",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string",
                           "description": "The math expression to evaluate"},
        },
        "required": ["expression"],
    },
    "handler": {"type": "echo"},
}


def agentic_config(**over):
    """The spec's `data_lookup` agentic task, merged with `over`."""
    task = {
        "name": "data_lookup",
        "prompt": {
            "system": "You are a data analysis assistant. Use the provided "
                      "tools to look up data and answer questions.",
            "user": "{question}",
        },
        "generation": {"scheme": "agentic", "max_iterations": 10,
                       "temperature": 0.0, "max_tokens": 512, "n": None},
        "evaluation": {"type": "exact_match", "answer_field": "answer",
                       "extract": "last_number"},
        "output_field": "answer",
        "tools": [json.loads(json.dumps(LOOKUP_TOOL)),
                  json.loads(json.dumps(CALCULATE_TOOL))],
    }
    task.update(over)
    return task


@pytest.fixture
def agentic_task():
    return agentic_config


@pytest.fixture
def run_agentic(run_task):
    """Run the spec's agentic task against a server; returns a RunResult."""
    def _run(server, task=None, rows=None, extra=(), check=None, **kw):
        cfg = agentic_config(**(task or {}))
        if rows is None:
            rows = [{"question": "What is the total revenue for Q1 and Q2?",
                     "answer": "2730000"}]
        return run_task(server=server, task=cfg, rows=rows, extra=extra,
                        check=check, **kw)
    return _run
