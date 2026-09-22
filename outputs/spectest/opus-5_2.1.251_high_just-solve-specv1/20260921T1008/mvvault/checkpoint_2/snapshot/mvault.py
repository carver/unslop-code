#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked entry fields keyed by sync timestamp.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
CATEGORIES = ("episodes", "streams", "clips")

# Version 1 catalogs only record a short platform identifier; the full source
# URL is derived from it deterministically.
V1_SOURCE_PREFIX = "https://media.example.com/channel/"

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)
ANNOTATIONS_FIELD = "annotations"

DT_FORMAT = "%Y-%m-%dT%H:%M:%S"
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FETCH_FAILURE = "Source metadata fetch failure"


class MVaultError(Exception):
    """An error that should be reported to stderr with a non-zero exit."""


class SourceFetchError(MVaultError):
    """The source metadata could not be fetched or was malformed."""

    def __init__(self, detail: str = "") -> None:
        message = FETCH_FAILURE
        if detail:
            message = "{0}: {1}".format(FETCH_FAILURE, detail)
        super().__init__(message)


# ---------------------------------------------------------------------------
# datetime helpers
# ---------------------------------------------------------------------------


def format_dt(moment: datetime) -> str:
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SS`` (no timezone suffix)."""
    return moment.replace(microsecond=0, tzinfo=None).strftime(DT_FORMAT)


def parse_dt(text: str):
    """Parse an ISO 8601 datetime string, returning ``None`` when impossible."""
    if not isinstance(text, str):
        return None
    value = text.strip()
    if not value:
        return None
    if value.endswith(("Z", "z")):
        value = value[:-1]
    value = value.replace(" ", "T", 1) if " " in value and "T" not in value else value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        for fmt in (DT_FORMAT, "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed.replace(microsecond=0, tzinfo=None)


def normalize_published(text: str) -> str:
    """Normalize a published value to ``YYYY-MM-DDTHH:MM:SS``.

    Date-only values gain a ``00:00:00`` time component.  Values that cannot be
    parsed are returned unchanged so no information is lost.
    """
    if DATE_ONLY_RE.match(text.strip()):
        return text.strip() + "T00:00:00"
    parsed = parse_dt(text)
    if parsed is None:
        return text
    return format_dt(parsed)


# ---------------------------------------------------------------------------
# history helpers
# ---------------------------------------------------------------------------


def history_sort_key(stamp: str):
    """Sort key placing history keys in chronological order."""
    parsed = parse_dt(stamp)
    if parsed is None:
        return (1, datetime.min, stamp)
    return (0, parsed, stamp)


def latest_stamp(history):
    """Return the newest key of a history object, or ``None`` when empty."""
    if not isinstance(history, dict) or not history:
        return None
    return max(history, key=history_sort_key)


def current_value(history):
    """Current value of a tracked field = value at the latest datetime key."""
    stamp = latest_stamp(history)
    if stamp is None:
        return None, False
    return history[stamp], True


def max_history_moment(catalog):
    """Newest datetime used anywhere in the catalog's tracked histories."""
    newest = None
    for category in CATEGORIES:
        for entry in catalog.get(category) or []:
            if not isinstance(entry, dict):
                continue
            for field in TRACKED_FIELDS:
                history = entry.get(field)
                if not isinstance(history, dict):
                    continue
                for stamp in history:
                    moment = parse_dt(stamp)
                    if moment is not None and (newest is None or moment > newest):
                        newest = moment
    return newest


def sync_timestamp(catalog) -> str:
    """Timestamp for this sync: now, advanced past every recorded second."""
    moment = datetime.now().replace(microsecond=0)
    newest = max_history_moment(catalog)
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    return format_dt(moment)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_source_entry(entry) -> None:
    """Raise :class:`SourceFetchError` when a source entry is malformed."""
    if not isinstance(entry, dict):
        raise SourceFetchError("source entry is not an object")

    checks = (
        ("id", lambda v: isinstance(v, str), "string"),
        ("published", lambda v: isinstance(v, str), "string"),
        ("width", is_int, "integer"),
        ("height", is_int, "integer"),
        ("title", lambda v: isinstance(v, str), "string"),
        ("description", lambda v: isinstance(v, str), "string"),
        ("views", is_int, "integer"),
        ("likes", lambda v: v is None or is_int(v), "integer or null"),
        ("preview", lambda v: isinstance(v, str), "string"),
    )
    for field, check, expected in checks:
        if field not in entry:
            raise SourceFetchError(
                "source entry is missing required field '{0}'".format(field)
            )
        if not check(entry[field]):
            raise SourceFetchError(
                "source entry field '{0}' must be {1}".format(field, expected)
            )


