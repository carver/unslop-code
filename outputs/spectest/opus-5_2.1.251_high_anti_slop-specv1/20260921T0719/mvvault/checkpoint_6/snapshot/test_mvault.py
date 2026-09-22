"""End-to-end tests for the mvault command line."""

import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from html import unescape
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import mvault
import vault
from server import viewer_server

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


def v3_catalog(source, episodes=(), streams=(), clips=()):
    """Build a native catalog out of hand-written entries."""
    return {"version": 3, "source": source, **document(episodes, streams, clips)}


def tracked_entry(identifier, **histories):
    """Build a native entry whose histories hold a single observation each."""
    first = ISO_KEYS[0]
    item = {
        "id": identifier,
        "published": "2024-03-01T10:00:00",
        "width": 1920,
        "height": 1080,
        "title": {first: f"Title {identifier}"},
        "description": {first: "Description"},
        "views": {first: 10},
        "likes": {first: 1},
        "preview": {first: "hash"},
        "removed": {first: False},
        "annotations": [],
    }
    item.update(histories)
    return item


#: Content type each kind of downloadable asset is served with.
ASSET_TYPES = {"media": "video/mp4", "preview": "image/jpeg"}


class SourceServer:
    """Serves the feed payload plus the media and preview files behind it.

    Tests drive it through ``payload``, ``statuses`` (a final HTTP error for
    an asset) and ``failures`` (a number of errors before it starts working),
    and read back every path that was requested from ``requests``.
    """

    def __init__(self):
        self.payload = document()
        self.statuses = {}
        self.failures = {}
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server.requests.append(self.path)
                if self.path.endswith("feed.json"):
                    self.respond(json.dumps(server.payload).encode("utf-8"), "application/json")
                else:
                    self.respond_with_asset("/".join(self.path.split("/")[-2:]))

            def respond_with_asset(self, asset):
                remaining = server.failures.get(asset, 0)
                if remaining:
                    server.failures[asset] = remaining - 1
                    self.send_error(503)
                elif asset in server.statuses:
                    self.send_error(server.statuses[asset])
                else:
                    kind = asset.split("/")[0]
                    self.respond(f"{asset} body".encode("utf-8"), ASSET_TYPES[kind])

            def respond(self, body, content_type):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
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

    def asset_requests(self):
        """The media and preview paths requested, as ``kind/id`` pairs."""
        return ["/".join(path.split("/")[-2:]) for path in self.requests if "feed.json/" in path]


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

    def sync(self, name="vault", *options):
        result = self.run_cli("sync", name, *options)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def files_in(self, directory, name="vault"):
        """Names of the files a vault subdirectory holds, sorted."""
        return sorted(path.name for path in (self.vault_path(name) / directory).glob("*"))

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
        options = vault.SyncOptions(skip_download=True)
        with patch("source.fetch", return_value=payload) as fetch:
            vault.sync_vault(str(self.vault), options)
        fetch.assert_called_once_with("https://media.example.com/channel/alpha")
        catalog = json.loads((self.vault / "catalog.json").read_text())
        self.assertEqual(catalog["version"], 3)
        stored = {e["id"]: e for e in catalog["episodes"]}
        self.assertEqual(list(stored["e1"]["views"])[:2], EPOCH_TIMESTAMPS)
        self.assertEqual(list(stored["e1"]["views"].values()), [10, 12, 20])
        self.assertEqual(list(stored["e1"]["removed"].values()), [False])
        self.assertEqual(stored["e2"]["annotations"], [])
        self.assertEqual(json.loads((self.vault / "catalog.bak").read_text()), legacy)


