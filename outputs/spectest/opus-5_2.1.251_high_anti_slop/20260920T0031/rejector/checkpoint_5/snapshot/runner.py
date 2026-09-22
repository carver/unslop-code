"""Concurrent execution of the planned tasks and of the rows within each one."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from agentic import AgenticLoop, Generation, build_loop
from api import REQUEST_TIMEOUT_SECONDS, ApiClient
from config import TaskConfig
from cost import CostTracker, build_tracker
from dataset import Row
from endpoints import build_endpoint
from evaluation import LLM_JUDGE, NO_EVALUATION, SCRIPT, Outcome, evaluate
from judge import Judge, build_judge
from limits import RequestLimiter
from plan import TaskRun
from rows import Attempt, Result, multi_row, single_row
from schedule import AttemptPlan, attempt_plan
from schema import SchemaResult, check
from script_eval import run_script
from summary import TaskResults, summarize
from templates import Message
from tracking import Progress, RunMetrics


async def run_suite(runs: Sequence[TaskRun], progress: bool = False) -> tuple[dict[str, list[Result]], dict[str, Any]]:
    """Run every task concurrently; returns each task's rows by name and the run summary."""
    metrics = RunMetrics(build_tracker([run.task.cost for run in runs]))
    reporter = _reporter(runs, progress)
    finished = await asyncio.gather(*(run_task(run, metrics, reporter) for run in runs))
    return (
        {task.name: task.results for task in finished},
        summarize(finished, metrics.timeline.elapsed_seconds, metrics.cost),
    )


def _reporter(runs: Sequence[TaskRun], progress: bool) -> Progress | None:
    """The `--progress` reporter, sized to every row the run still owes."""
    if not progress:
        return None
    total = sum(len(run.rows) for run in runs)
    return Progress(total, evaluated=any(run.task.evaluation is not None for run in runs))


async def run_task(run: TaskRun, metrics: RunMetrics, progress: Progress | None) -> TaskResults:
    """Process one task's rows concurrently against its own server and its own budgets."""
    task = run.task
    in_flight = task.limits.max_concurrent
    endpoint = build_endpoint(task)
    async with httpx.AsyncClient(
        base_url=task.api_url, timeout=REQUEST_TIMEOUT_SECONDS, limits=httpx.Limits(max_connections=in_flight)
    ) as http:
        client = ApiClient(http, RequestLimiter(task.limits), metrics, endpoint, task.cost)
        worker = TaskWorker(
            task,
            client,
            build_judge(task, client),
            attempt_plan(task, run.setups),
            build_loop(task, client, endpoint),
            metrics.cost,
        )
        semaphore = asyncio.Semaphore(in_flight)

        async def run_row(row: Row, messages: list[Message]) -> Result | None:
            async with semaphore:
                result = await worker.run_row(row, messages)
            if result is not None and progress is not None:
                progress.row(result, metrics)
            return result

        rows = await asyncio.gather(
            *(run_row(row, messages) for row, messages in zip(run.rows, run.prompts, strict=True))
        )

    return TaskResults(
        name=task.name,
        results=[result for result in rows if result is not None],
        api_calls=client.api_calls,
        resumed_from=run.resume_from,
    )


@dataclass(frozen=True)
class TaskWorker:
    """Turns one row of a task into its result row: generation, validation, evaluation."""

    task: TaskConfig
    client: ApiClient
    judge: Judge | None
    plan: AttemptPlan
    #: The tool-calling loop of an agentic task; None when one request is one attempt.
    loop: AgenticLoop | None = None
    #: The run's spend, which stops a row from starting once the budget is gone.
    budget: CostTracker = field(default_factory=CostTracker)

    async def run_row(self, row: Row, messages: list[Message]) -> Result | None:
        """Generate and evaluate for one row, or None when the budget left it unstarted."""
        attempts = await self._attempts(row, messages)
        if not attempts:
            return None
        if self.task.multi_solution:
            return multi_row(self.task, row, attempts)
        return single_row(self.task, row, attempts)

    async def _attempts(self, row: Row, messages: list[Message]) -> list[Attempt]:
        """Generate until the row has the solutions it wants, or runs out of attempts or budget."""
        attempts: list[Attempt] = []
        kept = 0

        for index in range(self.plan.limit):
            if self.budget.exhausted:
                break
            setup, prompt = self.plan.prompt_for(index, messages)
            generation = await self._generate(prompt)
            completion = generation.completion
            if completion is None:
                attempts.append(Attempt(None, setup, NO_EVALUATION, kept=False, schema=self._validate(None)))
                break

            schema = self._validate(completion.text)
            valid = schema is None or schema.valid
            outcome = await self._evaluate(completion.text, row) if valid else NO_EVALUATION
            keep = completion.text is not None and valid and (not self.plan.gated or outcome.passed is not False)
            attempts.append(
                Attempt(completion, setup, outcome, keep, generation.iterations, generation.tool_calls, schema)
            )
            kept += keep
            if kept == self.plan.target:
                break

        return attempts

    def _validate(self, text: str | None) -> SchemaResult | None:
        """Check a response against the task's `output_schema`, if it configures one."""
        if self.task.output_schema is None:
            return None
        return check(text, self.task.output_schema)

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