def validate_source_payload(payload):
    """Validate the decoded source document and return it by category."""
    if not isinstance(payload, dict):
        raise SourceFetchError("source response is not a JSON object")

    by_category = {}
    for category in CATEGORIES:
        if category not in payload:
            raise SourceFetchError(
                "source response is missing '{0}'".format(category)
            )
        entries = payload[category]
        if not isinstance(entries, list):
            raise SourceFetchError(
                "source response field '{0}' is not an array".format(category)
            )
        for entry in entries:
            validate_source_entry(entry)
        by_category[category] = entries
    return by_category


def invalid_vault(name: str, detail: str) -> MVaultError:
    """Build the standard ``invalid vault`` error for a catalog problem."""
    return MVaultError(
        "invalid vault '{0}': {1} {2}".format(name, CATALOG_NAME, detail)
    )


def validate_catalog(catalog, name: str):
    """Raise :class:`MVaultError` when a loaded v3 catalog is not a valid vault."""
    if not isinstance(catalog, dict):
        raise invalid_vault(name, "is not a JSON object")
    if not is_int(catalog.get("version")) or catalog.get("version") != CATALOG_VERSION:
        raise invalid_vault(
            name, "version must be {0}".format(CATALOG_VERSION)
        )
    if not isinstance(catalog.get("source"), str):
        raise invalid_vault(name, "has no source URL")
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise invalid_vault(
                name, "is missing the '{0}' array".format(category)
            )
    return catalog


# ---------------------------------------------------------------------------
# legacy catalogs (version 1 and version 2)
# ---------------------------------------------------------------------------

# Value type expected at every point of a tracked field's history.  Legacy and
# native catalogs share these rules; only the key format differs.
HISTORY_VALUE_CHECKS = (
    ("title", lambda v: isinstance(v, str), "string"),
    ("description", lambda v: isinstance(v, str), "string"),
    ("views", is_int, "integer"),
    ("likes", lambda v: v is None or is_int(v), "integer or null"),
    ("preview", lambda v: isinstance(v, str), "string"),
)

STATIC_FIELD_CHECKS = (
    ("id", lambda v: isinstance(v, str), "string"),
    ("published", lambda v: isinstance(v, str), "string"),
    ("width", is_int, "integer"),
    ("height", is_int, "integer"),
)

EPOCH_KEY_RE = re.compile(r"^[+-]?\d+$")


def derive_v1_source(source_id: str) -> str:
    """Full source URL of a version 1 vault, derived from its ``source_id``."""
    return V1_SOURCE_PREFIX + source_id


def epoch_key_to_iso(stamp: str) -> str:
    """Convert a UNIX-epoch-seconds history key to an ISO 8601 UTC key."""
    moment = datetime.fromtimestamp(int(stamp.strip()), tz=timezone.utc)
    return format_dt(moment)


def entry_label(entry, index: int) -> str:
    identifier = entry.get("id") if isinstance(entry, dict) else None
    if isinstance(identifier, str) and identifier:
        return "entry '{0}'".format(identifier)
    return "entry #{0}".format(index)


def validate_legacy_entry(entry, index: int, name: str, epoch_keys: bool) -> None:
    """Raise :class:`MVaultError` when a v1/v2 entry is malformed."""
    if not isinstance(entry, dict):
        raise invalid_vault(
            name, "{0} is not an object".format(entry_label(entry, index))
        )
    label = entry_label(entry, index)

    for field, check, expected in STATIC_FIELD_CHECKS:
        if field not in entry:
            raise invalid_vault(
                name, "{0} is missing required field '{1}'".format(label, field)
            )
        if not check(entry[field]):
            raise invalid_vault(
                name, "{0} field '{1}' must be {2}".format(label, field, expected)
            )

    for field, check, expected in HISTORY_VALUE_CHECKS:
        if field not in entry:
            raise invalid_vault(
                name, "{0} is missing required field '{1}'".format(label, field)
            )
        history = entry[field]
        if not isinstance(history, dict):
            raise invalid_vault(
                name,
                "{0} field '{1}' must be a history object".format(label, field),
            )
        for stamp, value in history.items():
            if not isinstance(stamp, str) or not stamp.strip():
                raise invalid_vault(
                    name,
                    "{0} field '{1}' has an empty history key".format(label, field),
                )
            if epoch_keys:
                if not EPOCH_KEY_RE.match(stamp.strip()):
                    raise invalid_vault(
                        name,
                        "{0} field '{1}' history key '{2}' is not UNIX epoch "
                        "seconds".format(label, field, stamp),
                    )
            elif parse_dt(stamp) is None:
                raise invalid_vault(
                    name,
                    "{0} field '{1}' history key '{2}' is not an ISO 8601 "
                    "datetime".format(label, field, stamp),
                )
            if not check(value):
                raise invalid_vault(
                    name,
                    "{0} field '{1}' history value at '{2}' must be {3}".format(
                        label, field, stamp, expected
                    ),
                )