class DownloadTests(MvaultTestCase):
    def test_sync_downloads_media_and_previews(self):
        self.source.payload = document(episodes=[entry("e1")], clips=[entry("c1")])
        self.init()
        self.sync()
        self.assertEqual(self.files_in("media"), ["c1.mp4", "e1.mp4"])
        self.assertEqual(self.files_in("previews"), ["c1.jpg", "e1.jpg"])
        self.assertEqual(
            (self.vault_path() / "media" / "e1.mp4").read_text(), "media/e1 body"
        )

    def test_media_already_in_the_vault_is_not_fetched_again(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.init()
        self.sync()
        self.source.requests.clear()
        self.sync()
        self.assertEqual(self.source.asset_requests(), [])

    def test_partial_artifact_does_not_block_a_later_download(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.init()
        (self.vault_path() / "media").mkdir()
        (self.vault_path() / "media" / "e1.mp4.part").write_text("stale")
        self.sync()
        self.assertEqual(self.files_in("media"), ["e1.mp4"])
        self.assertEqual((self.vault_path() / "media" / "e1.mp4").read_text(), "media/e1 body")

    def test_limit_takes_the_first_candidates_in_catalog_order(self):
        self.source.payload = document(
            episodes=[
                entry("old", published="2024-01-01T00:00:00"),
                entry("new", published="2024-05-01T00:00:00"),
                entry("mid", published="2024-03-01T00:00:00"),
            ]
        )
        self.init()
        self.sync("vault", "--episodes=2")
        self.assertEqual(self.files_in("media"), ["mid.mp4", "new.mp4"])

    def test_limits_are_independent_per_category(self):
        self.source.payload = document(
            episodes=[entry("e1"), entry("e2")],
            streams=[entry("s1")],
            clips=[entry("c1")],
        )
        self.init()
        self.sync("vault", "--episodes=0", "--streams=1")
        self.assertEqual(self.files_in("media"), ["c1.mp4", "s1.mp4"])

    def test_format_override_names_the_request_and_the_file(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.init()
        self.sync("vault", "--format=mp3")
        self.assertEqual(self.files_in("media"), ["e1.mp3"])
        self.assertIn("media/e1.mp3", self.source.asset_requests())

    def test_skip_download_records_metadata_only(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.init()
        self.sync("vault", "--skip-download")
        self.assertEqual(self.catalog()["episodes"][0]["id"], "e1")
        self.assertFalse((self.vault_path() / "media").exists())
        self.assertEqual(self.source.asset_requests(), [])

    def test_skip_metadata_downloads_against_the_stored_catalog(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.init()
        self.sync("vault", "--skip-download")
        before = (self.vault_path() / "catalog.json").read_bytes()
        self.source.payload = document(episodes=[entry("e1", views=99), entry("e2")])
        self.source.requests.clear()
        self.sync("vault", "--skip-metadata")
        self.assertEqual((self.vault_path() / "catalog.json").read_bytes(), before)
        self.assertEqual(self.files_in("media"), ["e1.mp4"])
        self.assertEqual(self.source.requests, ["/feed.json/media/e1", "/feed.json/preview/e1"])

    def test_legacy_vault_downloads_from_the_migrated_source(self):
        self.write_catalog(v2_catalog(self.source.url, episodes=[stored_entry("e1", ISO_KEYS)]))
        self.source.payload = document(episodes=[entry("e1")])
        self.sync()
        self.assertEqual(self.files_in("media"), ["e1.mp4"])


class DownloadFailureTests(MvaultTestCase):
    def test_missing_content_warns_and_keeps_going(self):
        self.source.payload = document(episodes=[entry("e1"), entry("e2")])
        self.source.statuses["media/e1"] = 404
        self.init()
        result = self.sync()
        self.assertIn("media/e1", result.stderr)
        self.assertEqual(self.files_in("media"), ["e2.mp4"])
        self.assertEqual(self.files_in("previews"), ["e1.jpg", "e2.jpg"])

    def test_missing_content_is_not_retried(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.source.statuses["media/e1"] = 404
        self.init()
        self.sync()
        self.assertEqual(self.source.asset_requests().count("media/e1"), 1)

    def test_transient_failure_is_retried_until_it_succeeds(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.source.failures["media/e1"] = 2
        self.init()
        result = self.sync()
        self.assertEqual(self.files_in("media"), ["e1.mp4"])
        self.assertEqual(result.stderr, "")

    def test_transient_failure_warns_once_retries_run_out(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.source.failures["media/e1"] = 99
        self.init()
        result = self.sync()
        self.assertIn("media/e1", result.stderr)
        self.assertEqual(self.source.asset_requests().count("media/e1"), 3)

    def test_metadata_is_saved_even_when_downloads_fail(self):
        self.source.payload = document(episodes=[entry("e1")])
        self.source.statuses["media/e1"] = 500
        self.source.statuses["preview/e1"] = 500
        self.init()
        result = self.sync()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.catalog()["episodes"][0]["id"], "e1")


class SyncOptionFailureTests(MvaultTestCase):
    def assert_rejected(self, *options):
        """A command line mvault refuses runs no sync at all."""
        self.source.payload = document(episodes=[entry("e1")])
        self.init()
        result = self.run_cli("sync", "vault", *options)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.stderr, "")
        self.assertEqual(self.catalog()["episodes"], [])
        self.assertEqual(self.source.requests, [])

    def test_non_numeric_limit(self):
        self.assert_rejected("--episodes=many")

    def test_negative_limit(self):
        self.assert_rejected("--clips=-1")

    def test_unknown_option(self):
        self.assert_rejected("--everything")


class SyncSummaryTests(MvaultTestCase):
    def test_counts_are_reported_on_stdout(self):
        self.source.payload = document(episodes=[entry("e1"), entry("e2")])
        self.init()
        result = self.sync("vault", "--skip-download")
        self.assertIn("2 added", result.stdout)
        self.source.payload = document(episodes=[entry("e1", views=20)])
        result = self.sync("vault", "--skip-download")
        self.assertIn("0 added", result.stdout)
        self.assertIn("1 removed", result.stdout)
        self.assertIn("1 updated", result.stdout)


#: A third history key, for entries that were observed three times.
LAST_KEY = "2024-06-17T09:40:00"


def changed_catalog(source):
    """A native catalog holding one entry of every kind a digest reports."""
    first, second = ISO_KEYS
    return v3_catalog(
        source,
        episodes=[
            tracked_entry("gone", removed={first: False, second: True}),
            tracked_entry("fresh"),
            tracked_entry("moved", views={first: 10, second: 12}, likes={first: 1, second: 5}),
            tracked_entry(
                "back",
                views={first: 10, second: 11},
                removed={first: False, second: True, LAST_KEY: False},
            ),
            tracked_entry("quiet", views={first: 10, second: 10}),
        ],
        clips=[tracked_entry("c1", title={first: "One", second: "Two"})],
    )


class DigestTests(MvaultTestCase):
    def digest(self, name="vault"):
        result = self.run_cli("digest", name)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_changes_are_grouped_by_category_and_kind(self):
        self.write_catalog(changed_catalog(self.source.url))
        lines = self.digest().splitlines()
        link = "http://127.0.0.1:8840/catalog/vault/episodes"
        self.assertEqual(
            lines[:8],
            [
                "Episodes",
                "  Removed",
                f"    - Title gone {link}/gone",
                "  Added",
                f"    - Title fresh {link}/fresh",
                "  Updated",
                f"    - Title moved (views, likes) {link}/moved",
                f"    - Title back (views, reappeared) {link}/back",
            ],
        )

    def test_updated_title_is_the_current_one(self):
        self.write_catalog(changed_catalog(self.source.url))
        self.assertIn("    - Two (title)", self.digest())

    def test_unchanged_entries_and_empty_categories_are_omitted(self):
        output = self.digest_of(changed_catalog(self.source.url))
        self.assertNotIn("quiet", output)
        self.assertNotIn("Streams", output)

    def digest_of(self, catalog):
        """Write a catalog of any version and return the digest of it."""
        self.write_catalog(catalog)
        return self.digest()

    def test_trailing_line_names_the_vault_and_its_source(self):
        output = self.digest_of(changed_catalog(self.source.url))
        self.assertEqual(
            output.splitlines()[-1].split(" at ")[0],
            f"Digest of vault 'vault' (catalog version 3) from {self.source.url}",
        )

    def test_empty_vault_reports_nothing_notable(self):
        self.init()
        self.assertIn("No notable changes found.", self.digest())

    def test_digest_never_writes_to_the_vault(self):
        self.write_catalog(changed_catalog(self.source.url))
        before = (self.vault_path() / "catalog.json").read_bytes()
        self.digest()
        self.assertEqual((self.vault_path() / "catalog.json").read_bytes(), before)
        self.assertFalse((self.vault_path() / "catalog.bak").exists())

    def test_version_2_vault_is_digested_without_migration(self):
        output = self.digest_of(
            v2_catalog(
                self.source.url,
                episodes=[stored_entry("e1", ISO_KEYS)],
                clips=[{**stored_entry("c1", ISO_KEYS), "views": {ISO_KEYS[0]: 10}}],
            )
        )
        self.assertIn("Episodes", output)
        self.assertIn("    - Retitled e1 (title, views, likes)", output)
        self.assertNotIn("Removed", output)
        self.assertIn("(catalog version 2)", output)
        self.assertIn(self.source.url, output)

    def test_version_1_vault_groups_every_entry_together(self):
        output = self.digest_of(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        self.assertEqual(output.splitlines()[0], "Entries")
        self.assertNotIn("Episodes", output)
        self.assertIn("https://media.example.com/channel/alpha", output)

    def test_version_1_history_keys_order_numerically(self):
        old, new = "999999999", EPOCH_KEYS[0]
        entry_with_old_key = stored_entry("e1", (old, new))
        output = self.digest_of(v1_catalog(entries=[entry_with_old_key]))
        self.assertIn("    - Retitled e1 (title, views, likes)", output)

    def test_missing_vault_is_reported(self):
        result = self.run_cli("digest", "ghost")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ghost", result.stderr)

    def test_unsupported_version_is_reported(self):
        self.write_catalog({**v2_catalog(self.source.url), "version": 9})
        result = self.run_cli("digest", "vault")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("9", result.stderr)

    def test_digest_follows_a_sync(self):
        self.source.payload = document(episodes=[entry("e1", views=10)])
        self.init()
        self.sync("vault", "--skip-download")
        self.source.payload = document(episodes=[entry("e1", views=25)])
        self.sync("vault", "--skip-download")
        self.assertIn("    - Title e1 (views)", self.digest())


class StubbornRedirects(urllib.request.HTTPRedirectHandler):
    """Leaves a redirect to the caller instead of following it."""

    def redirect_request(self, *args):
        return None


class ViewerTests(MvaultTestCase):
    """Drives the viewer over HTTP, against vaults of every version."""

    def setUp(self):
        super().setUp()
        self.opener = urllib.request.build_opener(StubbornRedirects)
        self.address = self.start_viewer()

    def start_viewer(self):
        """Serve the work directory on a port the system picks."""
        server = viewer_server(Path(self.workdir.name), "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def request(self, path, data=None, method=None):
        """Perform one request and return its status, target and body."""
        call = urllib.request.Request(self.address + path, data=data, method=method)
        try:
            with self.opener.open(call) as response:
                return response.status, "", response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Location", ""), error.read().decode("utf-8")

    def status_of(self, path):
        return self.request(path)[0]

    def redirect_of(self, path, data=None):
        """The target of a redirect, which must be one of the two allowed."""
        status, location, _ = self.request(path, data)
        self.assertIn(status, (302, 303))
        return location

    def body_of(self, path):
        status, _, body = self.request(path)
        self.assertEqual(status, 200)
        return body

    def entry_item(self, body, identifier):
        """The list item the listing page devotes to one entry."""
        items = [item for item in body.split("<li ") if f"id='{identifier}'" in item]
        self.assertEqual(len(items), 1, body)
        return items[0]

    def fetch(self, path):
        """One request for a stored file: its status, content type and bytes."""
        try:
            with self.opener.open(self.address + path) as response:
                return response.status, response.headers.get("Content-Type", ""), response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Content-Type", ""), error.read()

    def chart_data(self, body):
        """The chart points a detail page embeds, read back out of its HTML."""
        opening = body.index(">", body.index("id='chart-data'")) + 1
        return json.loads(body[opening : body.index("</script>", opening)])

    def store(self, directory, filename, content="asset"):
        """Put one downloaded file in a subdirectory of the default vault."""
        path = self.vault_path() / directory
        path.mkdir(exist_ok=True)
        (path / filename).write_text(content)


class LandingPageTests(ViewerTests):
    def test_landing_page_offers_a_vault_name_input(self):
        body = self.body_of("/")
        self.assertIn("name='catalog'", body)
        self.assertIn("method='post'", body)

    def test_form_submission_opens_the_named_vault(self):
        self.assertEqual(self.redirect_of("/", b"catalog=vault"), "/catalog/vault")

    def test_form_submission_without_a_vault_comes_back(self):
        self.assertEqual(self.redirect_of("/", b"other=vault"), "/")

    def test_visited_vaults_are_listed_most_recent_first(self):
        self.write_catalog(v3_catalog(self.source.url), name="first")
        self.write_catalog(v1_catalog(), name="second")
        self.request("/catalog/first")
        self.request("/catalog/second")
        body = self.body_of("/")
        self.assertLess(
            body.index("/catalog/second/entries"), body.index("/catalog/first/episodes")
        )

    def test_visits_outlive_the_server_that_recorded_them(self):
        self.write_catalog(v3_catalog(self.source.url))
        self.request("/catalog/vault")
        self.address = self.start_viewer()
        self.assertIn("/catalog/vault/episodes", self.body_of("/"))

    def test_landing_page_without_visits_lists_nothing(self):
        self.assertNotIn("<ul class='recent'>", self.body_of("/"))


class CatalogRouteTests(ViewerTests):
    def test_version_3_vault_opens_on_its_episodes(self):
        self.write_catalog(v3_catalog(self.source.url))
        self.assertEqual(self.redirect_of("/catalog/vault"), "/catalog/vault/episodes")

    def test_version_2_vault_opens_on_its_episodes(self):
        self.write_catalog(v2_catalog(self.source.url))
        self.assertEqual(self.redirect_of("/catalog/vault"), "/catalog/vault/episodes")

    def test_version_1_vault_opens_on_its_entries(self):
        self.write_catalog(v1_catalog())
        self.assertEqual(self.redirect_of("/catalog/vault"), "/catalog/vault/entries")

    def test_categories_of_a_version_3_vault(self):
        self.write_catalog(v3_catalog(self.source.url))
        for category in ("episodes", "streams", "clips"):
            self.assertEqual(self.status_of(f"/catalog/vault/{category}"), 200)

    def test_version_1_vault_knows_only_its_entries(self):
        self.write_catalog(v1_catalog())
        self.assertEqual(self.status_of("/catalog/vault/entries"), 200)
        self.assertEqual(self.redirect_of("/catalog/vault/episodes"), "/catalog/vault/entries")

    def test_unknown_category_opens_the_default_one(self):
        self.write_catalog(v3_catalog(self.source.url))
        self.assertEqual(self.redirect_of("/catalog/vault/Episodes"), "/catalog/vault/episodes")
        self.assertEqual(self.redirect_of("/catalog/vault/movies"), "/catalog/vault/episodes")

    def test_entry_route_serves_a_page_of_its_own(self):
        self.write_catalog(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))
        body = self.body_of("/catalog/vault/episodes/e1")
        self.assertIn("Back to episodes", body)
        self.assertNotIn("<ol class='entries'>", body)

    def test_unknown_vault_goes_back_to_the_landing_page(self):
        location = self.redirect_of("/catalog/ghost")
        self.assertTrue(location.startswith("/?"), location)
        self.assertIn("ghost", self.body_of(location))

    def test_unreadable_vault_is_not_a_server_error(self):
        self.write_catalog({**v3_catalog(self.source.url), "version": 9})
        for path in ("/catalog/vault", "/catalog/vault/episodes", "/catalog/vault/episodes/e1"):
            self.assertEqual(self.redirect_of(path), "/?missing=vault")

    def test_unknown_path_is_refused_without_a_traceback(self):
        status, _, body = self.request("/elsewhere")
        self.assertEqual(status, 404)
        self.assertIn("<html", body)
        self.assertNotIn("Traceback", body)


class ListingPageTests(ViewerTests):
    def listing(self, catalog, category="episodes"):
        """Write a catalog of any version and read its category listing."""
        self.write_catalog(catalog)
        return self.body_of(f"/catalog/vault/{category}")

    def test_entries_are_listed_in_catalog_order_with_links(self):
        body = self.listing(
            v3_catalog(
                self.source.url,
                episodes=[tracked_entry("e2"), tracked_entry("e1")],
            )
        )
        self.assertLess(body.index("Title e2"), body.index("Title e1"))
        self.assertIn("href='/catalog/vault/episodes/e1'", body)

    def test_current_title_is_the_latest_one(self):
        first, second = ISO_KEYS
        body = self.listing(
            v3_catalog(
                self.source.url,
                episodes=[tracked_entry("e1", title={first: "Old", second: "New"})],
            )
        )
        self.assertIn("New", self.entry_item(body, "e1"))
        self.assertNotIn("Old", self.entry_item(body, "e1"))

    def test_version_1_titles_order_by_their_epoch_keys(self):
        old, new = "999999999", EPOCH_KEYS[0]
        body = self.listing(
            v1_catalog(entries=[stored_entry("e1", (old, new))]), category="entries"
        )
        self.assertIn("Retitled e1", self.entry_item(body, "e1"))

    def test_downloaded_entries_are_distinguished(self):
        catalog = v3_catalog(
            self.source.url, episodes=[tracked_entry("e1"), tracked_entry("e2")]
        )
        self.write_catalog(catalog)
        (self.vault_path() / "media").mkdir()
        (self.vault_path() / "media" / "e1.mp4").write_text("held")
        body = self.body_of("/catalog/vault/episodes")
        self.assertIn("downloaded", self.entry_item(body, "e1"))
        self.assertIn("undownloaded", self.entry_item(body, "e2"))

    def test_removed_entries_are_distinguished(self):
        first, second = ISO_KEYS
        body = self.listing(
            v3_catalog(
                self.source.url,
                episodes=[
                    tracked_entry("gone", removed={first: False, second: True}),
                    tracked_entry("here"),
                ],
            )
        )
        self.assertIn("removed", self.entry_item(body, "gone"))
        self.assertNotIn("removed", self.entry_item(body, "here"))

    def test_version_2_entries_are_never_removed(self):
        body = self.listing(
            v2_catalog(self.source.url, episodes=[stored_entry("e1", ISO_KEYS)])
        )
        self.assertNotIn("removed", self.entry_item(body, "e1"))


class DetailPageTests(ViewerTests):
    """The page one entry has of its own, in a vault of any version."""

    def detail(self, catalog, path="/catalog/vault/episodes/e1"):
        """Write a catalog of any version and read one entry's detail page."""
        self.write_catalog(catalog)
        return self.body_of(path)

    def test_current_title_and_description_are_the_latest_ones(self):
        first, second = ISO_KEYS
        body = self.detail(
            v3_catalog(
                self.source.url,
                episodes=[
                    tracked_entry(
                        "e1",
                        title={first: "Old title", second: "New title"},
                        description={first: "Old words", second: "New words"},
                    )
                ],
            )
        )
        self.assertIn("New title", body)
        self.assertNotIn("Old title", body)
        self.assertIn("New words", body)
        self.assertNotIn("Old words", body)

    def test_publication_and_dimensions_are_shown(self):
        body = self.detail(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))
        self.assertIn("2024-03-01T10:00:00", body)
        self.assertIn("1920", body)
        self.assertIn("1080", body)

    def test_page_links_back_to_the_category_listing(self):
        body = self.detail(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))
        self.assertIn("href='/catalog/vault/episodes'", body)

    def test_source_link_of_a_version_3_vault_names_the_entry(self):
        body = self.detail(
            v3_catalog("https://media.example.com/feed", episodes=[tracked_entry("e1")])
        )
        self.assertIn("https://media.example.com/feed/entry/e1", body)

    def test_source_link_of_a_version_2_vault_names_the_entry(self):
        body = self.detail(
            v2_catalog("https://media.example.com/feed", episodes=[stored_entry("e1", ISO_KEYS)])
        )
        self.assertIn("https://media.example.com/feed/entry/e1", body)

    def test_source_link_of_a_version_1_vault_names_its_platform(self):
        body = self.detail(
            v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]), "/catalog/vault/entries/e1"
        )
        self.assertIn("https://media.example.com/channel/alpha/entry/e1", body)

    def test_downloaded_media_is_played_under_its_stored_filename(self):
        self.write_catalog(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))
        self.store("media", "e1.webm")
        body = self.body_of("/catalog/vault/episodes/e1")
        self.assertIn("src='/vault/vault/media/e1.webm'", body)
        self.assertIn("<span class='badge downloaded'>", body)

    def test_media_of_another_entry_is_not_played(self):
        self.write_catalog(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))
        self.store("media", "e2.mp4")
        self.assertNotIn("<video", self.body_of("/catalog/vault/episodes/e1"))

    def test_entry_without_media_keeps_its_metadata_and_charts(self):
        first, second = ISO_KEYS
        body = self.detail(
            v3_catalog(
                self.source.url,
                episodes=[tracked_entry("e1", views={first: 10, second: 20})],
            )
        )
        self.assertNotIn("<video", body)
        self.assertIn("2024-03-01T10:00:00", body)
        self.assertEqual([point["value"] for point in self.chart_data(body)["views"]], [10, 20])

    def test_lookup_stays_inside_the_named_category(self):
        self.write_catalog(
            v3_catalog(
                self.source.url, episodes=[tracked_entry("e1")], clips=[tracked_entry("c1")]
            )
        )
        self.assertEqual(self.status_of("/catalog/vault/episodes/c1"), 404)
        self.assertEqual(self.status_of("/catalog/vault/clips/c1"), 200)

    def test_the_same_identifier_in_two_categories_resolves_per_category(self):
        first = ISO_KEYS[0]
        self.write_catalog(
            v3_catalog(
                self.source.url,
                episodes=[tracked_entry("same", title={first: "Episode side"})],
                clips=[tracked_entry("same", title={first: "Clip side"})],
            )
        )
        self.assertIn("Episode side", self.body_of("/catalog/vault/episodes/same"))
        self.assertIn("Clip side", self.body_of("/catalog/vault/clips/same"))

    def test_removed_entries_are_still_readable(self):
        first, second = ISO_KEYS
        body = self.detail(
            v3_catalog(
                self.source.url,
                episodes=[tracked_entry("e1", removed={first: False, second: True})],
            )
        )
        self.assertIn("Title e1", body)
        self.assertIn("<span class='badge removed'>", body)

    def test_version_1_entry_is_looked_up_among_its_entries(self):
        body = self.detail(
            v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]), "/catalog/vault/entries/e1"
        )
        self.assertIn("Retitled e1", body)

    def test_version_2_entry_is_looked_up_in_its_category(self):
        body = self.detail(
            v2_catalog(self.source.url, clips=[stored_entry("c1", ISO_KEYS)]),
            "/catalog/vault/clips/c1",
        )
        self.assertIn("Retitled c1", body)

    def test_unknown_entry_is_refused_without_a_traceback(self):
        self.write_catalog(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))
        status, _, body = self.request("/catalog/vault/episodes/ghost")
        self.assertEqual(status, 404)
        self.assertIn("<html", body)
        self.assertNotIn("Traceback", body)

    def test_unknown_vault_goes_back_to_the_landing_page(self):
        self.assertEqual(self.redirect_of("/catalog/ghost/episodes/e1"), "/?missing=ghost")

    def test_unknown_category_opens_the_default_one(self):
        self.write_catalog(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))
        self.assertEqual(self.redirect_of("/catalog/vault/movies/e1"), "/catalog/vault/episodes")


