# What the control run can and cannot inherit from this host

Question: could my global Claude Code settings, CLAUDE.md, skills or plugins
leak into the benchmark agent and contaminate the control baseline?

Evidence: throwaway container run on 2026-08-29 with the setup-token
(`oauth_test.py`, image `slop-code:claude_code-2.1.44-python3.12`, started
exactly the way `ClaudeCodeAgent.setup()` starts it). The stream-json `init`
payload is what Claude Code actually loaded:

```
"mcp_servers": [], "plugins": [], "skills": ["debug"],
"slash_commands": [debug, compact, context, cost, init, pr-comments,
                   release-notes, review, security-review, insights],
"agents": [Bash, general-purpose, statusline-setup, Explore, Plan],
"model": "claude-sonnet-4-6", "apiKeySource": "none",
"output_style": "default", "permissionMode": "bypassPermissions"
```

`debug` and the slash commands/agents listed are the ones bundled inside
Claude Code 2.1.44; nothing from this host appears.

## Channel by channel

| Channel | Host state | Reaches the container? | Why |
|---|---|---|---|
| `~/.claude/CLAUDE.md` (symlink to GLOBAL_CLAUDE.md) | present | no | `~/.claude` is not mounted; container `$HOME/.claude` is a fresh temp dir holding only the benchmark's `settings.json`. `ls /tmp/agent_home/.claude/CLAUDE.md` -> missing |
| `~/.claude/skills/`, `~/.claude/plugins/` | present | no | same; `skills`/`plugins` dirs missing in container, `plugins: []` in init |
| `~/.claude/settings.json` (`model: fable`, `alwaysThinkingEnabled`, hooks etc.) | present | no | not mounted; container settings.json is `{"showThinkingSummaries": true, "alwaysThinkingEnabled": true}` written by the agent. Model is forced by `--model claude-sonnet-4-6` (init confirms) |
| `~/.claude.json` (onboarding, `customApiKeyResponses`, experiments cache) | present | no | container writes its own `/tmp/agent_home/.claude.json` at first start |
| `~/.claude/keybindings.json`, statusline | present | no | not mounted; `--print` mode anyway |
| Host env (`ANTHROPIC_API_KEY`, proxy vars, `TZ`, `BASH_ENV`, persistent-sh) | present | no | `include_os_env` defaults false; container env list has 25 vars, all from the image or the agent |
| Working directory contents (this project, its `.claude/`) | n/a | no | workspace is `tempfile.TemporaryDirectory()` + the problem's static assets (`execution/workspace.py:308,322`); `/workspace/CLAUDE.md` and `/workspace/.claude` absent |
| MCP servers | none configured in the container | no | `mcp_servers: []` |
| Server-managed / org settings | `~/.claude/remote-settings.json` is `{}`; personal Max org | no evidence of any | these apply to Team/Enterprise orgs |
| GrowthBook feature flags (`cachedGrowthBookFeatures` in container `.claude.json`) | fetched live from Anthropic per version/account | yes | not controllable by us; the leaderboard run (Apr 2026) had whatever flags were live then. `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` is set by the benchmark, same as the leaderboard |
| Auto-memory / session state across checkpoints | container `~/.claude/projects/-workspace/` persists for the life of the agent instance (one problem) | yes, by design | identical to the leaderboard harness; each checkpoint is still a fresh `--print` process |

## Residual differences from the leaderboard run that are not "pollution"

- Feature flags and any server-side prompt changes between Apr 2026 and now
  for the same CLI version. Unobservable; report it as a caveat.
- Rate limiting: a subscription can be throttled mid-run. Claude Code retries
  with backoff, which adds wall time but not tokens. If the 5-hour window
  hits 100%, requests fail and the checkpoint errors; `bin/usage` before a
  run and the run log afterwards will show it.
- Wall-clock: this sandbox vs. their machine. Only matters for the
  per-checkpoint `timeout` (3600 s) and the problems' own test timeouts.

## Things I did on purpose

- No CLAUDE.md, skills, prompts or template edits anywhere the agent can see.
- Run configs live outside the benchmark repo and only set provider, model,
  thinking, prompt name and output path.
- The agent config differs from the repo default only in `version: 2.1.44`,
  `timeout: 3600` and `cost_limit: 20` (a safety cap 10x above the
  leaderboard mean; it never binds in a normal checkpoint).
