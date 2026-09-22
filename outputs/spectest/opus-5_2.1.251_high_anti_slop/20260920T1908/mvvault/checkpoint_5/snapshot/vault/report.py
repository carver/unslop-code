"""The text ``digest`` and ``sync`` print on stdout.

Both report the same kind of thing, so both lay a change set out the same
way: a block per category, its groups below it, and one line per entry ending
in the link that opens that entry in the viewer.
"""

from datetime import datetime

from .changes import ADDED, REMOVED, UPDATED, Change, ChangeSet
from .timestamps import format_timestamp
from .viewer.links import entry_link
from .views import CatalogView

NOTHING_NOTABLE = "No notable changes were found."
INDENT = "  "


def render_digest(
    view: CatalogView, changes: ChangeSet, name: str, moment: datetime
) -> str:
    """Lay out a digest of ``name``: a block per category, then one line about the run."""
    blocks = _category_blocks(changes, name) or [NOTHING_NOTABLE]
    return "\n\n".join(blocks + [_trailer(view, changes, moment)])


def render_sync_summary(changes: ChangeSet, name: str) -> str:
    """State what one sync's metadata phase changed in ``name``."""
    counted = (
        f"Sync recorded {changes.count(ADDED)} added, "
        f"{changes.count(REMOVED)} removed and {changes.count(UPDATED)} updated entries."
    )
    return "\n\n".join(_category_blocks(changes, name) + [counted])


def _category_blocks(changes: ChangeSet, name: str) -> list[str]:
    """Render one block per category that has a change, in catalog order."""
    return [
        _category_block(category, grouped, name) for category, grouped in changes.categories
    ]


def _category_block(category: str, grouped: dict[str, list[Change]], name: str) -> str:
    """Render one category and the groups of changes below it."""
    lines = [category.capitalize()]
    for group, changes in grouped.items():
        lines.append(f"{INDENT}{group}:")
        lines.extend(f"{INDENT * 2}{_change_line(change, name, category)}" for change in changes)
    return "\n".join(lines)


def _change_line(change: Change, name: str, category: str) -> str:
    """One entry: what happened to it, and where the viewer shows it."""
    return f"{change.describe()}  {entry_link(name, category, change.entry_id)}"


def _trailer(view: CatalogView, changes: ChangeSet, moment: datetime) -> str:
    """Close the digest with the vault it came from and how much it covers."""
    return (
        f"{changes.total} notable change(s) from catalog version {view.version} "
        f"of {view.source}, read at {format_timestamp(moment)}."
    )