class ChartDataTests(ViewerTests):
    """The views and likes points a detail page embeds for its charts."""

    def points(self, catalog, path="/catalog/vault/episodes/e1"):
        """Write a catalog of any version and read back its chart points."""
        self.write_catalog(catalog)
        return self.chart_data(self.body_of(path))

    def test_both_fields_are_embedded_oldest_first(self):
        first, second = ISO_KEYS
        data = self.points(
            v3_catalog(
                self.source.url,
                episodes=[
                    tracked_entry(
                        "e1", views={second: 20, first: 10}, likes={second: 4, first: 1}
                    )
                ],
            )
        )
        self.assertEqual([point["timestamp"] for point in data["views"]], [first, second])
        self.assertEqual([point["value"] for point in data["views"]], [10, 20])
        self.assertEqual([point["value"] for point in data["likes"]], [1, 4])

    def test_unreported_likes_stay_null(self):
        first, second = ISO_KEYS
        data = self.points(
            v3_catalog(
                self.source.url,
                episodes=[tracked_entry("e1", likes={first: None, second: 3})],
            )
        )
        self.assertEqual([point["value"] for point in data["likes"]], [None, 3])

    def test_version_2_keys_are_passed_through(self):
        data = self.points(v2_catalog(self.source.url, episodes=[stored_entry("e1", ISO_KEYS)]))
        self.assertEqual([point["timestamp"] for point in data["views"]], list(ISO_KEYS))

    def test_version_1_epoch_keys_become_iso_timestamps(self):
        data = self.points(
            v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]), "/catalog/vault/entries/e1"
        )
        self.assertEqual([point["timestamp"] for point in data["views"]], EPOCH_TIMESTAMPS)

    def test_version_1_keys_order_numerically_not_lexicographically(self):
        older, newer = "999999999", EPOCH_KEYS[0]
        data = self.points(
            v1_catalog(entries=[stored_entry("e1", (older, newer))]),
            "/catalog/vault/entries/e1",
        )
        self.assertEqual(
            [point["timestamp"] for point in data["views"]],
            ["2001-09-09T01:46:39", EPOCH_TIMESTAMPS[0]],
        )
        self.assertEqual([point["value"] for point in data["views"]], [10, 12])

    def test_a_field_observed_once_has_no_chart(self):
        first, second = ISO_KEYS
        data = self.points(
            v3_catalog(
                self.source.url,
                episodes=[tracked_entry("e1", views={first: 10, second: 20})],
            )
        )
        self.assertIn("views", data)
        self.assertNotIn("likes", data)

    def test_an_entry_observed_once_keeps_its_metadata(self):
        self.write_catalog(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))
        body = self.body_of("/catalog/vault/episodes/e1")
        self.assertNotIn("chart-data", body)
        self.assertIn("Title e1", body)
        self.assertIn("Description", body)
        self.assertIn("2024-03-01T10:00:00", body)
        self.assertIn("1920", body)
        self.assertIn("/entry/e1", body)


