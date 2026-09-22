"""The `--dry-run` estimate of what a run would consume, without calling the API."""

from __future__ import annotations

from config import TaskConfig
from cost import PLACES
from jobs import Job

# Tokens one prompt word is worth when planning a run.
TOKENS_PER_WORD = 1.33


def estimate(jobs: list[Job]) -> dict:
    """Size up every planned task and what they add up to."""
    tasks = {job.config.name: _task_estimate(job) for job in jobs}
    return {
        "tasks": tasks,
        "total_inputs": sum(task["inputs"] for task in tasks.values()),
        "est_total_tokens": sum(task["est_total_tokens"] for task in tasks.values()),
        "est_total_cost": round(sum(task["est_cost"] for task in tasks.values()), PLACES),
        "est_time_minutes": round(sum(_minutes(job) for job in jobs), 4),
    }


def _task_estimate(job: Job) -> dict:
    """One task's rows, the tokens they would spend and what that would cost."""
    config = job.config
    inputs = len(job.rows)
    prompt_tokens = round(_average_words(job) * TOKENS_PER_WORD * inputs)
    completion_tokens = inputs * config.generation.max_tokens
    return {
        "inputs": inputs,
        "est_prompt_tokens": prompt_tokens,
        "est_completion_tokens": completion_tokens,
        "est_total_tokens": prompt_tokens + completion_tokens,
        "est_cost": round(_cost(config, prompt_tokens, completion_tokens), PLACES),
    }


def _average_words(job: Job) -> float:
    """The mean word count of the task's rendered prompts."""
    if not job.rows:
        return 0.0
    words = sum(
        len(str(message["content"]).split())
        for messages in job.messages
        for message in messages
        if message["content"]
    )
    return words / len(job.rows)


def _cost(config: TaskConfig, prompt_tokens: int, completion_tokens: int) -> float:
    """What those tokens would cost at the task's rates; nothing without any."""
    if config.cost is None:
        return 0.0
    return (
        prompt_tokens / 1000 * config.cost.prompt_per_1k
        + completion_tokens / 1000 * config.cost.completion_per_1k
    )


def _minutes(job: Job) -> float:
    """How long the task's requests would take to fit through its request budget."""
    rpm = job.config.rate_limits.rpm
    if rpm is None:
        return 0.0
    return len(job.rows) * _attempts(job.config) / rpm


def _attempts(config: TaskConfig) -> int:
    """Attempts one row makes, planning for the worst case rejection sampling allows.

    Every other scheme makes a single attempt per row, an agentic loop included:
    the loop is one attempt however many requests it takes.
    """
    if config.generation.scheme != "rejection":
        return 1
    return config.generation.n if config.legacy else config.generation.max_attempts
