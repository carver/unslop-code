"""The `digest` command: a human-readable summary of tracked-field changes.

Every entry of a vault is placed in at most one group -- removed, added or
updated -- by looking only at the shape of its stored histories, so a digest is
a pure read of the catalog and never touches the vault.
"""

import sys
from dataclasses import dataclass
from datetime import datetime

from mvaultlib.catalog import read_raw_catalog
from mvaultlib.timestamps import format_timestamp
from mvaultlib.viewer.links import viewer_link
from mvaultlib.views import build_view

REMOVED = "Removed"
ADDED = "Added"
UPDATED = "Updated"

#: Group precedence, and the order groups appear in within a category.
GROUP_ORDER = (REMOVED, ADDED, UPDATED)

REAPPEARED = "reappeared"
NO_CHANGES = "No notable changes found."
INDENT = "  "


@dataclass(frozen=True)
class Change:
    """One entry's place in the digest: its group, its title and its detail."""

    group: str
    title: str
    #: Viewer link to the entry, shown on the same line as the title.
    link: str
    #: Field names shown in parentheses; empty for removals and additions.
    details: tuple = ()

    def render(self):
        suffix = f" ({', '.join(self.details)})" if self.details else ""
        return f"{self.title}{suffix} {self.link}"


def digest_vault(name, now=None, out=sys.stdout):
    """Print the digest of the vault named `name` to `out`."""
    view = build_view(name, read_raw_catalog(name))
    print(render_digest(view, name, now or datetime.now()), file=out)


def render_digest(view, name, moment):
    """The full digest text: the changed categories followed by a trailing line."""
    sections = []
    for group in view.groups:
        changes = classify_entries(view, group, name)
        if changes:
            sections.append(_render_group(group.label, changes))
    body = "\n".join(sections) if sections else NO_CHANGES
    return f"{body}\n\n{_trailing_line(view, moment)}"


def classify_entries(view, group, name):
    """Classify a category's entries, keeping catalog order within each group."""
    changes = [
        classify_entry(view, entry, viewer_link(name, group.category, entry["id"]))
        for entry in group.entries
    ]
    return [change for change in changes if change is not None]


def classify_entry(view, entry, link):
    """Place one entry in its digest group, or return None when nothing is notable."""
    histories = [(field, entry[field]) for field in view.tracked_fields]
    title = view.current_value(entry["title"])
    if view.tracks_removal and _is_removal(view, entry["removed"]):
        return Change(REMOVED, title, link)
    if all(len(history) == 1 for _, history in histories):
        return Change(ADDED, title, link)
    changed = [field for field, history in histories if _has_new_value(view, history)]
    if not changed:
        return None
    return Change(UPDATED, title, link, _details(changed))


def _details(changed):
    """Changed field names, with a `removed` flip rendered as a reappearance."""
    names = [field for field in changed if field != "removed"]
    return tuple([REAPPEARED] + names if "removed" in changed else names)


def _is_removal(view, history):
    """True when the entry has just become removed rather than staying removed."""
    keys = view.ordered_keys(history)
    if history[keys[-1]] is not True:
        return False
    return len(keys) == 1 or history[keys[-2]] is False


def _has_new_value(view, history):
    """True when the history holds at least two keys whose latest values differ."""
    keys = view.ordered_keys(history)
    return len(keys) >= 2 and history[keys[-1]] != history[keys[-2]]


def _render_group(label, changes):
    """One category heading, its groups in precedence order and their entries."""
    lines = [f"{label}:"]
    for group in GROUP_ORDER:
        members = [change for change in changes if change.group == group]
        if members:
            lines.append(f"{INDENT}{group}:")
            lines.extend(f"{INDENT * 2}- {change.render()}" for change in members)
    return "\n".join(lines)


def _trailing_line(view, moment):
    """Deterministic metadata about this digest run, including the source URL."""
    return (
        f"Digest generated {format_timestamp(moment)} "
        f"from catalog version {view.version} at {view.source_url}"
    )
