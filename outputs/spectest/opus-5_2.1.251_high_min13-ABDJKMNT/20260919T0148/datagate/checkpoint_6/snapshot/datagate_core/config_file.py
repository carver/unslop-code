"""Reading the optional `KEY=VALUE` file named by `DATAGATE_CONFIG`."""

from pathlib import Path

from .errors import ConfigurationError

COMMENT = "#"


def read_config_file(path):
    """Return the assignments in `path`, or nothing when no file is configured.

    A file that cannot be read, and a line that is neither blank, a comment nor an
    assignment, are both invalid configuration and stop startup (AMBIGUITIES T60).
    """
    if path is None:
        return {}

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(f"Cannot read config file {path}: {error.strerror}.") from error
    return dict(_assignments(text, path))


def _assignments(text, path):
    """Yield the `(key, value)` of each assignment, skipping blank and comment lines.

    Only a line whose first non-blank character is `#` is a comment, so a `#` inside
    a value stays part of it (AMBIGUITIES T57). Keys repeated down the file take
    their last assignment, as the caller collects them into a mapping.
    """
    for number, line in enumerate(text.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith(COMMENT):
            continue

        key, separator, value = entry.partition("=")
        if not separator or not key.strip():
            raise ConfigurationError(f"Invalid config at {path}:{number}: {line!r}.")
        yield key.strip(), value.strip()
