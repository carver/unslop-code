"""End-to-end tests for the annotations an entry detail page keeps."""

import json
import unittest
from pathlib import Path

from test_migrate import V1_SOURCE_URL, make_v1_entry, make_v2_entry
from test_serve import ViewerTestCase, make_v3_entry


class AnnotationTestCase(ViewerTestCase):
    """Requests that annotate an entry, and the catalog they leave behind."""

    def annotate(self, path, method="POST", **fields):
        """Send one annotation request, its fields encoded as a JSON body."""
        return self.request(path, method, json.dumps(fields))

    def stored_annotations(self, category="episodes", name="vault"):
        """The annotations the catalog holds for the first entry of a category."""
        return self.catalog(name)[category][0]["annotations"]

    def create(self, path="/catalog/vault/episodes/e1", **fields):
        """Create one annotation and return the record the catalog stores."""
        reply = self.annotate(path, **{"title": "a note", "timecode": "1:30", **fields})
        self.assertEqual(reply.status, 303, reply.body)
        return self.stored_annotations()[-1]


class CreateAnnotationTests(AnnotationTestCase):
    def setUp(self):
        super().setUp()
        self.write_v3(episodes=[make_v3_entry("e1")])

    def test_a_created_annotation_is_stored_with_its_fields(self):
        annotation = self.create(title="the reveal", timecode="1:30", body="worth rewatching")

        self.assertEqual(annotation["timecode"], 90)
        self.assertEqual(annotation["title"], "the reveal")
        self.assertEqual(annotation["body"], "worth rewatching")
        self.assertIsInstance(annotation["id"], str)

    def test_an_omitted_body_is_stored_as_null(self):
        self.assertIsNone(self.create()["body"])

    def test_creation_redirects_to_the_entry_page_at_the_parsed_timecode(self):
        reply = self.annotate(
            "/catalog/vault/episodes/e1", title="the reveal", timecode="1:01:30"
        )

        self.assertRedirect(reply, "/catalog/vault/episodes/e1?timecode=3690")

    def test_annotations_keep_the_order_they_were_created_in(self):
        for title in ("first", "second", "third"):
            self.create(title=title)

        stored = [found["title"] for found in self.stored_annotations()]
        self.assertEqual(stored, ["first", "second", "third"])

    def test_every_annotation_of_an_entry_gets_its_own_id(self):
        for title in ("first", "second"):
            self.create(title=title)

        identifiers = {found["id"] for found in self.stored_annotations()}
        self.assertEqual(len(identifiers), 2)

    def test_the_catalog_is_backed_up_before_the_annotation_is_stored(self):
        vault = Path(self.workspace.name) / "vault"
        before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
        self.create()

        backup = json.loads((vault / "catalog.bak").read_text(encoding="utf-8"))
        self.assertEqual(backup, before)
        self.assertEqual(backup["episodes"][0]["annotations"], [])

    def test_an_annotation_can_be_created_in_any_category(self):
        self.write_v3(name="other", clips=[make_v3_entry("c1")])
        reply = self.annotate("/catalog/other/clips/c1", title="a clip note", timecode="5")

        self.assertRedirect(reply, "/catalog/other/clips/c1?timecode=5")
        self.assertEqual(len(self.stored_annotations("clips", "other")), 1)


class TimecodeGrammarTests(AnnotationTestCase):
    """What each accepted timecode spelling is stored and redirected to as."""

    def setUp(self):
        super().setUp()
        self.write_v3(episodes=[make_v3_entry("e1")])

    def test_each_spelling_parses_to_whole_seconds(self):
        for text, seconds in (
            ("90", 90),
            ("1:30", 90),
            ("1:01:30", 3690),
            ("90:00", 5400),
            ("0", 0),
            ("007", 7),
            ("00:00:09", 9),
        ):
            with self.subTest(timecode=text):
                reply = self.annotate(
                    "/catalog/vault/episodes/e1", title="a note", timecode=text
                )

                self.assertRedirect(reply, f"/catalog/vault/episodes/e1?timecode={seconds}")
                self.assertEqual(self.stored_annotations()[-1]["timecode"], seconds)

    def test_text_that_is_no_timecode_is_refused(self):
        for text in ("", "later", "1:30:00:00", "-5", "1.5", "1:", ":30", "90 "):
            with self.subTest(timecode=text):
                reply = self.annotate(
                    "/catalog/vault/episodes/e1", title="a note", timecode=text
                )

                self.assertEqual(reply.status, 400, text)
                self.assertEqual(self.stored_annotations(), [])


