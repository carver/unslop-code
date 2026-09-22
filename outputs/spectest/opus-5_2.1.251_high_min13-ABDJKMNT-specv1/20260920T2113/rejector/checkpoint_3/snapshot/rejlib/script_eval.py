"""`script` evaluation: run the rendered command in a shell and read its exit code."""

from __future__ import annotations

import asyncio

from rejlib.config import ScriptSpec
from rejlib.prompts import render_with_response

#: "command timeout is 10 seconds; timeout is a failed evaluation"
TIMEOUT_SECONDS = 10.0


async def run_command(script: ScriptSpec, row: dict, response: str) -> bool:
    """Render and run the command; ``True`` when it exits with the success code.

    Output is captured so it stays out of the JSONL output, and a command that
    outlives the timeout is killed and counts as a failure (T37).
    """
    command = render_with_response(script.command_template, row, response)
    process = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return False
    return process.returncode == script.success_exit_code
