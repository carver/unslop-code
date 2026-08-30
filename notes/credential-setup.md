# Credential plumbing: subscription auth inside the benchmark container

Status: verified 2026-08-29 (see "Verification" at the bottom).

## How credentials reach the container today (unmodified repo, commit 06b5c06)

1. `slop-code run --model <provider>/<name>` uses `<provider>` only for
   credential lookup. `configs/providers.yaml` maps it to a host env var
   (`type: env_var`) or a host file (`type: file`).
2. `APIKeyStore.resolve(provider)` (`src/slop_code/agent_runner/credentials.py`)
   reads that env var on the host and returns a `ProviderCredential` whose
   `destination_key` is the same env var name.
3. `ClaudeCodeAgent._build_runtime_auth_env()`
   (`src/slop_code/agent_runner/agents/claude_code/agent.py:388-461`) puts
   `destination_key=value` into the per-exec env. For any key other than
   `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` it also mirrors the value
   into `ANTHROPIC_AUTH_TOKEN`. `_build_settings_env()` (lines 463-483) does
   the same for the `env` block of the generated `settings.json`, again
   skipping those two keys.
4. The Docker streaming runtime passes env to the container twice:
   at `containers.create(environment=...)` and on every
   `docker exec --env KEY=VALUE` (`execution/docker_runtime/streaming.py:255,
   297-303`). Both start from `EnvironmentSpec.get_full_env()`, which copies
   `os.environ` only when `include_os_env` is true; it defaults to false
   (`execution/models.py:49-52, 228`) and `docker-python3.12-uv.yaml` does
   not set it. So the container env is: the environment YAML's `env` block,
   `HOME=/tmp/agent_home`, the agent's fixed flags
   (`DISABLE_AUTOUPDATER=1`, `MAX_THINKING_TOKENS`, ...), and the credential.
5. Mounted files: one temp dir per agent instance bound rw at
   `/tmp/agent_home/.claude` holding the generated `settings.json`
   (`agent.py:353-386`). No host credential files are mounted for
   `claude_code`. (File mounts are used for `codex`/`gemini`/`opencode`.)
6. Logging: `mask_sensitive_values()` redacts any env key containing
   `token`, `key`, `secret`, `password`, `credential`
   (`src/slop_code/common/common.py:3-28`), so
   `CLAUDE_CODE_OAUTH_TOKEN` is `***redacted***` in run logs. The value does
   appear on the `docker exec` command line on the host (visible in `ps`
   while a checkpoint runs) and in `docker inspect` of the container.

Both injection paths are env-var only; nothing in the repo injects
`ANTHROPIC_API_KEY` unless the chosen provider is `anthropic`.

## How Claude Code stores subscription credentials on this host

- Linux, no keyring: `~/.claude/.credentials.json` (mode 0600) with a
  `claudeAiOauth` object: `accessToken`, `refreshToken`, `expiresAt`,
  `scopes` (`user:inference`, `user:profile`, ...),
  `subscriptionType: max`, `rateLimitTier: default_claude_max_20x`.
- `~/.claude.json` carries `oauthAccount` (billingType
  `stripe_subscription`, organizationType `claude_max`).
- `claude auth status` on the host with `ANTHROPIC_API_KEY` exported reports
  `apiKeySource: ANTHROPIC_API_KEY` and `subscriptionType: null`; with the key
  unset it reports `authMethod: claude.ai`, `subscriptionType: max`. So the
  key must be unset in the benchmark shell, as the plan requires.
- Host Claude Code is 2.1.251; the container gets 2.1.44 from npm.

## The change: zero benchmark code edits

