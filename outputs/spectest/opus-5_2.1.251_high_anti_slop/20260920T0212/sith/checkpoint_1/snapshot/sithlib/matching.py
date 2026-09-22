"""Filtering candidate names against the partially typed prefix."""


def matches(name, prefix, fuzzy):
    """Whether `name` is offered for `prefix`; always case-insensitive."""
    if not prefix:
        return True
    lowered, wanted = name.lower(), prefix.lower()
    if not fuzzy:
        return lowered.startswith(wanted)
    remaining = iter(lowered)
    return all(character in remaining for character in wanted)