def convert_legacy_entry(entry, epoch_keys: bool):
    """Return the v3 shape of a validated v1/v2 entry (without ``removed``)."""
    converted = {field: entry[field] for field, _check, _e in STATIC_FIELD_CHECKS}
    for field, _check, _expected in HISTORY_VALUE_CHECKS:
        history = entry[field]
        if epoch_keys:
            converted[field] = {
                epoch_key_to_iso(stamp): value for stamp, value in history.items()
            }
        else:
            converted[field] = dict(history)
    # Keep any additional fields a legacy catalog happens to carry.
    for key, value in entry.items():
        if key not in converted and key not in ("removed", ANNOTATIONS_FIELD):
            converted[key] = value
    return converted


def legacy_category(raw, category: str, name: str):
    """Read a legacy category array, treating an absent one as empty."""
    entries = raw.get(category)
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise invalid_vault(name, "field '{0}' is not an array".format(category))
    return entries


def finalize_migration(catalog):
    """Stamp every migrated entry with ``removed`` and empty ``annotations``."""
    stamp = sync_timestamp(catalog)
    for category in CATEGORIES:
        for entry in catalog[category]:
            entry["removed"] = {stamp: False}
            entry[ANNOTATIONS_FIELD] = []
    return catalog


def migrate_v1(raw, name: str):
    """Convert a version 1 catalog document into the native v3 shape."""
    source_id = raw.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        raise invalid_vault(name, "has no 'source_id'")

    entries = legacy_category(raw, "entries", name)
    for index, entry in enumerate(entries):
        validate_legacy_entry(entry, index, name, True)

    catalog = {
        "version": CATALOG_VERSION,
        "source": derive_v1_source(source_id),
        # Every version 1 entry lives in a single flat list; they all become
        # episodes, and the remaining categories start out empty.
        "episodes": [convert_legacy_entry(entry, True) for entry in entries],
        "streams": [],
        "clips": [],
    }
    return finalize_migration(catalog)


def migrate_v2(raw, name: str):
    """Convert a version 2 catalog document into the native v3 shape."""
    source = raw.get("source")
    if not isinstance(source, str):
        raise invalid_vault(name, "has no source URL")

    by_category = {}
    for category in CATEGORIES:
        entries = legacy_category(raw, category, name)
        for index, entry in enumerate(entries):
            validate_legacy_entry(entry, index, name, False)
        by_category[category] = entries

    catalog = {"version": CATALOG_VERSION, "source": source}
    for category in CATEGORIES:
        catalog[category] = [
            convert_legacy_entry(entry, False) for entry in by_category[category]
        ]
    for key, value in raw.items():
        if key not in catalog:
            catalog[key] = value
    return finalize_migration(catalog)


def interpret_catalog(raw, name: str):
    """Return ``(catalog, migrated, version)`` for a decoded catalog document.

    The returned catalog is always in the native v3 in-memory shape, whatever
    the on-disk version was.  ``migrated`` tells the caller whether the result
    differs from what is on disk and therefore needs saving.
    """
    if not isinstance(raw, dict):
        raise invalid_vault(name, "is not a JSON object")
    if "version" not in raw:
        raise invalid_vault(name, "has no 'version' field")

    version = raw["version"]
    if not is_int(version):
        raise invalid_vault(name, "version must be an integer")
    if version not in SUPPORTED_VERSIONS:
        raise invalid_vault(
            name,
            "version {0} is not supported (supported versions: {1})".format(
                version, ", ".join(str(v) for v in SUPPORTED_VERSIONS)
            ),
        )

    if version == CATALOG_VERSION:
        return validate_catalog(raw, name), False, version
    if version == 1:
        return migrate_v1(raw, name), True, version
    return migrate_v2(raw, name), True, version