Claude Code's documented credential order
(https://code.claude.com/docs/en/authentication, "Generate a long-lived
token") puts `CLAUDE_CODE_OAUTH_TOKEN` (minted by `claude setup-token`,
one-year lifetime, "authenticates with your Claude subscription", "can only
make model requests") above `/login` credentials and below
`ANTHROPIC_API_KEY`. The repo already has a provider for it:

```yaml
# configs/providers.yaml (unchanged)
claude_code_oauth:
  type: env_var
  env_var: CLAUDE_CODE_OAUTH_TOKEN
```

So the whole change is:

1. Run with `--model claude_code_oauth/sonnet-4.6`. The model slug still
   resolves to `claude-sonnet-4-6` (`provider_slugs` has no
   `claude_code_oauth` entry, so `internal_name` is used).
2. Export `CLAUDE_CODE_OAUTH_TOKEN` in the shell that runs `slop-code`, with
   `ANTHROPIC_API_KEY` unset.

`bin/scb` in this project does step 2 mechanically: it unsets every
`ANTHROPIC*` variable, refuses to start if an `sk-ant-api` string is still in
the environment, reads the token from `~/.config/scbench/claude-oauth-token`
(must be mode 600), and execs `uv run slop-code`. Run configs in
`configs/runs/` set `model.provider: claude_code_oauth`.

Rejected alternatives:

- Mounting `~/.claude/.credentials.json` into the container. Claude Code
  refreshes and rewrites that file; two processes (host session + container)
  sharing one refresh token is a good way to log the host out mid-run, and
  the agent class would need editing to copy the file into its temp
  `claude_home`.
- Using the live `accessToken` from `.credentials.json` as the env token.
  Works for a short test (used for the throwaway check below) but it expires
  within a day and cannot refresh when supplied via env, so a multi-hour run
  would die mid-checkpoint.

## Sandbox network note

This machine runs inside a Docker sbx with an intercepting gateway proxy.
`SBX_CRED_ANTHROPIC_MODE=none` and `NO_PROXY` includes `api.anthropic.com`,
so the gateway does not inject Anthropic credentials. Containers started by
the inner Docker daemon receive no proxy env at all (checked with
`docker run --rm alpine env`) and reach `api.anthropic.com` directly, so a
container-side `env` audit is a complete check.

## Verification (2026-08-29, throwaway test, not a benchmark run)

Script: scratchpad `oauth_test.py`. It started `slop-code:claude_code-2.1.44-python3.12`
the way the agent does (`--user 1000:1000`, `HOME=/tmp/agent_home`, temp dir
mounted rw at `/tmp/agent_home/.claude` with the same `settings.json`, the
agent's fixed env flags, `MAX_THINKING_TOKENS=31999`,
`CLAUDE_CODE_EFFORT_LEVEL=high`) with `CLAUDE_CODE_OAUTH_TOKEN` as the only
credential. For this one test the token was the live access token from
`~/.claude/.credentials.json`; real runs use a `claude setup-token` token.

Observed:

- `docker exec ... env`: no variable starting with `ANTHROPIC`, no
  `sk-ant-api` string anywhere; `CLAUDE_CODE_OAUTH_TOKEN` present.
- `claude --version` inside: `2.1.44 (Claude Code)`.
- `claude auth status` inside: `{"loggedIn": true, "authMethod":
  "oauth_token", "apiProvider": "firstParty"}`.
- `claude --output-format stream-json --verbose --model claude-sonnet-4-6
  --permission-mode bypassPermissions --print -- "Reply with exactly the
  word hello"`: init payload `apiKeySource: "none"`, `model:
  claude-sonnet-4-6`, `claude_code_version: 2.1.44`; a thinking block was
  emitted (thinking works); result `hello`, exit 0, 4.4 s.
- Result usage: `input_tokens 10, cache_creation_input_tokens 18477,
  output_tokens 29`, `total_cost_usd 0.0698`. That equals list price
  (18477 x $3.75/M + 29 x $15/M + 10 x $3/M), so Claude Code prices
  subscription traffic at list price in its own output. The benchmark's
  `cost` column will therefore be a list-price estimate, which is what the
  $/checkpoint comparison needs.
- Host `~/.claude/.credentials.json` mtime unchanged after the run.
- Subscription usage endpoint (`bin/usage`) before/after: 5-hour window
  7% -> 7%, 7-day 2% -> 2%. One 18.5k-token call is below the 1% display
  granularity.

Sonnet 4.6 is available on this Max subscription, so no model substitution
is needed.

## Operating procedure

1. Once: `bin/setup-token-wizard` (runs `claude setup-token`, needs a TTY and
   a browser on the host; stores the token at
   `~/.config/scbench/claude-oauth-token`, mode 600).
2. Every run: `bin/scb run --config configs/runs/<name>.yaml`.
3. During a run: `docker exec <container> env | grep -i anthropic` must print
   nothing; `bin/usage` before and after gives the rate-limit cost.
