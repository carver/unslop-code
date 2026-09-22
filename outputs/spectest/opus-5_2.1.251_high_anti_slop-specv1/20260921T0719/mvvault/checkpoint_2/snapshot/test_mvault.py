"""End-to-end tests for the mvault command line."""

import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import vault

MVAULT = str(Path(__file__).resolve().parent / "mvault.py")


def entry(identifier, published="2024-03-01T10:00:00", **overrides):
    """Build a source entry with sensible defaults for every required field."""
    item = {
        "id": identifier,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": f"Title {identifier}",
        "description": "Description",
        "views": 10,
        "likes": 1,
        "preview": "hash",
    }
    item.update(overrides)
    return item


def document(episodes=(), streams=(), clips=()):
    """Build a source document from the three category lists."""
    return {"episodes": list(episodes), "streams": list(streams), "clips": list(clips)}


def stored_entry(identifier, keys, **overrides):
    """Build a legacy stored entry whose histories use the given two keys."""
    old, new = keys
    item = {
        "id": identifier,
        "published": "2024-03-01T10:00:00",
        "width": 1920,
        "height": 1080,
        "title": {old: f"Title {identifier}", new: f"Retitled {identifier}"},
        "description": {old: "Description"},
        "views": {old: 10, new: 12},
        "likes": {old: None, new: 3},
        "preview": {old: "hash"},
    }
    item.update(overrides)
    return item


#: Epoch history keys of a version 1 entry and the timestamps they stand for.
EPOCH_KEYS = ("1718444400", "1718530800")
EPOCH_TIMESTAMPS = ["2024-06-15T09:40:00", "2024-06-16T09:40:00"]

#: ISO history keys of a version 2 entry.
ISO_KEYS = ("2024-06-15T09:40:00", "2024-06-16T09:40:00")


def v1_catalog(source_id="alpha", entries=()):
    """Build a version 1 catalog: one flat list under a short source id."""
    return {"version": 1, "source_id": source_id, "entries": list(entries)}


def v2_catalog(source, episodes=(), streams=(), clips=()):
    """Build a version 2 catalog: categories without the local fields."""
    return {"version": 2, "source": source, **document(episodes, streams, clips)}


class SourceServer:
    """Serves whatever JSON payload the current test assigns to ``payload``."""

    def __init__(self):
        self.payload = document()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(server.payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/feed.json" % self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()


class MvaultTestCase(unittest.TestCase):
    def setUp(self):
        self.workdir = TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.source = SourceServer()
        self.addCleanup(self.source.close)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, MVAULT, *args],
            cwd=self.workdir.name,
            capture_output=True,
            text=True,
        )

    def catalog(self, name="vault"):
        return json.loads((Path(self.workdir.name) / name / "catalog.json").read_text())

    def init(self, name="vault"):
        result = self.run_cli("init", name, self.source.url)
        self.assertEqual(result.returncode, 0, result.stderr)

    def sync(self, name="vault"):
        result = self.run_cli("sync", name)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def vault_path(self, name="vault"):
        return Path(self.workdir.name) / name

    def write_catalog(self, catalog, name="vault"):
        """Put a hand-built catalog of any version in an otherwise new vault."""
        self.vault_path(name).mkdir()
        (self.vault_path(name) / "catalog.json").write_text(json.dumps(catalog))


