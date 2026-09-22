"""Inferring the output schema when `--schema` is not given.

Two axes combine. `--infer` decides what one file's values say about a column, and
`--schema-strategy` decides how files that disagree are reconciled; under the default
`authoritative` strategy the `--infer` rule also settles disagreement inside the
winning precedence tier, which keeps checkpoint-1 behaviour exact for CSV-only runs
(AMBIGUITIES T20).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from .coltypes import STRING, TYPE_PRIORITY, resolve_priority
from .schema import LOOSE, Column, Schema
from .values import candidates_of

AUTHORITATIVE = "authoritative"
CONSENSUS = "consensus"
UNION = "union"
STRATEGIES = (AUTHORITATIVE, CONSENSUS, UNION)


@dataclass(frozen=True)
class Opinion:
    """One file's evidence about one column: the types all its values support."""

    tier: int
    candidates: frozenset


class SchemaInferrer:
    """Accumulates per-file evidence and resolves it into an output schema.

    A column is included as soon as any source declares or mentions it, but only
    files with at least one non-null value get an opinion on its type; a column
    nobody had a value for resolves to `string` (AMBIGUITIES T14, T32).
    """

    def __init__(self, mode, strategy):
        self._resolve_type = _resolver(strategy, mode)
        self._names = set()
        self._opinions = {}
        self._current = {}

    def declare(self, names):
        """Record column names a source announces before any row is read."""
        self._names.update(names)

    def observe(self, record):
        """Record one source row: its keys are columns, its values are evidence."""
        for name, value in record.items():
            self._names.add(name)
            if value is None:
                continue
            candidates = candidates_of(value)
            seen = self._current.get(name)
            self._current[name] = candidates if seen is None else seen & candidates

    def end_file(self, tier):
        """Close the current file's scope, turning its evidence into opinions."""
        for name, candidates in self._current.items():
            self._opinions.setdefault(name, []).append(Opinion(tier, frozenset(candidates)))
        self._current = {}

    def resolve(self):
        """Return the inferred schema, ordered lexicographically by column name."""
        return Schema(tuple(Column(name, self._type_of(name)) for name in sorted(self._names)))

    def _type_of(self, name):
        opinions = self._opinions.get(name)
        return self._resolve_type(opinions) if opinions else STRING


def _resolver(strategy, mode):
    """Pick the function that turns one column's opinions into a single type."""
    if strategy == CONSENSUS:
        return _majority_supported
    if strategy == UNION:
        return _narrowest
    return partial(_authoritative, mode=mode)


def _authoritative(opinions, mode):
    """Let the most type-aware sources decide, combining ties with `--infer`."""
    top = max(opinion.tier for opinion in opinions)
    peers = [opinion for opinion in opinions if opinion.tier == top]
    if mode == LOOSE:
        return _narrowest(peers)
    agreed = {resolve_priority(opinion.candidates) for opinion in peers}
    return agreed.pop() if len(agreed) == 1 else STRING


def _majority_supported(opinions):
    """Take the best type more than half the files can hold (AMBIGUITIES T21)."""
    threshold = len(opinions) / 2
    supported = (
        name
        for name in TYPE_PRIORITY
        if sum(name in opinion.candidates for opinion in opinions) > threshold
    )
    return next(supported, STRING)


def _narrowest(opinions):
    """Take the best type every observed value can be held by (AMBIGUITIES T22)."""
    common = set(TYPE_PRIORITY)
    for opinion in opinions:
        common &= opinion.candidates
    return resolve_priority(common)
