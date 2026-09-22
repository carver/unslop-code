"""`--dry-run`: what a run would consume, worked out without calling the API."""

from __future__ import annotations

from .config import TaskConfig
from .cost import CENTS, CostRates
from .inputs import render_messages

WORDS_TO_TOKENS = 1.33
REJECTION = "rejection"


def estimate_run(jobs: list[tuple[TaskConfig, list[dict]]]) -> dict:
    """The estimate printed for `--dry-run`, per task and for the whole run."""
    tasks = {task.name: _task_estimate(task, rows) for task, rows in jobs}
    minutes = sum(_task_minutes(task, rows) for task, rows in jobs)
    return {
        "tasks": tasks,
        "total_inputs": sum(task["inputs"] for task in tasks.values()),
        "est_total_tokens": sum(task["est_total_tokens"] for task in tasks.values()),
        "est_total_cost": round(
            sum(task["est_cost"] for task in tasks.values()), CENTS
        ),
        "est_time_minutes": round(minutes, 1),
    }


def _task_estimate(task: TaskConfig, rows: list[dict]) -> dict:
    """One task's token and cost estimate, from its average prompt length."""
    prompt_tokens = round(len(rows) * _average_words(task, rows) * WORDS_TO_TOKENS)
    completion_tokens = len(rows) * task.generation.max_tokens
    rates = task.cost or CostRates()
    prompt_cost, completion_cost = rates.price(prompt_tokens, completion_tokens)
    return {
        "inputs": len(rows),
        "est_prompt_tokens": prompt_tokens,
        "est_completion_tokens": completion_tokens,
        "est_total_tokens": prompt_tokens + completion_tokens,
        "est_cost": round(prompt_cost + completion_cost, CENTS),
    }


def _average_words(task: TaskConfig, rows: list[dict]) -> float:
    """The mean word count of the prompts the task would send."""
    if not rows:
        return 0.0
    counts = [
        sum(len(message["content"].split()) for message in render_messages(row, task))
        for row in rows
    ]
    return sum(counts) / len(counts)


def _task_minutes(task: TaskConfig, rows: list[dict]) -> float:
    """`inputs * avg_attempts / rpm`; a task with no RPM limit paces itself."""
    if not task.limits.rpm:
        return 0.0
    return len(rows) * _average_attempts(task) / task.limits.rpm


def _average_attempts(task: TaskConfig) -> int:
    """Rejection plans for its worst case; every other scheme tries once."""
    return task.generation.n if task.generation.scheme == REJECTION else 1
