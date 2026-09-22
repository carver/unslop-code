"""Summarizing the notable changes a vault's tracked-field history records.

An entry counts as one change at most. It is a removal if its ``removed``
history says so, otherwise an addition if nothing about it has ever changed,
otherwise an update naming the tracked fields whose latest value differs from
the one before it.
"""

from .changes import ADDED, REAPPEARED, REMOVED, UPDATED, Change, ChangeSet, change_set
from .schema import REMOVED_FIELD
from .views import CatalogView


def collect_changes(view: CatalogView) -> ChangeSet:
    """Group the notable changes of every category by category and then by group.

    Categories without a change are left out, as are empty groups within a
    category. Entries keep their catalog order.
    """
    return change_set(
        [
            (category, [change for entry in entries if (change := _classify(entry, view))])
            for category, entries in view.groups
        ]
    )


def _classify(entry: dict, view: CatalogView) -> Change | None:
    """Decide which single change, if any, an entry represents."""
    title = view.current_value(entry["title"], "")
    if view.removals_tracked and _is_removal(entry.get(REMOVED_FIELD, {}), view):
        return Change(REMOVED, entry["id"], title)
    if _is_addition(entry, view):
        return Change(ADDED, entry["id"], title)
    changed = _changed_fields(entry, view)
    return Change(UPDATED, entry["id"], title, changed) if changed else None


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
