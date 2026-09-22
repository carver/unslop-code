"""The ``digest`` command: what changed, read straight off the histories.

A digest never touches the vault it reports on.  It reads the catalog in the
version it was written in, sorts the entries that changed into additions,
removals and field updates, and prints them grouped by category.  Every entry
is reported beside the viewer address it can be read at.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import catalogs
import viewer
import views
from timestamps import format_timestamp
from views import CatalogView

#: The kinds of change a digest reports, in the order they are listed in.
REMOVED = "Removed"
ADDED = "Added"
UPDATED = "Updated"
KINDS = (REMOVED, ADDED, UPDATED)

#: Noted among the changed fields of an entry that came back after removal.
REAPPEARED = "reappeared"

NO_CHANGES = "No notable changes found."


@dataclass(frozen=True)
class Change:
    """One entry worth reporting, what about it changed and where to read it."""

    kind: str
    title: str
    url: str
    fields: tuple[str, ...] = ()

    def __str__(self) -> str:
        named = f"{self.title} ({', '.join(self.fields)})" if self.fields else self.title
        return f"{named} {self.url}"


def digest_vault(name: str) -> str:
    """Summarize the notable changes recorded in the vault called ``name``."""
    vault = Path(name)
    view = views.open_view(catalogs.read(vault, name), name)
    sections = [
        section for group in view.groups if (section := _category(view, group, name))
    ]
    if not sections:
        sections = [NO_CHANGES]
    return "\n\n".join(sections + [_trailer(name, view, datetime.now())])


def _category(view: CatalogView, group: views.CatalogGroup, name: str) -> str:
    """Render one category, or nothing at all when it held no changes."""
    changes = [
        change
        for entry in group.entries
        if (change := _change_of(view, entry, name, group.category))
    ]
    if not changes:
        return ""
    lines = [group.label]
    for kind in KINDS:
        listed = [change for change in changes if change.kind == kind]
        if listed:
            lines.append(f"  {kind}")
            lines.extend(f"    - {change}" for change in listed)
    return "\n".join(lines)


def _change_of(
    view: CatalogView, entry: catalogs.Entry, name: str, category: str
) -> Optional[Change]:
    """Classify one entry, or return ``None`` when it has nothing to report.

    An entry whose histories hold nothing but their first observation is new
    since the vault started tracking it; one whose removal flag has just been
    raised is gone.  Anything else is reported by the fields that moved, with
    a return from removal noted alongside them.
    """
    url = viewer.entry_url(name, category, entry["id"])
    values = {field: view.observations(entry, field) for field in view.fields}
    title = values["title"][-1]
    removal = values.get("removed", [])
    if _is_removal(removal):
        return Change(REMOVED, title, url)
    if all(len(observations) < 2 for observations in values.values()):
        return Change(ADDED, title, url)
    changed = tuple(
        field
        for field, observations in values.items()
        if field != "removed" and _has_new_value(observations)
    )
    if _is_reappearance(removal):
        changed += (REAPPEARED,)
    return Change(UPDATED, title, url, changed) if changed else None


def _has_new_value(observations: list) -> bool:
    """True when a field was observed again and took a different value."""
    return len(observations) >= 2 and observations[-1] != observations[-2]


def _is_removal(observations: list) -> bool:
    """True when the last observation of the removal flag raised it."""
    return observations[-1:] == [True] and observations[-2:-1] in ([], [False])


def _is_reappearance(observations: list) -> bool:
    """True when the removal flag was lowered again on a returning entry."""
    return observations[-2:] == [True, False]


def _trailer(name: str, view: CatalogView, moment: datetime) -> str:
    """The closing line naming the vault, its version, source and run time."""
    return (
        f"Digest of vault '{name}' (catalog version {view.version}) "
        f"from {view.source} at {format_timestamp(moment)}"
    )