# ---------------------------------------------------------------------------
# catalog i/o
# ---------------------------------------------------------------------------


def catalog_path(name: str) -> str:
    return os.path.join(name, CATALOG_NAME)


def backup_path(name: str) -> str:
    return os.path.join(name, BACKUP_NAME)


def load_vault(name: str):
    """Load a vault of any supported version as ``(catalog, migrated, version)``.

    Reading never touches the vault on disk: a legacy catalog is migrated in
    memory only, and it is up to the caller to persist the result.
    """
    path = catalog_path(name)
    if not os.path.isdir(name):
        raise MVaultError("vault '{0}' does not exist".format(name))
    if not os.path.isfile(path):
        raise invalid_vault(name, "not found")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError) as exc:
        raise MVaultError(
            "invalid vault '{0}': cannot read {1} ({2})".format(name, CATALOG_NAME, exc)
        )
    return interpret_catalog(raw, name)


def load_catalog(name: str):
    """Load a vault for read-only use, transparently upgrading legacy shapes."""
    catalog, _migrated, _version = load_vault(name)
    return catalog


def dump_catalog(catalog) -> str:
    ordered = {
        "version": CATALOG_VERSION,
        "source": catalog.get("source", ""),
    }
    for category in CATEGORIES:
        ordered[category] = [order_entry(e) for e in catalog.get(category, [])]
    for key, value in catalog.items():
        if key not in ordered:
            ordered[key] = value
    return json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def order_entry(entry):
    """Render an entry with a stable, readable key order."""
    if not isinstance(entry, dict):
        return entry
    ordered = {}
    for field in STATIC_FIELDS:
        if field in entry:
            ordered[field] = entry[field]
    for field in TRACKED_FIELDS:
        if field in entry:
            ordered[field] = order_history(entry[field])
    if ANNOTATIONS_FIELD in entry:
        ordered[ANNOTATIONS_FIELD] = entry[ANNOTATIONS_FIELD]
    for key, value in entry.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def order_history(history):
    if not isinstance(history, dict):
        return history
    return {stamp: history[stamp] for stamp in sorted(history, key=history_sort_key)}


def write_catalog(name: str, catalog) -> None:
    """Write the catalog, backing up any pre-existing catalog byte-for-byte.

    The backup is written first, so a failure there aborts the write and leaves
    the original ``catalog.json`` untouched.
    """
    path = catalog_path(name)
    if os.path.isfile(path):
        try:
            with open(path, "rb") as handle:
                previous = handle.read()
            with open(backup_path(name), "wb") as handle:
                handle.write(previous)
        except OSError as exc:
            raise MVaultError(
                "cannot write {0} for vault '{1}': {2}".format(
                    BACKUP_NAME, name, exc
                )
            )
    payload = dump_catalog(catalog)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError as exc:
        raise MVaultError(
            "cannot write {0} for vault '{1}': {2}".format(CATALOG_NAME, name, exc)
        )


def entry_sort_key(entry):
    """Newest ``published`` first, ties broken by lexicographically smaller id."""
    published = entry.get("published")
    published = published if isinstance(published, str) else ""
    identifier = entry.get("id")
    identifier = identifier if isinstance(identifier, str) else ""
    parsed = parse_dt(published)
    # Sorting is done with reverse=False, so invert the datetime ordering by
    # using its negated timestamp; ids keep their natural ascending order.
    if parsed is None:
        rank = (1, 0.0, published)
    else:
        rank = (0, -parsed.timestamp(), "")
    return (rank, identifier)


def sort_entries(entries):
    return sorted(entries, key=entry_sort_key)


# ---------------------------------------------------------------------------
# source fetching
# ---------------------------------------------------------------------------


def fetch_source(url: str):
    try:
        with urllib.request.urlopen(url) as response:
            raw = response.read()
    except MVaultError:
        raise
    except Exception as exc:  # network, protocol, url errors ...
        raise SourceFetchError(str(exc) or exc.__class__.__name__)

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceFetchError(str(exc))
    else:
        text = raw

    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise SourceFetchError(str(exc))
    return validate_source_payload(payload)


# ---------------------------------------------------------------------------
# sync logic
# ---------------------------------------------------------------------------


