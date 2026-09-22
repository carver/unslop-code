"""Script evaluation: a shell command decides pass or fail by its exit code."""

import asyncio
from typing import Any

from config import EvaluationConfig
from dataset import RESPONSE_KEY, render_template

#: A command that has not finished by now is treated as a failed evaluation.
COMMAND_TIMEOUT_SECONDS = 10.0


async def run_command(config: EvaluationConfig, text: str, row: dict[str, Any]) -> bool:
    """Run the row's rendered command and report whether it exited with the success code.

    Output is captured so it stays out of the run's own streams, and discarded:
    only the exit code decides the verdict.
    """
    process = await asyncio.create_subprocess_shell(
        _render_command(config.command_template, text, row),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=COMMAND_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        return False
    return process.returncode == config.success_exit_code


def _render_command(template: str, text: str, row: dict[str, Any]) -> str:
    """Fill the command template, then the response placeholder any row field brought with it."""
    rendered = render_template(template, {**row, RESPONSE_KEY: text}, "command template")
    return rendered.replace("{" + RESPONSE_KEY + "}", text)
