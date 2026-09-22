"""End-to-end tests for the mvault command line."""

import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

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


if __name__ == "__main__":
    unittest.main()
