"""Per-row generation schemes: greedy, sample, and rejection sampling."""

from typing import Any

from api import ChatClient
from config import TaskConfig
from dataset import Messages
from evaluation import evaluate
from results import RowOutcome


async def generate_row(
    client: ChatClient, task: TaskConfig, messages: Messages, row: dict[str, Any]
) -> RowOutcome:
    """Produce one row's outcome.

    ``greedy`` and ``sample`` keep their single response whatever the evaluation
    says. ``rejection`` retries a failing response up to ``n`` times and keeps
    the first one that passes; if none does, the row has no output.
    """
    generation = task.generation
    rejecting = generation.scheme == "rejection"
    metas = []
    for _ in range(generation.n if rejecting else 1):
        completion = await client.complete(messages, generation.temperature, generation.max_tokens)
        metas.append(completion.meta)
        if completion.text is None:
            break
        passed, extracted = evaluate(task.evaluation, completion.text, row)
        if passed or not rejecting:
            return RowOutcome(row, completion.text, passed, extracted, metas)
    return RowOutcome(
        row=row,
        text=None,
        passed=False if task.evaluation else None,
        extracted_answer=None,
        metas=metas,
    )
