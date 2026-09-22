# rejector

CLI that runs YAML-configured prompting tasks over JSONL input files against
an OpenAI-compatible chat-completions API.  A config is either the Part 1
single-task form (`task:`) or the Part 2 multi-task form (`defaults:` +
`tasks:`).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
.venv/bin/python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --output results/
.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ --output results/ --task gsm8k
```

Multi-task runs write `<output_dir>/<task_name>.jsonl` and add a `tasks` object
to the stdout summary.  Tasks may declare named ICL setups (`icl.setups`, with
inline `examples` or a JSONL `file` resolved relative to the config) and ask for
several solutions per input (`num_solutions`); either switches the row format to
a list of `{<output_field>, icl_setup}` objects with one `meta` entry per
attempt.  Rejection sampling then collects up to `num_solutions` passing
solutions within `generation.max_attempts` (default `3 * num_solutions`).

Tasks may also use `generation.scheme: agentic`: the model calls the task's
`tools` in a loop (`generation.max_iterations` requests, default 10) before
producing a final answer.  Each tool has a `handler` — `echo`, `static_map`
(first required parameter looked up in `mapping`, else `default`) or `script`
(runs `command` with `arg_field` as one argument, 10 s timeout).  An agentic
row reports `result.iterations` / `result.tool_calls` and an aggregated `meta`
with `iterations_detail`; ICL or `num_solutions > 1` keeps the list format
with one loop per item.

With `api_type: completions` requests go to `{api_url}/v1/completions` as a
prompt string rendered with `chat_template` (`chatml`, `llama3`, `mistral`,
`zephyr`), and the output is read from `choices[0].text`.  In that mode tool
definitions are rendered into the prompt and tool calls are parsed from
`<tool_call>{...}</tool_call>` blocks.

Evaluation types: `exact_match`, `contains`, `regex`,
`script` (shell command, 10 s timeout), `llm_judge` (a second API call scored
against `threshold`).  Extract methods: `full`, `last_line`, `last_number`,
`first_number`, `letter`.

Overrides: `--api-url --model --rpm --max-tokens --scheme --temperature --n
--task --eval-model --num-solutions --icl-strategy --icl-k --api-type
--chat-template`.
Exit `0` on success, `1` on a configuration or input error.

- `rejector.py` — the tool (stdlib + PyYAML; concurrency via a thread pool
  sized from `rpm`, rejection attempts sequential within a row).
- `tests/` — spec-derived tests; `tests/fake_api.py` is a scriptable
  OpenAI-compatible fake server (latency, 5xx injection, queue capacity).
- `AMBIGUITIES.md` — T1–T86, the interpretation decisions and their risk.

```bash
.venv/bin/python -m pytest
```
