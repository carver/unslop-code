"""The vocabulary the sync and the change reports share.

A sync records what it did to each entry as an :class:`EntryChange`; the reports
group those records, and the entries a digest classifies, under the same names.
"""

from typing import NamedTuple

ADDED = "added"
REMOVED = "removed"
UPDATED = "updated"
#: Group headings in the order the reports print them.
HEADINGS = {ADDED: "Added", REMOVED: "Removed", UPDATED: "Updated"}
#: Name a changed ``removed`` field is reported under once the entry is back.
REAPPEARED = "reappeared"


class EntryChange(NamedTuple):
    """One entry a sync changed: its category, what happened and which fields moved."""

    category: str
    group: str
    entry: dict
    fields: tuple = ()
