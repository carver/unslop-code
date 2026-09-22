"""Classifying the notable changes of a vault read at its own version.

`digest` never migrates, so the catalog is read through a
:class:`~mvaultlib.vault_view.VaultView` and every rule here works off that
view rather than off the native layout.
"""

from .vault_view import ordered_values

#: The change groups, in the precedence order an entry is tested against.
REMOVED, ADDED, UPDATED = "Removed", "Added", "Updated"
GROUPS = (REMOVED, ADDED, UPDATED)


def classify(entry, view):
    """The group `entry` belongs to and its changed fields, or `None`.

    The groups are tested in precedence order, so an entry that would qualify
    for several of them is reported only as the first one that matches.
    """
    if view.detect_removals and _is_removal(entry, view):
        return REMOVED, ()
    if all(len(entry[field]) < 2 for field in view.tracked):
        return ADDED, ()
    changed = _changed_fields(entry, view)
    return (UPDATED, changed) if changed else None


def _is_removal(entry, view):
    """Whether `removed` has just turned true, a first observation included."""
    values = ordered_values(entry, "removed", view)
    return values[-1] is True and (len(values) == 1 or values[-2] is False)


def _changed_fields(entry, view):
    """Tracked fields with at least two observations whose latest two differ."""
    changed = []
    for field in view.tracked:
        values = ordered_values(entry, field, view)
        if len(values) > 1 and values[-1] != values[-2]:
            changed.append(field)
    return tuple(changed)
