"""Running evaluation commands in a shell."""

from __future__ import annotations

import asyncio

# A command that has not finished by now is treated as a failed evaluation.
COMMAND_TIMEOUT_SECONDS = 10.0


async def run_command(command: str, timeout: float = COMMAND_TIMEOUT_SECONDS) -> int | None:
    """Run `command` in a shell and return its exit code, or None if it timed out.

    Output is captured so it cannot leak into the tool's own stdout, and discarded.
    """
    process = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    return process.returncode
