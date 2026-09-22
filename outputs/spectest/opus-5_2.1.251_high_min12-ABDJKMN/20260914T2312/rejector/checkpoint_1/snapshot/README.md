# rejector

CLI that runs a YAML-configured prompting task over a JSONL input file against
an OpenAI-compatible chat-completions API.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Overrides: `--api-url --model --rpm --max-tokens --scheme --temperature --n`.
Exit `0` on success, `1` on a configuration or input error.

- `rejector.py` — the tool (stdlib + PyYAML; concurrency via a thread pool
  sized from `rpm`, rejection attempts sequential within a row).
- `tests/` — spec-derived tests; `tests/fake_api.py` is a scriptable
  OpenAI-compatible fake server (latency, 5xx injection, queue capacity).
- `AMBIGUITIES.md` — T1–T24, the interpretation decisions and their risk.

```bash
.venv/bin/python -m pytest
```
