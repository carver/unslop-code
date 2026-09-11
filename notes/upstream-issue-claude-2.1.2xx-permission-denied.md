# ClaudeCodeAgent crashes on Claude Code 2.1.251's `permission_denied` stream event

Claude Code 2.1.251 emits a `system` / `permission_denied` event whose `message` field is a
string. `ClaudeCodeAgent._run()` assumes `message` is a dict and raises
`AttributeError: 'str' object has no attribute 'get'`, which fails the whole problem. Claude
Code 2.1.44, the version on the leaderboard, never emits this event, so the crash only shows
up on current CLI versions. Fix and test on branch `claude-2.1.2xx-compatibility`.

## What I tried

Ran the benchmark with `version=2.1.251` (Opus 5 and Fable 5.1, `just-solve` prompt,
`bypassPermissions`, harness at `06b5c06`). On the first Opus 5 run, file_merger died at
checkpoint 2 with the traceback below. The agent had asked Bash to run
`mkdir -p /tmp/x && cd /tmp/x && rm -rf *`, the CLI's safety check blocked it, and the
harness crashed on the event the CLI streamed to explain the block.

The same event sits in three other saved runs on 2.1.251 (sith checkpoint 4 and file_merger
checkpoint 4 on Opus 5, file_merger checkpoint 2 on Fable 5.1). Every one of them is the
same shape: a `cd` followed by an `rm -rf *`, blocked with `decision_reason_type:
"safetyCheck"`. This is a habit the models have, so any 2.1.2xx run that lasts long enough
hits it.

## What I expected

The harness records the event as a step, the agent sees the tool error in its `tool_result`
and moves on, and the checkpoint completes. That is what happens on 2.1.44, where the CLI
blocks the same command but reports it only inside the `tool_result` and in the result
payload's `permission_denials` list.

## What actually happened

`_run()` raises on the first `permission_denied` line and the problem errors out:

```
  File "<slop-code-bench>/src/slop_code/agent_runner/agents/claude_code/agent.py", line 614, in _run
    msg_id = payload.get("message", {}).get("id", None)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'str' object has no attribute 'get'
```

The line it trips on, from a real Opus 5 run (sith, checkpoint 4):

```json
{"type":"system","subtype":"permission_denied","tool_name":"Bash","tool_use_id":"toolu_01HEG4AtEGE3gF1J8UnYYwo2","decision_reason_type":"safetyCheck","decision_reason":"Dangerous rm operation on statically-unresolvable target: /workspace/*","message":"Dangerous rm operation detected: '/workspace/*'\n\nThis command changes directories before the removal, so the relative glob target cannot be statically resolved. This requires explicit approval and cannot be auto-allowed by permission rules.","uuid":"f74cfa23-370d-41e1-85e0-32a6c9f42cc3","session_id":"e7a25af0-fe05-4a3c-9d2a-d0f0b2efd986"}
```

The offending code, `agent.py:614-616` on main:

```python
msg_id = payload.get("message", {}).get("id", None)
content = payload.get("message", {}).get("content", {})
if "text" in content:
```

A side effect worth knowing about while you debug this: a checkpoint whose `_run()` raises
saves the previous checkpoint's `stdout.jsonl`, because `final_result` is only set by a
finished `_run()` and nothing clears it. So the crashed checkpoint's own stream is gone and
the cause looks like a mystery. That is a separate issue and I have a separate branch for
it (`claude-code-stdout-keeps-stream`).

## How to reproduce

Four ways, from cheapest to most faithful. All were run on 2026-09-10 and 2026-09-11 against
main at `06b5c06`.

### 1. Unit test (no network)

Branch `claude-2.1.2xx-compatibility` adds `TestStreamMessageShapes` to
`tests/agent_runner/agents/claude_code_agent_test.py`. The first case is the real event above.

```
uv run pytest tests/agent_runner/agents/claude_code_agent_test.py -k TestStreamMessageShapes -q
```

| Checkout | Result |
|---|---|
| main (`06b5c06`), test file copied over | 5 failed, 1 passed. Each failure is `agent.py:614: AttributeError` (`'str'`, `'NoneType'`, `'list'` object has no attribute `'get'`) |
| branch (`ff3cfcf`) | 6 passed |

### 2. Replay a captured stream through `_run()` (no network)

I captured one `claude -p` run per CLI version, each with the same prompt, and fed the
`stdout.jsonl` through `_run()` with `stream_cli_command` stubbed to yield the file's lines.
Captures attached: `2.1.251-bypass.stdout.jsonl`, `2.1.44-bypass.stdout.jsonl`,
`2.1.44-default.stdout.jsonl`, plus the `replay_stream.py` stub.

```
PYTHONPATH=<checkout>/src uv run python replay_stream.py <capture>
```

