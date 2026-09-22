"""`script` evaluation: a row passes when its shell command exits with the expected code."""

from __future__ import annotations

import asyncio
from typing import Any

from evaluation import EvaluationConfig, Outcome
from templates import render_command

TIMEOUT_SECONDS = 10.0


async def run_script(config: EvaluationConfig, text: str, row: dict[str, Any]) -> Outcome:
    """Run the command rendered for this row; its output is captured but not reported."""
    command = render_command(config.command_template, row, text)
    process = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        await asyncio.wait_for(process.communicate(), TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return Outcome(passed=False, extracted=None)
    return Outcome(passed=process.returncode == config.success_exit_code, extracted=None)