class GlobalCommandTests(MvaultTestCase):
    def test_help_lists_subcommands(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("init", result.stdout)
        self.assertIn("sync", result.stdout)

    def test_no_subcommand_prints_usage_to_stderr(self):
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage", result.stderr.lower())
        self.assertEqual(result.stdout, "")


class InitTests(MvaultTestCase):
    def test_creates_empty_catalog(self):
        self.init()
        self.assertEqual(
            self.catalog(),
            {
                "version": 3,
                "source": self.source.url,
                "episodes": [],
                "streams": [],
                "clips": [],
            },
        )

    def test_existing_directory_is_refused(self):
        self.init()
        (Path(self.workdir.name) / "vault" / "marker").write_text("keep")
        result = self.run_cli("init", "vault", "http://elsewhere.example/feed.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vault", result.stderr)
        self.assertEqual(self.catalog()["source"], self.source.url)
        self.assertTrue((Path(self.workdir.name) / "vault" / "marker").exists())


class SyncTests(MvaultTestCase):
    def test_first_sync_records_every_tracked_field(self):
        self.source.payload = document(episodes=[entry("e1", likes=None)])
        self.init()
        self.sync()
        stored = self.catalog()["episodes"][0]
        self.assertEqual(stored["id"], "e1")
        self.assertEqual(stored["published"], "2024-03-01T10:00:00")
        self.assertEqual(stored["width"], 1920)
        for field in ("title", "description", "views", "likes", "preview", "removed"):
            self.assertEqual(len(stored[field]), 1, field)
        self.assertIsNone(list(stored["likes"].values())[0])
        self.assertIs(list(stored["removed"].values())[0], False)

    def test_date_only_publication_is_normalized(self):
        self.source.payload = document(clips=[entry("c1", published="2024-03-05")])
        self.init()
        self.sync()
        self.assertEqual(self.catalog()["clips"][0]["published"], "2024-03-05T00:00:00")

    def test_unchanged_values_add_no_history(self):
        self.source.payload = document(streams=[entry("s1")])
        self.init()
        self.sync()
        self.sync()
        stored = self.catalog()["streams"][0]
        self.assertEqual(len(stored["title"]), 1)
        self.assertEqual(len(stored["views"]), 1)

    def test_changed_values_append_history_in_order(self):
        self.source.payload = document(episodes=[entry("e1", views=10, likes=1)])
        self.init()
        self.sync()
        self.source.payload = document(episodes=[entry("e1", views=11, likes=None)])
        self.sync()
        stored = self.catalog()["episodes"][0]
        self.assertEqual(list(stored["views"].values()), [10, 11])
        self.assertEqual(list(stored["likes"].values()), [1, None])
        self.assertEqual(sorted(stored["views"]), list(stored["views"]))
        self.assertLess(*sorted(stored["views"]))

    def test_null_to_number_is_a_change(self):
        self.source.payload = document(episodes=[entry("e1", likes=None)])
        self.init()
        self.sync()
        self.source.payload = document(episodes=[entry("e1", likes=7)])
        self.sync()
        self.assertEqual(list(self.catalog()["episodes"][0]["likes"].values()), [None, 7])

    def test_removal_and_restoration(self):
        self.source.payload = document(episodes=[entry("e1"), entry("e2")])
        self.init()
        self.sync()
        self.source.payload = document(episodes=[entry("e1")])
        self.sync()
        self.source.payload = document(episodes=[entry("e1"), entry("e2")])
        self.sync()
        removed = {e["id"]: list(e["removed"].values()) for e in self.catalog()["episodes"]}
        self.assertEqual(removed["e2"], [False, True, False])
        self.assertEqual(removed["e1"], [False])

    def test_entries_are_sorted_by_publication_then_id(self):
        self.source.payload = document(
            episodes=[
                entry("b", published="2024-01-01T00:00:00"),
                entry("a", published="2024-01-01T00:00:00"),
                entry("c", published="2024-05-09T12:00:00"),
            ]
        )
        self.init()
        self.sync()
        self.assertEqual([e["id"] for e in self.catalog()["episodes"]], ["c", "a", "b"])

    def test_sync_timestamps_strictly_increase_within_a_second(self):
        self.source.payload = document(episodes=[entry("e1", views=1)])
        self.init()
        self.sync()
        for views in (2, 3, 4):
            self.source.payload = document(episodes=[entry("e1", views=views)])
            self.sync()
        keys = list(self.catalog()["episodes"][0]["views"])
        self.assertEqual(keys, sorted(set(keys)))
        self.assertEqual(len(keys), 4)

    def test_local_annotations_survive_sync(self):
        self.source.payload = document(clips=[entry("c1")])
        self.init()
        self.sync()
        path = Path(self.workdir.name) / "vault" / "catalog.json"
        catalog = json.loads(path.read_text())
        catalog["clips"][0]["annotations"] = ["keep me"]
        path.write_text(json.dumps(catalog))
        self.sync()
        self.assertEqual(self.catalog()["clips"][0]["annotations"], ["keep me"])


class PersistenceTests(MvaultTestCase):
    def test_backup_holds_the_previous_catalog_bytes(self):
        self.source.payload = document(episodes=[entry("e1", views=1)])
        self.init()
        self.sync()
        vault = Path(self.workdir.name) / "vault"
        before = (vault / "catalog.json").read_bytes()
        self.source.payload = document(episodes=[entry("e1", views=2)])
        self.sync()
        self.assertEqual((vault / "catalog.bak").read_bytes(), before)
        self.assertNotEqual((vault / "catalog.json").read_bytes(), before)


class FailureTests(MvaultTestCase):
    def test_sync_of_missing_vault(self):
        result = self.run_cli("sync", "ghost")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ghost", result.stderr)

    def test_sync_of_invalid_vault(self):
        self.init()
        (Path(self.workdir.name) / "vault" / "catalog.json").write_text("{not json")
        result = self.run_cli("sync", "vault")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vault", result.stderr)

    def test_malformed_entry_fails_and_leaves_vault_unchanged(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.init()
        self.sync()
        before = (Path(self.workdir.name) / "vault" / "catalog.json").read_bytes()
        broken = entry("e2")
        del broken["preview"]
        self.source.payload = document(episodes=[entry("e1"), broken])
        result = self.run_cli("sync", "vault")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source metadata fetch failure", result.stderr)
        self.assertEqual(
            (Path(self.workdir.name) / "vault" / "catalog.json").read_bytes(), before
        )

    def test_wrong_field_type_fails(self):
        self.source.payload = document(streams=[entry("s1", views="many")])
        self.init()
        result = self.run_cli("sync", "vault")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source metadata fetch failure", result.stderr)

    def test_unreachable_source_fails(self):
        result = self.run_cli("init", "dead", "http://127.0.0.1:1/feed.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("sync", "dead")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source metadata fetch failure", result.stderr)


class MigrateTests(MvaultTestCase):
    def test_version_1_catalog_becomes_native(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        result = self.run_cli("migrate", "vault")
        self.assertEqual(result.returncode, 0, result.stderr)
        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual(catalog["source"], "https://media.example.com/channel/alpha")
        self.assertEqual(catalog["streams"], [])
        self.assertEqual(catalog["clips"], [])
        self.assertNotIn("entries", catalog)
        self.assertNotIn("source_id", catalog)
        stored = catalog["episodes"][0]
        self.assertEqual(stored["id"], "e1")
        self.assertEqual(stored["width"], 1920)
        self.assertEqual(list(stored["views"]), EPOCH_TIMESTAMPS)
        self.assertEqual(list(stored["views"].values()), [10, 12])
        self.assertEqual(list(stored["likes"].values()), [None, 3])
        self.assertEqual(list(stored["removed"].values()), [False])
        self.assertEqual(stored["annotations"], [])

    def test_version_2_catalog_keeps_source_and_categories(self):
        self.write_catalog(
            v2_catalog(
                self.source.url,
                episodes=[stored_entry("e1", ISO_KEYS)],
                clips=[stored_entry("c1", ISO_KEYS)],
            )
        )
        result = self.run_cli("migrate", "vault")
        self.assertEqual(result.returncode, 0, result.stderr)
        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual(catalog["source"], self.source.url)
        self.assertEqual([e["id"] for e in catalog["episodes"]], ["e1"])
        self.assertEqual([e["id"] for e in catalog["clips"]], ["c1"])
        self.assertEqual(catalog["streams"], [])
        for stored in (catalog["episodes"][0], catalog["clips"][0]):
            self.assertEqual(list(stored["title"]), list(ISO_KEYS))
            self.assertEqual(list(stored["removed"].values()), [False])
            self.assertEqual(stored["annotations"], [])

    def test_migration_backs_the_legacy_catalog_up(self):
        legacy = v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)])
        self.write_catalog(legacy)
        self.run_cli("migrate", "vault")
        backup = json.loads((self.vault_path() / "catalog.bak").read_text())
        self.assertEqual(backup, legacy)

    def test_native_catalog_is_left_alone(self):
        self.write_catalog({"version": 3, "source": self.source.url, **document()})
        before = (self.vault_path() / "catalog.json").read_bytes()
        result = self.run_cli("migrate", "vault")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.vault_path() / "catalog.json").read_bytes(), before)
        self.assertFalse((self.vault_path() / "catalog.bak").exists())

    def test_migration_is_idempotent(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        self.run_cli("migrate", "vault")
        migrated = (self.vault_path() / "catalog.json").read_bytes()
        result = self.run_cli("migrate", "vault")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.vault_path() / "catalog.json").read_bytes(), migrated)

    def test_migrate_of_missing_vault(self):
        result = self.run_cli("migrate", "ghost")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ghost", result.stderr)


