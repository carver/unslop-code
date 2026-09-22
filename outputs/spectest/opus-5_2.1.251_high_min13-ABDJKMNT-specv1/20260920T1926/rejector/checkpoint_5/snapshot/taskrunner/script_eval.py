"""`script` evaluation: render a shell command per row and check its exit code."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Mapping

from .config import ScriptConfig
from .prompts import RESPONSE_FIELD, render

# A `{__response__}` that only appeared once a row field had been expanded.
NESTED_RESPONSE = re.compile(r"\{" + RESPONSE_FIELD + r"\}")


def render_command(template: str, row: Mapping[str, Any], response: str) -> str:
    """Fill the command template from the row, then expand nested responses.

    The second pass exists because a row field such as `test_code` may itself
    contain `{__response__}`; it runs only over text the first pass produced,
    so a response mentioning other placeholders is never re-expanded.
    """
    command = render(template, {**row, RESPONSE_FIELD: response})
    return NESTED_RESPONSE.sub(lambda _: response, command)


async def run_script(config: ScriptConfig, row: Mapping[str, Any], response: str) -> bool:
    """Run the rendered command in a shell; a timeout counts as a failure."""
    process = await asyncio.create_subprocess_shell(
        render_command(config.command_template, row, response),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        # Output is drained but deliberately never reported in the JSONL.
        await asyncio.wait_for(process.communicate(), timeout=config.timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return False
    return process.returncode == config.success_exit_code