class UpdateAnnotationTests(AnnotationTestCase):
    def setUp(self):
        super().setUp()
        self.write_v3(episodes=[make_v3_entry("e1")])
        self.annotation = self.create(title="first title", body="first body")

    def patch(self, **fields):
        return self.annotate("/catalog/vault/episodes/e1", "PATCH", **fields)

    def test_a_new_title_replaces_the_stored_one(self):
        reply = self.patch(id=self.annotation["id"], title="second title")

        self.assertRedirect(reply, "/catalog/vault/episodes/e1")
        stored, = self.stored_annotations()
        self.assertEqual(stored["title"], "second title")
        self.assertEqual(stored["body"], "first body")

    def test_a_new_body_replaces_the_stored_one(self):
        self.patch(id=self.annotation["id"], body="second body")

        stored, = self.stored_annotations()
        self.assertEqual(stored["title"], "first title")
        self.assertEqual(stored["body"], "second body")

    def test_both_fields_can_be_replaced_at_once(self):
        self.patch(id=self.annotation["id"], title="other", body="other body")

        stored, = self.stored_annotations()
        self.assertEqual((stored["title"], stored["body"]), ("other", "other body"))

    def test_the_timecode_and_the_id_are_left_alone(self):
        self.patch(id=self.annotation["id"], title="second title")

        stored, = self.stored_annotations()
        self.assertEqual(stored["timecode"], self.annotation["timecode"])
        self.assertEqual(stored["id"], self.annotation["id"])

    def test_only_the_named_annotation_changes(self):
        other = self.create(title="untouched")
        self.patch(id=self.annotation["id"], title="changed")

        titles = [found["title"] for found in self.stored_annotations()]
        self.assertEqual(titles, ["changed", other["title"]])

    def test_the_catalog_is_backed_up_before_the_update(self):
        vault = Path(self.workspace.name) / "vault"
        before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
        self.patch(id=self.annotation["id"], title="second title")

        backup = json.loads((vault / "catalog.bak").read_text(encoding="utf-8"))
        self.assertEqual(backup, before)


class DeleteAnnotationTests(AnnotationTestCase):
    def setUp(self):
        super().setUp()
        self.write_v3(episodes=[make_v3_entry("e1")])

    def test_a_deleted_annotation_is_gone_from_the_catalog(self):
        annotation = self.create(title="a note")
        reply = self.annotate("/catalog/vault/episodes/e1", "DELETE", id=annotation["id"])

        self.assertRedirect(reply, "/catalog/vault/episodes/e1")
        self.assertEqual(self.stored_annotations(), [])

    def test_the_annotations_that_remain_keep_their_order(self):
        kept = [self.create(title=title) for title in ("first", "second", "third")]
        self.annotate("/catalog/vault/episodes/e1", "DELETE", id=kept[1]["id"])

        titles = [found["title"] for found in self.stored_annotations()]
        self.assertEqual(titles, ["first", "third"])

    def test_the_catalog_is_backed_up_before_the_delete(self):
        annotation = self.create(title="a note")
        vault = Path(self.workspace.name) / "vault"
        before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
        self.annotate("/catalog/vault/episodes/e1", "DELETE", id=annotation["id"])

        backup = json.loads((vault / "catalog.bak").read_text(encoding="utf-8"))
        self.assertEqual(backup, before)


class AnnotationPageTests(AnnotationTestCase):
    """What a later ``GET`` of the entry page shows of the stored annotations."""

    def setUp(self):
        super().setUp()
        self.write_v3(episodes=[make_v3_entry("e1")])

    def test_a_created_annotation_is_rendered_with_its_raw_seconds(self):
        self.create(title="the reveal", timecode="1:01:30", body="worth rewatching")
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertIn("the reveal", body)
        self.assertIn("worth rewatching", body)
        self.assertIn(">3690<", body)
        self.assertNotIn("1:01:30", body)

    def test_the_page_renders_annotations_in_catalog_order(self):
        for title in ("first", "second"):
            self.create(title=title)
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertLess(body.index("first"), body.index("second"))

    def test_an_updated_title_is_what_a_later_get_shows(self):
        annotation = self.create(title="first title")
        self.annotate(
            "/catalog/vault/episodes/e1", "PATCH", id=annotation["id"], title="second title"
        )
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertIn("second title", body)
        self.assertNotIn("first title", body)

    def test_a_deleted_annotation_is_gone_from_a_later_get(self):
        annotation = self.create(title="a note")
        self.annotate("/catalog/vault/episodes/e1", "DELETE", id=annotation["id"])
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertNotIn("a note", body)
        self.assertIn("no annotations", body)

    def test_an_entry_without_annotations_says_so(self):
        self.assertIn("no annotations", self.request("/catalog/vault/episodes/e1").body)

    def test_the_timecode_query_seeks_the_stored_media(self):
        self.store_media("e1")
        body = self.request("/catalog/vault/episodes/e1?timecode=90").body

        self.assertIn("#t=90", body)

    def test_a_page_asked_for_without_a_timecode_plays_from_the_start(self):
        self.store_media("e1")
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertNotIn("#t=", body)

    def test_a_legacy_entry_page_shows_no_annotations(self):
        self.write_v2(name="legacy", episodes=[make_v2_entry("e1")])
        body = self.request("/catalog/legacy/episodes/e1").body

        self.assertEqual(self.request("/catalog/legacy/episodes/e1").status, 200)
        self.assertIn("no annotations", body)