class LegacySyncTests(MvaultTestCase):
    def test_sync_upgrades_a_version_2_vault(self):
        self.write_catalog(
            v2_catalog(self.source.url, episodes=[stored_entry("e1", ISO_KEYS)])
        )
        self.source.payload = document(episodes=[entry("e1", views=20), entry("e2")])
        self.sync()
        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual(catalog["source"], self.source.url)
        stored = {e["id"]: e for e in catalog["episodes"]}
        self.assertEqual(list(stored["e1"]["views"].values()), [10, 12, 20])
        self.assertEqual(list(stored["e1"]["removed"].values()), [False])
        self.assertEqual(stored["e1"]["annotations"], [])
        self.assertEqual(stored["e2"]["annotations"], [])

    def test_sync_backup_holds_the_pre_migration_catalog(self):
        legacy = v2_catalog(self.source.url, episodes=[stored_entry("e1", ISO_KEYS)])
        self.write_catalog(legacy)
        self.source.payload = document(episodes=[entry("e1")])
        self.sync()
        self.assertEqual(json.loads((self.vault_path() / "catalog.bak").read_text()), legacy)


class VersionFailureTests(MvaultTestCase):
    def assert_refused(self, catalog, *expected):
        """A catalog mvault cannot read fails every command and stays put."""
        self.write_catalog(catalog)
        before = (self.vault_path() / "catalog.json").read_bytes()
        for command in ("migrate", "sync"):
            result = self.run_cli(command, "vault")
            self.assertNotEqual(result.returncode, 0)
            for text in ("vault",) + expected:
                self.assertIn(text, result.stderr)
            self.assertEqual((self.vault_path() / "catalog.json").read_bytes(), before)
            self.assertFalse((self.vault_path() / "catalog.bak").exists())

    def test_missing_version(self):
        catalog = v2_catalog(self.source.url)
        del catalog["version"]
        self.assert_refused(catalog, "version")

    def test_non_integer_version(self):
        self.assert_refused({**v2_catalog(self.source.url), "version": "2"}, "version")

    def test_unsupported_future_version(self):
        self.assert_refused({**v2_catalog(self.source.url), "version": 4}, "version")

    def test_malformed_version_1_entry(self):
        broken = stored_entry("e1", EPOCH_KEYS)
        broken["views"] = {"not-a-number": 10}
        self.assert_refused(v1_catalog(entries=[broken]), "entries[0]")

    def test_version_1_entry_with_a_missing_history(self):
        broken = stored_entry("e1", EPOCH_KEYS)
        del broken["preview"]
        self.assert_refused(v1_catalog(entries=[broken]), "preview")

    def test_version_2_entry_with_an_unreadable_key(self):
        broken = stored_entry("e1", ("yesterday", "today"))
        self.assert_refused(v2_catalog(self.source.url, episodes=[broken]), "episodes[0]")


