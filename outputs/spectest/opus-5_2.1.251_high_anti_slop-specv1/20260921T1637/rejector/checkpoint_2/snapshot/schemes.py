"""Per-row generation schemes: greedy, sample, and rejection sampling."""

from typing import Any

from api import ChatClient
from config import TaskConfig
from dataset import Messages
from evaluation import evaluate
from results import Attempt, RowOutcome


async def generate_row(
    client: ChatClient,
    judge: ChatClient | None,
    task: TaskConfig,
    messages: Messages,
    row: dict[str, Any],
) -> RowOutcome:
    """Produce one row's outcome.

    ``greedy`` and ``sample`` keep their single response whatever the evaluation
    says. ``rejection`` retries a failing response up to ``n`` times and keeps
    the first one that passes; if none does, the row has no output.
    """
    generation = task.generation
    rejecting = generation.scheme == "rejection"
    attempts: list[Attempt] = []
    for _ in range(generation.n if rejecting else 1):
        completion = await client.complete(messages, generation.temperature, generation.max_tokens)
        if completion.text is None:
            attempts.append(Attempt(completion.meta))
            break
        result = await evaluate(task.evaluation, completion.text, row, judge)
        attempts.append(Attempt(completion.meta, result.judge_meta))
        if result.passed or not rejecting:
            return RowOutcome(
                row=row,
                text=completion.text,
                passed=result.passed,
                extracted_answer=result.extracted_answer,
                judge_score=result.judge_score,
                attempts=attempts,
            )
    return RowOutcome(
        row=row,
        text=None,
        passed=False if task.evaluation else None,
        extracted_answer=None,
        judge_score=None,
        attempts=attempts,
    )
