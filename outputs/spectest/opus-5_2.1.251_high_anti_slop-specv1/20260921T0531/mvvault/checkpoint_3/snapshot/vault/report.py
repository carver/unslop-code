"""Human-readable reports printed to stdout: the digest and the sync summary."""

from . import digest
from .timestamps import format_timestamp

INDENT = "  "
NO_CHANGES = "No notable changes found."
REAPPEARED = "reappeared"


def render_digest(view, generated_at):
    """Render the notable changes of ``view`` as the text of a digest report."""
    lines = []
    for category in digest.summarize(view):
        lines.append(category.label)
        for group, changes in category.groups:
            lines.append(INDENT + group)
            lines.extend(INDENT * 2 + _change_line(change) for change in changes)
    if not lines:
        lines.append(NO_CHANGES)
    lines.append(_trailer(view, generated_at))
    return "\n".join(lines)


def _change_line(change):
    """One entry line: its current title, then what about it changed."""
    notes = ([REAPPEARED] if change.reappeared else []) + list(change.fields)
    return f"{change.title} ({', '.join(notes)})" if notes else change.title


def _trailer(view, generated_at):
    """The closing line naming the vault's source, version and digest time."""
    return (
        f"-- digest of {view.source} (catalog version {view.version})"
        f" at {format_timestamp(generated_at)}"
    )


def sync_summary(changes):
    """Render the counts a sync's metadata phase produced as one line."""
    return (
        f"Sync summary: {changes.added} added, {changes.removed} removed,"
        f" {changes.updated} updated"
    )
