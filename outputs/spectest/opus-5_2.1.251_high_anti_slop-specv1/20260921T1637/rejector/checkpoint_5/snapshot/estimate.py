"""Dry-run estimation: what a run would cost, without sending a request."""

from typing import Any

from accounting import TOKENS_PER_PRICED_UNIT, round_cost
from config import TaskConfig
from jobs import TaskJob

#: Tokens one prompt word is estimated to become.
TOKENS_PER_WORD = 1.33


def estimate_run(jobs: list[TaskJob]) -> dict[str, Any]:
    """Estimate every job's inputs, tokens, cost, and time from the rendered prompts."""
    tasks = {job.task.name: _estimate_task(job) for job in jobs}
    return {
        "tasks": tasks,
        "total_inputs": sum(task["inputs"] for task in tasks.values()),
        "est_total_tokens": sum(task["est_total_tokens"] for task in tasks.values()),
        "est_total_cost": round_cost(sum(task["est_cost"] for task in tasks.values())),
        "est_time_minutes": round_cost(sum(_estimate_minutes(job) for job in jobs)),
    }


def _estimate_task(job: TaskJob) -> dict[str, Any]:
    """One task's estimate: its prompts as tokens, plus the completions they will draw."""
    inputs = len(job.rows)
    prompt_tokens = round(_average_words(job) * TOKENS_PER_WORD * inputs)
    completion_tokens = inputs * job.task.generation.max_tokens
    return {
        "inputs": inputs,
        "est_prompt_tokens": prompt_tokens,
        "est_completion_tokens": completion_tokens,
        "est_total_tokens": prompt_tokens + completion_tokens,
        "est_cost": _estimate_cost(job.task, prompt_tokens, completion_tokens),
    }


def _average_words(job: TaskJob) -> float:
    """Words in an average rendered prompt for this task."""
    if not job.prompts:
        return 0.0
    words = sum(
        len(str(message["content"]).split()) for prompt in job.prompts for message in prompt
    )
    return words / len(job.prompts)


def _estimate_cost(task: TaskConfig, prompt_tokens: int, completion_tokens: int) -> float:
    """What those tokens would cost at the task's prices; free when it sets none."""
    if task.cost is None:
        return 0.0
    prompt = prompt_tokens / TOKENS_PER_PRICED_UNIT * task.cost.prompt_per_1k
    completion = completion_tokens / TOKENS_PER_PRICED_UNIT * task.cost.completion_per_1k
    return round_cost(prompt + completion)


def _estimate_minutes(job: TaskJob) -> float:
    """How long the task's requests take to clear its request budget, if it has one."""
    rpm = job.task.limits.rpm
    if rpm is None:
        return 0.0
    return len(job.rows) * _average_attempts(job.task) / rpm


def _average_attempts(task: TaskConfig) -> int:
    """Requests one row is planned to spend, taking the worst case where there is a choice.

    ``greedy`` and ``sample`` spend one request per solution they are asked for,
    ``rejection`` may spend its whole attempt budget, and an agentic row may
    spend its whole iteration budget.
    """
    generation = task.generation
    if generation.scheme == "agentic":
        return generation.max_iterations * task.num_solutions
    if generation.scheme != "rejection":
        return task.num_solutions
    if task.num_solutions == 1 and task.icl is None:
        return generation.n
    return generation.max_attempts
