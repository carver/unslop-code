# rejector

A CLI that runs a YAML-defined prompt task over a JSONL dataset against an
OpenAI-compatible chat completions API, evaluates each response, and writes one
JSONL result row per input row.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
python rejector.py run --config examples/greedy.yaml \
                       --input examples/data.jsonl \
                       --output results.jsonl
```

Optional flags override the matching config value: `--api-url`, `--model`,
`--rpm`, `--max-tokens`, `--scheme`, `--temperature`, `--n`.

Exit codes: `0` on success, `1` for a configuration or input error (the message
goes to stderr). The run summary is printed to stdout as a single JSON object.

## Configuration

```yaml
task:
  name: "gsm8k_solve"
  api_url: "http://localhost:8000"   # required
  model: "gpt-4"                     # required
  rpm: 60                            # request budget per minute (default 60)

  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"               # required; {field} is taken from the input row

  generation:
    scheme: "greedy"                 # greedy | sample | rejection (default greedy)
    temperature: 0.0
    max_tokens: 512                  # default 512
    n: 1                             # rejection sampling attempts (default 1)

  evaluation:                        # required for rejection, optional otherwise
    type: "exact_match"              # exact_match | contains | regex
    answer_field: "answer"           # required for exact_match and contains
    extract: "last_number"           # last_number | last_line | full (default full)
    # pattern: "####\\s+\\d+"        # required for regex

  output_field: "solution"           # required; names the key inside "output"
```

### Schemes

| Scheme | Temperature | Attempts per row |
| --- | --- | --- |
| `greedy` | forced to `0.0` | 1 |
| `sample` | must be `> 0` | 1 |
| `rejection` | must be `> 0` | up to `n`, stopping at the first response that passes evaluation |

A rejection row that never passes is written with `"output": null`,
`"passed": false` and one metadata entry per attempt.

### Evaluation

`exact_match` compares the extracted answer with the row's `answer_field`;
numbers compare by value (`8` == `8.0`) and other text compares
case-insensitively. `contains` tests whether the response text contains the
`answer_field` value. `regex` searches the response text for `pattern`.
Without an `evaluation` section, `result.passed` is `null` and any row the API
answered counts as passed in the summary.

## Behaviour notes

- **Concurrency.** Requests are paced by a token bucket sized to `rpm`. The
  bucket starts full, so a run can put a minute of budget in flight immediately
  and then settles at `rpm` requests per minute — enough in-flight work to keep
  a queueing server busy instead of idling between responses. Measured
  throughput lands within a few percent of the configured `rpm` when the server
  can sustain it.
- **Retries.** An HTTP 5xx is retried up to 3 times (4 requests in total). Once
  the budget is spent the row is written with a `null` output and counted as
  failed. Retries count toward `total_api_calls` but never toward
  `result.attempts`, which only counts logical generation attempts. Any other
  non-2xx status is reported as an error and stops the run with exit code 1.
- **Validation order.** The config and every input row are validated before the
  first request, so a missing prompt field fails fast (`input row 0: missing
  field 'question'`) without spending API calls.

## Layout

| File | Responsibility |
| --- | --- |
| `rejector.py` | CLI parsing, wiring and exit codes |
| `config.py` | YAML loading, CLI overrides, config validation |
| `dataset.py` | JSONL input/output, prompt rendering and row validation |
| `api.py` | async chat completions client, rate limiter, retries |
| `evaluation.py` | answer extraction and the pass/fail checks |
| `runner.py` | per-row schemes, concurrency, summary aggregation |
| `errors.py` | the user-facing error type |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

`tests/mock_server.py` is a standalone OpenAI-compatible mock used by the
end-to-end tests; it processes a bounded number of requests at a time so extra
requests queue, and it can inject 5xx failures and wrong answers:

```bash
.venv/bin/python tests/mock_server.py --port 8000 --rpm 60 --latency 3.0 --accuracy 0.5
python rejector.py run --config examples/rejection.yaml --input tests/data.jsonl --output out.jsonl
```

It answers with the last number in the prompt, which is why `tests/data.jsonl`
states each expected answer in the question.