| Capture | CLI mode | What the CLI did | `permission_denied` lines | main `_run()` | branch `_run()` |
|---|---|---|---|---|---|
| `2.1.251-bypass` | bypassPermissions | blocked the command | 1 (line 123) | `CRASH on line 123 of 282`, `AttributeError: 'str' object has no attribute 'get'` | `OK: 282 payloads` |
| `2.1.44-bypass` | bypassPermissions | ran the command | 0 | `OK: 5 payloads` | `OK: 5 payloads` |
| `2.1.44-default` | default | blocked the command | 0 | `OK: 5 payloads` | `OK: 5 payloads` |

### 3. Live probe of the CLI (uses an API key, about $0.05)

This asks the CLI to run the trigger once, inside the agent image the harness builds for
that version, launched the way `ClaudeCodeAgent` launches it (uid 1000, `/workspace`,
`HOME=/tmp/agent_home`, same env overrides). Haiku keeps it cheap; the permission check runs
in the CLI, so the model does not decide it.

```bash
version=2.1.251            # or 2.1.44
out=/tmp/probe-$version
mkdir -p $out/workspace $out/claude_home && chmod -R 777 $out
echo '{"alwaysThinkingEnabled": true}' > $out/claude_home/settings.json

prompt='Use the Bash tool to run exactly this command once, unchanged: mkdir -p /tmp/t && cd /tmp/t && rm -rf *
Run nothing else. Then reply with one line saying what the tool returned.'

docker run --rm -u 1000:1000 -w /workspace \
  -e HOME=/tmp/agent_home -e ANTHROPIC_API_KEY \
  -e CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 -e DISABLE_AUTOUPDATER=1 \
  -e DISABLE_NON_ESSENTIAL_MODEL_CALLS=1 \
  -v $out/workspace:/workspace -v $out/claude_home:/tmp/agent_home/.claude \
  --entrypoint sh slop-code:claude_code-$version-python3.12 \
  -c 'exec claude "$@"' claude \
  --output-format stream-json --verbose --model claude-haiku-4-5-20251001 \
  --permission-mode bypassPermissions --print -- "$prompt" > $out/stdout.jsonl

grep -c '"subtype":"permission_denied"' $out/stdout.jsonl
```

The image is the one the harness builds on first run (`docker.j2` does
`npm install -g @anthropic-ai/claude-code@<version>`). With 2.1.251 the count is 1 and the
replay above crashes; with 2.1.44 it is 0. The block reason in the probe is
`subcommandResults` rather than `safetyCheck`, but the event has the same shape either way.

### 4. The benchmark itself

Any 2.1.251 run will do once the agent writes a `cd ... && rm -rf *`. In my runs it
happened in four checkpoints across three runs, all on file_merger or sith, so those two are
the ones to try.

```
uv run slop-code run --agent claude_code --model anthropic/claude-opus-5 \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/just-solve.jinja \
  --problem file_merger --problem sith thinking=high version=2.1.251
```

## What changed between Claude Code 2.1.44 and 2.1.251

The CLI added a stream event type. Nothing in the harness changed.

| | 2.1.44 | 2.1.251 |
|---|---|---|
| Blocks `cd ... && rm -rf *` under `bypassPermissions`? | No. It runs the command (`tool_result` `is_error=false`, "Shell cwd was reset to /workspace") | Yes. The safety check overrides bypass |
| How a block is reported | `tool_result` with `is_error: true`, and the result payload's `permission_denials` list | Both of those, plus a new `system` / `permission_denied` event streamed before the `tool_result` |
| `message` field on that event | n/a | A plain string, unlike every other event the parser had seen, where `message` is a dict with `id`, `content`, `usage` |
| `permission_denied` in `cli.js` | Absent as an event type. The string occurs twice, both auto-updater telemetry | Present |

So on 2.1.44 the parser's dict assumption held for every line the CLI could produce. On
2.1.251 the first blocked command breaks it. Two things changed at once, and both matter:
the CLI now blocks this command even in bypass mode, and it announces the block with a
string-message event.

Every capture's `init` line confirms it came from the version and mode it claims to:

```json
{"type":"system","subtype":"init","cwd":"/workspace","model":"claude-haiku-4-5-20251001","permissionMode":"bypassPermissions","apiKeySource":"none","claude_code_version":"2.1.251"}
{"type":"system","subtype":"init","cwd":"/workspace","model":"claude-haiku-4-5-20251001","permissionMode":"bypassPermissions","apiKeySource":"none","claude_code_version":"2.1.44"}
{"type":"system","subtype":"init","cwd":"/workspace","model":"claude-haiku-4-5-20251001","permissionMode":"default","apiKeySource":"none","claude_code_version":"2.1.44"}
```

## The fix

Branch `claude-2.1.2xx-compatibility`, two commits on top of `06b5c06`:

- `0b34d16` treats a non-dict `message` as empty and only looks for `"text"` in a dict
  `content`. Eight lines in `agent.py`.
- `ff3cfcf` adds the six-case test above.

I will open a PR from it. The `stdout.jsonl` overwrite that hid this for twelve days is on
`claude-code-stdout-keeps-stream` and I will file that separately.
