# permission_denied probe, 2026-09-10

The question: does Claude Code stream an event whose `message` is a string when it
blocks a Bash command, and which versions do it? Unpatched `ClaudeCodeAgent._run()`
calls `.get()` on `message` and crashes on such an event. The upstream PR on branch
`claude-2.1.2xx-compatibility` rests on this.

Each capture is one `claude -p` run with the same prompt, which asks for
`mkdir -p /tmp/t && cd /tmp/t && rm -rf *`. `probe.sh` launches it the way the harness
does. Every capture's `init` event matches a real run of that version: `cwd` is
`/workspace`, `apiKeySource` is `none`, and `permissionMode` is `bypassPermissions`
for the two bypass captures.

| Capture | Mode | What the CLI did | String-`message` events | Unpatched `_run()` |
|---|---|---|---|---|
| `2.1.251-bypass.stdout.jsonl` | bypassPermissions | blocked the command | 1, `system` / `permission_denied` (line 123) | `AttributeError: 'str' object has no attribute 'get'` on line 123 |
| `2.1.44-bypass.stdout.jsonl` | bypassPermissions | ran the command | 0 | fine |
| `2.1.44-default.stdout.jsonl` | default | blocked the command | 0 | fine |

2.1.44 reports its block only inside the `tool_result` (`is_error: true`) and in the
result payload's `permission_denials` list. Its `cli.js` has no `permission_denied` event
type. The string's only two occurrences are auto-updater telemetry.

The 2.1.251 block reason here is `subcommandResults`. The real Opus 5 and Fable 5.1 runs
were blocked with `safetyCheck` ("Dangerous rm operation"). The event has the same shape
either way.

Rerun a capture (uses the subscription; about $0.03 to $0.08 at list price):

    notes/evidence/permission-denied-probe-2026-09-10/probe.sh 2.1.251 bypass /tmp/probe-251

Replay a capture through a checkout's `_run()`:

    PYTHONPATH=<checkout>/src uv run --project slop-code-bench \
      python notes/evidence/permission-denied-probe-2026-09-10/replay_stream.py <capture>