class AnnotationErrorTests(AnnotationTestCase):
    """The answers a request the catalog cannot carry out is refused with."""

    def setUp(self):
        super().setUp()
        self.write_v3(episodes=[make_v3_entry("e1")])

    def assertRefused(self, reply, status, named):
        """A refusal is a well-formed page naming what was wrong with the request."""
        self.assertEqual(reply.status, status, reply.body)
        self.assertIn("<html", reply.body)
        self.assertNotIn("Traceback", reply.body)
        self.assertIn(named, reply.body)

    def test_a_create_without_a_title_is_refused(self):
        reply = self.annotate("/catalog/vault/episodes/e1", timecode="90")

        self.assertRefused(reply, 400, "title")
        self.assertEqual(self.stored_annotations(), [])

    def test_a_create_without_a_timecode_is_refused(self):
        reply = self.annotate("/catalog/vault/episodes/e1", title="a note")

        self.assertRefused(reply, 400, "timecode")

    def test_a_create_with_an_unreadable_timecode_is_refused(self):
        reply = self.annotate("/catalog/vault/episodes/e1", title="a note", timecode="soon")

        self.assertRefused(reply, 400, "timecode")

    def test_an_update_without_an_id_is_refused(self):
        reply = self.annotate("/catalog/vault/episodes/e1", "PATCH", title="a note")

        self.assertRefused(reply, 400, "id")

    def test_a_delete_without_an_id_is_refused(self):
        reply = self.annotate("/catalog/vault/episodes/e1", "DELETE", title="a note")

        self.assertRefused(reply, 400, "id")

    def test_an_update_of_an_annotation_that_is_not_there_is_not_found(self):
        self.create(title="a note")
        reply = self.annotate("/catalog/vault/episodes/e1", "PATCH", id="absent", title="x")

        self.assertRefused(reply, 404, "absent")
        self.assertEqual(self.stored_annotations()[0]["title"], "a note")

    def test_a_delete_of_an_annotation_that_is_not_there_is_not_found(self):
        self.create(title="a note")
        reply = self.annotate("/catalog/vault/episodes/e1", "DELETE", id="absent")

        self.assertRefused(reply, 404, "absent")
        self.assertEqual(len(self.stored_annotations()), 1)

    def test_a_malformed_json_body_is_refused(self):
        reply = self.request("/catalog/vault/episodes/e1", "POST", "{not json")

        self.assertRefused(reply, 400, "JSON")

    def test_a_body_that_is_not_a_json_object_is_refused(self):
        reply = self.request("/catalog/vault/episodes/e1", "POST", '["a note"]')

        self.assertRefused(reply, 400, "JSON")

    def test_an_entry_that_is_not_there_is_not_found(self):
        reply = self.annotate("/catalog/vault/episodes/absent", title="a note", timecode="90")

        self.assertRefused(reply, 404, "absent")

    def test_a_category_the_vault_does_not_offer_is_not_found(self):
        reply = self.annotate("/catalog/vault/elsewhere/e1", title="a note", timecode="90")

        self.assertEqual(reply.status, 404)

    def test_a_vault_that_is_not_there_returns_to_the_landing_page(self):
        reply = self.annotate("/catalog/absent/episodes/e1", title="a note", timecode="90")

        self.assertIn(reply.status, (302, 303))
        self.assertIn("absent", self.request(reply.location).body)

    def test_a_path_that_is_no_entry_redirects_to_the_landing_page(self):
        self.assertRedirect(self.annotate("/catalog/vault/episodes", title="x"), "/")

    def test_a_failed_migration_leaves_the_catalog_as_it_was(self):
        broken = make_v1_entry("e1")
        broken["views"] = {"yesterday": 10}
        vault = self.write_catalog(
            {"version": 1, "source_id": "channel-42", "entries": [broken]}, "legacy"
        )
        before = (vault / "catalog.json").read_bytes()
        reply = self.annotate("/catalog/legacy/entries/e1", title="a note", timecode="90")

        self.assertRefused(reply, 500, "views")
        self.assertEqual((vault / "catalog.json").read_bytes(), before)
        self.assertFalse((vault / "catalog.bak").exists())


