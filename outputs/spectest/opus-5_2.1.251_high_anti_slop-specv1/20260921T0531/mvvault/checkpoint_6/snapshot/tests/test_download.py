"""End-to-end tests for the download phase of ``mvault.py sync``."""

import unittest

from test_mvault import MvaultTestCase, make_entry

MEDIA = b"media bytes"
PREVIEW = b"preview bytes"


class DownloadTestCase(MvaultTestCase):
    """A vault whose source offers a downloadable media file per entry."""

    def offer(self, *identifiers, **published):
        """Serve one episode per id and register its media and preview."""
        self.serve(episodes=[make_entry(identifier, **published) for identifier in identifiers])
        for identifier in identifiers:
            self.source.add_asset(f"media/{identifier}", MEDIA)
            self.source.add_asset(f"preview/{identifier}", PREVIEW, "image/jpeg")

    def media_names(self, name="vault"):
        return sorted(path.name for path in self.vault_path("media", name=name).glob("*"))

    def preview_names(self, name="vault"):
        return sorted(path.name for path in self.vault_path("previews", name=name).glob("*"))


class DownloadTests(DownloadTestCase):
    def test_media_and_preview_are_stored_under_the_vault(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault()

        self.assertEqual(self.media_names(), ["e1.mp4"])
        self.assertEqual(self.preview_names(), ["e1.jpg"])
        self.assertEqual(self.vault_path("media", "e1.mp4").read_bytes(), MEDIA)
        self.assertEqual(self.vault_path("previews", "e1.jpg").read_bytes(), PREVIEW)

    def test_extension_follows_the_content_type(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.source.add_asset("media/e1", MEDIA, "audio/mpeg")
        self.sync_vault()

        self.assertEqual(self.media_names(), ["e1.mp3"])

    def test_entries_with_media_already_stored_are_not_fetched_again(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault()
        self.source.requests.clear()
        self.sync_vault()

        self.assertEqual(self.source.requests, [])

    def test_only_the_missing_entry_is_fetched(self):
        self.init_vault()
        self.offer("e1", "e2")
        self.sync_vault()
        self.vault_path("media", "e1.mp4").unlink()
        self.source.requests.clear()
        self.sync_vault()

        self.assertEqual(self.source.requests, ["media/e1", "preview/e1"])

    def test_every_candidate_is_downloaded_without_a_limit(self):
        self.init_vault()
        self.offer("e1", "e2", "e3")
        self.sync_vault()

        self.assertEqual(self.media_names(), ["e1.mp4", "e2.mp4", "e3.mp4"])

    def test_no_partial_files_are_left_behind(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault()

        self.assertEqual(self.media_names(), ["e1.mp4"])
        self.assertEqual(self.preview_names(), ["e1.jpg"])

    def test_a_stale_partial_file_does_not_block_a_later_download(self):
        self.init_vault()
        self.offer("e1")
        partial = self.vault_path("media", "e1.part")
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b"half a file")
        self.sync_vault()

        self.assertEqual(self.media_names(), ["e1.mp4"])


class DownloadLimitTests(DownloadTestCase):
    def serve_three_episodes(self):
        """Three episodes whose catalog order is ``e3``, ``e2``, ``e1``."""
        self.serve(episodes=[
            make_entry("e1", published="2024-01-01T00:00:00"),
            make_entry("e2", published="2024-02-01T00:00:00"),
            make_entry("e3", published="2024-03-01T00:00:00"),
        ])
        for identifier in ("e1", "e2", "e3"):
            self.source.add_asset(f"media/{identifier}", MEDIA)
            self.source.add_asset(f"preview/{identifier}", PREVIEW, "image/jpeg")

    def test_limit_takes_the_first_candidates_in_catalog_order(self):
        self.init_vault()
        self.serve_three_episodes()
        self.sync_vault("vault", "--episodes=2")

        self.assertEqual(self.media_names(), ["e2.mp4", "e3.mp4"])

    def test_a_zero_limit_downloads_nothing_from_that_category(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault("vault", "--episodes=0")

        self.assertEqual(self.source.requests, [])

    def test_each_category_has_its_own_limit(self):
        self.init_vault()
        self.serve(
            episodes=[make_entry("e1")],
            streams=[make_entry("s1")],
            clips=[make_entry("c1"), make_entry("c2")],
        )
        for identifier in ("e1", "s1", "c1", "c2"):
            self.source.add_asset(f"media/{identifier}", MEDIA)
        self.sync_vault("vault", "--episodes=0", "--clips=1")

        self.assertEqual(self.media_names(), ["c1.mp4", "s1.mp4"])

    def test_a_limit_beyond_the_candidates_downloads_them_all(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault("vault", "--episodes=9")

        self.assertEqual(self.media_names(), ["e1.mp4"])


class DownloadFormatTests(DownloadTestCase):
    def test_format_override_requests_and_stores_that_extension(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.source.add_asset("media/e1.ogg", MEDIA, "video/mp4")
        self.source.add_asset("preview/e1", PREVIEW, "image/jpeg")
        self.sync_vault("vault", "--format=ogg")

        self.assertEqual(self.source.requests, ["media/e1.ogg", "preview/e1"])
        self.assertEqual(self.media_names(), ["e1.ogg"])
        self.assertEqual(self.preview_names(), ["e1.jpg"])

    def test_media_stored_under_an_override_is_not_fetched_again(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.source.add_asset("media/e1.ogg", MEDIA)
        self.sync_vault("vault", "--format=ogg")
        self.source.requests.clear()
        self.sync_vault("vault", "--format=ogg")

        self.assertEqual(self.source.requests, [])


class DownloadPhaseTests(DownloadTestCase):
    def test_skip_download_updates_the_catalog_only(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault("vault", "--skip-download")

        self.assertEqual(self.source.requests, [])
        self.assertEqual([entry["id"] for entry in self.catalog()["episodes"]], ["e1"])
        self.assertFalse(self.vault_path("media").exists())

    def test_skip_metadata_downloads_without_touching_the_catalog(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault("vault", "--skip-download")
        before = self.vault_path("catalog.json").read_bytes()
        self.serve(episodes=[make_entry("e1", title="renamed"), make_entry("e2")])
        result = self.sync_vault("vault", "--skip-metadata")

        self.assertEqual(self.media_names(), ["e1.mp4"])
        self.assertEqual(self.vault_path("catalog.json").read_bytes(), before)
        self.assertEqual(result.stdout, "")

    def test_skip_metadata_needs_no_reachable_source_metadata(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault("vault", "--skip-download")
        self.source.status = 500
        self.sync_vault("vault", "--skip-metadata")

        self.assertEqual(self.media_names(), ["e1.mp4"])

    def test_both_phases_can_be_skipped(self):
        self.init_vault()
        self.offer("e1")
        self.sync_vault("vault", "--skip-metadata", "--skip-download")

        self.assertEqual(self.source.requests, [])
        self.assertEqual(self.catalog()["episodes"], [])


class DownloadFailureTests(DownloadTestCase):
    def test_missing_content_warns_and_leaves_the_sync_successful(self):
        self.init_vault()
        self.offer("e1", "e2")
        self.source.fail("media/e1", 404)
        result = self.sync_vault()

        self.assertIn("e1", result.stderr)
        self.assertEqual(self.media_names(), ["e2.mp4"])

    def test_a_permanent_failure_is_not_retried(self):
        self.init_vault()
        self.offer("e1")
        self.source.fail("media/e1", 404)
        self.sync_vault()

        self.assertEqual(self.source.requests.count("media/e1"), 1)

    def test_a_transient_failure_is_retried_until_it_succeeds(self):
        self.init_vault()
        self.offer("e1")
        self.source.fail("media/e1", 503, times=2)
        result = self.sync_vault()

        self.assertEqual(self.source.requests.count("media/e1"), 3)
        self.assertEqual(self.media_names(), ["e1.mp4"])
        self.assertEqual(result.stderr, "")

    def test_a_transient_failure_warns_once_the_retries_are_spent(self):
        self.init_vault()
        self.offer("e1")
        self.source.fail("media/e1", 503)
        result = self.sync_vault()

        self.assertEqual(self.source.requests.count("media/e1"), 3)
        self.assertIn("e1", result.stderr)
        self.assertEqual(self.media_names(), [])

    def test_a_failed_download_leaves_no_partial_file(self):
        self.init_vault()
        self.offer("e1")
        self.source.fail("media/e1", 404)
        self.sync_vault()

        self.assertEqual(self.media_names(), [])

    def test_a_failed_preview_does_not_cost_the_entry_its_media(self):
        self.init_vault()
        self.offer("e1")
        self.source.fail("preview/e1", 404)
        result = self.sync_vault()

        self.assertEqual(self.media_names(), ["e1.mp4"])
        self.assertEqual(self.preview_names(), [])
        self.assertIn("preview", result.stderr)

    def test_metadata_is_saved_even_when_every_download_fails(self):
        self.init_vault()
        self.offer("e1")
        self.source.fail("media/e1", 404)
        self.source.fail("preview/e1", 404)
        self.sync_vault()

        self.assertEqual([entry["id"] for entry in self.catalog()["episodes"]], ["e1"])


class DownloadOptionTests(DownloadTestCase):
    def assert_rejected(self, *options):
        """The option combination fails before the vault is read at all."""
        self.init_vault()
        self.offer("e1")
        result = self.run_mvault("sync", "vault", *options)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.stderr, "")
        self.assertEqual(self.source.requests, [])
        self.assertEqual(self.catalog()["episodes"], [])

    def test_a_non_numeric_limit_is_rejected(self):
        self.assert_rejected("--episodes=two")

    def test_a_negative_limit_is_rejected(self):
        self.assert_rejected("--streams=-1")

    def test_a_fractional_limit_is_rejected(self):
        self.assert_rejected("--clips=1.5")

    def test_an_unknown_option_is_rejected(self):
        self.assert_rejected("--everything")


class LegacyDownloadTests(DownloadTestCase):
    def test_a_migrated_vault_downloads_from_its_migrated_source(self):
        directory = self.vault_path(name="legacy")
        directory.mkdir()
        (directory / "catalog.json").write_text(
            '{"version": 2, "source": "%s", "episodes": [], "streams": [], "clips": []}'
            % self.source.url,
            encoding="utf-8",
        )
        self.offer("e1")
        self.sync_vault("legacy")

        self.assertEqual(self.catalog("legacy")["version"], 3)
        self.assertEqual(self.media_names("legacy"), ["e1.mp4"])


if __name__ == "__main__":
    unittest.main()