class VaultFileTests(ViewerTests):
    """The media and preview files the viewer serves straight off a vault."""

    def setUp(self):
        super().setUp()
        self.write_catalog(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))

    def test_media_is_served_under_a_media_type(self):
        self.store("media", "e1.mp4", "movie bytes")
        status, content_type, body = self.fetch("/vault/vault/media/e1.mp4")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("video/"), content_type)
        self.assertEqual(body, b"movie bytes")

    def test_preview_is_served_for_the_entry_its_name_holds(self):
        self.store("previews", "e1.jpg", "image bytes")
        status, content_type, body = self.fetch("/vault/vault/preview/e1")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("image/"), content_type)
        self.assertEqual(body, b"image bytes")

    def test_detail_page_shows_the_preview_it_can_serve(self):
        self.store("previews", "e1.jpg")
        self.assertIn("src='/vault/vault/preview/e1'", self.body_of("/catalog/vault/episodes/e1"))

    def test_partial_download_is_not_served(self):
        self.store("previews", "e1.jpg.part")
        self.assertEqual(self.fetch("/vault/vault/preview/e1")[0], 404)

    def test_files_the_vault_does_not_hold_are_not_found(self):
        self.assertEqual(self.fetch("/vault/vault/media/e1.mp4")[0], 404)
        self.assertEqual(self.fetch("/vault/vault/preview/e1")[0], 404)

    def test_traversal_cannot_reach_outside_the_served_directories(self):
        (Path(self.workdir.name) / "secret.txt").write_text("private")
        for path in (
            "/vault/vault/media/../../secret.txt",
            "/vault/vault/media/%2e%2e%2f%2e%2e%2fsecret.txt",
            "/vault/vault/preview/..%2f..%2fsecret.txt",
            "/vault/vault/media/%2fetc%2fpasswd",
            "/vault/vault/media/..",
        ):
            status, _, body = self.fetch(path)
            self.assertIn(status, (403, 404), path)
            self.assertNotIn(b"private", body)

    def test_unknown_vault_goes_back_to_the_landing_page(self):
        self.assertEqual(self.redirect_of("/vault/ghost/media/e1.mp4"), "/?missing=ghost")

    def test_a_kind_of_file_the_viewer_does_not_serve_is_not_found(self):
        self.store("media", "e1.mp4")
        self.assertEqual(self.fetch("/vault/vault/catalog.json/e1")[0], 404)
        self.assertEqual(self.fetch("/vault/vault/media")[0], 404)