class AutoMigrationTests(AnnotationTestCase):
    """Annotating a legacy vault, which migrates it to version 3 on the way."""

    def test_a_version_one_vault_is_migrated_and_annotated_in_one_write(self):
        vault = self.write_v1([make_v1_entry("e1")])
        before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
        reply = self.annotate("/catalog/vault/entries/e1", title="a note", timecode="90")

        self.assertRedirect(reply, "/catalog/vault/episodes/e1?timecode=90")
        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual(
            json.loads((vault / "catalog.bak").read_text(encoding="utf-8")), before
        )
        self.assertEqual(len(catalog["episodes"][0]["annotations"]), 1)

    def test_version_one_entries_move_to_episodes_under_the_derived_source(self):
        self.write_v1([make_v1_entry("e1"), make_v1_entry("e2")])
        self.annotate("/catalog/vault/entries/e2", title="a note", timecode="90")

        catalog = self.catalog()
        self.assertEqual(catalog["source"], V1_SOURCE_URL)
        self.assertNotIn("source_id", catalog)
        self.assertNotIn("entries", catalog)
        self.assertEqual([entry["id"] for entry in catalog["episodes"]], ["e1", "e2"])
        self.assertEqual(catalog["episodes"][0]["annotations"], [])

    def test_version_one_epoch_keys_become_timestamps_and_removed_points(self):
        self.write_v1([make_v1_entry("e1"), make_v1_entry("e2")])
        self.annotate("/catalog/vault/entries/e1", title="a note", timecode="90")

        episodes = self.catalog()["episodes"]
        self.assertEqual(episodes[0]["title"], {"2024-06-15T09:40:00": "title e1"})
        stamps = [list(entry["removed"]) for entry in episodes]
        self.assertEqual(stamps[0], stamps[1])
        self.assertEqual(list(episodes[0]["removed"].values()), [False])

    def test_a_version_two_vault_is_migrated_where_its_entries_already_lie(self):
        vault = self.write_v2(streams=[make_v2_entry("s1")])
        before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
        reply = self.annotate("/catalog/vault/streams/s1", title="a note", timecode="1:30")

        self.assertRedirect(reply, "/catalog/vault/streams/s1?timecode=90")
        catalog = self.catalog()
        self.assertEqual(catalog["version"], 3)
        self.assertEqual(catalog["source"], self.source.url)
        self.assertEqual(len(catalog["streams"][0]["annotations"]), 1)
        self.assertEqual(
            json.loads((vault / "catalog.bak").read_text(encoding="utf-8")), before
        )

    def test_the_migrated_vault_serves_the_version_three_categories(self):
        self.write_v1([make_v1_entry("e1")])
        self.annotate("/catalog/vault/entries/e1", title="a note", timecode="90")

        self.assertEqual(self.request("/catalog/vault/episodes/e1").status, 200)
        self.assertRedirect(self.request("/catalog/vault"), "/catalog/vault/episodes")
        self.assertRedirect(self.request("/catalog/vault/entries"), "/catalog/vault/episodes")

    def test_the_annotation_is_shown_on_the_page_it_redirects_to(self):
        self.write_v1([make_v1_entry("e1")])
        reply = self.annotate("/catalog/vault/entries/e1", title="the reveal", timecode="1:30")
        body = self.request(reply.location).body

        self.assertIn("the reveal", body)
        self.assertIn(">90<", body)

    def test_a_second_annotation_is_appended_after_the_migration(self):
        self.write_v1([make_v1_entry("e1")])
        self.annotate("/catalog/vault/entries/e1", title="first", timecode="90")
        reply = self.annotate("/catalog/vault/episodes/e1", title="second", timecode="120")

        self.assertRedirect(reply, "/catalog/vault/episodes/e1?timecode=120")
        titles = [found["title"] for found in self.stored_annotations()]
        self.assertEqual(titles, ["first", "second"])

    def test_an_annotation_of_a_migrated_vault_can_be_updated_and_deleted(self):
        self.write_v2(episodes=[make_v2_entry("e1")])
        self.annotate("/catalog/vault/episodes/e1", title="first", timecode="90")
        annotation, = self.stored_annotations()
        self.annotate(
            "/catalog/vault/episodes/e1", "PATCH", id=annotation["id"], title="second"
        )

        self.assertEqual(self.stored_annotations()[0]["title"], "second")

        self.annotate("/catalog/vault/episodes/e1", "DELETE", id=annotation["id"])
        self.assertEqual(self.stored_annotations(), [])

    def test_a_legacy_vault_holds_no_annotation_to_update(self):
        self.write_v2(episodes=[make_v2_entry("e1")])
        reply = self.annotate("/catalog/vault/episodes/e1", "PATCH", id="a1", title="x")

        self.assertEqual(reply.status, 404)
        self.assertEqual(self.catalog()["version"], 2)


if __name__ == "__main__":
    unittest.main()
