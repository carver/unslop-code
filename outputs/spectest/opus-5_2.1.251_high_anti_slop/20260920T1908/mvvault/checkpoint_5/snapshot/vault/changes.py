"""The notable changes a report describes, grouped by category and by cause.

Both a digest of stored history and the merge phase of a sync end up with the
same thing to say: per category, which entries were added, which the source
dropped, and which moved on. They produce a :class:`ChangeSet` so that one
renderer can lay either of them out.
"""

from dataclasses import dataclass

ADDED = "Added"
REMOVED = "Removed"
UPDATED = "Updated"
GROUP_ORDER = (REMOVED, ADDED, UPDATED)

REAPPEARED = "reappeared"


@dataclass(frozen=True)
class Change:
    """One entry's place in a report: its cause, its identity and its title."""

    group: str
    entry_id: str
    title: str
    fields: tuple[str, ...] = ()

    def describe(self) -> str:
        """The entry's line in a report, naming changed fields if there are any."""
        if not self.fields:
            return self.title
        return f"{self.title} ({', '.join(self.fields)})"


@dataclass(frozen=True)
class ChangeSet:
    """Every notable change of one catalog, in catalog order."""

    categories: tuple[tuple[str, dict[str, list[Change]]], ...]

    @property
    def total(self) -> int:
        """How many entries the set speaks about."""
        return self.count(*GROUP_ORDER)

    def count(self, *groups: str) -> int:
        """How many entries fall into the named groups."""
        return sum(
            len(grouped.get(group, ()))
            for _, grouped in self.categories
            for group in groups
        )


def change_set(per_category: list[tuple[str, list[Change]]]) -> ChangeSet:
    """Build a change set, leaving out categories and groups without a change."""
    return ChangeSet(
        tuple(
            (category, grouped)
            for category, changes in per_category
            if (grouped := _by_group(changes))
        )
    )


def _by_group(changes: list[Change]) -> dict[str, list[Change]]:
    """Sort one category's changes into the fixed group order."""
    grouped = {group: [] for group in GROUP_ORDER}
    for change in changes:
        grouped[change.group].append(change)
    return {group: members for group, members in grouped.items() if members}
