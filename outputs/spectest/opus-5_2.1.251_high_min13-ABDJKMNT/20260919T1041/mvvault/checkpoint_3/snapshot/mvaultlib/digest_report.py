"""Laying a :class:`~mvaultlib.digest.VaultView` out as the `digest` report."""

from .digest import GROUPS, classify, current_title

NO_CHANGES = "No notable changes found."

#: How a `removed` value that has gone back to false is named in a change list.
REAPPEARED = "reappeared"


def render(name, view, stamp):
    """The digest text for `view`, its trailing run-metadata line included."""
    lines = []
    for label, entries in view.groups:
        section = _section(entries, view)
        if section:
            lines.append(label)
            lines.extend(section)

    body = lines or [NO_CHANGES]
    return "\n".join([*body, _trailing_line(name, view, stamp)])


def _section(entries, view):
    """One category's change lines, grouped by type; empty if nothing qualifies."""
    grouped = {group: [] for group in GROUPS}
    for entry in entries:
        classified = classify(entry, view)
        if classified:
            group, changed = classified
            grouped[group].append(f"    - {current_title(entry, view)}{_suffix(changed)}")

    lines = []
    for group in GROUPS:
        if grouped[group]:
            lines.append(f"  {group}:")
            lines.extend(grouped[group])
    return lines


def _suffix(changed):
    """The parenthesised change list that follows an updated entry's title."""
    if not changed:
        return ""
    names = [REAPPEARED if field == "removed" else field for field in changed]
    return f" ({', '.join(names)})"


def _trailing_line(name, view, stamp):
    """What the digest was run against, and when."""
    return f"digest of vault '{name}' (version {view.version}) generated {stamp} from {view.source}"
