"""Reading the `DATAGATE_CONFIG` file into raw `KEY=VALUE` strings."""

from pathlib import Path
from typing import Iterator

from datagate_core.errors import ConfigurationError

COMMENT_MARKER = "#"


def read_config_file(path: str | None) -> dict[str, str]:
    """Parse the config file at `path`, or nothing at all when no path is given.

    An unset or empty `DATAGATE_CONFIG` names no file, which is not a failure;
    a path that cannot be read is one (T59). Keys and values are trimmed, the
    value keeps every `=` after the first, and a line that is neither blank nor
    a comment nor `KEY=VALUE` is invalid config (T58).
    """
    if not path:
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        raise ConfigurationError(f"cannot read config file {path!r}: {error}")
    return dict(_setting(line, number, path) for number, line in _content_lines(text))


def _content_lines(text: str) -> Iterator[tuple[int, str]]:
    """The numbered, trimmed lines that are neither blank nor comments."""
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith(COMMENT_MARKER):
            yield number, stripped


def _setting(line: str, number: int, path: str) -> tuple[str, str]:
    """Split one `KEY=VALUE` line into its trimmed key and value."""
    key, separator, value = line.partition("=")
    if not separator:
        raise ConfigurationError(f"{path}:{number}: expected KEY=VALUE, got {line!r}")
    return key.strip(), value.strip()
