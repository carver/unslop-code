"""Feed a captured Claude Code stdout.jsonl through ClaudeCodeAgent._run().

Usage: PYTHONPATH=<checkout>/src python replay_stream.py <stdout.jsonl>
Prints which checkout was imported, then OK with the payload kinds, or the
exception _run() raised and the line it was on.
"""

import sys
import traceback
from pathlib import Path

from slop_code.agent_runner.agents.claude_code import agent as mod
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.common.llms import APIPricing
from slop_code.execution.runtime import RuntimeResult

lines = [line for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
position = {"line": None}


def fake_stream_cli_command(*, parser, **_):
    for number, line in enumerate(lines, start=1):
        position["line"] = number
        yield parser(line)
    yield RuntimeResult(
        exit_code=0,
        stdout="\n".join(lines),
        stderr="",
        setup_stdout="",
        setup_stderr="",
        elapsed=0.0,
        timed_out=False,
    )


mod.stream_cli_command = fake_stream_cli_command
agent = mod.ClaudeCodeAgent(
    problem_name="replay",
    image="replay",
    verbose=False,
    cost_limits=AgentCostLimits(step_limit=0, cost_limit=100.0, net_cost_limit=100.0),
    pricing=APIPricing(input=1.0, output=5.0, cache_read=0.1),
    credential=ProviderCredential(
        provider="anthropic",
        value="unused",
        source="replay",
        destination_key="CLAUDE_CODE_OAUTH_TOKEN",
        credential_type=CredentialType.ENV_VAR,
    ),
    binary="claude",
    model="replay",
    timeout=None,
    settings={},
    env={},
    extra_args=[],
    append_system_prompt=None,
    allowed_tools=[],
    disallowed_tools=[],
    permission_mode=None,
    base_url=None,
    thinking=None,
    max_thinking_tokens=None,
    max_output_tokens=None,
)
agent._runtime = object()

print("imported:", mod.__file__)
try:
    agent._run("claude", {})
except Exception:
    print(f"CRASH on line {position['line']} of {len(lines)}")
    print(traceback.format_exc().strip().splitlines()[-1])
else:
    kinds = [step.get("subtype") or step.get("type") for step in agent.steps]
    print(f"OK: {len(agent.steps)} payloads:", ", ".join(kinds))
