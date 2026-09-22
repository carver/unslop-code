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

    def rows_for(self, task_name):
        """Parsed rows of `<output_dir>/<task_name>.jsonl` (Part 2)."""
        path = self._output_path / f"{task_name}.jsonl"
        text = path.read_text()
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def task_file(self, task_name):
        return self._output_path / f"{task_name}.jsonl"

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
            values = input if isinstance(input, (list, tuple)) else [input]
            for value in values:
                argv += ["--input", str(value)]
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


# ---------------------------------------------------------------------------
# Part 2 helpers: multi-task configs (`defaults` + `tasks`).
# ---------------------------------------------------------------------------
def multi_config(api_url, tasks, defaults=None):
    """Build a `defaults`/`tasks` config with sane shared defaults."""
    base_defaults = {
        "api_url": api_url,
        "model": "gpt-4",
        "rpm": 600,
        "generation": {"max_tokens": 512},
    }
    if defaults:
        for key, value in defaults.items():
            if value is None:
                base_defaults.pop(key, None)
            elif isinstance(value, dict) and isinstance(base_defaults.get(key), dict):
                merged = dict(base_defaults[key])
                merged.update(value)
                base_defaults[key] = merged
            else:
                base_defaults[key] = value
    return {"defaults": base_defaults, "tasks": tasks}


GSM8K_TASK = {
    "prompt": {
        "system": "Solve the math problem step by step. Put your final answer after ####.",
        "user": "{question}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {
        "type": "exact_match",
        "answer_field": "answer",
        "extract": "last_number",
    },
    "output_field": "solution",
}

MMLU_TASK = {
    "prompt": {
        "system": "Answer the multiple choice question with a single letter.",
        "user": "{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {
        "type": "exact_match",
        "answer_field": "answer",
        "extract": "letter",
    },
    "output_field": "choice",
}

SCRIPT_TASK = {
    "prompt": {
        "system": "Write a Python function. Output only code.",
        "user": "{problem}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {
        "type": "script",
        "command_template": "python3 -c \"{test_code}\"",
        "success_exit_code": 0,
    },
    "output_field": "code",
}

JUDGE_TASK = {
    "prompt": {
        "system": "You are a writing assistant. Write a response to the given prompt.",
        "user": "{prompt_text}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {
        "type": "llm_judge",
        "judge_prompt": {
            "system": "You are a quality evaluator. Respond with only a single integer from 1 to 10.",
            "user": "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:",
        },
        "threshold": 7,
        "extract": "first_number",
    },
    "output_field": "response",
}


def judge_responder(gen_text="a fine response", judge_text="8", *,
                    gen_by_prompt=None, judge_by_response=None):
    """Responder that tells generation calls from judge calls.

    A judge call is identified by the judge system prompt ("quality evaluator").
    `gen_by_prompt` maps user prompt -> generation text; `judge_by_response`
    maps the generated text found inside the judge prompt -> judge reply.
    """
    from mock_server import completion

    def responder(req, i):
        messages = (req or {}).get("messages", [])
        system = ""
        user = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            elif m.get("role") == "user":
                user = m.get("content", "")
        is_judge = "evaluator" in system.lower() or "rate" in user.lower()[:40]
        if is_judge:
            reply = judge_text
            if judge_by_response:
                for needle, value in judge_by_response.items():
                    if needle in user:
                        reply = value
                        break
            return 200, completion(reply, prompt_tokens=11,
                                   completion_tokens=2,
                                   finish_reason="length")
        text = gen_text
        if gen_by_prompt:
            text = gen_by_prompt.get(user, gen_text)
        return 200, completion(text)

    return responder


# ---------------------------------------------------------------------------
# Part 3 helpers: ICL setups and multi-solution configs.
# ---------------------------------------------------------------------------
COT_SETUP = {
    "name": "chain_of_thought",
    "examples": [
        {"input": {"question": "What is 2+2?"},
         "output": "Let me think step by step.\n2 + 2 = 4\n#### 4"},
        {"input": {"question": "If I have 3 cats and get 2 more, how many cats do I have?"},
         "output": "Step by step:\nI start with 3 cats.\nI get 2 more.\n3 + 2 = 5\n#### 5"},
    ],
}

DIRECT_SETUP = {
    "name": "direct",
    "examples": [
        {"input": {"question": "What is 2+2?"}, "output": "#### 4"},
        {"input": {"question": "If I have 3 cats and get 2 more, how many cats do I have?"},
         "output": "#### 5"},
    ],
}

TERSE_SETUP = {
    "name": "terse",
    "examples": [
        {"input": {"question": "What is 1+1?"}, "output": "#### 2"},
    ],
}


def icl_config(api_url, setups, *, k=None, strategy=None, **overrides):
    """A single-task config with an `icl` section."""
    icl = {"setups": setups}
    if k is not None:
        icl["k"] = k
    if strategy is not None:
        icl["strategy"] = strategy
    return base_config(api_url, icl=icl, **overrides)


def messages_of(request):
    return [(m.get("role"), m.get("content")) for m in request["messages"]]


def roles_of(request):
    return [m.get("role") for m in request["messages"]]


def assistant_texts(request):
    return [m["content"] for m in request["messages"]
            if m.get("role") == "assistant"]


def setup_of_request(request, names_by_first_assistant):
    """Map a request to the setup name that produced its ICL block."""
    shots = assistant_texts(request)
    if not shots:
        return None
    return names_by_first_assistant.get(shots[0])


def setup_marker(api, marker_map):
    """Sequence of setup names used by each recorded request, in order."""
    return [setup_of_request(req, marker_map) for req in api.requests]
