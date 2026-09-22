# rejector

A CLI that runs a prompt task from a YAML config over a JSONL dataset against an
OpenAI compatible `/v1/chat/completions` endpoint, evaluates each response, and
writes one JSONL result per input row.

## Install

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
python rejector.py run --config examples/task.yaml \
                       --input examples/data.jsonl \
                       --output results.jsonl
```

`--api-url`, `--model`, `--rpm`, `--scheme`, `--temperature`, `--max-tokens`
and `--n` override the matching config values. The run summary is printed to
stdout as a single JSON object; configuration and input problems are reported on
stderr with exit code `1`.

## Configuration

```yaml
task:
  name: "gsm8k_solve"
  api_url: "http://localhost:8000"
  model: "gpt-4"
  rpm: 60                       # request budget, also the target throughput

  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"          # {field} placeholders come from the input row

  generation:
    scheme: "greedy"            # greedy | sample | rejection
    temperature: 0.0            # must be > 0 for sample and rejection
    max_tokens: 512
    n: 1                        # rejection only: attempts per row

  evaluation:                   # required for rejection, optional otherwise
    type: "exact_match"         # exact_match | contains | regex
    answer_field: "answer"      # exact_match and contains
    extract: "last_number"      # last_number | last_line | full
    # pattern: "####\\s*(\\d+)" # regex only

  output_field: "solution"
```

Schemes:

| scheme | behaviour |
| --- | --- |
| `greedy` | one attempt at temperature `0.0` |
| `sample` | one attempt at the configured temperature |
| `rejection` | up to `n` attempts, keeping the first that passes evaluation; `output` is `null` if none do |

Evaluation types compare a response against the row: `exact_match` extracts a
value with the configured `extract` method and compares it to `answer_field`,
`contains` looks for the `answer_field` value as a substring, and `regex`
searches for `pattern` (its first capturing group, if any, becomes the extracted
answer). Without an `evaluation` block `result.passed` is `null`.

## Output

One JSON object per input row, in input order:

```json
{
  "input": {"question": "What is 2 + 3?", "answer": "5"},
  "output": {"solution": "2 + 3 = 5\n#### 5"},
  "result": {"passed": true, "extracted_answer": "5", "attempts": 1},
  "meta": {"model": "gpt-4", "prompt_tokens": 30, "completion_tokens": 10,
           "total_tokens": 40, "latency_ms": 150, "finish_reason": "stop"}
}
```

`meta` becomes a list with one entry per attempt when rejection sampling makes
more than one. A row whose request kept failing gets `"output": null` and
`"meta": null`.

## Throughput

Requests run concurrently: up to `rpm` rows are in flight at once and a token
bucket paces request starts at `rpm` per minute with a one minute burst, so a
slow server is kept busy without exceeding the configured budget. Rows are
claimed in input order and results are stored by row index, so a late response
can never be attributed to another row. HTTP `5xx` responses are retried up to
three requests in total; the retries count toward `total_api_calls` but not
toward `result.attempts`.

## Layout

| file | contents |
| --- | --- |
| `rejector.py` | CLI parsing, wiring, exit codes |
| `config.py` | YAML loading, CLI override merging, validation |
| `prompts.py` | prompt template rendering |
| `evaluation.py` | answer extraction and the evaluation types |
| `client.py` | chat completions client, retries, rate limiting |
| `runner.py` | concurrency, generation schemes, records and summary |
| `jsonl.py` | JSONL reading and writing |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

`tests/mock_server.py` stands in for the API: it queues requests and serves a
limited number in parallel. It also runs standalone for manual tries, answering
with the sum of the numbers in the prompt:

```bash
python tests/mock_server.py --port 8000 --delay 0.5 --capacity 8 --wrong-first 2
```
