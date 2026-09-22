"""`--dry-run`: forecasting tokens, cost and time without calling the API."""

from __future__ import annotations

from dataclasses import dataclass

from rejlib.api import request_payload
from rejlib.config import TaskConfig
from rejlib.cost import FREE, PRECISION, CostConfig
from rejlib.prompts import build_messages
from rejlib.tokens import dry_run_tokens, payload_words

#: Logical attempts one input row is planned for, by scheme (T87).
ATTEMPTS = {
    "greedy": lambda config: 1,
    "sample": lambda config: 1,
    "rejection": lambda config: config.rejection_attempts,
    "agentic": lambda config: config.generation.max_iterations,
}


@dataclass(frozen=True)
class TaskEstimate:
    """One task's forecast, in tokens, dollars and minutes."""

    inputs: int
    prompt_tokens: float
    completion_tokens: float
    cost: float
    minutes: float

    @property
    def total_tokens(self) -> float:
        return self.prompt_tokens + self.completion_tokens

    def report(self) -> dict:
        """The task's entry in the estimate JSON."""
        return {
            "inputs": self.inputs,
            "est_prompt_tokens": round(self.prompt_tokens),
            "est_completion_tokens": round(self.completion_tokens),
            "est_total_tokens": round(self.total_tokens),
            "est_cost": round(self.cost, PRECISION),
        }


def estimate(tasks: dict[str, TaskConfig], inputs: dict[str, list[dict]]) -> dict:
    """The estimate a dry run prints: one entry per task, plus the run totals."""
    estimates = {name: _task_estimate(config, inputs[name]) for name, config in tasks.items()}
    return {
        "tasks": {name: task.report() for name, task in estimates.items()},
        "total_inputs": sum(task.inputs for task in estimates.values()),
        "est_total_tokens": round(sum(task.total_tokens for task in estimates.values())),
        "est_total_cost": round(sum(task.cost for task in estimates.values()), PRECISION),
        # "prefer precision over rounding" (T85, T86)
        "est_time_minutes": sum(task.minutes for task in estimates.values()),
    }


def _task_estimate(config: TaskConfig, rows: list[dict]) -> TaskEstimate:
    """Forecast one task from the prompts its rows would render."""
    rates = config.cost or FREE
    prompt_tokens = dry_run_tokens(_average_words(config, rows)) * len(rows)
    completion_tokens = config.generation.max_tokens * len(rows)
    return TaskEstimate(
        inputs=len(rows),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost=_cost(prompt_tokens, completion_tokens, rates),
        minutes=_minutes(config, len(rows)),
    )


def _average_words(config: TaskConfig, rows: list[dict]) -> float:
    """Mean word count of the requests the task would send, one per row."""
    if not rows:
        return 0.0
    examples = () if config.icl is None else config.icl.examples(config.icl.select(0))
    counts = [
        payload_words(request_payload(config, build_messages(config, row, examples)))
        for row in rows
    ]
    return sum(counts) / len(counts)


def _cost(prompt_tokens: float, completion_tokens: float, rates: CostConfig) -> float:
    return rates.prompt_cost(prompt_tokens) + rates.completion_cost(completion_tokens)


def _minutes(config: TaskConfig, inputs: int) -> float:
    """``total_inputs * avg_attempts / rpm``; unpaced tasks wait for nothing (T86)."""
    if config.rpm is None:
        return 0.0
    return inputs * ATTEMPTS[config.generation.scheme](config) / config.rpm
