"""Concurrent execution of the planned tasks and of the rows within each one."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from api import REQUEST_TIMEOUT_SECONDS, ChatClient, RateLimiter, Timeline
from config import TaskConfig
from dataset import Row
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
    async with httpx.AsyncClient(
        base_url=task.api_url, timeout=REQUEST_TIMEOUT_SECONDS, limits=httpx.Limits(max_connections=in_flight)
    ) as http:
        client = ChatClient(http, RateLimiter(task.rpm), timeline)
        worker = TaskWorker(task, client, build_judge(task, client), attempt_plan(task, run.setups))
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
    client: ChatClient
    judge: Judge | None
    plan: AttemptPlan

    async def run_row(self, row: Row, messages: list[Message]) -> Result:
        """Generate and evaluate for one row, then write it in the task's output format."""
        attempts = await self._attempts(row, messages)
        if self.task.multi_solution:
            return multi_row(self.task, row, attempts)
        return single_row(self.task, row, attempts)

    async def _attempts(self, row: Row, messages: list[Message]) -> list[Attempt]:
        """Generate until the row has the solutions it wants or its attempt budget runs out."""
        generation = self.task.generation
        attempts: list[Attempt] = []
        kept = 0

        for index in range(self.plan.limit):
            setup, prompt = self.plan.prompt_for(index, messages)
            completion = await self.client.complete(
                prompt, self.task.model, generation.temperature, generation.max_tokens
            )
            if completion is None:
                attempts.append(Attempt(None, setup, NO_EVALUATION, kept=False))
                break

            outcome = await self._evaluate(completion.text, row)
            keep = not self.plan.gated or outcome.passed is True
            attempts.append(Attempt(completion, setup, outcome, kept=keep))
            kept += keep
            if kept == self.plan.target:
                break

        return attempts

    async def _evaluate(self, text: str, row: Row) -> Outcome:
        """Score a response with the task's evaluation, calling out to a judge or shell if needed."""
        config = self.task.evaluation
        if config is None:
            return NO_EVALUATION
        if config.type == LLM_JUDGE:
            return await self.judge.score(text, row)
        if config.type == SCRIPT:
            return await run_script(config, text, row)
        return evaluate(text, row, config)
