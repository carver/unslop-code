"""Concurrent execution of the planned tasks and of the rows within each one."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from api import REQUEST_TIMEOUT_SECONDS, ChatClient, Completion, RateLimiter, Timeline
from config import TaskConfig
from dataset import Row
from evaluation import LLM_JUDGE, NO_EVALUATION, SCRIPT, Outcome, evaluate
from judge import Judge, build_judge
from plan import TaskRun
from script_eval import run_script
from summary import Result, TaskResults, summarize
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
        worker = TaskWorker(task, client, build_judge(task, client))
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

    async def run_row(self, row: Row, messages: list[Message]) -> Result:
        """Generate for one row, resampling while rejection sampling has attempts left."""
        generation = self.task.generation
        metas: list[dict[str, Any]] = []
        completion: Completion | None = None
        outcome = NO_EVALUATION

        for _ in range(generation.attempts):
            completion = await self.client.complete(
                messages, self.task.model, generation.temperature, generation.max_tokens
            )
            if completion is None:
                break
            outcome = await self._evaluate(completion.text, row)
            metas.append(_attempt_meta(completion, outcome))
            if outcome.passed is not False:
                break

        return self._result_row(row, completion, outcome, metas)

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

    def _result_row(
        self, row: Row, completion: Completion | None, outcome: Outcome, metas: list[dict[str, Any]]
    ) -> Result:
        rejected = self.task.generation.scheme == "rejection" and outcome.passed is False
        output = None if completion is None or rejected else {self.task.output_field: completion.text}
        result = {
            "passed": None if self.task.evaluation is None else (outcome.passed is True and output is not None),
            "extracted_answer": outcome.extracted if output is not None else None,
            "attempts": max(len(metas), 1),
        }
        if self.judge is not None:
            result["judge_score"] = outcome.judge_score if output is not None else None
        return {"input": row, "output": output, "result": result, "meta": _meta_field(metas)}


def _attempt_meta(completion: Completion, outcome: Outcome) -> dict[str, Any]:
    """One attempt's metadata, carrying the judge call's own metadata when there was one."""
    if outcome.judge_meta is None:
        return completion.meta
    return {**completion.meta, "judge_meta": outcome.judge_meta}


def _meta_field(metas: list[dict[str, Any]]) -> Any:
    """A single metadata object for one-attempt rows, a list for multi-attempt ones."""
    if len(metas) == 1:
        return metas[0]
    return metas or None