class AnnotationTests(ViewerTests):
    """Writes annotations to a native vault over its entry detail route."""

    ENTRY = "/catalog/vault/episodes/e1"

    def setUp(self):
        super().setUp()
        self.write_catalog(v3_catalog(self.source.url, episodes=[tracked_entry("e1")]))

    def send(self, method, payload, path=ENTRY):
        """Send one annotation request and return its status and target."""
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        status, location, page = self.request(path, body, method)
        return status, location, page

    def annotate(self, **payload):
        """Create one annotation, returning where the visitor was sent."""
        status, location, _ = self.send("POST", payload)
        self.assertEqual(status, 303)
        return location

    def stored(self, category="episodes"):
        """The annotations the catalog holds for the entry under test."""
        return self.catalog()[category][0]["annotations"]

    def refusal(self, method, payload):
        """The status and body of a request the viewer does not serve."""
        status, _, page = self.send(method, payload)
        self.assertIn("<html", page)
        self.assertNotIn("Traceback", page)
        return status, unescape(page)

    def test_created_annotation_holds_every_field(self):
        self.annotate(title="Intro", timecode="1:30", body="Says hello")
        [annotation] = self.stored()
        self.assertEqual(annotation["timecode"], 90)
        self.assertEqual(annotation["title"], "Intro")
        self.assertEqual(annotation["body"], "Says hello")
        self.assertIsInstance(annotation["id"], str)

    def test_body_defaults_to_null(self):
        self.annotate(title="Intro", timecode="0")
        self.assertIsNone(self.stored()[0]["body"])

    def test_annotations_keep_creation_order(self):
        for title in ("first", "second", "third"):
            self.annotate(title=title, timecode="0")
        titles = [note["title"] for note in self.stored()]
        self.assertEqual(titles, ["first", "second", "third"])

    def test_identifiers_are_unique_within_the_entry(self):
        for title in ("first", "second"):
            self.annotate(title=title, timecode="0")
        self.assertEqual(len({note["id"] for note in self.stored()}), 2)

    def test_creation_redirects_to_the_second_it_marks(self):
        location = self.annotate(title="Intro", timecode="1:01:30")
        self.assertEqual(location, "/catalog/vault/episodes/e1?timecode=3690")

    def test_timecode_formats_are_read_as_whole_seconds(self):
        for timecode, seconds in (("90", 90), ("1:30", 90), ("1:01:30", 3690), ("90:00", 5400)):
            with self.subTest(timecode=timecode):
                self.assertEqual(
                    self.annotate(title="Intro", timecode=timecode),
                    f"/catalog/vault/episodes/e1?timecode={seconds}",
                )

    def test_leading_zeros_are_allowed(self):
        location = self.annotate(title="Intro", timecode="00:07")
        self.assertEqual(location, f"{self.ENTRY}?timecode=7")

    def test_stored_annotations_are_rendered_with_raw_seconds(self):
        self.annotate(title="Intro", timecode="90:00", body="Says hello")
        body = self.body_of(self.ENTRY)
        self.assertIn(">5400</a>", body)
        self.assertIn("Intro", body)
        self.assertIn("Says hello", body)

    def test_update_replaces_only_the_fields_it_carries(self):
        self.annotate(title="Intro", timecode="1:30", body="Says hello")
        identifier = self.stored()[0]["id"]
        status, location, _ = self.send("PATCH", {"id": identifier, "title": "Opening"})
        self.assertEqual((status, location), (303, self.ENTRY))
        self.assertEqual(
            self.stored()[0],
            {"id": identifier, "timecode": 90, "title": "Opening", "body": "Says hello"},
        )

    def test_update_can_replace_the_body_alone(self):
        self.annotate(title="Intro", timecode="1:30")
        identifier = self.stored()[0]["id"]
        self.send("PATCH", {"id": identifier, "body": "Later"})
        self.assertEqual(self.stored()[0]["title"], "Intro")
        self.assertEqual(self.stored()[0]["body"], "Later")

    def test_delete_drops_only_the_annotation_it_names(self):
        for title in ("first", "second"):
            self.annotate(title=title, timecode="0")
        status, location, _ = self.send("DELETE", {"id": self.stored()[0]["id"]})
        self.assertEqual((status, location), (303, self.ENTRY))
        self.assertEqual([note["title"] for note in self.stored()], ["second"])

    def test_deleted_annotation_is_gone_from_the_page(self):
        self.annotate(title="Intro", timecode="0")
        self.send("DELETE", {"id": self.stored()[0]["id"]})
        self.assertNotIn("Intro", self.body_of(self.ENTRY))

    def test_backup_holds_the_catalog_from_before_the_annotation(self):
        self.annotate(title="Intro", timecode="0")
        backup = json.loads((self.vault_path() / "catalog.bak").read_text())
        self.assertEqual(backup["episodes"][0]["annotations"], [])

    def test_missing_title_names_the_field_it_needs(self):
        status, page = self.refusal("POST", {"timecode": "90"})
        self.assertEqual(status, 400)
        self.assertIn("title", page)

    def test_missing_timecode_names_the_field_it_needs(self):
        status, page = self.refusal("POST", {"title": "Intro"})
        self.assertEqual(status, 400)
        self.assertIn("timecode", page)

    def test_invalid_timecodes_are_refused(self):
        for timecode in ("", "1:30:00:00", "-5", "1:", "a:b", "1.5", " 90"):
            with self.subTest(timecode=timecode):
                status, page = self.refusal("POST", {"title": "Intro", "timecode": timecode})
                self.assertEqual(status, 400)
                self.assertIn("timecode", page)

    def test_update_without_an_identifier_is_refused(self):
        status, page = self.refusal("PATCH", {"title": "Opening"})
        self.assertEqual(status, 400)
        self.assertIn("'id'", page)

    def test_delete_without_an_identifier_is_refused(self):
        status, page = self.refusal("DELETE", {})
        self.assertEqual(status, 400)
        self.assertIn("'id'", page)

    def test_unknown_annotation_is_not_found(self):
        for method in ("PATCH", "DELETE"):
            with self.subTest(method=method):
                status, _ = self.refusal(method, {"id": "ghost", "title": "Opening"})
                self.assertEqual(status, 404)

    def test_malformed_body_is_refused(self):
        for body in (b"{not json", b"", b'"a string"'):
            with self.subTest(body=body):
                self.assertEqual(self.refusal("POST", body)[0], 400)

    def test_annotating_an_unknown_entry_is_not_found(self):
        note = {"title": "Intro", "timecode": "0"}
        status, _, _ = self.send("POST", note, "/catalog/vault/episodes/ghost")
        self.assertEqual(status, 404)

    def test_annotating_an_unknown_category_is_not_found(self):
        note = {"title": "Intro", "timecode": "0"}
        status, _, _ = self.send("POST", note, "/catalog/vault/movies/e1")
        self.assertEqual(status, 404)

    def test_annotating_an_unknown_vault_goes_back_to_the_landing_page(self):
        note = {"title": "Intro", "timecode": "0"}
        status, location, _ = self.send("POST", note, "/catalog/ghost/episodes/e1")
        self.assertEqual((status, location), (303, "/?missing=ghost"))

    def test_a_path_that_is_not_an_entry_carries_no_annotations(self):
        for path in ("/catalog/vault/episodes", "/", "/vault/vault/media/e1.mp4"):
            with self.subTest(path=path):
                self.assertEqual(self.send("PATCH", {"id": "x"}, path)[0], 404)

    def test_a_refused_annotation_writes_nothing(self):
        self.refusal("POST", {"title": "Intro", "timecode": "noon"})
        self.assertEqual(self.stored(), [])
        self.assertFalse((self.vault_path() / "catalog.bak").exists())


