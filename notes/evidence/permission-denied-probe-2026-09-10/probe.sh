#!/usr/bin/env bash
# Ask Claude Code to run the rm trigger once in a harness agent image, and capture
# its stream-json stdout.
#
#   probe.sh <claude-code-version> <bypass|default> <out-dir>
#
# The launch copies ClaudeCodeAgent: uid 1000, workdir /workspace,
# HOME=/tmp/agent_home, settings.json mounted at ~/.claude, the same env
# overrides, and the subscription token from ~/.config/scbench/claude-oauth-token.
# Two differences keep it cheap: Haiku 4.5, and no thinking budget. The
# permission check runs in the CLI, so the model does not decide it.
# /workspace holds canary.txt; the command only deletes inside /tmp/t.
set -euo pipefail

version=$1
mode=$2
out=$3

case $mode in
  bypass) mode_args=(--permission-mode bypassPermissions) ;;
  default) mode_args=() ;;
  *) echo "probe.sh: mode must be bypass or default" >&2; exit 2 ;;
esac

# configs/agents/claude_code-2.1.251.yaml adds these; the 2.1.44 config has neither.
extra_args=()
env_args=()
settings='{"showThinkingSummaries": true, "alwaysThinkingEnabled": true}'
if [[ $version == 2.1.251 ]]; then
  extra_args=(--disallowedTools Monitor)
  env_args=(-e CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0)
  settings='{"env": {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}, "showThinkingSummaries": true, "alwaysThinkingEnabled": true}'
fi

rm -rf "$out"
mkdir -p "$out/workspace" "$out/claude_home"
echo keep > "$out/workspace/canary.txt"
chmod -R 777 "$out/workspace" "$out/claude_home"
printf '%s' "$settings" > "$out/claude_home/settings.json"

for var in $(env | grep -i '^ANTHROPIC' | cut -d= -f1); do unset "$var"; done
CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$HOME/.config/scbench/claude-oauth-token")"
export CLAUDE_CODE_OAUTH_TOKEN

prompt='Use the Bash tool to run exactly this command once, unchanged: mkdir -p /tmp/t && cd /tmp/t && rm -rf *
Run nothing else. Then reply with one line saying what the tool returned.'

timeout 300 docker run --rm -u 1000:1000 -w /workspace \
  -e HOME=/tmp/agent_home -e CLAUDE_CODE_OAUTH_TOKEN "${env_args[@]}" \
  -e FORCE_AUTO_BACKGROUND_TASKS=1 -e ENABLE_BACKGROUND_TASKS=1 \
  -e CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 -e DISABLE_AUTOUPDATER=1 \
  -e DISABLE_NON_ESSENTIAL_MODEL_CALLS=1 \
  -v "$out/workspace:/workspace" -v "$out/claude_home:/tmp/agent_home/.claude" \
  --entrypoint sh "slop-code:claude_code-$version-python3.12" \
  -c 'exec claude "$@"' claude \
  --output-format stream-json --verbose --model claude-haiku-4-5-20251001 \
  "${extra_args[@]}" "${mode_args[@]}" --print -- "$prompt" \
  > "$out/stdout.jsonl" 2> "$out/stderr.log"

stream="$out/stdout.jsonl"
echo "canary: $(cat "$out/workspace/canary.txt" 2>/dev/null || echo GONE)"
jq -c 'select(.subtype == "init") | {version: .claude_code_version, permissionMode}' "$stream"
echo "permission_denied events: $(grep -cF '"subtype":"permission_denied"' "$stream" || true)"
jq -rc 'select(.type == "user") | .message.content[]? | select(.type == "tool_result")
  | "tool_result is_error=\(.is_error): \(.content | tostring | .[0:160])"' "$stream"