class Version1SyncTests(unittest.TestCase):
    """Sync of a version 1 vault, whose derived source no test can serve.

    The URL derived from ``source_id`` always points at the media platform, so
    these drive ``sync`` in process with the download stubbed out.
    """

    def setUp(self):
        self.workdir = TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.vault = Path(self.workdir.name) / "vault"
        self.vault.mkdir()

    def test_sync_upgrades_the_catalog_and_writes_it_back(self):
        legacy = v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)])
        (self.vault / "catalog.json").write_text(json.dumps(legacy))
        payload = document(episodes=[entry("e1", views=20), entry("e2")])
        with patch("source.fetch", return_value=payload) as fetch:
            vault.sync_vault(str(self.vault))
        fetch.assert_called_once_with("https://media.example.com/channel/alpha")
        catalog = json.loads((self.vault / "catalog.json").read_text())
        self.assertEqual(catalog["version"], 3)
        stored = {e["id"]: e for e in catalog["episodes"]}
        self.assertEqual(list(stored["e1"]["views"])[:2], EPOCH_TIMESTAMPS)
        self.assertEqual(list(stored["e1"]["views"].values()), [10, 12, 20])
        self.assertEqual(list(stored["e1"]["removed"].values()), [False])
        self.assertEqual(stored["e2"]["annotations"], [])
        self.assertEqual(json.loads((self.vault / "catalog.bak").read_text()), legacy)


if __name__ == "__main__":
    unittest.main()
