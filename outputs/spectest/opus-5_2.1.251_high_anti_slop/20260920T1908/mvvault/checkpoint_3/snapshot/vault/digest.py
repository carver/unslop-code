"""Summarizing the notable changes a vault's tracked-field history records.

An entry counts as one change at most. It is a removal if its ``removed``
history says so, otherwise an addition if nothing about it has ever changed,
otherwise an update naming the tracked fields whose latest value differs from
the one before it.
"""

from dataclasses import dataclass

from .views import REMOVED_FIELD, CatalogView

ADDED = "Added"
REMOVED = "Removed"
UPDATED = "Updated"
GROUP_ORDER = (REMOVED, ADDED, UPDATED)

REAPPEARED = "reappeared"


@dataclass(frozen=True)
class Change:
    """One entry's place in the digest: its group, its title and its cause."""

    group: str
    title: str
    fields: tuple[str, ...]

    def describe(self) -> str:
        """The entry's line in the digest, naming changed fields if there are any."""
        if not self.fields:
            return self.title
        return f"{self.title} ({', '.join(self.fields)})"


def collect_changes(view: CatalogView) -> list[tuple[str, dict[str, list[Change]]]]:
    """Group the notable changes of every category by category and then by group.

    Categories without a change are left out, as are empty groups within a
    category. Entries keep their catalog order.
    """
    collected = []
    for label, entries in view.groups:
        changes = [change for change in (_classify(entry, view) for entry in entries) if change]
        if changes:
            collected.append((label, _by_group(changes)))
    return collected


def _by_group(changes: list[Change]) -> dict[str, list[Change]]:
    """Sort one category's changes into the fixed group order."""
    grouped = {group: [] for group in GROUP_ORDER}
    for change in changes:
        grouped[change.group].append(change)
    return {group: members for group, members in grouped.items() if members}


def _classify(entry: dict, view: CatalogView) -> Change | None:
    """Decide which single change, if any, an entry represents."""
    title = view.ordered_values(entry["title"])[-1]
    if view.removals_tracked and _is_removal(entry.get(REMOVED_FIELD, {}), view):
        return Change(REMOVED, title, ())
    if _is_addition(entry, view):
        return Change(ADDED, title, ())
    changed = _changed_fields(entry, view)
    return Change(UPDATED, title, changed) if changed else None


def _is_removal(history: dict, view: CatalogView) -> bool:
    """A removal is a latest ``removed`` of ``True`` preceded by ``False``, or by nothing."""
    values = view.ordered_values(history)
    if not values or values[-1] is not True:
        return False
    return values[-2:-1] in ([], [False])


def _is_addition(entry: dict, view: CatalogView) -> bool:
    """An addition has been observed once: no tracked field has a second value."""
    return all(len(entry.get(field, {})) < 2 for field in view.tracked_fields)


def _changed_fields(entry: dict, view: CatalogView) -> tuple[str, ...]:
    """Name the tracked fields whose latest value differs from the one before it.

    A ``removed`` field reaching this point went back to ``False``, which is an
    entry the source published again rather than a field the source changed.
    """
    changed = []
    for field in view.tracked_fields:
        values = view.ordered_values(entry.get(field, {}))
        if len(values) >= 2 and values[-1] != values[-2]:
            changed.append(REAPPEARED if field == REMOVED_FIELD else field)
    return tuple(changed)
