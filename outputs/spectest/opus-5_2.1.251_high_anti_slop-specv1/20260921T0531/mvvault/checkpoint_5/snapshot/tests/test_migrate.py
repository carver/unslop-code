"""End-to-end tests for loading and migrating legacy catalog versions."""

import json
import unittest
from pathlib import Path

from test_mvault import MvaultTestCase, make_entry

V1_SOURCE_ID = "channel-42"
V1_SOURCE_URL = "https://media.example.com/channel/channel-42"


def make_v1_entry(identifier, published="2024-03-01T10:00:00"):
    """Build a version 1 entry: no ``removed``, no ``annotations``, epoch keys."""
    return {
        "id": identifier,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": {"1718444400": f"title {identifier}"},
        "description": {"1718444400": f"description {identifier}"},
        "views": {"1718444400": 10, "1718530800": 12},
        "likes": {"1718444400": None},
        "preview": {"1718444400": f"hash-{identifier}"},
    }


def make_v2_entry(identifier, published="2024-03-01T10:00:00", **tracked):
    """Build a version 2 entry: category placement and ISO keys, but no ``removed``."""
    entry = {
        "id": identifier,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": {"2024-06-15T09:40:00": f"title {identifier}"},
        "description": {"2024-06-15T09:40:00": f"description {identifier}"},
        "views": {"2024-06-15T09:40:00": 10},
        "likes": {"2024-06-15T09:40:00": None},
        "preview": {"2024-06-15T09:40:00": f"hash-{identifier}"},
    }
    entry.update(tracked)
    return entry


