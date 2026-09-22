"""Filtering candidate names against the partially typed prefix."""


def matches(name, prefix, fuzzy, case_insensitive=True):
    """Whether `name` is offered for `prefix`, ignoring case unless asked not to."""
    if not prefix:
        return True
    lowered, wanted = ((name.lower(), prefix.lower()) if case_insensitive
                       else (name, prefix))
    if not fuzzy:
        return lowered.startswith(wanted)
    remaining = iter(lowered)
    return all(character in remaining for character in wanted)