class AnnotationMigrationTests(ViewerTests):
    """Annotating a legacy vault, which upgrades it before it is written."""

    def send(self, path, method, payload):
        """Send one annotation request and return its status and target."""
        status, location, _ = self.request(path, json.dumps(payload).encode(), method)
        return status, location

    def create(self, path, **payload):
        """Create one annotation, returning where the visitor was sent."""
        status, location = self.send(path, "POST", payload)
        self.assertEqual(status, 303)
        return location

    def test_version_1_vault_is_annotated_under_its_own_category(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        location = self.create("/catalog/vault/entries/e1", title="Intro", timecode="1:30")
        self.assertEqual(location, "/catalog/vault/episodes/e1?timecode=90")

    def test_version_1_entry_moves_to_the_episodes_it_is_annotated_in(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        self.create("/catalog/vault/entries/e1", title="Intro", timecode="0")
        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual(catalog["source"], "https://media.example.com/channel/alpha")
        self.assertEqual(list(catalog["episodes"][0]["title"]), EPOCH_TIMESTAMPS)
        self.assertEqual(catalog["episodes"][0]["annotations"][0]["title"], "Intro")

    def test_migration_added_removals_share_one_timestamp(self):
        entries = [stored_entry("e1", EPOCH_KEYS), stored_entry("e2", EPOCH_KEYS)]
        self.write_catalog(v1_catalog(entries=entries))
        self.create("/catalog/vault/entries/e1", title="Intro", timecode="0")
        moments = {tuple(entry["removed"]) for entry in self.catalog()["episodes"]}
        self.assertEqual(len(moments), 1)

    def test_backup_holds_the_catalog_from_before_the_migration(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        self.create("/catalog/vault/entries/e1", title="Intro", timecode="0")
        backup = json.loads((self.vault_path() / "catalog.bak").read_text())
        self.assertEqual(backup, v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))

    def test_the_retired_version_1_route_leads_to_the_migrated_one(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        self.create("/catalog/vault/entries/e1", title="Intro", timecode="0")
        status, location, _ = self.request("/catalog/vault/entries/e1")
        self.assertIn(status, (303, 404))
        if status == 303:
            self.assertEqual(location, "/catalog/vault/episodes")
        self.assertIn("Intro", self.body_of("/catalog/vault/episodes/e1"))

    def test_a_migrated_annotation_can_be_updated_and_deleted(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        self.create("/catalog/vault/entries/e1", title="Intro", timecode="0")
        entry = "/catalog/vault/episodes/e1"
        identifier = self.catalog()["episodes"][0]["annotations"][0]["id"]
        rewritten = self.send(entry, "PATCH", {"id": identifier, "title": "Opening"})
        self.assertEqual(rewritten, (303, entry))
        self.assertEqual(self.catalog()["episodes"][0]["annotations"][0]["title"], "Opening")
        self.assertEqual(self.send(entry, "DELETE", {"id": identifier}), (303, entry))
        self.assertEqual(self.catalog()["episodes"][0]["annotations"], [])

    def test_version_2_vault_is_annotated_in_the_category_it_names(self):
        self.write_catalog(v2_catalog(self.source.url, clips=[stored_entry("c1", ISO_KEYS)]))
        location = self.create("/catalog/vault/clips/c1", title="Intro", timecode="2:00")
        self.assertEqual(location, "/catalog/vault/clips/c1?timecode=120")
        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual(catalog["clips"][0]["annotations"][0]["timecode"], 120)
        self.assertEqual(list(catalog["clips"][0]["removed"].values()), [False])

    def test_version_1_entries_are_no_longer_annotated_after_migrating(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        self.create("/catalog/vault/entries/e1", title="Intro", timecode="0")
        note = {"title": "Again", "timecode": "0"}
        status, _ = self.send("/catalog/vault/entries/e1", "POST", note)
        self.assertEqual(status, 404)

    def test_a_catalog_that_cannot_be_migrated_is_left_alone(self):
        broken = stored_entry("e2", EPOCH_KEYS, views="not a history")
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS), broken]))
        before = (self.vault_path() / "catalog.json").read_text()
        status, _, page = self.request(
            "/catalog/vault/entries/e1",
            json.dumps({"title": "Intro", "timecode": "0"}).encode(),
            "POST",
        )
        self.assertEqual(status, 500)
        self.assertIn("<html", page)
        self.assertNotIn("Traceback", page)
        self.assertEqual((self.vault_path() / "catalog.json").read_text(), before)
        self.assertFalse((self.vault_path() / "catalog.bak").exists())


class ServeCommandTests(MvaultTestCase):
    def serve(self, *options):
        """Run ``serve`` in the work directory and return the URL it opens."""
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.workdir.name)
        with patch("webbrowser.open") as browser:
            with patch.object(ThreadingHTTPServer, "serve_forever"):
                self.assertEqual(mvault.main(["serve", *options]), 0)
        return browser.call_args.args[0]

    def test_without_a_vault_the_browser_opens_the_landing_page(self):
        url = self.serve("--port=0")
        self.assertTrue(url.startswith("http://127.0.0.1:"), url)
        self.assertTrue(url.endswith("/"), url)

    def test_the_browser_url_uses_the_host_it_was_given(self):
        url = self.serve("--host=localhost", "--port=0")
        self.assertTrue(url.startswith("http://localhost:"), url)

    def test_a_named_vault_opens_on_its_default_category(self):
        self.write_catalog(v1_catalog())
        self.assertTrue(self.serve("vault", "--port=0").endswith("/catalog/vault/entries"))

    def test_a_named_version_3_vault_opens_on_its_episodes(self):
        self.write_catalog(v3_catalog(self.source.url))
        self.assertTrue(self.serve("vault", "--port=0").endswith("/catalog/vault/episodes"))

    def test_a_busy_address_is_reported(self):
        server = viewer_server(Path(self.workdir.name), "127.0.0.1", 0)
        self.addCleanup(server.server_close)
        result = self.run_cli("serve", f"--port={server.server_address[1]}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot serve the viewer", result.stderr)


