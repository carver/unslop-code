# rejector

A CLI that runs a YAML-described generation task over a JSONL input file
against an OpenAI-compatible chat completions API, evaluates each response,
and writes one JSONL result per input row.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python rejector.py run \
  --config examples/task.yaml \
  --input examples/data.jsonl \
  --output results.jsonl
```

Any of `--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`,
`--temperature`, and `--n` override the matching config value. The run prints a
JSON summary to stdout and exits `0`; configuration and input problems print a
message to stderr and exit `1`.

## Configuration

See `examples/task.yaml`. Highlights:

- `prompt.system` / `prompt.user` are templates with `{field}` placeholders
  filled from each input row. `prompt.system` is optional.
- `generation.scheme`:
  - `greedy` forces `temperature` to `0.0`, one response per row.
  - `sample` requires `temperature > 0`, one response per row.
  - `rejection` requires `temperature > 0` and an `evaluation`; it makes up to
    `n` attempts and keeps the first response that passes.
- `evaluation.type` is `exact_match`, `contains`, or `regex`. The first two need
  `answer_field`; `regex` needs `pattern`. Without an `evaluation` block,
  `result.passed` is `null`. `exact_match` compares numerically when both the
  extracted and expected values are numbers.
- `evaluation.extract` (`last_number`, `last_line`, or `full`, default `full`)
  selects the value reported as `result.extracted_answer`.

## Throughput

`rpm` is treated as the server's request budget. A token bucket
(`ratelimit.py`) paces requests at that rate, allowing a tenth of the budget as
an initial burst so the server's queue fills immediately, and a pool of workers
(sized to the budget, capped at `MAX_WORKERS`) keeps that many requests in
flight. Workers pull row indices from a shared queue in input order and each
one owns its row's response, so results stay aligned with the input regardless
of completion order.

A `5xx` response or a transport failure is retried up to 3 requests in total per
attempt. Retries count toward `total_api_calls` but not toward
`result.attempts`; a row that never gets a response has `output: null` and is
counted as failed.

## Layout

| File | Responsibility |
| --- | --- |
| `rejector.py` | entry point |
| `cli.py` | argument parsing, exit codes, summary printing |
| `config.py` | YAML loading, override merging, validation |
| `dataset.py` | JSONL loading, prompt rendering, per-row field checks |
| `schemes.py` | greedy / sample / rejection generation logic |
| `pipeline.py` | worker pool and per-run orchestration |
| `ratelimit.py` | request pacing |
| `api.py` | HTTP client, retries, call statistics |
| `evaluation.py` | answer extraction and pass/fail checks |
| `results.py` | result records, JSONL output, run summary |
| `errors.py` | user-facing error types |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

`tests/mock_server.py` is a small stand-in API that serves a fixed number of
requests concurrently after a configurable delay, and can fail a prompt's first
`N` attempts (`--pass-after`) or reply `503` to everything (`--always-fail`).
