"""The `script` evaluation: run a rendered shell command and read its exit code."""

from __future__ import annotations

import asyncio
import os
import signal

from .config import ScriptConfig
from .inputs import RESPONSE_PLACEHOLDER, render_template

TIMEOUT_SECONDS = 10


def render_command(template: str, row: dict, response: str) -> str:
    """Substitute row fields, then any `{__response__}` a field expanded into."""
    rendered = render_template(template, row, response)
    return rendered.replace(RESPONSE_PLACEHOLDER, response)


async def run_script(script: ScriptConfig, row: dict, response: str) -> bool:
    """Run the command in a shell; its exit code decides the verdict.

    Output is captured so it stays out of the run's own streams. A command that
    outlives the timeout counts as a failure; it runs in its own session so
    that the whole pipeline dies with it rather than outliving the run.
    """
    process = await asyncio.create_subprocess_shell(
        render_command(script.command_template, row, response),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        await asyncio.wait_for(process.communicate(), TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        return False
    return process.returncode == script.success_exit_code
