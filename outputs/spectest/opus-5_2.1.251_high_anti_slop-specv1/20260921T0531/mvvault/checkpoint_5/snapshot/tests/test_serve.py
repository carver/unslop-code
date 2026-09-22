"""End-to-end tests for the local viewer that ``mvault.py serve`` runs."""

import os
import socket
import subprocess
import sys
import threading
import unittest
from collections import namedtuple
from http.client import HTTPConnection

from test_migrate import LegacyVaultTestCase, make_v1_entry, make_v2_entry
from test_mvault import ENTRY_POINT

from vault.viewer import server

#: One reply, read far enough to assert on without following any redirect.
Reply = namedtuple("Reply", "status location content_type cookie body")

REDIRECT_STATUSES = (302, 303)
FORM_TYPE = "application/x-www-form-urlencoded"
MEDIA_BODY = b"media bytes"
PREVIEW_BODY = b"preview bytes"


def make_v3_entry(identifier, removed=False, **tracked):
    """Build a version 3 entry, removed or not, with ISO history keys."""
    entry = make_v2_entry(identifier, **tracked)
    entry["removed"] = {"2024-06-15T09:40:00": removed}
    entry["annotations"] = []
    return entry


def free_port():
    """A port nothing is listening on, for a viewer started as a subprocess."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ViewerTestCase(LegacyVaultTestCase):
    """Runs a viewer over the temporary workspace the vault fixtures write to."""

    def setUp(self):
        super().setUp()
        self.viewer = server.create(self.workspace.name, "127.0.0.1", 0)
        self.addCleanup(self.viewer.server_close)
        threading.Thread(target=self.viewer.serve_forever, daemon=True).start()
        self.addCleanup(self.viewer.shutdown)

    def request(self, path, method="GET", body=None, cookie=None):
        """Make one request without following redirects, as a browser reports it."""
        headers = {"Content-Type": FORM_TYPE} if body is not None else {}
        if cookie is not None:
            headers["Cookie"] = cookie
        connection = HTTPConnection("127.0.0.1", self.viewer.server_port)
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            return Reply(
                response.status,
                response.getheader("Location"),
                response.getheader("Content-Type"),
                response.getheader("Set-Cookie"),
                response.read().decode("utf-8"),
            )
        finally:
            connection.close()

    def assertRedirect(self, reply, location):
        self.assertIn(reply.status, REDIRECT_STATUSES)
        self.assertEqual(reply.location, location)

    def write_v3(self, name="vault", episodes=(), streams=(), clips=()):
        return self.write_catalog(
            {
                "version": 3,
                "source": self.source.url,
                "episodes": list(episodes),
                "streams": list(streams),
                "clips": list(clips),
            },
            name,
        )

    def store_media(self, identifier, name="vault", body=MEDIA_BODY):
        """Put a downloaded media file for ``identifier`` in the vault."""
        return self.store_asset("media", f"{identifier}.mp4", body, name)

    def store_preview(self, identifier, name="vault", body=PREVIEW_BODY):
        """Put a downloaded preview image for ``identifier`` in the vault."""
        return self.store_asset("previews", f"{identifier}.jpg", body, name)

    def store_asset(self, kind, filename, body, name="vault"):
        """Write one downloaded file into a vault directory and return its name."""
        directory = self.vault_path(kind, name=name)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_bytes(body)
        return filename

    def entry_markup(self, reply, identifier):
        """The listing line of one entry, which carries its states and classes."""
        lines = [line for line in reply.body.splitlines() if f'id="{identifier}"' in line]
        self.assertEqual(len(lines), 1, reply.body)
        return lines[0]


class LandingPageTests(ViewerTestCase):
    def test_the_landing_page_offers_a_vault_name_field(self):
        reply = self.request("/")

        self.assertEqual(reply.status, 200)
        self.assertIn('name="catalog"', reply.body)

    def test_a_submitted_name_redirects_to_its_catalog(self):
        reply = self.request("/", "POST", "catalog=vault")

        self.assertRedirect(reply, "/catalog/vault")

    def test_a_submission_without_the_field_redirects_to_the_landing_page(self):
        reply = self.request("/", "POST", "other=vault")

        self.assertRedirect(reply, "/")

    def test_an_unknown_path_redirects_to_the_landing_page(self):
        self.assertRedirect(self.request("/elsewhere"), "/")


class DefaultCategoryTests(ViewerTestCase):
    def test_a_version_one_vault_defaults_to_entries(self):
        self.write_v1([make_v1_entry("e1")])

        self.assertRedirect(self.request("/catalog/vault"), "/catalog/vault/entries")

    def test_a_version_two_vault_defaults_to_episodes(self):
        self.write_v2(episodes=[make_v2_entry("e1")])

        self.assertRedirect(self.request("/catalog/vault"), "/catalog/vault/episodes")

    def test_a_version_three_vault_defaults_to_episodes(self):
        self.write_v3(episodes=[make_v3_entry("e1")])

        self.assertRedirect(self.request("/catalog/vault"), "/catalog/vault/episodes")


class CategoryListingTests(ViewerTestCase):
    def test_entries_keep_their_catalog_order(self):
        self.write_v3(episodes=[make_v3_entry("e2"), make_v3_entry("e1")])
        body = self.request("/catalog/vault/episodes").body

        self.assertLess(body.index("title e2"), body.index("title e1"))

    def test_the_listing_shows_the_latest_title(self):
        entry = make_v3_entry("e1", title={"2024-01-01T00:00:00": "old", "2024-02-01T00:00:00": "new"})
        self.write_v3(episodes=[entry])
        body = self.request("/catalog/vault/episodes").body

        self.assertIn("new", body)
        self.assertNotIn(">old<", body)

    def test_version_one_titles_are_read_by_epoch_order(self):
        entry = make_v1_entry("e1")
        entry["title"] = {"1000000000": "newer title", "999999999": "older title"}
        self.write_v1([entry])
        body = self.request("/catalog/vault/entries").body

        self.assertIn("newer title", body)
        self.assertNotIn(">older title<", body)

    def test_each_entry_links_to_its_own_page(self):
        self.write_v3(streams=[make_v3_entry("s1")])
        reply = self.request("/catalog/vault/streams")

        self.assertIn('href="/catalog/vault/streams/s1"', reply.body)

    def test_downloaded_and_undownloaded_entries_differ(self):
        self.write_v3(episodes=[make_v3_entry("e1"), make_v3_entry("e2")])
        self.store_media("e1")
        reply = self.request("/catalog/vault/episodes")

        self.assertIn("downloaded", self.entry_markup(reply, "e1"))
        self.assertNotEqual(self.entry_markup(reply, "e1"), self.entry_markup(reply, "e2"))
        self.assertNotIn("downloaded", self.entry_markup(reply, "e2"))

    def test_a_media_file_named_after_the_entry_counts_as_downloaded(self):
        self.write_v1([make_v1_entry("e1")])
        self.store_media("e1")
        reply = self.request("/catalog/vault/entries")

        self.assertIn("downloaded", self.entry_markup(reply, "e1"))

    def test_removed_entries_are_marked_apart_from_active_ones(self):
        self.write_v3(episodes=[make_v3_entry("e1", removed=True), make_v3_entry("e2")])
        reply = self.request("/catalog/vault/episodes")

        self.assertIn("removed", self.entry_markup(reply, "e1"))
        self.assertNotIn("removed", self.entry_markup(reply, "e2"))

    def test_categories_are_matched_case_sensitively(self):
        self.write_v3(episodes=[make_v3_entry("e1")])

        self.assertRedirect(self.request("/catalog/vault/Episodes"), "/catalog/vault/episodes")


class ViewerErrorTests(ViewerTestCase):
    def test_an_unknown_category_falls_back_to_the_default_one(self):
        self.write_v3(episodes=[make_v3_entry("e1")])

        self.assertRedirect(self.request("/catalog/vault/entries"), "/catalog/vault/episodes")

    def test_a_version_one_vault_falls_back_to_its_entries(self):
        self.write_v1([make_v1_entry("e1")])

        self.assertRedirect(self.request("/catalog/vault/episodes"), "/catalog/vault/entries")

    def test_a_missing_vault_returns_to_the_landing_page(self):
        reply = self.request("/catalog/absent/episodes")

        self.assertIn(reply.status, REDIRECT_STATUSES)
        self.assertTrue(reply.location.startswith("/"))
        self.assertIn("absent", self.request(reply.location).body)

    def test_an_unreadable_catalog_is_no_server_error(self):
        directory = self.write_v3()
        (directory / "catalog.json").write_text("{not json", encoding="utf-8")

        self.assertIn(self.request("/catalog/vault").status, REDIRECT_STATUSES)

    def test_a_name_reaching_outside_the_root_finds_no_vault(self):
        reply = self.request("/catalog/%2E%2E%2Fvault/episodes")

        self.assertIn(reply.status, REDIRECT_STATUSES)
        self.assertNotIn("/catalog/", reply.location)


class RecentVaultTests(ViewerTestCase):
    def visit(self, path, cookie=None):
        """Navigate to a vault and return the recent-vault cookie that came back."""
        reply = self.request(path, cookie=cookie)
        self.assertIsNotNone(reply.cookie, reply.body)
        return reply.cookie.split(";")[0]

    def test_a_visited_vault_is_offered_on_the_landing_page(self):
        self.write_v3(name="alpha", episodes=[make_v3_entry("e1")])
        cookie = self.visit("/catalog/alpha")

        self.assertIn('href="/catalog/alpha/episodes"', self.request("/", cookie=cookie).body)

    def test_a_remembered_vault_outlives_the_browser_session(self):
        self.write_v1([make_v1_entry("e1")], name="legacy")
        cookie = self.visit("/catalog/legacy/entries")

        self.assertIn("Max-Age=", self.request("/catalog/legacy/entries").cookie)
        self.assertIn('href="/catalog/legacy/entries"', self.request("/", cookie=cookie).body)

    def test_the_most_recently_visited_vault_comes_first(self):
        self.write_v3(name="alpha", episodes=[make_v3_entry("e1")])
        self.write_v3(name="beta", episodes=[make_v3_entry("e1")])
        cookie = self.visit("/catalog/beta", self.visit("/catalog/alpha"))
        body = self.request("/", cookie=cookie).body

        self.assertLess(body.index('"/catalog/beta/'), body.index('"/catalog/alpha/'))

    def test_a_browser_that_has_seen_nothing_is_offered_nothing(self):
        reply = self.request("/")

        self.assertEqual(reply.status, 200)
        self.assertNotIn("/catalog/", reply.body)


class StartPathTests(ViewerTestCase):
    """The page ``serve`` opens the browser on."""

    def test_no_vault_starts_at_the_landing_page(self):
        self.assertEqual(server.start_path(self.workspace.name, None), "/")

    def test_a_vault_starts_at_its_default_category(self):
        self.write_v1([make_v1_entry("e1")])

        self.assertEqual(server.start_path(self.workspace.name, "vault"), "/catalog/vault/entries")

    def test_an_unknown_vault_starts_at_its_catalog(self):
        self.assertEqual(server.start_path(self.workspace.name, "absent"), "/catalog/absent")


class ServeCommandTests(LegacyVaultTestCase):
    """``mvault.py serve`` itself, with a browser that does nothing."""

    def start_viewer(self, *options):
        """Run the serve command until the viewer answers, and return its port."""
        port = free_port()
        environment = dict(os.environ, BROWSER="true")
        viewer = subprocess.Popen(
            [sys.executable, str(ENTRY_POINT), *options, f"--port={port}"],
            cwd=self.workspace.name,
            env=environment,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(viewer.stdout.close)
        self.addCleanup(viewer.wait)
        self.addCleanup(viewer.terminate)
        self.assertIn(str(port), viewer.stdout.readline())
        return port

    def get(self, port, path):
        connection = HTTPConnection("127.0.0.1", port)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.getheader("Location")
        finally:
            connection.close()

    def test_the_viewer_serves_the_vaults_of_its_working_directory(self):
        self.write_v2(episodes=[make_v2_entry("e1")])
        port = self.start_viewer("serve")

        self.assertEqual(self.get(port, "/")[0], 200)
        self.assertEqual(self.get(port, "/catalog/vault")[1], "/catalog/vault/episodes")

    def test_a_named_vault_is_served_from_a_chosen_host_and_port(self):
        self.write_v2(episodes=[make_v2_entry("e1")])
        port = self.start_viewer("serve", "vault", "--host=127.0.0.1")

        self.assertEqual(self.get(port, "/catalog/vault/episodes")[0], 200)


if __name__ == "__main__":
    unittest.main()
