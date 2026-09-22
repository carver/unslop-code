"""End-to-end tests driving ``mvault.py`` against a local metadata server."""

import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = PROJECT_ROOT / "mvault.py"


def make_entry(identifier, published="2024-03-01T10:00:00", **overrides):
    """Build a source entry with every required field populated."""
    entry = {
        "id": identifier,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": f"title {identifier}",
        "description": f"description {identifier}",
        "views": 10,
        "likes": 5,
        "preview": f"hash-{identifier}",
    }
    entry.update(overrides)
    return entry


ASSET_KINDS = ("media", "preview")


def asset_key(path):
    """The ``media/e1`` key a request path asks for, or ``None`` for the feed."""
    head, _, name = path.rpartition("/")
    kind = head.rpartition("/")[2]
    return f"{kind}/{name}" if kind in ASSET_KINDS else None


class SourceServer:
    """A local HTTP server for the metadata feed and the asset files below it.

    Tests set ``payload`` for the feed, register asset bodies with
    :meth:`add_asset` and schedule failures with :meth:`fail`; ``requests``
    records every asset key that was asked for, in order.
    """

    def __init__(self):
        self.payload = {"episodes": [], "streams": [], "clips": []}
        self.status = 200
        self.assets = {}
        self.failures = {}
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                key = asset_key(self.path)
                if key is None:
                    body = json.dumps(owner.payload).encode("utf-8")
                    self.respond(owner.status, "application/json", body)
                    return
                owner.requests.append(key)
                status = owner.next_failure(key)
                if status is not None:
                    self.send_error(status)
                elif key in owner.assets:
                    self.respond(200, *owner.assets[key])
                else:
                    self.send_error(404)

            def respond(self, status, content_type, body):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:{}/feed.json".format(self._server.server_port)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def add_asset(self, key, body, content_type="video/mp4"):
        """Serve ``body`` for the asset key ``media/e1`` or ``preview/e1``."""
        self.assets[key] = (content_type, body)

    def fail(self, key, status, times=None):
        """Answer the next ``times`` requests for ``key`` with ``status``.

        ``times`` of ``None`` fails every request for it.
        """
        self.failures[key] = [status, times]

    def next_failure(self, key):
        """Status the current request should fail with, if one is scheduled."""
        failure = self.failures.get(key)
        if failure is None or failure[1] == 0:
            return None
        if failure[1] is not None:
            failure[1] -= 1
        return failure[0]

    def close(self):
        self._server.shutdown()
        self._server.server_close()


class MvaultTestCase(unittest.TestCase):
    """Shared fixtures: a temporary working directory and a source server."""

    def setUp(self):
        self.workspace = TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.source = SourceServer()
        self.addCleanup(self.source.close)

    def run_mvault(self, *args):
        return subprocess.run(
            [sys.executable, str(ENTRY_POINT), *args],
            cwd=self.workspace.name,
            capture_output=True,
            text=True,
        )

    def catalog(self, name="vault"):
        path = Path(self.workspace.name) / name / "catalog.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def serve(self, episodes=(), streams=(), clips=()):
        self.source.payload = {
            "episodes": list(episodes),
            "streams": list(streams),
            "clips": list(clips),
        }

    def init_vault(self, name="vault"):
        result = self.run_mvault("init", name, self.source.url)
        self.assertEqual(result.returncode, 0, result.stderr)

    def sync_vault(self, name="vault", *options):
        result = self.run_mvault("sync", name, *options)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def vault_path(self, *parts, name="vault"):
        return Path(self.workspace.name, name, *parts)


