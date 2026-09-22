"""The agentic scheme: each solution comes from a loop of tool calls and model replies.

One loop keeps sending the growing conversation back to the model, executing
whatever tools it asks for, until the model answers with plain text or the
iteration budget runs out.
"""

import time
from dataclasses import replace
from typing import Any, Mapping

from api import ModelClient, ToolCall
from config import TaskConfig
from dataset import Messages
from evaluation import evaluate
from icl import DEFAULT_STRATEGY, RenderedSetup, build_messages, setup_for_attempt
from results import AgenticOutcome, AgenticRun, MultiAgenticOutcome, Outcome, ToolInvocation
from tools import ToolConfig, run_tool

#: Reported instead of a finish reason when the loop never reached a final answer.
MAX_ITERATIONS_REASON = "max_iterations"


async def generate_agentic_row(
    client: ModelClient,
    judge: ModelClient | None,
    task: TaskConfig,
    messages: Messages,
    setups: tuple[RenderedSetup, ...],
    row: dict[str, Any],
) -> Outcome:
    """Run the row's agentic loops and report them in the format its task calls for."""
    if task.num_solutions == 1 and task.icl is None:
        return await _single(client, judge, task, messages, setups[0], row)
    return await _many(client, judge, task, messages, setups, row)


async def _single(
    client: ModelClient,
    judge: ModelClient | None,
    task: TaskConfig,
    messages: Messages,
    setup: RenderedSetup,
    row: dict[str, Any],
) -> AgenticOutcome:
    """One loop, evaluated on its final text; a loop that never answered fails."""
    run = await _run_loop(client, task, messages, setup)
    if run.text is None:
        return AgenticOutcome(row, run, passed=False, extracted_answer=None)
    result = await evaluate(task.evaluation, run.text, row, judge)
    return AgenticOutcome(
        row,
        run,
        passed=result.passed,
        extracted_answer=result.extracted_answer,
        judge_score=result.judge_score,
        judged=result.judge_meta is not None,
    )


async def _many(
    client: ModelClient,
    judge: ModelClient | None,
    task: TaskConfig,
    messages: Messages,
    setups: tuple[RenderedSetup, ...],
    row: dict[str, Any],
) -> MultiAgenticOutcome:
    """One independent loop per requested solution, each with its own ICL setup."""
    strategy = task.icl.strategy if task.icl else DEFAULT_STRATEGY
    runs = []
    for index in range(task.num_solutions):
        run = await _run_loop(client, task, messages, setup_for_attempt(setups, strategy, index))
        passed = None
        if run.text is not None:
            passed = (await evaluate(task.evaluation, run.text, row, judge)).passed
        runs.append(replace(run, evaluation_passed=passed))
    return MultiAgenticOutcome(row, runs, graded=task.evaluation is not None)


async def _run_loop(
    client: ModelClient, task: TaskConfig, messages: Messages, setup: RenderedSetup
) -> AgenticRun:
    """Call the model until it answers without tool calls, or the iteration budget runs out."""
    generation = task.generation
    by_name = {tool.name: tool for tool in task.tools}
    conversation = build_messages(messages, setup)
    started = time.monotonic()
    metas, invocations = [], []

    for iteration in range(1, generation.max_iterations + 1):
        completion = await client.complete(
            conversation, generation.temperature, generation.max_tokens, task.tools
        )
        metas.append(completion.meta)
        if not completion.tool_calls:
            return AgenticRun(
                text=completion.text,
                tool_calls=invocations,
                metas=metas,
                latency_ms=_elapsed_ms(started),
                finish_reason=completion.meta.finish_reason,
                icl_setup=setup.name,
            )
        conversation.append(client.assistant_tool_message(completion.tool_calls))
        for call in completion.tool_calls:
            result = await _invoke(by_name, call)
            invocations.append(ToolInvocation(iteration, call.name, call.args, result))
            conversation.append(client.tool_result_message(call, result))

    return AgenticRun(
        text=None,
        tool_calls=invocations,
        metas=metas,
        latency_ms=_elapsed_ms(started),
        finish_reason=MAX_ITERATIONS_REASON,
        icl_setup=setup.name,
    )


async def _invoke(tools: Mapping[str, ToolConfig], call: ToolCall) -> str:
    """Run one requested call, reporting a name the task does not define as an error result."""
    tool = tools.get(call.name)
    if tool is None:
        return f"ERROR: unknown tool '{call.name}'"
    return await run_tool(tool, call.args)


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