class LegacyVaultTestCase(MvaultTestCase):
    """Fixtures writing hand-built legacy catalogs into the workspace."""

    def write_catalog(self, catalog, name="vault"):
        """Create the vault directory ``name`` holding ``catalog`` verbatim."""
        directory = Path(self.workspace.name) / name
        directory.mkdir()
        (directory / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        return directory

    def write_v1(self, entries, name="vault"):
        return self.write_catalog(
            {"version": 1, "source_id": V1_SOURCE_ID, "entries": list(entries)}, name
        )

    def write_v2(self, episodes=(), streams=(), clips=(), name="vault"):
        return self.write_catalog(
            {
                "version": 2,
                "source": self.source.url,
                "episodes": list(episodes),
                "streams": list(streams),
                "clips": list(clips),
            },
            name,
        )

    def migrate_vault(self, name="vault"):
        result = self.run_mvault("migrate", name)
        self.assertEqual(result.returncode, 0, result.stderr)


class MigrateVersionOneTests(LegacyVaultTestCase):
    def test_source_id_becomes_the_derived_source_url(self):
        self.write_v1([])
        self.migrate_vault()

        catalog = self.catalog()
        self.assertEqual(catalog["source"], V1_SOURCE_URL)
        self.assertNotIn("source_id", catalog)

    def test_flat_entries_become_episodes_and_the_other_categories_are_empty(self):
        self.write_v1([make_v1_entry("e1"), make_v1_entry("e2")])
        self.migrate_vault()

        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual([entry["id"] for entry in catalog["episodes"]], ["e1", "e2"])
        self.assertEqual(catalog["streams"], [])
        self.assertEqual(catalog["clips"], [])
        self.assertNotIn("entries", catalog)

    def test_epoch_history_keys_become_timestamp_text(self):
        self.write_v1([make_v1_entry("e1")])
        self.migrate_vault()

        entry = self.catalog()["episodes"][0]
        self.assertEqual(entry["title"], {"2024-06-15T09:40:00": "title e1"})
        self.assertEqual(
            entry["views"], {"2024-06-15T09:40:00": 10, "2024-06-16T09:40:00": 12}
        )
        self.assertEqual(list(entry["likes"].values()), [None])

    def test_static_fields_survive_the_migration(self):
        self.write_v1([make_v1_entry("e1", published="2024-03-01T10:00:00")])
        self.migrate_vault()

        entry = self.catalog()["episodes"][0]
        self.assertEqual(entry["published"], "2024-03-01T10:00:00")
        self.assertEqual(entry["width"], 1920)
        self.assertEqual(entry["height"], 1080)

    def test_every_entry_gains_removed_and_annotations(self):
        self.write_v1([make_v1_entry("e1"), make_v1_entry("e2")])
        self.migrate_vault()

        for entry in self.catalog()["episodes"]:
            self.assertEqual(list(entry["removed"].values()), [False])
            self.assertEqual(entry["annotations"], [])
            stamp, = entry["removed"]
            self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_the_backup_holds_the_pre_migration_catalog(self):
        vault = self.write_v1([make_v1_entry("e1")])
        before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
        self.migrate_vault()

        self.assertEqual(
            json.loads((vault / "catalog.bak").read_text(encoding="utf-8")), before
        )


class MigrateVersionTwoTests(LegacyVaultTestCase):
    def test_source_and_category_placement_are_preserved(self):
        self.write_v2(episodes=[make_v2_entry("e1")], clips=[make_v2_entry("c1")])
        self.migrate_vault()

        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual(catalog["source"], self.source.url)
        self.assertEqual([entry["id"] for entry in catalog["episodes"]], ["e1"])
        self.assertEqual(catalog["streams"], [])
        self.assertEqual([entry["id"] for entry in catalog["clips"]], ["c1"])

    def test_iso_history_keys_are_kept_as_they_are(self):
        self.write_v2(streams=[make_v2_entry("s1")])
        self.migrate_vault()

        entry = self.catalog()["streams"][0]
        self.assertEqual(entry["title"], {"2024-06-15T09:40:00": "title s1"})

    def test_entries_in_every_category_gain_removed_and_annotations(self):
        self.write_v2(
            episodes=[make_v2_entry("e1")],
            streams=[make_v2_entry("s1")],
            clips=[make_v2_entry("c1")],
        )
        self.migrate_vault()

        catalog = self.catalog()
        for category in ("episodes", "streams", "clips"):
            entry = catalog[category][0]
            self.assertEqual(list(entry["removed"].values()), [False], category)
            self.assertEqual(entry["annotations"], [], category)

    def test_the_backup_holds_the_pre_migration_catalog(self):
        vault = self.write_v2(episodes=[make_v2_entry("e1")])
        before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
        self.migrate_vault()

        self.assertEqual(
            json.loads((vault / "catalog.bak").read_text(encoding="utf-8")), before
        )


class MigrateNativeTests(LegacyVaultTestCase):
    def test_migrating_a_current_vault_changes_nothing_and_writes_no_backup(self):
        self.init_vault()
        self.serve(episodes=[make_entry("e1")])
        self.sync_vault()
        before = self.catalog()
        backup = Path(self.workspace.name) / "vault" / "catalog.bak"
        backed_up = backup.read_bytes()

        self.migrate_vault()

        self.assertEqual(self.catalog(), before)
        self.assertEqual(backup.read_bytes(), backed_up)

    def test_migrating_twice_leaves_the_first_result_untouched(self):
        self.write_v1([make_v1_entry("e1")])
        self.migrate_vault()
        migrated = self.catalog()
        backup = (Path(self.workspace.name) / "vault" / "catalog.bak").read_bytes()

        self.migrate_vault()

        self.assertEqual(self.catalog(), migrated)
        self.assertEqual((Path(self.workspace.name) / "vault" / "catalog.bak").read_bytes(), backup)

    def test_missing_vault_is_reported(self):
        result = self.run_mvault("migrate", "absent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absent", result.stderr)


class LegacySyncTests(LegacyVaultTestCase):
    def test_sync_migrates_a_v2_vault_and_folds_in_the_snapshot(self):
        self.write_v2(episodes=[make_v2_entry("e1")])
        self.serve(episodes=[make_entry("e1", views=11), make_entry("e2")])
        self.sync_vault()

        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        entries = {entry["id"]: entry for entry in catalog["episodes"]}
        self.assertEqual(list(entries["e1"]["views"].values()), [10, 11])
        self.assertEqual(list(entries["e1"]["removed"].values()), [False])
        self.assertEqual(entries["e1"]["annotations"], [])
        self.assertEqual(entries["e2"]["annotations"], [])

    def test_sync_records_removal_of_a_legacy_entry_the_source_dropped(self):
        self.write_v2(clips=[make_v2_entry("c1")])
        self.serve()
        self.sync_vault()

        entry = self.catalog()["clips"][0]
        self.assertEqual(list(entry["removed"].values()), [False, True])

    def test_sync_backs_up_the_pre_migration_catalog(self):
        vault = self.write_v2(episodes=[make_v2_entry("e1")])
        before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
        self.serve(episodes=[make_entry("e1")])
        self.sync_vault()

        self.assertEqual(
            json.loads((vault / "catalog.bak").read_text(encoding="utf-8")), before
        )

    def test_sync_of_a_v1_vault_fetches_the_derived_source_url(self):
        vault = self.write_v1([make_v1_entry("e1")])
        before = (vault / "catalog.json").read_bytes()
        result = self.run_mvault("sync", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(V1_SOURCE_URL, result.stderr)
        self.assertEqual((vault / "catalog.json").read_bytes(), before)
        self.assertFalse((vault / "catalog.bak").exists())


class VersionFailureTests(LegacyVaultTestCase):
    def assert_rejected(self, catalog, expected_text="version"):
        """A rejected catalog leaves the vault byte-for-byte as it was."""
        vault = self.write_catalog(catalog)
        before = (vault / "catalog.json").read_bytes()
        result = self.run_mvault("migrate", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(expected_text, result.stderr)
        self.assertEqual((vault / "catalog.json").read_bytes(), before)
        self.assertFalse((vault / "catalog.bak").exists())

    def test_missing_version_is_rejected(self):
        self.assert_rejected({"source": "http://example.invalid/feed.json", "episodes": []})

    def test_non_integer_version_is_rejected(self):
        self.assert_rejected({"version": "2", "source": "http://example.invalid/feed.json"})

    def test_future_version_is_rejected(self):
        self.assert_rejected({"version": 4, "source": "http://example.invalid/feed.json"})

    def test_invalid_json_is_rejected(self):
        vault = self.write_v1([])
        (vault / "catalog.json").write_text("{not json", encoding="utf-8")
        result = self.run_mvault("migrate", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vault", result.stderr)
        self.assertFalse((vault / "catalog.bak").exists())

    def test_v1_entry_with_an_unreadable_epoch_key_is_rejected(self):
        broken = make_v1_entry("e1")
        broken["views"] = {"yesterday": 10}
        self.assert_rejected(
            {"version": 1, "source_id": V1_SOURCE_ID, "entries": [broken]}, "views"
        )

    def test_v1_entry_missing_a_static_field_is_rejected(self):
        broken = make_v1_entry("e1")
        del broken["width"]
        self.assert_rejected(
            {"version": 1, "source_id": V1_SOURCE_ID, "entries": [broken]}, "width"
        )

    def test_v2_entry_with_a_missing_history_is_rejected(self):
        broken = make_v2_entry("e1")
        del broken["preview"]
        self.assert_rejected(
            {
                "version": 2,
                "source": "http://example.invalid/feed.json",
                "episodes": [broken],
                "streams": [],
                "clips": [],
            },
            "preview",
        )

    def test_unwritable_backup_aborts_the_migration(self):
        vault = self.write_v1([make_v1_entry("e1")])
        before = (vault / "catalog.json").read_bytes()
        (vault / "catalog.bak").mkdir()
        result = self.run_mvault("migrate", "vault")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vault", result.stderr)
        self.assertEqual((vault / "catalog.json").read_bytes(), before)

    def test_v1_catalog_without_an_entries_array_is_rejected(self):
        self.assert_rejected({"version": 1, "source_id": V1_SOURCE_ID}, "entries")


if __name__ == "__main__":
    unittest.main()
