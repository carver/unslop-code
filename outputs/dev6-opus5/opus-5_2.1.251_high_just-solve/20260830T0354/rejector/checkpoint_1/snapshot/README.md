# rejector

A CLI that reads a YAML task config plus a JSONL input file, sends prompts to an
OpenAI-compatible chat completions API concurrently, and writes one JSONL result
per input row.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Optional overrides, each replacing the matching config value:
`--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`, `--temperature`, `--n`.

Exit codes: `0` on success, `1` on a configuration or input error (message on stderr).

## Config

```yaml
task:
  name: "gsm8k_solve"
  api_url: "http://localhost:8000"
  model: "gpt-4"
  rpm: 60
  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"
  generation:
    scheme: "greedy"      # greedy | sample | rejection
    temperature: 0.0
    max_tokens: 512
    n: 1
  evaluation:
    type: "exact_match"   # exact_match | contains | regex
    answer_field: "answer"
    extract: "last_number"  # last_number | last_line | full
  output_field: "solution"
```

- `greedy` forces `temperature: 0.0` and ignores `n`.
- `sample` and `rejection` require `temperature > 0`; `sample` ignores `n`.
- `rejection` makes up to `n` attempts and keeps the first response that passes
  evaluation; if none pass, `output` is `null` and `result.passed` is `false`.
- `evaluation` is required for `rejection` and optional otherwise. Without it,
  `result.passed` is `null`.

## Output

One JSON object per input row, in input order:

```json
{"input": {...}, "output": {"solution": "..."}, "result": {"passed": true, "extracted_answer": "8", "attempts": 1}, "meta": {"model": "gpt-4", "prompt_tokens": 45, "completion_tokens": 120, "total_tokens": 165, "latency_ms": 230, "finish_reason": "stop"}}
```

`meta` is a single object for one-attempt rows and a list (one entry per attempt)
for rejection rows that took more than one attempt. A JSON summary is printed to
stdout when the run finishes.

## Concurrency

Requests are issued concurrently and paced by a token bucket set to the
configured `rpm`. The bucket's capacity — the number of requests allowed in
flight — starts small and grows with observed latency (Little's law: sustaining
`rate` requests per second against `L`-second requests needs `rate * L` in
flight). That fills the pipeline once, then holds the steady-state issue rate at
roughly the configured budget. `5xx` responses are retried up to 3 times; retries
count toward `total_api_calls` but not toward `result.attempts`.

## Tests

```bash
.venv/bin/python tests/run_tests.py
```

Spins up a mock OpenAI-compatible server (`tests/mock_server.py`) that queues
requests with a bounded worker pool, and exercises the schemes, evaluation types,
extraction methods, retry behaviour, validation errors, and throughput.
