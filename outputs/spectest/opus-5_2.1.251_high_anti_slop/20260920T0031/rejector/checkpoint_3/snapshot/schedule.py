"""How many attempts a row gets, and which ICL setup each of those attempts uses."""

from __future__ import annotations

from dataclasses import dataclass

from config import TaskConfig
from icl import FIXED, RenderedSetup, select
from templates import Message


@dataclass(frozen=True)
class AttemptPlan:
    """The attempt budget every row of one task follows.

    `limit` caps the generations a row may spend and `target` the solutions it
    wants; a row stops as soon as it reaches either. Rejection sampling is the
    only scheme whose solutions are `gated` on passing evaluation — the others
    keep whatever they generate.
    """

    limit: int
    target: int
    gated: bool
    setups: tuple[RenderedSetup, ...]
    strategy: str
    #: Greedy walks the setups in declared order instead of following the strategy.
    ordered: bool

    def prompt_for(self, attempt: int, base: list[Message]) -> tuple[str | None, list[Message]]:
        """The ICL setup name of this attempt and the messages it sends.

        Demonstrations go between the system message and the row's own user
        message, which `base` always ends with.
        """
        if not self.setups:
            return None, base
        setup = self.setups[attempt] if self.ordered else select(self.setups, self.strategy, attempt)
        return setup.name, base[:-1] + list(setup.messages) + base[-1:]


def attempt_plan(task: TaskConfig, setups: tuple[RenderedSetup, ...]) -> AttemptPlan:
    """Plan the attempts of one task's rows.

    A task asking for a single solution without ICL keeps the Part 1 budget:
    `generation.n` attempts for rejection sampling, one for anything else.
    """
    gated = task.generation.scheme == "rejection"
    if not task.multi_solution:
        return AttemptPlan(
            limit=task.generation.attempts, target=1, gated=gated, setups=(), strategy=FIXED, ordered=False
        )
    return AttemptPlan(
        limit=_limit(task, len(setups)),
        target=task.num_solutions,
        gated=gated,
        setups=setups,
        strategy=task.icl.strategy if task.icl else FIXED,
        ordered=task.generation.scheme == "greedy" and task.num_solutions > 1,
    )


def _limit(task: TaskConfig, setup_count: int) -> int:
    """Generations a multi-solution row may spend.

    Greedy is deterministic per setup, so it gets one attempt per setup at most;
    sampling gets one per requested solution and rejection its whole budget.
    """
    if task.generation.scheme == "greedy":
        return min(task.num_solutions, max(setup_count, 1))
    if task.generation.scheme == "sample":
        return task.num_solutions
    return task.generation.max_attempts
