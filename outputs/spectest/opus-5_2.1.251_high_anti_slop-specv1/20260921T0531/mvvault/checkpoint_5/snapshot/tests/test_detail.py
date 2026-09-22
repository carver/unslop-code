"""End-to-end tests for entry detail pages and the vault files they play."""

import json
import unittest

from test_migrate import V1_SOURCE_URL, make_v1_entry, make_v2_entry
from test_serve import MEDIA_BODY, PREVIEW_BODY, REDIRECT_STATUSES, ViewerTestCase, make_v3_entry

DATA_BLOCK = 'id="chart-data">'


def chart_data(body):
    """The chart payload a detail page embeds, read back as a browser would."""
    return json.loads(body.partition(DATA_BLOCK)[2].partition("</script>")[0])


def points(body, field):
    """The ``(timestamp, value)`` pairs the page charts for one field."""
    return [(point["timestamp"], point["value"]) for point in chart_data(body)[field]]


class DetailPageTests(ViewerTestCase):
    """What the page of one entry of a version 3 vault says about it."""

    def test_the_current_title_and_description_are_shown(self):
        entry = make_v3_entry(
            "e1",
            title={"2024-01-01T00:00:00": "old title", "2024-02-01T00:00:00": "new title"},
            description={"2024-01-01T00:00:00": "old text", "2024-02-01T00:00:00": "new text"},
        )
        self.write_v3(episodes=[entry])
        reply = self.request("/catalog/vault/episodes/e1")

        self.assertEqual(reply.status, 200)
        self.assertIn("new title", reply.body)
        self.assertIn("new text", reply.body)
        self.assertNotIn("old title", reply.body)
        self.assertNotIn("old text", reply.body)

    def test_the_published_date_and_dimensions_are_shown(self):
        self.write_v3(episodes=[make_v3_entry("e1", published="2024-03-01T10:00:00")])
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertIn("2024-03-01T10:00:00", body)
        self.assertIn("1920", body)
        self.assertIn("1080", body)

    def test_the_source_platform_link_is_derived_from_the_vault_source(self):
        self.write_v3(clips=[make_v3_entry("c1")])
        body = self.request("/catalog/vault/clips/c1").body

        self.assertIn(f'href="{self.source.url}/entry/c1"', body)

    def test_the_page_links_back_to_its_own_category_listing(self):
        self.write_v3(streams=[make_v3_entry("s1")])
        body = self.request("/catalog/vault/streams/s1").body

        self.assertIn('href="/catalog/vault/streams"', body)

    def test_a_removed_entry_still_has_a_page(self):
        self.write_v3(episodes=[make_v3_entry("e1", removed=True)])
        reply = self.request("/catalog/vault/episodes/e1")

        self.assertEqual(reply.status, 200)
        self.assertIn("title e1", reply.body)

    def test_the_visited_vault_is_remembered(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        reply = self.request("/catalog/vault/episodes/e1")

        self.assertIn("mvault_recent", reply.cookie)


class DetailLookupTests(ViewerTestCase):
    """Which entry a detail path resolves to, and what happens when none does."""

    def test_an_entry_of_another_category_is_not_found(self):
        self.write_v3(episodes=[make_v3_entry("e1")], streams=[make_v3_entry("s1")])
        reply = self.request("/catalog/vault/episodes/s1")

        self.assertEqual(reply.status, 404)

    def test_the_same_id_in_two_categories_resolves_inside_each(self):
        episode = make_v3_entry("shared", title={"2024-06-15T09:40:00": "the episode"})
        clip = make_v3_entry("shared", title={"2024-06-15T09:40:00": "the clip"})
        self.write_v3(episodes=[episode], clips=[clip])

        self.assertIn("the episode", self.request("/catalog/vault/episodes/shared").body)
        self.assertIn("the clip", self.request("/catalog/vault/clips/shared").body)

    def test_a_version_one_entry_is_found_under_entries(self):
        self.write_v1([make_v1_entry("e1")])
        reply = self.request("/catalog/vault/entries/e1")

        self.assertEqual(reply.status, 200)
        self.assertIn("title e1", reply.body)

    def test_an_unknown_id_is_reported_without_a_traceback(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        reply = self.request("/catalog/vault/episodes/absent")

        self.assertEqual(reply.status, 404)
        self.assertNotIn("Traceback", reply.body)
        self.assertIn("<html", reply.body)

    def test_an_invalid_category_falls_back_to_the_default_listing(self):
        self.write_v3(episodes=[make_v3_entry("e1")])

        self.assertRedirect(self.request("/catalog/vault/elsewhere/e1"), "/catalog/vault/episodes")

    def test_a_missing_vault_returns_to_the_landing_page(self):
        reply = self.request("/catalog/absent/episodes/e1")

        self.assertIn(reply.status, REDIRECT_STATUSES)
        self.assertIn("absent", self.request(reply.location).body)


class DetailMediaTests(ViewerTestCase):
    """How the page refers to the files the vault downloaded for the entry."""

    def test_downloaded_media_is_played_from_the_media_route(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        filename = self.store_media("e1")
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertIn(f'src="/vault/vault/media/{filename}"', body)

    def test_the_stored_filename_is_used_as_it_is_saved(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        filename = self.store_asset("media", "episode-e1-1080p.webm", MEDIA_BODY)
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertIn(f'src="/vault/vault/media/{filename}"', body)

    def test_a_stored_preview_is_shown_from_the_preview_route(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        self.store_preview("e1")
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertIn("/vault/vault/preview/e1", body)

    def test_missing_media_keeps_the_metadata_and_the_chart_data(self):
        entry = make_v3_entry("e1", views={"2024-06-15T09:40:00": 10, "2024-06-16T09:40:00": 12})
        self.write_v3(episodes=[entry])
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertNotIn("/vault/vault/media/", body)
        self.assertIn("2024-03-01T10:00:00", body)
        self.assertIn(f'href="{self.source.url}/entry/e1"', body)
        self.assertEqual(
            points(body, "views"), [("2024-06-15T09:40:00", 10), ("2024-06-16T09:40:00", 12)]
        )


class ChartDataTests(ViewerTestCase):
    """The ``views`` and ``likes`` data a detail page embeds, whatever the version."""

    def test_both_fields_are_exposed(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        data = chart_data(self.request("/catalog/vault/episodes/e1").body)

        self.assertEqual(sorted(data), ["likes", "views"])

    def test_version_three_points_keep_their_iso_keys_in_order(self):
        entry = make_v3_entry(
            "e1",
            views={"2024-06-16T09:40:00": 12, "2024-06-15T09:40:00": 10, "2024-06-17T09:40:00": 30},
        )
        self.write_v3(episodes=[entry])
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertEqual(
            points(body, "views"),
            [("2024-06-15T09:40:00", 10), ("2024-06-16T09:40:00", 12), ("2024-06-17T09:40:00", 30)],
        )

    def test_version_two_points_keep_their_iso_keys_in_order(self):
        entry = make_v2_entry(
            "e1", views={"2024-07-01T00:00:00": 20, "2024-06-15T09:40:00": 10}
        )
        self.write_v2(episodes=[entry])
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertEqual(
            points(body, "views"), [("2024-06-15T09:40:00", 10), ("2024-07-01T00:00:00", 20)]
        )

    def test_version_one_epoch_keys_become_iso_timestamps(self):
        self.write_v1([make_v1_entry("e1")])
        body = self.request("/catalog/vault/entries/e1").body

        self.assertEqual(
            points(body, "views"), [("2024-06-15T09:40:00", 10), ("2024-06-16T09:40:00", 12)]
        )

    def test_version_one_points_order_by_epoch_value_not_by_text(self):
        entry = make_v1_entry("e1")
        entry["views"] = {"1000000000": 7, "999999999": 5}
        self.write_v1([entry])
        body = self.request("/catalog/vault/entries/e1").body

        self.assertEqual(
            points(body, "views"), [("2001-09-09T01:46:39", 5), ("2001-09-09T01:46:40", 7)]
        )

    def test_null_likes_are_kept_as_they_are_recorded(self):
        entry = make_v3_entry(
            "e1", likes={"2024-06-15T09:40:00": None, "2024-06-16T09:40:00": 4}
        )
        self.write_v3(episodes=[entry])
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertEqual(
            points(body, "likes"), [("2024-06-15T09:40:00", None), ("2024-06-16T09:40:00", 4)]
        )

    def test_a_field_with_two_points_is_charted(self):
        entry = make_v3_entry("e1", views={"2024-06-15T09:40:00": 10, "2024-06-16T09:40:00": 12})
        self.write_v3(episodes=[entry])
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertIn("chart-views", body)
        self.assertIn("<polyline", body)

    def test_a_single_point_field_is_not_charted_but_keeps_its_metadata(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        body = self.request("/catalog/vault/episodes/e1").body

        self.assertNotIn("<polyline", body)
        self.assertIn("title e1", body)
        self.assertIn("2024-03-01T10:00:00", body)
        self.assertIn(f'href="{self.source.url}/entry/e1"', body)
        self.assertEqual(points(body, "views"), [("2024-06-15T09:40:00", 10)])


class SourceLinkTests(ViewerTestCase):
    """The source-platform link each catalog version derives for an entry."""

    def test_a_version_one_link_is_derived_from_the_source_id(self):
        self.write_v1([make_v1_entry("e1")])
        body = self.request("/catalog/vault/entries/e1").body

        self.assertIn(f'href="{V1_SOURCE_URL}/entry/e1"', body)

    def test_a_version_two_link_is_derived_from_the_source_url(self):
        self.write_v2(streams=[make_v2_entry("s1")])
        body = self.request("/catalog/vault/streams/s1").body

        self.assertIn(f'href="{self.source.url}/entry/s1"', body)

    def test_a_version_three_link_is_derived_from_the_source_url(self):
        self.write_v3(clips=[make_v3_entry("c1")])
        body = self.request("/catalog/vault/clips/c1").body

        self.assertIn(f'href="{self.source.url}/entry/c1"', body)


class MediaRouteTests(ViewerTestCase):
    """``/vault/<name>/media/<file>``: the media files a vault downloaded."""

    def test_a_stored_media_file_is_served_as_media(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        filename = self.store_media("e1")
        reply = self.request(f"/vault/vault/media/{filename}")

        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.body, MEDIA_BODY.decode())
        self.assertEqual(reply.content_type, "video/mp4")

    def test_a_file_the_vault_does_not_hold_is_not_found(self):
        self.write_v3(episodes=[make_v3_entry("e1")])

        self.assertEqual(self.request("/vault/vault/media/e1.mp4").status, 404)

    def test_a_partial_download_is_not_served(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        self.store_asset("media", "e1.mp4.part", MEDIA_BODY)

        self.assertEqual(self.request("/vault/vault/media/e1.mp4.part").status, 404)

    def test_a_traversal_sequence_does_not_escape_the_media_directory(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        self.store_media("e1")

        for path in ("/vault/vault/media/..%2Fcatalog.json", "/vault/vault/media/%2Fetc%2Fhosts"):
            reply = self.request(path)
            self.assertIn(reply.status, (403, 404), path)
            self.assertNotIn("version", reply.body)

    def test_a_missing_vault_returns_to_the_landing_page(self):
        reply = self.request("/vault/absent/media/e1.mp4")

        self.assertIn(reply.status, REDIRECT_STATUSES)
        self.assertIn("absent", self.request(reply.location).body)


class PreviewRouteTests(ViewerTestCase):
    """``/vault/<name>/preview/<id>``: the preview image saved for an entry."""

    def test_the_preview_of_an_entry_is_served_as_an_image(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        self.store_preview("e1")
        reply = self.request("/vault/vault/preview/e1")

        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.body, PREVIEW_BODY.decode())
        self.assertEqual(reply.content_type, "image/jpeg")

    def test_the_saved_name_only_has_to_hold_the_requested_id(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        self.store_asset("previews", "preview-e1-thumb.png", PREVIEW_BODY)
        reply = self.request("/vault/vault/preview/e1")

        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.content_type, "image/png")

    def test_an_entry_without_a_preview_is_not_found(self):
        self.write_v3(episodes=[make_v3_entry("e1")])

        self.assertEqual(self.request("/vault/vault/preview/e1").status, 404)

    def test_a_traversal_sequence_does_not_escape_the_preview_directory(self):
        self.write_v3(episodes=[make_v3_entry("e1")])
        self.store_preview("e1")
        reply = self.request("/vault/vault/preview/..%2F..%2Fcatalog.json")

        self.assertIn(reply.status, (403, 404))
        self.assertNotIn("version", reply.body)

    def test_an_unknown_asset_kind_redirects_to_the_landing_page(self):
        self.write_v3(episodes=[make_v3_entry("e1")])

        self.assertRedirect(self.request("/vault/vault/catalog/catalog.json"), "/")


if __name__ == "__main__":
    unittest.main()
