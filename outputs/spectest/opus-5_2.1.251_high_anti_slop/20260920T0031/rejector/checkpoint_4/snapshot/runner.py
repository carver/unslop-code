"""Concurrent execution of the planned tasks and of the rows within each one."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from agentic import AgenticLoop, Generation, build_loop
from api import REQUEST_TIMEOUT_SECONDS, ApiClient, RateLimiter, Timeline
from config import TaskConfig
from dataset import Row
from endpoints import build_endpoint
from evaluation import LLM_JUDGE, NO_EVALUATION, SCRIPT, Outcome, evaluate
from judge import Judge, build_judge
from plan import TaskRun
from rows import Attempt, Result, multi_row, single_row
from schedule import AttemptPlan, attempt_plan
from script_eval import run_script
from summary import TaskResults, summarize
from templates import Message


async def run_suite(runs: Sequence[TaskRun]) -> tuple[dict[str, list[Result]], dict[str, Any]]:
    """Run every task concurrently; returns each task's rows by name and the run summary."""
    timeline = Timeline()
    finished = await asyncio.gather(*(run_task(run, timeline) for run in runs))
    return {task.name: task.results for task in finished}, summarize(finished, timeline.elapsed_seconds)


async def run_task(run: TaskRun, timeline: Timeline) -> TaskResults:
    """Process one task's rows concurrently against its own server and request budget."""
    task = run.task
    # A full minute of the request budget may be in flight at once; the limiter paces the rest.
    in_flight = task.rpm
    endpoint = build_endpoint(task)
    async with httpx.AsyncClient(
        base_url=task.api_url, timeout=REQUEST_TIMEOUT_SECONDS, limits=httpx.Limits(max_connections=in_flight)
    ) as http:
        client = ApiClient(http, RateLimiter(task.rpm), timeline, endpoint)
        worker = TaskWorker(
            task,
            client,
            build_judge(task, client),
            attempt_plan(task, run.setups),
            build_loop(task, client, endpoint),
        )
        semaphore = asyncio.Semaphore(in_flight)

        async def run_row(row: Row, messages: list[Message]) -> Result:
            async with semaphore:
                return await worker.run_row(row, messages)

        results = await asyncio.gather(
            *(run_row(row, messages) for row, messages in zip(run.rows, run.prompts, strict=True))
        )

    return TaskResults(name=task.name, results=list(results), api_calls=client.api_calls)


@dataclass(frozen=True)
class TaskWorker:
    """Turns one row of a task into its result row: generation, evaluation, metadata."""

    task: TaskConfig
    client: ApiClient
    judge: Judge | None
    plan: AttemptPlan
    #: The tool-calling loop of an agentic task; None when one request is one attempt.
    loop: AgenticLoop | None = None

    async def run_row(self, row: Row, messages: list[Message]) -> Result:
        """Generate and evaluate for one row, then write it in the task's output format."""
        attempts = await self._attempts(row, messages)
        if self.task.multi_solution:
            return multi_row(self.task, row, attempts)
        return single_row(self.task, row, attempts)

    async def _attempts(self, row: Row, messages: list[Message]) -> list[Attempt]:
        """Generate until the row has the solutions it wants or its attempt budget runs out."""
        attempts: list[Attempt] = []
        kept = 0

        for index in range(self.plan.limit):
            setup, prompt = self.plan.prompt_for(index, messages)
            generation = await self._generate(prompt)
            completion = generation.completion
            if completion is None:
                attempts.append(Attempt(None, setup, NO_EVALUATION, kept=False))
                break

            outcome = await self._evaluate(completion.text, row)
            keep = completion.text is not None and (not self.plan.gated or outcome.passed is True)
            attempts.append(Attempt(completion, setup, outcome, keep, generation.iterations, generation.tool_calls))
            kept += keep
            if kept == self.plan.target:
                break

        return attempts

    async def _generate(self, prompt: list[Message]) -> Generation:
        """One attempt: a whole agentic loop, or a single request for every other scheme."""
        if self.loop is not None:
            return await self.loop.run(prompt)

        generation = self.task.generation
        completion = await self.client.complete(prompt, self.task.model, generation.temperature, generation.max_tokens)
        return Generation(completion)

    async def _evaluate(self, text: str | None, row: Row) -> Outcome:
        """Score a response with the task's evaluation, calling out to a judge or shell if needed.

        An agentic loop that ran out of iterations has no text to score, which
        leaves the row without an output and so without a passing evaluation.
        """
        config = self.task.evaluation
        if config is None or text is None:
            return NO_EVALUATION
        if config.type == LLM_JUDGE:
            return await self.judge.score(text, row)
        if config.type == SCRIPT:
            return await run_script(config, text, row)
        return evaluate(text, row, config)