class GlobalCommandTests(MvaultTestCase):
    def test_help_lists_subcommands(self):
        result = self.run_mvault("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("init", result.stdout)
        self.assertIn("sync", result.stdout)

    def test_no_subcommand_prints_usage_to_stderr(self):
        result = self.run_mvault()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage", result.stderr.lower())
        self.assertEqual(result.stdout, "")


class InitTests(MvaultTestCase):
    def test_creates_empty_catalog(self):
        self.init_vault()
        self.assertEqual(
            self.catalog(),
            {"version": 3, "source": self.source.url, "episodes": [], "streams": [], "clips": []},
        )

    def test_existing_directory_is_reported_and_left_alone(self):
        self.init_vault()
        before = self.catalog()
        result = self.run_mvault("init", "vault", "http://example.invalid/other.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vault", result.stderr)
        self.assertEqual(self.catalog(), before)


class SyncTests(MvaultTestCase):
    def test_first_observation_records_all_tracked_fields(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1", likes=None)])
        self.sync_vault()

        entry = self.catalog()["episodes"][0]
        self.assertEqual(entry["id"], "e1")
        self.assertEqual(entry["published"], "2024-03-01T10:00:00")
        self.assertEqual(entry["width"], 1920)
        self.assertEqual(entry["height"], 1080)
        for field in ("title", "description", "views", "likes", "preview", "removed"):
            self.assertEqual(len(entry[field]), 1, field)
        self.assertEqual(list(entry["likes"].values()), [None])
        self.assertEqual(list(entry["removed"].values()), [False])

    def test_unchanged_values_add_no_history(self):
        self.init_vault()
        self.serve(clips=[make_entry("c1")])
        self.sync_vault()
        self.sync_vault()

        entry = self.catalog()["clips"][0]
        self.assertEqual(len(entry["title"]), 1)
        self.assertEqual(len(entry["views"]), 1)

    def test_changed_values_append_later_history_entries(self):
        self.init_vault()
        self.serve(streams=[make_entry("s1", views=10, likes=5)])
        self.sync_vault()
        self.serve(streams=[make_entry("s1", views=11, likes=None, title="renamed")])
        self.sync_vault()

        entry = self.catalog()["streams"][0]
        self.assertEqual(list(entry["views"].values()), [10, 11])
        self.assertEqual(list(entry["likes"].values()), [5, None])
        self.assertEqual(list(entry["title"].values()), ["title s1", "renamed"])
        self.assertEqual(len(entry["description"]), 1)
        stamps = list(entry["views"])
        self.assertLess(stamps[0], stamps[1])

    def test_null_likes_returning_to_a_number_is_a_change(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1", likes=None)])
        self.sync_vault()
        self.serve(episodes=[make_entry("e1", likes=None)])
        self.sync_vault()
        self.serve(episodes=[make_entry("e1", likes=3)])
        self.sync_vault()

        self.assertEqual(list(self.catalog()["episodes"][0]["likes"].values()), [None, 3])

    def test_removal_and_restoration_are_recorded(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_vault()
        self.serve(episodes=[])
        self.sync_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_vault()

        entry = self.catalog()["episodes"][0]
        self.assertEqual(list(entry["removed"].values()), [False, True, False])
        self.assertEqual(sorted(entry["removed"]), list(entry["removed"]))

    def test_repeated_removal_adds_no_history(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_vault()
        self.serve(episodes=[])
        self.sync_vault()
        self.sync_vault()

        self.assertEqual(list(self.catalog()["episodes"][0]["removed"].values()), [False, True])

    def test_date_only_published_is_normalized(self):
        self.init_vault()
        self.serve(clips=[make_entry("c1", published="2024-05-06")])
        self.sync_vault()

        self.assertEqual(self.catalog()["clips"][0]["published"], "2024-05-06T00:00:00")

    def test_offset_published_loses_its_timezone_suffix(self):
        self.init_vault()
        self.serve(clips=[make_entry("c1", published="2024-05-06T07:08:09Z")])
        self.sync_vault()

        self.assertEqual(self.catalog()["clips"][0]["published"], "2024-05-06T07:08:09")

    def test_entries_are_ordered_by_published_then_id(self):
        self.init_vault()
        self.serve(episodes=[
            make_entry("b", published="2024-01-01T00:00:00"),
            make_entry("a", published="2024-01-01T00:00:00"),
            make_entry("c", published="2024-06-01T00:00:00"),
        ])
        self.sync_vault()

        self.assertEqual([entry["id"] for entry in self.catalog()["episodes"]], ["c", "a", "b"])

    def test_backup_holds_the_previous_catalog_bytes(self):
        self.init_vault()
        vault = Path(self.workspace.name) / "vault"
        before = (vault / "catalog.json").read_bytes()
        self.serve(episodes=[make_entry("e1")])
        self.sync_vault()

        self.assertEqual((vault / "catalog.bak").read_bytes(), before)
        self.assertNotEqual((vault / "catalog.json").read_bytes(), before)


class SyncFailureTests(MvaultTestCase):
    def test_missing_vault_is_reported(self):
        result = self.run_mvault("sync", "absent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absent", result.stderr)

    def test_invalid_catalog_is_reported(self):
        self.init_vault()
        (Path(self.workspace.name) / "vault" / "catalog.json").write_text("{not json", encoding="utf-8")
        result = self.run_mvault("sync", "vault")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vault", result.stderr)

    def test_unreachable_source_is_a_fetch_failure(self):
        self.init_vault()
        self.source.close()
        result = self.run_mvault("sync", "vault")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source metadata fetch failure", result.stderr)

    def test_malformed_entry_fails_and_leaves_the_vault_unchanged(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_vault()
        before = self.catalog()

        broken = make_entry("e2")
        del broken["preview"]
        self.serve(episodes=[make_entry("e1"), broken])
        result = self.run_mvault("sync", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source metadata fetch failure", result.stderr)
        self.assertEqual(self.catalog(), before)

    def test_wrongly_typed_entry_field_fails(self):
        self.init_vault()
        self.serve(streams=[make_entry("s1", views="many")])
        result = self.run_mvault("sync", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source metadata fetch failure", result.stderr)
        self.assertEqual(self.catalog()["streams"], [])

    def test_missing_category_array_fails(self):
        self.init_vault()
        self.source.payload = {"episodes": [], "streams": []}
        result = self.run_mvault("sync", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source metadata fetch failure", result.stderr)


if __name__ == "__main__":
    unittest.main()
