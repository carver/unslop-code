# rejector

CLI tool that runs a YAML-defined generation task over a JSONL input file
against an OpenAI-compatible chat completions API, and writes one JSONL result
per input row.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl \
  [--api-url URL] [--model NAME] [--rpm N] [--max-tokens N] \
  [--scheme greedy|sample|rejection] [--temperature F] [--n N]
```

Exit code `0` on success, `1` on a configuration or input error (message on
stderr). A JSON summary is printed to stdout when the run finishes.

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | argument parsing and the top-level run sequence |
| `rejlib/config.py` | YAML loading, CLI override merging, validation |
| `rejlib/prompts.py` | `{field}` template rendering, per-row field requirements |
| `rejlib/evaluation.py` | extraction methods and the three evaluation types |
| `rejlib/api.py` | chat completions client, 5xx retries, run-wide counters |
| `rejlib/ratelimit.py` | token bucket pacing requests against the `rpm` budget |
| `rejlib/schemes.py` | greedy / sample / rejection generation per row |
| `rejlib/runner.py` | concurrent fan-out, output row assembly, summary |
| `rejlib/jsonl.py` | JSONL input parsing and output writing |

Concurrency: rows are dispatched in input order, up to one minute of `rpm`
budget in flight, each row keeping its own response. See `AMBIGUITIES.md` for
the interpretation decisions behind the behaviour.

## Tests

```bash
.venv/bin/python -m pytest
```

`tests/fake_api.py` provides a threaded OpenAI-compatible stand-in with
scriptable responses, an optional per-request delay, and a request log.