class ViewerLinkTests(MvaultTestCase):
    def test_digest_links_name_the_category_of_each_entry(self):
        self.write_catalog(changed_catalog(self.source.url))
        output = self.run_cli("digest", "vault").stdout
        self.assertIn("http://127.0.0.1:8840/catalog/vault/episodes/gone", output)
        self.assertIn("http://127.0.0.1:8840/catalog/vault/clips/c1", output)

    def test_digest_links_of_a_version_1_vault_name_its_entries(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        output = self.run_cli("digest", "vault").stdout
        self.assertIn("Retitled e1 (title, views, likes) ", output)
        self.assertIn("http://127.0.0.1:8840/catalog/vault/entries/e1", output)

    def test_sync_links_every_entry_it_touched(self):
        self.source.payload = document(episodes=[entry("e1")], clips=[entry("c1")])
        self.init()
        output = self.sync("vault", "--skip-download").stdout
        self.assertIn("Title e1 http://127.0.0.1:8840/catalog/vault/episodes/e1", output)
        self.assertIn("Title c1 http://127.0.0.1:8840/catalog/vault/clips/c1", output)

    def test_sync_of_a_version_1_vault_links_its_migrated_episodes(self):
        self.write_catalog(v1_catalog(entries=[stored_entry("e1", EPOCH_KEYS)]))
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.workdir.name)
        payload = document(episodes=[entry("e1", views=20)])
        with patch("source.fetch", return_value=payload):
            output = vault.sync_vault("vault", vault.SyncOptions(skip_download=True))
        self.assertIn(
            "updated: Title e1 http://127.0.0.1:8840/catalog/vault/episodes/e1", output
        )


if __name__ == "__main__":
    unittest.main()