def record(entry, field, value, stamp) -> bool:
    """Append ``value`` to a tracked field's history when it changed."""
    history = entry.get(field)
    if not isinstance(history, dict):
        history = {}
        entry[field] = history
    existing, has_value = current_value(history)
    if has_value and existing == value and type(existing) is type(value):
        return False
    history[stamp] = value
    return True


def make_entry(source_entry, stamp):
    entry = {
        "id": source_entry["id"],
        "published": normalize_published(source_entry["published"]),
        "width": source_entry["width"],
        "height": source_entry["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        entry[field] = {stamp: source_entry[field]}
    entry["removed"] = {stamp: False}
    entry[ANNOTATIONS_FIELD] = []
    return entry


def update_entry(entry, source_entry, stamp) -> None:
    entry["published"] = normalize_published(source_entry["published"])
    entry["width"] = source_entry["width"]
    entry["height"] = source_entry["height"]
    for field in SOURCE_TRACKED_FIELDS:
        record(entry, field, source_entry[field], stamp)
    record(entry, "removed", False, stamp)


def sync_catalog(catalog, source_by_category, stamp) -> None:
    for category in CATEGORIES:
        entries = [e for e in catalog.get(category, []) if isinstance(e, dict)]
        by_id = {}
        for entry in entries:
            identifier = entry.get("id")
            if isinstance(identifier, str) and identifier not in by_id:
                by_id[identifier] = entry

        seen = set()
        for source_entry in source_by_category[category]:
            identifier = source_entry["id"]
            seen.add(identifier)
            existing = by_id.get(identifier)
            if existing is None:
                new_entry = make_entry(source_entry, stamp)
                entries.append(new_entry)
                by_id[identifier] = new_entry
            else:
                update_entry(existing, source_entry, stamp)

        for entry in entries:
            if entry.get("id") not in seen:
                record(entry, "removed", True, stamp)

        catalog[category] = sort_entries(entries)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_init(name: str, url: str) -> int:
    if os.path.exists(name):
        raise MVaultError("vault '{0}' already exists".format(name))
    try:
        os.makedirs(name)
    except OSError as exc:
        raise MVaultError("cannot create vault '{0}': {1}".format(name, exc))

    catalog = {"version": CATALOG_VERSION, "source": url}
    for category in CATEGORIES:
        catalog[category] = []
    write_catalog(name, catalog)
    print("Initialized vault '{0}' at {1}".format(name, catalog_path(name)))
    return 0


def cmd_sync(name: str) -> int:
    # A legacy vault is migrated in memory first; the single write at the end
    # backs up the original catalog and stores the synced v3 result.
    catalog, _migrated, _version = load_vault(name)
    source_by_category = fetch_source(catalog["source"])
    stamp = sync_timestamp(catalog)
    sync_catalog(catalog, source_by_category, stamp)
    write_catalog(name, catalog)
    total = sum(len(catalog[category]) for category in CATEGORIES)
    print("Synced vault '{0}' at {1} ({2} entries)".format(name, stamp, total))
    return 0


def cmd_migrate(name: str) -> int:
    catalog, migrated, version = load_vault(name)
    if not migrated:
        print(
            "Vault '{0}' already uses catalog version {1}".format(
                name, CATALOG_VERSION
            )
        )
        return 0
    write_catalog(name, catalog)
    print(
        "Migrated vault '{0}' from catalog version {1} to {2}".format(
            name, version, CATALOG_VERSION
        )
    )
    return 0


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mvault",
        description=(
            "Create local vaults for media-platform metadata and record "
            "tracked-field history by sync timestamp."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault with an empty catalog"
    )
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source metadata URL")

    sync_parser = subparsers.add_parser(
        "sync", help="fetch the source and update the vault catalog"
    )
    sync_parser.add_argument("name", help="existing vault directory")

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy catalog to the native version"
    )
    migrate_parser.add_argument("name", help="existing vault directory")

    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not argv:
        parser.print_usage(sys.stderr)
        sys.stderr.write("mvault: error: a subcommand is required\n")
        return 2

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        sys.stderr.write("mvault: error: a subcommand is required\n")
        return 2

    try:
        if args.command == "init":
            return cmd_init(args.name, args.url)
        if args.command == "migrate":
            return cmd_migrate(args.name)
        return cmd_sync(args.name)
    except MVaultError as exc:
        sys.stderr.write("mvault: error: {0}\n".format(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
