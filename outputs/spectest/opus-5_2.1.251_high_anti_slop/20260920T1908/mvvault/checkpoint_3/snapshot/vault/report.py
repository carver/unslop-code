"""The text ``digest`` and ``sync`` print on stdout."""

from datetime import datetime

from .digest import Change
from .sync import SyncCounts
from .timestamps import format_timestamp
from .views import CatalogView

NOTHING_NOTABLE = "No notable changes were found."
INDENT = "  "


def render_digest(
    view: CatalogView,
    collected: list[tuple[str, dict[str, list[Change]]]],
    moment: datetime,
) -> str:
    """Lay out a digest: a block per category, then one line about the run.

    Each block names the category, then each non-empty group, then the entries
    of that group in catalog order.
    """
    blocks = [_category_block(label, grouped) for label, grouped in collected]
    if not blocks:
        blocks = [NOTHING_NOTABLE]
    return "\n\n".join(blocks + [_trailer(view, collected, moment)])


def render_sync_summary(counts: SyncCounts) -> str:
    """State what one sync's metadata phase changed."""
    return (
        f"Sync recorded {counts.added} added, "
        f"{counts.removed} removed and {counts.updated} updated entries."
    )


def _category_block(label: str, grouped: dict[str, list[Change]]) -> str:
    """Render one category and the groups of changes below it."""
    lines = [label]
    for group, changes in grouped.items():
        lines.append(f"{INDENT}{group}:")
        lines.extend(f"{INDENT * 2}{change.describe()}" for change in changes)
    return "\n".join(lines)


def _trailer(
    view: CatalogView,
    collected: list[tuple[str, dict[str, list[Change]]]],
    moment: datetime,
) -> str:
    """Close the digest with the vault it came from and how much it covers."""
    total = sum(len(changes) for _, grouped in collected for changes in grouped.values())
    return (
        f"{total} notable change(s) from catalog version {view.version} "
        f"of {view.source}, read at {format_timestamp(moment)}."
    )
