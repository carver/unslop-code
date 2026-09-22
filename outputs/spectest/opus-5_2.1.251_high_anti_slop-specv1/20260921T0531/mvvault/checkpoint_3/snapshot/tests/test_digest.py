"""End-to-end tests for ``mvault.py digest`` across the catalog versions."""

import unittest

from test_migrate import LegacyVaultTestCase, V1_SOURCE_URL, make_v1_entry, make_v2_entry
from test_mvault import MvaultTestCase, make_entry


class DigestReader:
    """Reads a vault's digest as lines, split from its trailing metadata line."""

    def digest(self, name="vault"):
        result = self.run_mvault("digest", name)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        return lines[:-1], lines[-1]

    def changes(self, name="vault"):
        return self.digest(name)[0]


class DigestTests(MvaultTestCase, DigestReader):
    """Digesting the native catalog version, which tracks removals too."""

    def sync_metadata(self, name="vault"):
        return self.sync_vault(name, "--skip-download")

    def test_a_new_entry_is_an_addition(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_metadata()

        self.assertEqual(self.changes(), ["Episodes", "  Added", "    title e1"])

    def test_the_current_title_names_the_entry(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_metadata()
        self.serve(episodes=[make_entry("e1", title="renamed")])
        self.sync_metadata()

        self.assertEqual(self.changes(), ["Episodes", "  Updated", "    renamed (title)"])

    def test_an_update_names_every_changed_field(self):
        self.init_vault()
        self.serve(streams=[make_entry("s1")])
        self.sync_metadata()
        self.serve(streams=[make_entry("s1", views=11, likes=None, preview="hash-other")])
        self.sync_metadata()

        self.assertEqual(self.changes(), ["Streams", "  Updated", "    title s1 (views, likes, preview)"])

    def test_a_vanished_entry_is_a_removal(self):
        self.init_vault()
        self.serve(clips=[make_entry("c1")])
        self.sync_metadata()
        self.serve()
        self.sync_metadata()

        self.assertEqual(self.changes(), ["Clips", "  Removed", "    title c1"])

    def test_a_removal_outranks_the_fields_that_changed_with_it(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_metadata()
        self.serve(episodes=[make_entry("e1", views=12)])
        self.sync_metadata()
        self.serve()
        self.sync_metadata()

        self.assertEqual(self.changes(), ["Episodes", "  Removed", "    title e1"])

    def test_an_entry_back_from_removal_is_reported_as_reappeared(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_metadata()
        self.serve()
        self.sync_metadata()
        self.serve(episodes=[make_entry("e1", views=12)])
        self.sync_metadata()

        self.assertEqual(
            self.changes(), ["Episodes", "  Updated", "    title e1 (reappeared, views)"]
        )

    def test_groups_and_categories_keep_a_fixed_order(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1"), make_entry("e2")], clips=[make_entry("c1")])
        self.sync_metadata()
        self.serve(episodes=[make_entry("e1", views=12), make_entry("e3")], clips=[make_entry("c1")])
        self.sync_metadata()

        self.assertEqual(self.changes(), [
            "Episodes",
            "  Removed",
            "    title e2",
            "  Added",
            "    title e3",
            "  Updated",
            "    title e1 (views)",
            "Clips",
            "  Added",
            "    title c1",
        ])

    def test_entries_follow_catalog_order(self):
        self.init_vault()
        self.serve(episodes=[
            make_entry("e1", published="2024-01-01T00:00:00"),
            make_entry("e2", published="2024-02-01T00:00:00"),
        ])
        self.sync_metadata()

        self.assertEqual(self.changes()[2:], ["    title e2", "    title e1"])

    def test_an_empty_vault_reports_no_notable_changes(self):
        self.init_vault()

        self.assertEqual(self.changes(), ["No notable changes found."])

    def test_the_trailing_line_names_the_source_and_version(self):
        self.init_vault()
        trailer = self.digest()[1]

        self.assertIn(self.source.url, trailer)
        self.assertIn("3", trailer)

    def test_digesting_writes_nothing(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_metadata()
        before = self.vault_path("catalog.json").read_bytes()
        backup = self.vault_path("catalog.bak").read_bytes()
        self.digest()

        self.assertEqual(self.vault_path("catalog.json").read_bytes(), before)
        self.assertEqual(self.vault_path("catalog.bak").read_bytes(), backup)


class DigestLegacyTests(LegacyVaultTestCase, DigestReader):
    """Digesting version 1 and 2 catalogs, which are never migrated for it."""

    def test_version_one_entries_share_a_single_group(self):
        self.write_v1([make_v1_entry("e1"), make_v1_entry("e2")])

        self.assertEqual(self.changes(), [
            "Entries",
            "  Updated",
            "    title e1 (views)",
            "    title e2 (views)",
        ])

    def test_version_one_history_is_ordered_numerically(self):
        entry = make_v1_entry("e1")
        entry["title"] = {"999999999": "older title", "1000000000": "newer title"}
        self.write_v1([entry])

        self.assertIn("    newer title (title, views)", self.changes())

    def test_version_one_reports_its_derived_source_url(self):
        self.write_v1([])

        self.assertIn(V1_SOURCE_URL, self.digest()[1])

    def test_version_two_groups_by_category(self):
        self.write_v2(episodes=[make_v2_entry("e1")], clips=[make_v2_entry("c1")])

        self.assertEqual(self.changes(), [
            "Episodes",
            "  Added",
            "    title e1",
            "Clips",
            "  Added",
            "    title c1",
        ])

    def test_version_two_reports_its_stored_source_url(self):
        self.write_v2()
        changes, trailer = self.digest()

        self.assertEqual(changes, ["No notable changes found."])
        self.assertIn(self.source.url, trailer)

    def test_a_legacy_vault_is_left_on_its_own_version(self):
        self.write_v1([make_v1_entry("e1")])
        self.digest()

        self.assertEqual(self.catalog()["version"], 1)
        self.assertFalse(self.vault_path("catalog.bak").exists())

    def test_legacy_entries_are_never_reported_as_removed(self):
        entry = make_v2_entry("e1", title={"2024-06-15T09:40:00": "gone"})
        entry["removed"] = {"2024-06-15T09:40:00": True}
        self.write_v2(episodes=[entry])

        self.assertEqual(self.changes(), ["Episodes", "  Added", "    gone"])


class DigestFailureTests(LegacyVaultTestCase, DigestReader):
    def test_a_missing_vault_is_reported_by_name(self):
        result = self.run_mvault("digest", "absent")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absent", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_an_unsupported_version_is_reported_with_its_value(self):
        self.write_catalog({"version": 9, "source": self.source.url})
        result = self.run_mvault("digest", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("9", result.stderr)

    def test_a_catalog_missing_a_category_is_reported(self):
        self.write_catalog({"version": 3, "source": self.source.url, "episodes": []})
        result = self.run_mvault("digest", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("streams", result.stderr)


class SyncSummaryTests(MvaultTestCase):
    """The counts a sync prints once its metadata phase is done."""

    def summary(self, *options):
        return self.sync_vault("vault", "--skip-download", *options).stdout

    def test_new_entries_are_counted_as_added(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")], clips=[make_entry("c1")])

        self.assertIn("2 added", self.summary())

    def test_unchanged_entries_are_counted_nowhere(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.summary()

        self.assertEqual(self.summary().strip(), "Sync summary: 0 added, 0 removed, 0 updated")

    def test_changed_and_vanished_entries_are_counted_apart(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1"), make_entry("e2")])
        self.summary()
        self.serve(episodes=[make_entry("e1", views=12)])
        summary = self.summary()

        self.assertIn("0 added", summary)
        self.assertIn("1 removed", summary)
        self.assertIn("1 updated", summary)

    def test_an_entry_back_from_removal_counts_as_updated(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.summary()
        self.serve()
        self.summary()
        self.serve(episodes=[make_entry("e1")])

        self.assertIn("1 updated", self.summary())

    def test_a_download_only_run_prints_no_summary(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])

        self.assertEqual(self.sync_vault("vault", "--skip-metadata").stdout, "")


if __name__ == "__main__":
    unittest.main()
