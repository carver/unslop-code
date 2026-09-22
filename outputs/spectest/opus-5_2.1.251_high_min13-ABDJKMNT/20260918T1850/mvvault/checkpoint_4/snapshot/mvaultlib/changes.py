"""What a change report is made of: one changed entry, and how changes group."""

from dataclasses import dataclass

#: Change groups in the order they take precedence, and so the order they print.
GROUP_ORDER = ("removed", "added", "updated")


@dataclass(frozen=True)
class Change:
    """One entry that qualifies for a report group.

    `fields` names the tracked fields whose value changed, and `reappeared` says
    the entry came back after having been removed. Both are empty for an entry
    that is merely an addition or a removal.
    """

    entry_id: str
    title: str
    fields: tuple = ()
    reappeared: bool = False


def group_changes(classified):
    """Group `(category, group, change)` triples as `{category: {group: [...]}}`.

    Categories with nothing to report are left out entirely, and within a
    category the groups appear in precedence order.
    """
    grouped = {}
    for category, group, change in classified:
        grouped.setdefault(category, {}).setdefault(group, []).append(change)
    return {
        category: {group: groups[group] for group in GROUP_ORDER if group in groups}
        for category, groups in grouped.items()
    }
